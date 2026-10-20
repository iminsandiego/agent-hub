import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_hub.store import SCHEMA_VERSION, Store


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "memory.sqlite3")
    result.create_project("alpha")
    result.create_project("beta")
    return result


def event(identifier, text=None, **overrides):
    item = {
        "event_id": str(identifier),
        "role": "user",
        "text": text if text is not None else f"Event {identifier} controller",
        "raw": '{"message": "exact JSON, spacing preserved", "i": ' + str(identifier) + '}\r\n',
        "timestamp": "2026-10-07T12:00:00Z",
    }
    item.update(overrides)
    return item


def ingest(store, events, project="alpha", session="session", **kwargs):
    return store.ingest(project, "codex", "machine", session, events, **kwargs)


def test_raw_archive_and_retry_dedup_are_exact(store):
    original = event(0, "A normalized view\n文")
    first = ingest(store, [original], metadata={"cwd": "/repos/alpha"})
    second = ingest(store, [original], metadata={"cwd": "/repos/alpha"})
    assert first["event_ids"] == second["event_ids"]
    assert (second["inserted"], second["duplicates"], second["total_events"]) == (0, 1, 1)
    saved = store.get_event("alpha", first["event_ids"][0])
    assert saved["raw"] == original["raw"]
    assert saved["text"] == original["text"]
    assert saved["timestamp"] == original["timestamp"]
    assert saved["ingested_at"] != original["timestamp"]
    assert saved["sequence"] == 0
    assert json.dumps(saved)  # Public results contain only serializable values.


def test_conflict_rolls_back_whole_batch_and_tree(store):
    original = ingest(store, [event(0)])
    before = store.view("alpha")
    with pytest.raises(ValueError, match="conflicts"):
        ingest(store, [event(1), event(0, "changed old payload")])
    assert store.stats("alpha")["events"] == 1
    assert store.view("alpha") == before
    assert not store.search("alpha", "changed old payload")
    retry = ingest(store, [event(1)])
    assert store.get_event("alpha", retry["event_ids"][0])["sequence"] == 1
    assert store.get_session("alpha", original["session_id"])["total"] == 2


def test_duplicate_keys_within_batch_are_checked_transactionally(store):
    result = ingest(store, [event(0), event(0)])
    assert result["inserted"] == result["duplicates"] == 1
    assert result["event_ids"][0] == result["event_ids"][1]
    with pytest.raises(ValueError):
        ingest(store, [event(0), event(0, "different")], session="other-session")
    assert len(store.list_sessions("alpha")) == 1


def test_metadata_is_immutable_but_an_unspecified_retry_is_allowed(store):
    result = ingest(store, [event(0)], metadata={"cwd": "/alpha"})
    ingest(store, [event(0)])
    with pytest.raises(ValueError, match="metadata"):
        ingest(store, [event(1)], metadata={"cwd": "/elsewhere"})
    assert store.get_session("alpha", result["session_id"])["metadata"] == {"cwd": "/alpha"}
    assert store.stats("alpha")["events"] == 1


def test_all_reads_and_mutations_respect_project_scope(store):
    alpha = ingest(store, [event(0, "alphasensitive")])
    beta = ingest(store, [event(0, "betasensitive")], project="beta")
    memory = store.add_memory("alpha", "alphamemory", source_event_ids=alpha["event_ids"])
    assert alpha["session_id"] != beta["session_id"]
    node = store.view("alpha")[0]
    for operation in (
        lambda: store.get_event("beta", alpha["event_ids"][0]),
        lambda: store.get_session("beta", alpha["session_id"]),
        lambda: store.get_memory("beta", memory["id"]),
        lambda: store.review_memory("beta", memory["id"], "active"),
        lambda: store.zoom("beta", node["id"]),
        lambda: store.add_memory("beta", "stolen source", source_event_ids=alpha["event_ids"]),
        lambda: store.complete_summary("beta", node["id"], "wrong", "wrong", "test"),
    ):
        with pytest.raises(KeyError):
            operation()
    assert not store.search("beta", "alphasensitive alphamemory")
    assert "alphasensitive" not in store.context("beta")["text"]
    assert all(session["project"] == "beta" for session in store.list_sessions("beta"))
    assert [record["text"] for record in store.events_after("beta")] == ["betasensitive"]
    store.rebuild_tree("beta")
    assert store.get_event("alpha", alpha["event_ids"][0])["text"] == "alphasensitive"


