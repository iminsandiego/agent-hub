import json

import pytest

from agent_hub.classify import (
    BOOKKEEPING, DERIVED, INJECTED, METADATA, TITLE, TOOL, chat_title, classify_event, classify_session, excluded_session,
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
        con.execute("INSERT OR REPLACE INTO derived_versions VALUES('alpha','classifier',1)")
    plan = store.prune("alpha")
    assert plan["records_removed"] == 0 and plan["kept_because_a_note_cites_them"] == 1
