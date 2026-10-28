import json

import pytest

from agent_hub.classify import (
    BOOKKEEPING, CLASSIFIER_VERSION, DERIVED, INJECTED, METADATA, TITLE, TOOL, chat_title, classify_event, classify_session, excluded_session,
)
from agent_hub.store import Store


def codex(kind, payload, **extra):
    return json.dumps({"timestamp": "2026-10-07T12:00:00Z", "type": kind, "payload": payload, **extra})


@pytest.mark.parametrize("role,text,raw,expected", [
    ("user", "Where is the spelling app deployed?", "", None),
    ("assistant", "It runs on agent-vm at /opt/wordgarden.", "", None),
    ("system", "", "", BOOKKEEPING),
    ("assistant", "   ", "", BOOKKEEPING),
    ("system", "Codex event: token_count", codex("event_msg", {"type": "token_count"}), BOOKKEEPING),
    ("system", "{\"tokens\": 3}", codex("event_msg", {"type": "token_count", "tokens": 3}), BOOKKEEPING),
    # parser version 1 kept a message's event copy as the message; it stays
    ("user", "sample", codex("event_msg", {"type": "user_message", "message": "sample"}), None),
    ("system", "Codex event: user_message (also recorded as a response item)", "", BOOKKEEPING),
    ("system", "Codex turn_context metadata.", "", BOOKKEEPING),
    ("system", "Claude file-history-snapshot metadata.", "", BOOKKEEPING),
    ("system", "Codex session_meta metadata.", codex("session_meta", {"id": "t", "cwd": "/w"}), METADATA),
    ("system", "Unsupported Codex record (token_usage_record); raw source retained.", "{}", BOOKKEEPING),
    ("system", "Unsupported Claude record (api-request-blob); raw source retained.", "{}", BOOKKEEPING),
    ("system", "Unsupported Claude record (attachment); raw source retained.", '{"type":"attachment","attachment":{"type":"hook_additional_context"}}', BOOKKEEPING),
    ("system", "Unsupported Claude record (attachment); raw source retained.", '{"type":"attachment","attachment":{"type":"queued_command","prompt":"x"}}', METADATA),
    ("system", "Unsupported Codex record (future_record); raw source retained.", "{}", METADATA),
    ("system", "a queued prompt", '{"type":"queue-operation","operation":"enqueue","content":"a queued prompt"}', BOOKKEEPING),
    ("system", "reasoning summary", codex("response_item", {"type": "reasoning", "summary": []}), INJECTED),
    ("developer", "<permissions instructions>", "", INJECTED),
    ("user", "<environment_context>\n<cwd>/w</cwd>", "", INJECTED),
    ("user", "# AGENTS.md instructions for /w", "", INJECTED),
    ("user", "Context handoff (full_thread_summary): ...", "", INJECTED),
    ("user", "<command-name>/review</command-name>", "", None),
    ("tool", "exit 0", "", TOOL),
    ("assistant", "Tool call: Bash\n{\"command\": \"ls\"}", "", TOOL),
    ("system", "Unsupported Claude record (custom-title); raw source retained.", '{"type":"custom-title","customTitle":"Garden"}', TITLE),
])
def test_record_classes(role, text, raw, expected):
    assert classify_event(role, text, raw) == expected


def test_codex_heads_are_recognized_with_or_without_json_spacing():
    spaced = json.dumps({"type": "event_msg", "payload": {"type": "token_count"}})
    compact = json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}, separators=(",", ":"))
    assert classify_event("system", "x", spaced) == classify_event("system", "x", compact) == BOOKKEEPING


def test_session_classes_and_exclusion():
    guardian = codex("session_meta", {"id": "g", "source": {"subagent": {"other": "guardian"}}, "thread_source": "subagent"})
    worker = codex("session_meta", {"id": "w", "source": {"subagent": {"thread_spawn": {}}}})
    primary = codex("session_meta", {"id": "p", "source": "vscode"})
    assert classify_session("codex", {}, guardian) == DERIVED and excluded_session("codex", {}, guardian)
    assert classify_session("codex", {}, worker) == DERIVED and excluded_session("codex", {}, worker) is None
    assert classify_session("codex", {}, primary) is None and excluded_session("codex", {}, primary) is None
    assert classify_session("claude", {"source_path": "/p/s/subagents/agent-1.jsonl"}) == DERIVED
    title = {"format": "codex_sqlite_title_v1"}
    assert classify_session("generic", title, json.dumps({"name": "Fix garden"})) == TITLE
    assert excluded_session("generic", title, json.dumps({"name": "Guardian review"}))


