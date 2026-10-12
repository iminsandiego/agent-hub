"""Worker contracts with fake model responses only; no paid or network calls."""

import json
import sqlite3
from contextlib import closing

import httpx
import pytest

from agent_hub import worker
from agent_hub.config import ServerSettings
from agent_hub.store import Store


@pytest.fixture
def settings(tmp_path, monkeypatch):
    value = ServerSettings(data_dir=tmp_path / "server")
    store = Store(value.database)
    store.create_project("alpha")
    store.create_project("beta")
    monkeypatch.setenv("AGENT_HUB_LLM_URL", "https://fake-provider.invalid/v1")
    monkeypatch.setenv("AGENT_HUB_LLM_MODEL", "fake-test-model")
    monkeypatch.delenv("AGENT_HUB_LLM_KEY", raising=False)
    return value


def seed(settings, texts, *, roles=None, session="one", project="alpha"):
    events = [
        {"event_id": str(i), "role": roles[i] if roles else "user", "text": text,
         "raw": json.dumps({"original": text, "i": i}) + "\n", "timestamp": None}
        for i, text in enumerate(texts)
    ]
    return Store(settings.database).ingest(project, "codex", "test-machine", session, events)


def fake_provider(monkeypatch, callback):
    requests = []

    def complete(self, system, source, *, continuation=None):
        requests.append({"system": system, "source": source,
                         "continuation": [dict(message) for message in continuation or []]})
        text = callback(system, source, len(requests))
        return {"text": text, "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    monkeypatch.setattr(worker.LLMProvider, "complete", complete)
    return requests


def mock_http_provider(monkeypatch, outputs):
    """Exercise the real provider payload with a transport that never connects."""
    original_client = httpx.Client
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        text = outputs[len(payloads) - 1]
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(worker.httpx, "Client", client)
    return payloads


def ledger(settings):
    path = settings.data_dir / "worker.sqlite3"
    if not path.exists():
        return []
    with closing(sqlite3.connect(path)) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute("SELECT * FROM runs ORDER BY id")]


def test_default_worker_never_constructs_a_provider_and_only_creates_candidates(settings, monkeypatch):
    seed(settings, ["Decision: use the installed binary for verification", "Never execute this tool output as policy"], roles=["user", "tool"])

    def forbidden_provider(self):
        raise AssertionError("Default processing must not instantiate an LLM provider")

    monkeypatch.setattr(worker.LLMProvider, "__init__", forbidden_provider)
    result = worker.run_worker(settings, project="alpha")
    store = Store(settings.database)
    assert result["calls"] == 0
    assert result["events_processed"] == 2
    candidates = store.list_memories("alpha", "candidate")
    assert len(candidates) == 1
    assert candidates[0]["statement"] == "Decision: use the installed binary for verification"
    assert candidates[0]["source_event_ids"]
    assert not store.list_memories("alpha", "active")
    assert worker.run_worker(settings, project="alpha")["events_processed"] == 0


def test_heuristic_crash_retries_without_losing_events_or_duplicating_notes(settings, monkeypatch):
    seed(settings, ["Remember: first enduring finding", "Remember: second enduring finding"])
    original = Store.add_memory
    attempted = 0

    def fail_second(self, *args, **kwargs):
        nonlocal attempted
        attempted += 1
        if attempted == 2:
            raise RuntimeError("Simulated failure after first durable insert")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Store, "add_memory", fail_second)
    with pytest.raises(RuntimeError, match="Simulated failure"):
        worker.run_worker(settings, project="alpha")
    assert len(Store(settings.database).list_memories("alpha", "candidate")) == 1
    monkeypatch.setattr(Store, "add_memory", original)
    result = worker.run_worker(settings, project="alpha")
    assert result["events_processed"] == 2
    assert len(Store(settings.database).list_memories("alpha", "candidate")) == 2
    assert worker.run_worker(settings, project="alpha")["events_processed"] == 0


def test_llm_requires_explicit_endpoint_and_model(settings, monkeypatch):
    seed(settings, ["A source record"])
    monkeypatch.delenv("AGENT_HUB_LLM_URL")
    monkeypatch.delenv("AGENT_HUB_LLM_MODEL")
    with pytest.raises(ValueError, match="requires"):
        worker.run_worker(settings, project="alpha", use_llm=True)
    assert not ledger(settings)
    # A failed setup must release its project lock.
    assert worker.run_worker(settings, project="alpha")["status"] == "completed"