def test_missing_projects_are_not_implicitly_created(store):
    for operation in (
        lambda: ingest(store, [event(0)], project="missing"),
        lambda: store.search("missing", "controller"),
        lambda: store.context("missing"),
        lambda: store.view("missing"),
        lambda: store.stats("missing"),
        lambda: store.events_after("missing"),
        lambda: store.summary_tasks("missing"),
    ):
        with pytest.raises(KeyError):
            operation()


@pytest.mark.parametrize("query", ['"controller" OR *', 'NEAR(controller, 2)', "controller' ; DROP TABLE events;--", 'controller : ^ { } [ ] ( )', '""*', "文"])
def test_search_input_is_literal_and_never_sql_or_fts_syntax(store, query):
    result = ingest(store, [event(0, "controller 文")])
    matches = store.search("alpha", query)
    assert all(match["project"] == "alpha" for match in matches)
    assert store.get_event("alpha", result["event_ids"][0])["text"] == "controller 文"


def test_search_includes_candidate_provenance_and_excludes_rejected_notes(store):
    archived = ingest(store, [event(0, "controller response source")])
    note = store.add_memory("alpha", "controller response note", source_event_ids=archived["event_ids"])
    matches = store.search("alpha", "controller")
    assert {match["type"] for match in matches} == {"event", "memory"}
    assert next(match for match in matches if match["type"] == "memory")["source_event_ids"] == archived["event_ids"]
    store.review_memory("alpha", note["id"], "rejected")
    assert {match["type"] for match in store.search("alpha", "controller")} == {"event"}


def test_fallback_search_is_explicit_and_handles_wildcards_as_data(store):
    ingest(store, [event(0, "literal_under controller")])
    store.fts_enabled = False
    assert store.search("alpha", "controller")[0]["retrieval"] == "substring_fallback"
    assert not store.search("alpha", "different_under")
    assert store.stats("alpha")["search_backend"] == "substring_fallback"


def test_actual_concurrent_ingestion_has_unique_contiguous_sequences(store):
    def import_batch(batch):
        return ingest(store, [event(i, f"batch {batch} event {i}") for i in range(20)], session=f"concurrent-{batch}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(import_batch, range(12)))
    assert sum(result["inserted"] for result in results) == 240
    records = store.events_after("alpha", limit=1000)
    assert [record["sequence"] for record in records] == list(range(240))
    assert len({record["id"] for record in records}) == 240
    assert len(store.list_sessions("alpha")) == 12
    covered = [i for node in store.view("alpha", 17) for i in range(node["lo"], node["hi"] + 1)]
    assert covered == list(range(240))


def test_concurrent_identical_retries_insert_once(store):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: ingest(store, [event(0)]), range(16)))
    assert sum(result["inserted"] for result in results) == 1
    assert len({result["event_ids"][0] for result in results}) == 1


def test_memory_dedup_keys_and_review_supersession_are_audited(store):
    old = store.add_memory("alpha", "Old unique statement", idempotency_key="old")
    assert old["status"] == "candidate"
    assert old["provenance"] == "unverified_explicit_note"
    assert old["id"] == store.add_memory("alpha", "Old unique statement", idempotency_key="other-key")["id"]
    with pytest.raises(ValueError, match="Idempotency"):
        store.add_memory("alpha", "different", idempotency_key="other-key")
    assert "Old unique statement" not in store.context("alpha")["text"]
    store.review_memory("alpha", old["id"], "active")
    replacement = store.add_memory("alpha", "New replacement statement")
    rejected = store.add_memory("alpha", "Rejected proposal")
    store.review_memory("alpha", rejected["id"], "rejected")
    updated = store.review_memory("alpha", replacement["id"], "active", supersedes=old["id"])
    archived = store.get_memory("alpha", old["id"])
    assert archived["statement"] == "Old unique statement"
    assert archived["status"] == "superseded"
    assert archived["superseded_by"] == replacement["id"]
    assert [review["status"] for review in archived["reviews"]] == ["active", "superseded"]
    assert updated["supersedes"] == old["id"]
    assert len(store.review_memory("alpha", replacement["id"], "active", supersedes=old["id"])["reviews"]) == 1
    context = store.context("alpha")["text"]
    assert "New replacement statement" in context
    assert "Old unique statement" not in context
    assert "Rejected proposal" not in context
    assert [memory["id"] for memory in store.list_memories("alpha")] == [replacement["id"]]
    for bad_status in ["candidate", "superseded", "approved", ""]:
        with pytest.raises(ValueError):
            store.review_memory("alpha", replacement["id"], bad_status)