def test_chat_titles():
    assert chat_title("Unsupported Claude record (ai-title); raw source retained.", '{"type":"ai-title","aiTitle":"Plan"}') == ("Plan", "ai", None)
    assert chat_title("Codex chat title: Garden fix\nNative session: n\nAgent Hub original session: s_ab12", "") == ("Garden fix", "codex", "s_ab12")
    assert chat_title("hello", "") is None


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "memory.sqlite3")
    result.create_project("alpha")
    return result


def record(i, role, text, raw=None, ts=None):
    return {"event_id": str(i), "role": role, "text": text, "raw": raw if raw is not None else json.dumps({"i": i}),
            "timestamp": ts or f"2026-10-07T12:{i:02d}:00Z"}


def test_ingest_discards_bookkeeping_and_never_archives_the_approval_reviewer(store):
    guardian_meta = codex("session_meta", {"id": "g", "source": {"subagent": {"other": "guardian"}}})
    first = store.ingest("alpha", "codex", "m", "g", [record(0, "system", "Codex session_meta metadata.", guardian_meta),
                                                     record(1, "user", "The following is the Codex agent history ...")])
    assert first["excluded"] and first["discarded"] == 2 and store.stats("alpha")["events"] == 0
    # A later batch of the same thread carries no session_meta; it is still skipped.
    later = store.ingest("alpha", "codex", "m", "g", [record(2, "assistant", '{"outcome":"allow"}')])
    assert later["excluded"] and store.stats("alpha")["events"] == 0
    kept = store.ingest("alpha", "codex", "m", "p", [
        record(0, "system", "Codex session_meta metadata.", codex("session_meta", {"id": "p"})),
        record(1, "system", "Codex event: token_count", codex("event_msg", {"type": "token_count"})),
        record(2, "user", "Where is the spelling app?"),
    ])
    assert (kept["inserted"], kept["discarded"]) == (2, 1)
    replay = store.ingest("alpha", "codex", "m", "p", [record(1, "system", "Codex event: token_count", codex("event_msg", {"type": "token_count"}))])
    assert (replay["inserted"], replay["discarded"]) == (0, 1)


def test_hidden_records_keep_positions_but_not_excerpts_or_search(store):
    events = [record(0, "user", "Deploy the garden app"), record(1, "tool", "garden " * 200),
              record(2, "developer", "<permissions instructions> garden"), record(3, "assistant", "Garden is live at /opt/garden.")]
    store.ingest("alpha", "codex", "m", "s", events)
    root = store.view("alpha", max_nodes=1)[0]
    assert (root["lo"], root["hi"]) == (0, 3)
    assert "Deploy the garden app" in root["summary"] and "Garden is live" in root["summary"]
    assert "garden garden" not in root["summary"] and "permissions" not in root["summary"]
    hits = store.search("alpha", "garden")
    assert [hit["role"] for hit in hits][-1] == "developer"  # injected text ranks after the conversation
    assert {hit["class"] for hit in hits} >= {None, "tool", "injected"}


def test_rebuild_reclassifies_and_prune_removes_noise_then_closes_gaps(store, tmp_path):
    con_path = store.path
    store.ingest("alpha", "codex", "m", "p", [record(0, "user", "Plan the garden"), record(1, "assistant", "Planned.")])
    # Simulate records archived by an older server, before ingest discarded them.
    import sqlite3
    with sqlite3.connect(con_path) as con:
        con.execute("DELETE FROM event_classes")
    store.ingest("alpha", "codex", "m", "g", [record(0, "user", "first")])
    with sqlite3.connect(con_path) as con:
        con.execute("UPDATE events SET raw=? WHERE external_event_id='0' AND session_id=(SELECT id FROM sessions WHERE external_id='g')",
                    (codex("session_meta", {"id": "g", "source": {"subagent": {"other": "guardian"}}}),))
        con.execute("UPDATE events SET text='Codex event: token_count', role='system' WHERE external_event_id='1' "
                    "AND session_id=(SELECT id FROM sessions WHERE external_id='p')")
    rebuilt = store.rebuild_tree("alpha")
    assert rebuilt["classes"]["records_bookkeeping"] == 1 and rebuilt["classes"]["sessions_derived"] == 1
    plan = store.prune("alpha")
    assert (plan["records_removed"], plan["sessions_excluded"]) == (2, {"codex approval reviewer": 1})
    assert store.stats("alpha")["events"] == 3  # report only
    done = store.prune("alpha", apply=True)
    assert done["positions"] == {"before": 3, "after": 1} and store.stats("alpha")["events"] == 1
    assert store.view("alpha", max_nodes=1)[0]["hi"] == 0
    again = store.ingest("alpha", "codex", "m", "g", [record(5, "user", "more")])
    assert again["excluded"]  # remembered: a replay does not bring the thread back
    chats = store.context("alpha", 4000, sections=["chats"])["text"]
    assert "0+1 | " in chats and "Plan the garden" in chats