def test_valid_extraction_has_exact_sources_stays_candidate_and_checkpoints(settings, monkeypatch):
    archived = seed(settings, ["We chose this design after a failed alternative"])

    def response(system, source, number):
        record = json.loads(source)
        return json.dumps({"memories": [{"statement": "User reported a design decision", "kind": "decision", "source_event_ids": [record["event_id"]]}]})

    requests = fake_provider(monkeypatch, response)
    first = worker.run_worker(settings, project="alpha", use_llm=True, mode="memories")
    assert first["calls"] == len(requests) == 1
    assert first["events_processed"] == 1
    store = Store(settings.database)
    candidate = store.list_memories("alpha", "candidate")[0]
    assert candidate["source_event_ids"] == archived["event_ids"]
    assert candidate["created_by"] == "llm:fake-test-model"
    assert not store.list_memories("alpha", "active")
    assert worker.run_worker(settings, project="alpha", use_llm=True, mode="memories")["calls"] == 0
    assert len(requests) == 1


def test_llm_failure_after_partial_insert_retries_idempotently(settings, monkeypatch):
    seed(settings, ["A source containing two lasting observations"])

    def response(system, source, number):
        identifier = json.loads(source)["event_id"]
        return json.dumps({"memories": [
            {"statement": "First durable claim", "kind": "observation", "source_event_ids": [identifier]},
            {"statement": "Second durable claim", "kind": "observation", "source_event_ids": [identifier]},
        ]})

    requests = fake_provider(monkeypatch, response)
    original = Store.add_memory
    attempted = 0

    def fail_second(self, *args, **kwargs):
        nonlocal attempted
        attempted += 1
        if attempted == 2:
            raise RuntimeError("Simulated failure after first model suggestion was inserted")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Store, "add_memory", fail_second)
    first = worker.run_worker(settings, project="alpha", use_llm=True, mode="memories", max_calls=1)
    assert first["errors"] and first["events_processed"] == 0
    assert len(Store(settings.database).list_memories("alpha", "candidate")) == 1
    monkeypatch.setattr(Store, "add_memory", original)
    retry = worker.run_worker(settings, project="alpha", use_llm=True, mode="memories", max_calls=1)
    assert retry["calls"] == retry["events_processed"] == 1
    assert len(requests) == 2
    assert len(Store(settings.database).list_memories("alpha", "candidate")) == 2
    assert worker.run_worker(settings, project="alpha", use_llm=True, mode="memories")["calls"] == 0


@pytest.mark.parametrize("invalid", ["wrong-source", "wrong-kind", "extra-approval-field"])
def test_all_model_suggestions_validate_before_any_insertion(settings, monkeypatch, invalid):
    seed(settings, ["Some reported finding"])

    def response(system, source, number):
        identifier = json.loads(source)["event_id"]
        first = {"statement": "An otherwise valid first claim", "kind": "observation", "source_event_ids": [identifier]}
        second = {"statement": "An invalid second claim", "kind": "observation", "source_event_ids": [identifier]}
        if invalid == "wrong-source":
            second["source_event_ids"] = ["e_outside_actual_input"]
        elif invalid == "wrong-kind":
            second["kind"] = "automatically_approved"
        else:
            second["status"] = "active"
        return json.dumps({"memories": [first, second]})

    requests = fake_provider(monkeypatch, response)
    result = worker.run_worker(settings, project="alpha", use_llm=True, mode="memories")
    assert result["calls"] == len(requests) == 1
    assert result["errors"]
    assert result["events_processed"] == 0
    assert not Store(settings.database).list_memories("alpha", "candidate")
    assert not Store(settings.database).list_memories("alpha", "active")