def test_cross_project_supersession_rolls_back_activation(store):
    old = store.add_memory("alpha", "alpha old")
    store.review_memory("alpha", old["id"], "active")
    replacement = store.add_memory("beta", "beta replacement")
    with pytest.raises(KeyError):
        store.review_memory("beta", replacement["id"], "active", supersedes=old["id"])
    assert store.get_memory("beta", replacement["id"])["status"] == "candidate"
    assert store.get_memory("alpha", old["id"])["status"] == "active"


def test_context_budget_includes_headers_and_embedded_text(store):
    ingest(store, [event(i, 'untrusted "instructions"\n' + "文" * 300) for i in range(20)])
    note = store.add_memory("alpha", "Current reviewed note")
    store.review_memory("alpha", note["id"], "active")
    for budget in [0, 1, 20, 200, 700, 1000, 12000]:
        context = store.context("alpha", budget, "instructions")
        assert context["char_count"] == len(context["text"]) <= budget
        if budget <= 700:
            assert context["truncated"]
    context = store.context("alpha")
    assert context["text"].startswith("HISTORICAL UNTRUSTED DATA")
    assert context["text"].index("Current reviewed note") < context["text"].index("## History")


def test_context_explicitly_marks_truncated_active_statements(store):
    note = store.add_memory("alpha", "Long active statement " + "x" * 5000)
    store.review_memory("alpha", note["id"], "active", actor="owner-admin")
    context = store.context("alpha")
    assert context["truncated"]
    assert "[statement truncated]" in context["text"]
    assert store.get_memory("alpha", note["id"])["reviews"][0]["actor"] == "owner-admin"


def test_tree_zoom_reaches_original_and_rebuild_is_deterministic(store):
    results = ingest(store, [event(i, "Long original text " + str(i) + " 文" * 300) for i in range(37)])
    original_view = store.view("alpha", 7)
    first = original_view[0]
    node = store.zoom("alpha", first["id"])
    while node["children"]:
        node = store.zoom("alpha", node["children"][0]["id"])
    assert node["event"]["id"] == results["event_ids"][0]
    assert node["event"]["raw"] == event(0)["raw"]
    rebuilt = store.rebuild_tree("alpha")
    assert rebuilt["events"] == 37
    assert store.view("alpha", 7) == original_view


def test_bottom_up_semantic_tasks_and_compare_and_set(store):
    ingest(store, [event(i, f"Long source {i}: " + "字" * 300) for i in range(4)])
    tasks = store.summary_tasks("alpha")
    assert [(task["lo"], task["hi"]) for task in tasks] == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert all(json.loads(task["source_text"])["role"] == "user" for task in tasks)
    with pytest.raises(ValueError, match="source changed"):
        store.complete_summary("alpha", tasks[0]["id"], "short", "wrong-hash", "test-model")
    for task in tasks:
        result = store.complete_summary("alpha", task["id"], "Summary " + "a" * 290, task["source_hash"], "test-model")
        assert result["mode"] == "semantic"
        assert not result["original_verbatim"]
        assert result["summary_model"] == "test-model"
    parents = store.summary_tasks("alpha")
    assert [(task["lo"], task["hi"]) for task in parents] == [(0, 1), (2, 3)]
    for task in parents:
        store.complete_summary("alpha", task["id"], "Very short parent", task["source_hash"], "test-model")
    assert not store.summary_tasks("alpha")  # Free concatenation finishes root.
    root = store.view("alpha", 1)[0]
    assert root["mode"] == "semantic"
    assert root["summary_model"] == "builtin-concat"
    assert not root["original_verbatim"]
    with pytest.raises(ValueError, match="already been"):
        store.complete_summary("alpha", tasks[0]["id"], "Overwrite", tasks[0]["source_hash"], "test-model")
    with pytest.raises(ValueError, match="512"):
        store.complete_summary("alpha", tasks[0]["id"], "字" * 200, tasks[0]["source_hash"], "test-model")
    store.rebuild_tree("alpha")
    assert len(store.summary_tasks("alpha")) == 4