def test_prune_keeps_records_a_note_cites(store):
    store.ingest("alpha", "codex", "m", "p", [record(0, "user", "keep"), record(1, "assistant", "noted")])
    import sqlite3
    with sqlite3.connect(store.path) as con:
        con.execute("INSERT INTO event_classes SELECT id,project,'bookkeeping' FROM events WHERE external_event_id='1'")
        cited = con.execute("SELECT id FROM events WHERE external_event_id='1'").fetchone()[0]
    store.add_memory("alpha", "A decision", "decision", [cited])
    with sqlite3.connect(store.path) as con:
        con.execute("INSERT OR REPLACE INTO derived_versions VALUES('alpha','classifier',?)", (CLASSIFIER_VERSION,))
    plan = store.prune("alpha")
    assert plan["records_removed"] == 0 and plan["kept_because_a_note_cites_them"] == 1


def test_an_image_only_message_is_kept_not_discarded(store):
    raw = json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "data": "AAAA"}}]}})
    assert classify_event("user", "", raw) == METADATA
    assert classify_event("assistant", "", json.dumps({"content": [{"type": "image", "source": {}}]})) == METADATA
    assert classify_event("assistant", "", json.dumps({"content": [{"type": "thinking", "thinking": "..."}]})) == BOOKKEEPING
    receipt = store.ingest("alpha", "claude", "m", "s", [record(0, "user", "", raw)])
    assert (receipt["inserted"], receipt["discarded"]) == (1, 0)
    assert store.prune("alpha")["records_removed"] == 0


def test_rebuild_judges_a_queued_prompt_on_its_whole_source(store):
    # The discriminator sits past the 400-character head rebuild reads first.
    raw = json.dumps({"parentUuid": "p" * 500, "isSidechain": False, "type": "attachment",
                      "attachment": {"type": "queued_command", "prompt": "Also check the porch camera"}})
    assert raw.index("queued_command") > 400
    text = "Unsupported Claude record (attachment); raw source retained."
    store.ingest("alpha", "claude", "m", "s", [record(0, "user", "Check the cameras"), record(1, "system", text, raw)])
    store.rebuild_tree("alpha")
    plan = store.prune("alpha")
    assert plan["records_removed"] == 0 and store.stats("alpha")["events"] == 2


def test_search_finds_the_conversation_behind_many_unsearched_matches(store):
    events = [record(i, "system", f"Unsupported Codex record (future_record_{i}); raw source retained.") for i in range(1100)]
    events.append(record(2000, "user", "The " + "long " * 60 + "record that matters: the valve key is in the garage."))
    store.ingest("alpha", "codex", "m", "s", events)
    hits = store.search("alpha", "record")
    assert [hit["role"] for hit in hits] == ["user"]


def test_span_detail_skips_spans_of_only_hidden_records(store):
    import time
    events = [record(0, "user", "Start " + "question " * 80)] + [record(i, "tool", "x" * 20) for i in range(1, 8191)]
    events.append(record(8191, "assistant", "Done " + "answer " * 80))
    store.ingest("alpha", "codex", "m", "s", events)
    root = store.view("alpha", max_nodes=1)[0]
    with store._read() as con:
        started = time.monotonic()
        store._span_detail(con, "alpha", root, 7000)
        assert time.monotonic() - started < 0.2  # quadratic before 0.1.12's fix: about 0.8 s here


def test_classifier_readiness_is_reported_and_prune_requires_current_classes(store):
    import sqlite3
    stats = store.stats("alpha")["classifier"]
    assert stats["applied"] == stats["current"]  # a new project is classified as records arrive
    with sqlite3.connect(store.path) as con:  # an archive upgraded from 0.1.11
        con.execute("DELETE FROM derived_versions")
    assert store.stats("alpha")["classifier"]["applied"] is None
    with pytest.raises(ValueError, match="rebuild"):
        store.prune("alpha")
    store.rebuild_tree("alpha")
    assert store.prune("alpha")["records_removed"] == 0