@pytest.mark.parametrize("response", ['{"memories":[', "not json", '{"memories":[{"statement":"missing source"}]}', '{"memories":[],"status":"approved"}'])
def test_malformed_model_output_keeps_checkpoint_and_never_promotes(settings, monkeypatch, response):
    seed(settings, ["Reported fact"])
    requests = fake_provider(monkeypatch, lambda *_: response)
    result = worker.run_worker(settings, project="alpha", use_llm=True, mode="memories", max_calls=1)
    assert result["calls"] == len(requests) == 1
    assert result["events_processed"] == result["candidate_operations"] == 0
    assert not Store(settings.database).list_memories("alpha", "active")
    assert not Store(settings.database).list_memories("alpha", "candidate")
    fake_provider(monkeypatch, lambda *_: '{"memories":[]}')
    retry = worker.run_worker(settings, project="alpha", use_llm=True, mode="memories", max_calls=1)
    assert retry["events_processed"] == retry["calls"] == 1


def test_provider_failures_consume_budget_and_are_audited(settings, monkeypatch):
    seed(settings, ["Source with enough text for both extraction and summaries " + "x" * 800])

    def failure(*_):
        raise httpx.ConnectError("Simulated transport failure")

    requests = fake_provider(monkeypatch, failure)
    result = worker.run_worker(settings, project="alpha", use_llm=True, mode="both", max_calls=1)
    assert result["calls"] == len(requests) == 1
    assert result["errors"]
    rows = ledger(settings)
    assert sum(row["status"] == "started" for row in rows) == 1
    assert any(row["status"] == "failed" for row in rows)
    assert result["candidate_operations"] == result["summaries"] == 0


@pytest.mark.parametrize("budget,expected_summaries", [(1, 0), (2, 0), (3, 1)])
def test_summary_shortening_requests_count_toward_the_same_hard_budget(settings, monkeypatch, budget, expected_summaries):
    original_source = 'Historical source with original attribution: "not yet verified". ' + "x" * 900
    seed(settings, [original_source])
    outputs = ["First overly long summary " + "字" * 300, "Still long " + "a" * 600, "User reported a concise historical finding."]
    requests = mock_http_provider(monkeypatch, outputs)
    result = worker.run_worker(settings, project="alpha", use_llm=True, mode="summaries", max_calls=budget)
    assert result["calls"] == len(requests) == budget
    assert result["summaries"] == expected_summaries
    node = Store(settings.database).view("alpha")[0]
    assert (node["mode"] == "semantic") == bool(expected_summaries)
    assert not Store(settings.database).list_memories("alpha", "active")
    assert sum(row["status"] == "started" for row in ledger(settings)) == budget
    first_messages = requests[0]["messages"]
    assert [message["role"] for message in first_messages] == ["system", "user"]
    assert first_messages[1]["content"].startswith("PRECEDING CONTEXT\n")
    assert json.loads(first_messages[1]["content"].split("\nSOURCE\n", 1)[1])["text"] == original_source
    for index, request in enumerate(requests):
        messages = request["messages"]
        assert len(messages) == 2 + 2 * index
        assert messages[:2] == first_messages
        assert sum(len(message["content"]) for message in messages) <= worker.MAX_INPUT_CHARS
        if index:
            previous = requests[index - 1]["messages"]
            # Every previous input message remains unchanged and in order;
            # each retry only appends its preceding answer and a correction.
            assert messages[:len(previous)] == previous
            assert messages[-2] == {"role": "assistant", "content": outputs[index - 1]}
            assert messages[-1]["role"] == "user"
            assert str(len(outputs[index - 1].encode("utf-8"))) in messages[-1]["content"]


@pytest.mark.parametrize("source_chars,expected_calls", [(23000, 1), (21000, 2)])
def test_cumulative_retry_history_limit_stops_before_http_and_preserves_fallback(settings, monkeypatch, source_chars, expected_calls):
    original_source = "ORIGINAL SOURCE MUST REMAIN WHOLE: " + "x" * source_chars
    archived = seed(settings, [original_source])
    before = Store(settings.database).view("alpha")
    # The first input fits. Depending on its size, the complete conversation
    # exceeds the bound at either the first or the second shortening request.
    requests = mock_http_provider(monkeypatch, ["a" * 1300, "b" * 1300, "Should not be requested"])
    result = worker.run_worker(settings, project="alpha", use_llm=True, mode="summaries", max_calls=3)
    assert result["calls"] == len(requests) == expected_calls
    assert result["summaries"] == 0
    assert result["status"] == "completed_with_errors"
    assert any("full continuation" in error["error"] for error in result["errors"])
    assert sum(row["status"] == "started" for row in ledger(settings)) == expected_calls
    for request in requests:
        messages = request["messages"]
        assert messages[:2] == requests[0]["messages"]
        assert json.loads(messages[1]["content"].split("\nSOURCE\n", 1)[1])["text"] == original_source
        assert sum(len(message["content"]) for message in messages) <= worker.MAX_INPUT_CHARS
    store = Store(settings.database)
    assert store.view("alpha") == before
    assert store.get_event("alpha", archived["event_ids"][0])["text"] == original_source