def test_summary_task_exclusions_do_not_change_tree_or_block_other_branches(store):
    ingest(store, [event(i, f"Long source {i}: " + "字" * 300) for i in range(4)])
    tasks = store.summary_tasks("alpha")
    blocked = tasks[0]["id"]
    assert [task["id"] for task in store.summary_tasks("alpha", 1, [blocked])] == [tasks[1]["id"]]
    for task in store.summary_tasks("alpha", exclude_ids=[blocked]):
        store.complete_summary("alpha", task["id"], "Brief semantic summary", task["source_hash"], "fake-model")
    assert not store.summary_tasks("alpha", exclude_ids=[blocked])
    assert store.zoom("alpha", blocked)["node"]["mode"] == "extractive"
    # The unaffected [2,3] branch can finish with free semantic concatenation.
    right = store.zoom("alpha", store.view("alpha", 1)[0]["id"])["children"][1]
    assert right["mode"] == "semantic"
    assert right["summary_model"] == "builtin-concat"
    assert [task["id"] for task in store.summary_tasks("alpha")] == [blocked]
    assert store.stats("alpha")["events"] == 4


def test_online_backup_restores_raw_history_memories_tree_and_fts(store, tmp_path):
    archived = ingest(store, [event(i, f"backup controller {i}") for i in range(23)])
    note = store.add_memory("alpha", "backup remembered decision", source_event_ids=archived["event_ids"][:2])
    store.review_memory("alpha", note["id"], "active")
    destination = tmp_path / "backups" / "snapshot.sqlite3"
    result = store.backup(destination)
    assert result["size_bytes"] > 0
    restored = Store(destination)
    assert restored.stats("alpha") == store.stats("alpha")
    assert restored.get_session("alpha", archived["session_id"]) == store.get_session("alpha", archived["session_id"])
    assert restored.get_memory("alpha", note["id"]) == store.get_memory("alpha", note["id"])
    assert restored.view("alpha") == store.view("alpha")
    assert restored.search("alpha", "remembered") == store.search("alpha", "remembered")
    with pytest.raises(ValueError):
        store.backup(store.path)