def test_prune_report_does_not_take_the_write_lock(store):
    import sqlite3
    store.ingest("alpha", "codex", "m", "s", [record(0, "user", "hello")])
    writer = sqlite3.connect(store.path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    try:
        assert store.prune("alpha")["records_removed"] == 0
    finally:
        writer.execute("ROLLBACK")
        writer.close()


def test_search_index_holds_only_searchable_records(store):
    import sqlite3
    meta = codex("session_meta", {"id": "t", "cwd": "/w"})
    store.ingest("alpha", "codex", "m", "t", [record(0, "system", "Codex session_meta metadata.", meta),
                                             record(1, "user", "codex session question")])
    indexed = lambda: {row[0] for row in sqlite3.connect(store.path).execute(
        "SELECT e.role FROM history_fts h JOIN events e ON e.id=h.item_id WHERE h.item_type='event'")}
    assert indexed() == {"user"}
    # An archive from 0.1.11 indexed everything; rebuild takes the metadata back out.
    with sqlite3.connect(store.path) as con:
        con.execute("INSERT INTO history_fts(project,item_type,item_id,content) SELECT project,'event',id,text FROM events WHERE role='system'")
        con.execute("DELETE FROM derived_versions WHERE name='search_index'")
    store.rebuild_tree("alpha")
    assert indexed() == {"user"}
    assert [hit["role"] for hit in store.search("alpha", "codex session")] == ["user"]


def test_compaction_and_turn_context_records():
    with_summary = codex("compacted", {"message": "Summary of the earlier work", "replacement_history": []})
    assert classify_event("system", "Summary of the earlier work", with_summary) == INJECTED
    assert classify_event("system", "Codex compacted metadata.", codex("compacted", {"message": ""})) == BOOKKEEPING
    assert classify_event("system", '{"cwd": "/w"}', codex("turn_context", {"cwd": "/w"})) == BOOKKEEPING


def test_a_message_is_injected_only_when_every_block_is():
    mixed = json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": "<system-reminder>context</system-reminder>"}, {"type": "text", "text": "Fix the porch light"}]}})
    assert classify_event("user", "<system-reminder>context</system-reminder>\nFix the porch light", mixed) is None
    only = json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "<system-reminder>x</system-reminder>"}]}})
    assert classify_event("user", "<system-reminder>x</system-reminder>", only) == INJECTED
    assert classify_event("user", "<pasted_content id=1>log text</pasted_content>", "") is None


def test_a_codex_title_captured_before_its_chat_names_it_when_it_arrives(store):
    from agent_hub.store import _hash
    target = "s_" + _hash(["alpha", "codex", "m", "late"])
    store.ingest("alpha", "generic", "m", "codex-title-v1:late", [record(0, "system",
        f"Codex chat title: Roof plan\nNative session: late\nAgent Hub original session: {target}", json.dumps({"name": "Roof plan"}))],
        {"format": "codex_sqlite_title_v1"})
    store.ingest("alpha", "codex", "m", "late", [record(0, "user", "Plan the roof")])
    assert "Roof plan — Plan the roof" in store.context("alpha", 4000, sections=["chats"])["text"]


def test_stdio_gateway_forwards_sections(tmp_path, monkeypatch):
    import asyncio
    import httpx
    from agent_hub.client import ClientConfig, MemoryClient, create_gateway
    monkeypatch.setenv("TEST_AGENT_HUB_TOKEN", "synthetic-test-token")
    cfg = ClientConfig(url="http://127.0.0.1:9867", machine_id="m", token_env="TEST_AGENT_HUB_TOKEN",
                       mappings=[{"path": str(tmp_path), "project": "atlas"}], state_dir=str(tmp_path / "state"))
    seen = []
    memory = MemoryClient(cfg, transport=httpx.MockTransport(lambda request: seen.append(dict(request.url.params)) or httpx.Response(200, json={"text": "ok"})))
    gateway = create_gateway(cfg, memory=memory)
    tools = {tool.name: tool for tool in asyncio.run(gateway.list_tools())}
    assert "sections" in tools["memory_context"].inputSchema["properties"]
    asyncio.run(gateway.call_tool("memory_context", {"project": "atlas", "sections": ["chats", "history"]}))
    assert seen[-1]["sections"] == "chats,history"