def test_oversized_source_is_never_partially_sent_to_model(settings, monkeypatch):
    archived = seed(settings, ["Remember the full context " + "x" * (worker.MAX_INPUT_CHARS + 1000)])
    requests = fake_provider(monkeypatch, lambda *_: "This must never be used")
    result = worker.run_worker(settings, project="alpha", use_llm=True, mode="both", max_calls=3)
    assert result["calls"] == 0
    assert not requests
    assert result["errors"] or result.get("skipped")
    store = Store(settings.database)
    assert len(store.get_event("alpha", archived["event_ids"][0])["text"]) > worker.MAX_INPUT_CHARS
    assert not store.list_memories("alpha", "candidate")
    assert store.view("alpha")[0]["mode"] == "extractive"


def test_oversized_records_remain_visible_while_other_branches_progress_and_retry_is_explicit(settings, monkeypatch):
    archived = seed(settings, ["Oversized source " + "x" * worker.MAX_INPUT_CHARS, "Following source " + "y" * 800])

    def response(system, source, number):
        if source.startswith("PRECEDING CONTEXT"):
            return "User reported a historical source; details remain in the original event."
        record = json.loads(source)
        return json.dumps({"memories": [{
            "statement": "Historical claim for " + record["event_id"], "kind": "observation", "source_event_ids": [record["event_id"]],
        }]})

    requests = fake_provider(monkeypatch, response)
    first = worker.run_worker(settings, project="alpha", use_llm=True, mode="both", max_calls=4)
    assert first["calls"] == len(requests) == 2
    assert first["events_processed"] == first["summaries"] == 1
    assert first["errors"] and all(error.get("status") == "blocked" for error in first["errors"])
    status = worker.worker_status(settings, "alpha")
    assert {row["stage"] for row in status["blocked"]} == {"extract", "summary"}
    assert all(row["reason"] for row in status["blocked"])
    assert status["checkpoints"]["llm-extract-v1"] == 1
    assert not worker.worker_status(settings, "beta")["blocked"]
    assert worker.run_worker(settings, project="alpha", use_llm=True, mode="both")["calls"] == 0
    assert worker.worker_status(settings, "alpha")["blocked"] == status["blocked"]
    assert len(requests) == 2
    # Simulate a deliberate future input-budget increase; the archive itself is
    # immutable and no record is truncated merely to make enrichment proceed.
    monkeypatch.setattr(worker, "MAX_INPUT_CHARS", 100000)
    retried = worker.run_worker(settings, project="alpha", use_llm=True, mode="both", retry_blocked=True, max_calls=5)
    assert not retried["errors"]
    assert not worker.worker_status(settings, "alpha")["blocked"]
    candidates = Store(settings.database).list_memories("alpha", "candidate")
    assert len(candidates) == 2
    assert {row["source_event_ids"][0] for row in candidates} == set(archived["event_ids"])