def test_unknown_newer_schema_is_refused(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as con:
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        Store(path)


@pytest.mark.parametrize("project", ["../private", "Alpha", "a/b", "", "x" * 65])
def test_store_rejects_invalid_project_slugs(store, project):
    with pytest.raises(ValueError):
        store.create_project(project)


def test_session_list_previews_the_first_typed_request_and_source_span(store):
    ingest(store, [
        event(0, "<environment_context>cwd: /synthetic</environment_context>", timestamp="2026-10-07T12:00:00Z"),
        event(1, "# AGENTS.md instructions for /synthetic", timestamp="2026-10-07T12:00:01Z"),
        event(2, "Assistant text is never a preview", role="assistant", timestamp="2026-10-07T12:00:02Z"),
        event(3, "Why   does the\nexport fail?", timestamp="2026-10-07T12:05:00Z"),
    ])
    ingest(store, [event(0, "Tool output only", role="tool", timestamp=None)], session="tool-only")
    sessions = {item["external_id"]: item for item in store.list_sessions("alpha")}
    assert sessions["session"]["preview"] == "Why does the export fail?"
    assert sessions["session"]["first_timestamp"] == "2026-10-07T12:00:00Z"
    assert sessions["session"]["last_timestamp"] == "2026-10-07T12:05:00Z"
    assert sessions["tool-only"]["preview"] == "Tool output only"
    assert sessions["tool-only"]["first_timestamp"] is None
    assert len(store.list_sessions("alpha")[0]["preview"]) <= 240


@pytest.mark.parametrize("budget", [8000, 24000, 64000])
def test_context_history_covers_every_event_once_with_recent_detail(store, budget):
    for batch in range(10):
        ingest(store, [event(i, f"Event {batch * 100 + i} " + "word " * 60) for i in range(100)], session=f"s{batch}")
    pack = store.context("alpha", budget)
    nodes = history_spans(pack["text"])
    assert nodes[0][0] == 0 and nodes[-1][1] == 999
    assert all(a[1] + 1 == b[0] for a, b in zip(nodes, nodes[1:]))
    assert nodes[-1] == (999, 999)  # the newest event is shown on its own
    assert pack["char_count"] <= budget and not pack["truncated"]


def test_context_keeps_the_newest_history_when_even_the_roots_do_not_fit(store):
    for batch in range(10):
        ingest(store, [event(i, f"Event {batch * 100 + i} " + "word " * 60) for i in range(100)], session=f"s{batch}")
    pack = store.context("alpha", 2000)
    nodes = history_spans(pack["text"])
    assert pack["truncated"] and pack["char_count"] <= 2000
    assert max(hi for _, hi in nodes) == 999


def test_context_respects_the_result_byte_guard_for_multibyte_text(store):
    for batch in range(4):
        ingest(store, [event(i, "記録" * 800) for i in range(64)], session=f"cjk{batch}")
    for index in range(60):
        note = store.add_memory("alpha", f"{index}決定" + "決定" * 690, "decision", [])
        store.review_memory("alpha", note["id"], "active")
    pack = store.context("alpha", 64000)
    assert len(pack["active_memory_ids"]) > 10
    assert 120_000 < len(pack["text"].encode("utf-8")) <= 140_000


def test_zoom_accepts_lo_plus_n_references_and_explains_bad_ones(store):
    ingest(store, [event(i, f"Record {i} " + "word " * 120) for i in range(12)])
    whole = store.zoom("alpha", "0+8")
    assert (whole["node"]["lo"], whole["node"]["hi"]) == (0, 7) and whole["node"]["ref"] == "0+8"
    assert [child["ref"] for child in whole["children"]] == ["0+4", "4+4"]
    leaf = store.zoom("alpha", "9+1")
    assert leaf["event"]["sequence"] == 9 and leaf["node"]["ref"] == "9+1"
    for bad in ("3+2", "0+3", "8+8", "12+1"):
        with pytest.raises(ValueError, match="top nodes: 0\\+8, 8\\+4"):
            store.zoom("alpha", bad)
    hit = [h for h in store.search("alpha", "Record") if h["type"] == "event"][0]
    assert store.zoom("alpha", hit["ref"])["event"]["id"] == hit["id"]


def history_spans(text):
    """(lo, hi) of each history line in a context pack."""
    history = text.split("## History", 1)[1] if "## History" in text else ""
    spans = []
    for line in history.splitlines()[1:]:
        match = re.match(r"^(\d+)\+(\d+) \| ", line)
        if match:
            spans.append((int(match[1]), int(match[1]) + int(match[2]) - 1))
    return sorted(spans)


def test_context_lines_carry_dates_and_read_oldest_first(store):
    ingest(store, [event(i, f"Record {i}", timestamp=f"2026-0{1 + i // 4}-0{1 + i % 4}T09:30:00Z") for i in range(8)])
    text = store.context("alpha", 64000)["text"]
    history = text.split("## History", 1)[1].splitlines()[1:]
    assert history[0].startswith("0+1 | 2026-01-01 09:30 | user: Record 0")
    assert history[-1].startswith("7+1 | 2026-02-04 09:30 | user: Record 7")
    from agent_hub.store import CONTEXT_HEADER, HISTORY_TITLE
    coarse = store.context("alpha", len(CONTEXT_HEADER) + len(HISTORY_TITLE) + 200)["text"]
    assert "0+4 | 2026-01-01..2026-01-04 | user: Record 0 ¶ user: Record 1" in coarse


def test_query_matches_leave_room_for_history(store):
    ingest(store, [event(i, f"Shared term record {i} " + "word " * 80) for i in range(64)])
    pack = store.context("alpha", 6000, "Shared term")
    assert "## Records matching the task" in pack["text"] and "## History" in pack["text"]
    spans = history_spans(pack["text"])
    assert spans[0][0] == 0 and spans[-1][1] == 63


def test_reorder_puts_a_backfilled_session_in_time_order(store):
    newer = ingest(store, [event(i, f"October work {i}", timestamp=f"2026-10-0{i + 1}T10:00:00Z") for i in range(4)], session="newer")
    older = ingest(store, [
        event(0, "Old question", timestamp="2024-03-01T09:00:00Z"),
        event(1, "Old answer, no timestamp", timestamp=None),
        event(2, "Old follow-up with a clock that went backwards", timestamp="2024-02-28T09:00:00Z"),
    ], session="older")
    note = store.add_memory("alpha", "Old decision", "decision", [older["event_ids"][0]])
    plan = store.reorder_by_time("alpha")
    assert plan == {**plan, "applied": False, "events": 7, "moved": 7}
    assert store.get_event("alpha", older["event_ids"][0])["sequence"] == 4  # nothing written yet
    done = store.reorder_by_time("alpha", apply=True)
    assert done["applied"] and done["positions"] == {"before": 7, "after": 7}
    order = [store.get_event("alpha", identifier)["text"] for identifier in sorted(
        older["event_ids"] + newer["event_ids"], key=lambda i: store.get_event("alpha", i)["sequence"])]
    assert order[:3] == ["Old question", "Old answer, no timestamp", "Old follow-up with a clock that went backwards"]
    assert order[3:] == [f"October work {i}" for i in range(4)]
    assert store.get_memory("alpha", note["id"])["source_event_ids"] == [older["event_ids"][0]]
    assert store.search("alpha", "Old question")[0]["sequence"] == 0
    assert history_spans(store.context("alpha", 64000)["text"]) == [(i, i) for i in range(7)]
    later = ingest(store, [event(9, "Live record after the reorder")], session="newer")
    assert store.get_event("alpha", later["event_ids"][0])["sequence"] == 7


def test_reorder_interleaves_concurrent_sessions_and_drops_forgotten_gaps(store):
    ingest(store, [event(i, f"A{i}", timestamp=f"2026-10-01T10:0{2 * i}:00Z") for i in range(3)], session="a")
    gone = ingest(store, [event(0, "temporary chat", timestamp="2026-10-01T09:00:00Z")], session="gone")
    ingest(store, [event(i, f"B{i}", timestamp=f"2026-10-01T10:0{2 * i + 1}:00Z") for i in range(3)], session="b")
    store.set_session_privacy("alpha", gone["session_id"], "forgotten")
    assert store.stats("alpha")["events"] == 6
    store.reorder_by_time("alpha", apply=True)
    texts = [hit["excerpt"] for hit in sorted((h for q in ("A0", "A1", "A2", "B0", "B1", "B2") for h in store.search("alpha", q)),
                                               key=lambda h: h["sequence"])]
    assert texts == ["A0", "B0", "A1", "B1", "A2", "B2"]
    assert max(node["hi"] for node in store.view("alpha", max_nodes=1)) == 5  # six positions, no gap marker left


FOREIGN_KEY_INDEXES = ["memories_supersedes", "memories_superseded_by", "memory_sources_event", "memory_keys_memory",
                       "memory_reviews_memory", "memory_reviews_related", "tree_left", "tree_right", "tree_event"]


def test_every_foreign_key_child_column_is_indexed(store):
    # Deleting a referenced row looks up its children; an index that only narrows
    # by project scans the whole project per row (a reorder of ~1M tree nodes stalled).
    con = sqlite3.connect(store.path)
    tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%REFERENCES%'")]
    for table in tables:
        keys = {}
        for row in con.execute(f"PRAGMA foreign_key_list({table})"):
            keys.setdefault(row[0], []).append(row[3])
        for columns in keys.values():
            where = " AND ".join(f"{column}=?" for column in columns)
            plan = " ".join(row[3] for row in con.execute(f"EXPLAIN QUERY PLAN SELECT 1 FROM {table} WHERE {where}", [None] * len(columns)))
            assert re.search(rf"\b{columns[0]}=\?", plan), (table, columns, plan)


def test_opening_an_older_database_adds_the_foreign_key_indexes(tmp_path):
    path = tmp_path / "memory.sqlite3"
    older = Store(path)
    older.create_project("alpha")
    ingest(older, [event(i) for i in range(5)])
    con = sqlite3.connect(path)
    for name in FOREIGN_KEY_INDEXES:
        con.execute(f"DROP INDEX {name}")
    con.commit()
    Store(path)
    present = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert set(FOREIGN_KEY_INDEXES) <= present
    assert Store(path).rebuild_tree("alpha")["events"] == 5


def test_a_moved_transcript_is_the_same_session_but_a_parser_change_is_not(store):
    store.ingest("alpha", "codex", "m", "s", [event(0)], {"adapter_version": 1, "source_path": "/sessions/a.jsonl"})
    moved = store.ingest("alpha", "codex", "m", "s", [event(0)], {"adapter_version": 1, "source_path": "/archived_sessions/a.jsonl"})
    assert moved["duplicates"] == 1
    with pytest.raises(ValueError, match="metadata"):
        store.ingest("alpha", "codex", "m", "s", [event(0)], {"adapter_version": 2, "source_path": "/sessions/a.jsonl"})


def test_recent_chats_name_each_chat_newest_first_and_follow_a_reorder(store):
    old = ingest(store, [event(0, "Plan the vegetable garden", timestamp="2024-01-01T10:00:00Z"),
                         event(1, "Raised beds, south fence.", role="assistant", timestamp="2024-01-01T10:05:00Z")], session="old")
    ingest(store, [event(0, "Fix the sprinkler timer", timestamp="2026-10-01T10:00:00Z"),
                   event(1, "Unsupported Claude record (custom-title); raw source retained.", role="system",
                         raw='{"type":"custom-title","customTitle":"Sprinkler fix"}', timestamp="2026-10-01T10:01:00Z")],
           session="new")
    text = store.context("alpha", 4000, sections=["chats"])["text"]
    lines = [line for line in text.splitlines() if line[:1].isdigit()]
    assert "Sprinkler fix — Fix the sprinkler timer" in lines[0] and "Plan the vegetable garden" in lines[1]
    # Backfilled later, the older chat sorts first once reordered; its line follows its new position.
    ingest(store, [event(2, "Add tomatoes", timestamp="2024-01-01T10:10:00Z")], session="old")
    store.reorder_by_time("alpha", apply=True)
    text = store.context("alpha", 4000, sections=["chats"])["text"]
    assert [line.split(" | ")[0] for line in text.splitlines() if line[:1].isdigit()] == ["3+1", "0+1"]
    assert store.get_event("alpha", old["event_ids"][0])["sequence"] == 0


def test_matches_are_grouped_by_chat_and_sections_are_validated(store):
    ingest(store, [event(i, f"garden hose note {i}") for i in range(5)], session="one")
    ingest(store, [event(0, "garden shed plan")], session="two")
    pack = store.context("alpha", 6000, "please tell me about the garden", ["matches"])
    lines = [line for line in pack["text"].splitlines() if line[:1].isdigit()]
    assert len(lines) == 3 and sum("garden hose" in line for line in lines) == 2
    assert all(" | chat: " in line for line in lines) and "## History" not in pack["text"]
    with pytest.raises(ValueError, match="sections"):
        store.context("alpha", 4000, sections=["everything"])


def test_queries_drop_common_words_and_excerpts_show_the_match(store):
    long = "filler " * 400 + "the sprinkler valve is in the side yard" + " filler" * 400
    ingest(store, [event(0, long)])
    hit = store.search("alpha", "where is the sprinkler valve?")[0]
    assert "sprinkler valve" in hit["excerpt"] and hit["excerpt"].startswith("…")
    assert store._terms("what is it") == ["what", "is", "it"]  # only common words: keep them
    assert store._terms("where is the sprinkler valve") == ["sprinkler", "valve"]