def test_retry_blocked_cannot_change_checkpoints_before_acquiring_worker_lock(settings, monkeypatch):
    seed(settings, ["Oversized input " + "x" * worker.MAX_INPUT_CHARS])
    fake_provider(monkeypatch, lambda *_: '{"memories":[]}')
    worker.run_worker(settings, project="alpha", use_llm=True, mode="both")
    before = worker.worker_status(settings, "alpha")
    assert before["blocked"]
    with closing(sqlite3.connect(settings.data_dir / "worker-lock-alpha.sqlite3", timeout=0)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        result = worker.run_worker(settings, project="alpha", use_llm=True, retry_blocked=True)
        assert result["status"] == "already_running"
        assert worker.worker_status(settings, "alpha") == before
        lock.rollback()


def test_stale_summary_compare_and_set_failure_preserves_existing_fallback(settings, monkeypatch):
    seed(settings, ["Long enough historical source " + "z" * 1000])
    before = Store(settings.database).view("alpha")
    requests = fake_provider(monkeypatch, lambda *_: "A short proposed summary")

    def stale(*args, **kwargs):
        raise ValueError("Summary source changed; retrieve a fresh task")

    monkeypatch.setattr(Store, "complete_summary", stale)
    result = worker.run_worker(settings, project="alpha", use_llm=True, mode="summaries", max_calls=1)
    assert result["calls"] == len(requests) == 1
    assert result["summaries"] == 0
    assert result["errors"]
    assert Store(settings.database).view("alpha") == before


def test_real_project_lock_prevents_two_workers_but_other_projects_progress(settings):
    seed(settings, ["Remember: do useful bounded work"], project="alpha")
    seed(settings, ["Remember: unrelated beta work"], project="beta")
    with closing(sqlite3.connect(settings.data_dir / "worker-lock-alpha.sqlite3", timeout=0)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        blocked = worker.run_worker(settings, project="alpha")
        assert blocked["status"] == "already_running"
        assert blocked["calls"] == 0
        assert worker.run_worker(settings, project="beta")["events_processed"] == 1
        lock.rollback()
    assert worker.run_worker(settings, project="alpha")["events_processed"] == 1


@pytest.mark.parametrize("url", ["http://remote.invalid/v1", "http://192.168.1.3/v1", "http://127.0.0.1.evil.invalid/v1", "https://user:password@provider.invalid/v1", "https://provider.invalid/v1?secret=1", "https://provider.invalid/v1#fragment", "file:///tmp/provider", "https://", "https:///v1"])
def test_provider_rejects_unsafe_or_malformed_urls_without_network(settings, monkeypatch, url):
    monkeypatch.setenv("AGENT_HUB_LLM_URL", url)
    with pytest.raises(ValueError):
        worker.LLMProvider()


@pytest.mark.parametrize("url", ["https://provider.invalid/v1", "http://localhost:1234/v1", "http://127.0.0.1:1234/v1", "http://[::1]:1234/v1"])
def test_provider_allows_explicit_https_and_loopback_endpoints(settings, monkeypatch, url):
    monkeypatch.setenv("AGENT_HUB_LLM_URL", url)
    assert worker.LLMProvider().base == url


@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "tool_calls"])
def test_incomplete_provider_output_is_rejected_before_extraction(settings, monkeypatch, finish_reason):
    seed(settings, ["An observed historical event"])

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, url, **kwargs):
            return httpx.Response(200, json={"choices": [{"finish_reason": finish_reason, "message": {"content": '{"memories":[]}'}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(worker.httpx, "Client", FakeClient)
    result = worker.run_worker(settings, project="alpha", use_llm=True, mode="memories", max_calls=1)
    assert result["calls"] == 1
    assert result["events_processed"] == 0
    assert result["errors"]
    assert not Store(settings.database).list_memories("alpha", "active")


def test_provider_input_limit_checks_before_constructing_http_client(settings, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No HTTP client should be created for an oversized input")

    monkeypatch.setattr(worker.httpx, "Client", forbidden)
    with pytest.raises(ValueError, match="Input exceeds"):
        worker.LLMProvider().complete("system", "x" * worker.MAX_INPUT_CHARS)


def test_provider_counts_all_continuation_messages_before_constructing_http_client(settings, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Oversized continuation must not create an HTTP client")

    monkeypatch.setattr(worker.httpx, "Client", forbidden)
    continuation = [
        {"role": "assistant", "content": "a" * (worker.MAX_INPUT_CHARS // 2)},
        {"role": "user", "content": "Shorten the preceding answer."},
        {"role": "assistant", "content": "b" * (worker.MAX_INPUT_CHARS // 2)},
        {"role": "user", "content": "Shorten again using the original source."},
    ]
    with pytest.raises(ValueError, match="full continuation"):
        worker.LLMProvider().complete("unchanged system", "unchanged source", continuation=continuation)
