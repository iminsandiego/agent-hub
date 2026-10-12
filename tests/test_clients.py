from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import tomlkit

from agent_hub.adapters import AdapterError, CodexRpcError, export_codex_thread, parse_jsonl
from agent_hub.bootstrap import _windows_hook_command, setup_clients
from agent_hub.cli import main
from agent_hub.client import (
    ClientConfig, ClientError, LocalState, MemoryClient, ServiceError,
    discover_paths, drain_queue, enqueue_hook, hook_context, ingest_file,
    validate_url,
)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_AGENT_HUB_TOKEN", "synthetic-test-token")
    return ClientConfig(
        url="http://127.0.0.1:9867", machine_id="test-machine", token_env="TEST_AGENT_HUB_TOKEN",
        mappings=[{"path": str(tmp_path / "work"), "project": "atlas"}],
        state_dir=str(tmp_path / "state"),
    )


def jsonl(*records):
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records).encode("utf-8")


def codex_records(cwd):
    return [
        {"timestamp": "2026-10-07T12:00:00Z", "type": "session_meta", "payload": {"id": "native-1", "cwd": str(cwd)}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Keep naïve Unicode 🧪 intact."}]}},
    ]


class RecordingService:
    def __init__(self):
        self.events = {}
        self.metadata = {}
        self.payloads = []
        self.drop_receipt = False

    def handle(self, request):
        assert request.headers["authorization"] == "Bearer synthetic-test-token"
        payload = json.loads(request.content)
        self.payloads.append(payload)
        session = (payload["project"], payload["client"], payload["machine"], payload["session_id"])
        if session in self.metadata and self.metadata[session] != payload["metadata"]:
            return httpx.Response(409, json={"error": "immutable session metadata changed"})
        self.metadata[session] = payload["metadata"]
        inserted = duplicates = 0
        for event in payload["events"]:
            key = (payload["project"], payload["client"], payload["machine"], payload["session_id"], event["event_id"])
            if key in self.events:
                if self.events[key] != event:
                    return httpx.Response(409, json={"error": "conflict"})
                duplicates += 1
            else:
                self.events[key] = event
                inserted += 1
        if self.drop_receipt:
            self.drop_receipt = False
            raise httpx.ReadTimeout("synthetic lost acknowledgment")
        return httpx.Response(200, json={"session_id": "server-session", "inserted": inserted, "duplicates": duplicates})


def connection(cfg, service):
    return MemoryClient(cfg, transport=httpx.MockTransport(service.handle))


def test_jsonl_raw_unicode_and_stable_identity(tmp_path):
    data = jsonl(*codex_records(tmp_path))
    parsed = parse_jsonl(data, machine="one", path="source.jsonl")
    assert parsed.client == "codex"
    assert parsed.session_id == "native-1"
    assert "🧪" in parsed.events[1]["text"]
    assert parsed.events[1]["raw"] == data.decode().splitlines()[1]
    changed = data.replace("intact".encode(), "changed".encode())
    reparsed = parse_jsonl(changed, machine="one", path="source.jsonl")
    assert parsed.events[1]["event_id"] == reparsed.events[1]["event_id"]
    assert parsed.events[1]["raw"] != reparsed.events[1]["raw"]


def test_partial_tail_and_malformed_complete_lines(tmp_path):
    source = jsonl(*codex_records(tmp_path))
    partial = source + b'{"type":"response_item","payload":'
    parsed = parse_jsonl(partial, machine="one", path="source.jsonl")
    assert len(parsed.events) == 2
    assert parsed.pending_bytes > 0
    assert parsed.complete_bytes == len(source)
    with pytest.raises(AdapterError, match="line 3"):
        parse_jsonl(partial + b"\n", machine="one", path="source.jsonl")


def test_final_import_and_unknown_record_preservation(tmp_path):
    source = jsonl(*codex_records(tmp_path)) + b'{ "type": "future_native_type", "payload": {"x":42} }'
    parsed = parse_jsonl(source, machine="one", path="source.jsonl", final=True)
    assert parsed.events[-1]["raw"] == '{ "type": "future_native_type", "payload": {"x":42} }'
    assert "future_native_type" in parsed.unknown_types
    assert len(parsed.events) == 3


def test_claude_tool_results_and_subagents_have_separate_identity(tmp_path):
    raw = jsonl(
        {"type": "user", "sessionId": "parent", "cwd": str(tmp_path), "uuid": "a", "message": {"content": "hello"}},
        {"type": "user", "sessionId": "parent", "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "result"}]}},
    )
    normal = parse_jsonl(raw, machine="m", path="parent.jsonl")
    child = parse_jsonl(raw, machine="m", path="parent/subagents/agent-one.jsonl")
    assert normal.client == "claude"
    assert normal.events[1]["role"] == "tool"
    assert child.session_id == "parent:subagent:agent-one"
    assert child.events[0]["event_id"] != normal.events[0]["event_id"]


def test_project_mapping_boundaries_unicode_and_windows(cfg, tmp_path):
    cfg.mappings += [
        {"path": str(tmp_path / "work" / "日本語"), "project": "unicode"},
        {"path": r"C:\Work\Atlas", "project": "windows"},
    ]
    assert cfg.resolve_project(str(tmp_path / "work" / "日本語" / "src")) == "unicode"
    assert cfg.resolve_project(r"c:\work\ATLAS\src") == "windows"
    with pytest.raises(ClientError, match="No project mapping"):
        cfg.resolve_project(r"C:\Work\Atlases")
    with pytest.raises(ClientError, match="No project mapping"):
        cfg.resolve_project(r"C:\Work\Atlas\..\Secret")
    with pytest.raises(ClientError, match="No project mapping"):
        cfg.resolve_project(str(tmp_path / "work-other"))


@pytest.mark.parametrize("url", ["http://memory.example.com", "http://localhost.evil.test", "https://secret@example.com", "https://example.com?token=oops"])
def test_unsafe_service_urls_rejected(url):
    with pytest.raises(ClientError):
        validate_url(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080", "http://[::1]:8080", "http://localhost:8080", "https://memory.example.com/hub"])
def test_valid_service_urls(url):
    assert validate_url(url) == url


def test_token_env_precedes_file_and_no_plaintext_config(cfg, tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    token_file.write_text("file-test-token\n")
    cfg.token_file = str(token_file)
    assert cfg.token() == "synthetic-test-token"
    monkeypatch.delenv(cfg.token_env)
    assert cfg.token() == "file-test-token"
    destination = cfg.save(tmp_path / "client.json")
    content = destination.read_text()
    assert "file-test-token" not in content
    assert "synthetic-test-token" not in content
    if os.name != "nt":
        assert destination.stat().st_mode & 0o777 == 0o600


def test_invalid_configuration_does_not_rotate_working_token(cfg, tmp_path, capsys):
    secret = tmp_path / "machine.token"
    secret.write_text("working-old-token\n")
    cfg.token_file = str(secret)
    path = cfg.save(tmp_path / "client.json")
    before = path.read_bytes()
    assert main(["--config", str(path), "configure", "--save-token", "--url", "http://unsafe.example.com"]) == 1
    assert secret.read_text() == "working-old-token\n"
    assert path.read_bytes() == before
    assert "working-old-token" not in capsys.readouterr().err


def test_config_and_secret_cannot_be_same_relative_file(cfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = cfg.save(tmp_path / "client.json")
    before = path.read_bytes()
    assert main(["--config", "client.json", "configure", "--token-file", "client.json", "--save-token"]) == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize("overrides", [{"project": "Other Project"}, {"capture_paths": [""]}, {"mappings": [{"path": "/valid", "project": "../bad"}]}])
def test_invalid_capture_configuration_fails_early(overrides):
    with pytest.raises(ClientError):
        ClientConfig(url="https://example.com", machine_id="machine", **overrides)


def test_append_ingestion_and_prefix_mutation_detection(cfg, tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_bytes(jsonl(*codex_records(tmp_path / "work")))
    service = RecordingService()
    client = connection(cfg, service)
    first = ingest_file(cfg, source, memory=client)
    assert first["inserted"] == 2
    assert ingest_file(cfg, source, memory=client)["inserted"] == 0
    source.write_bytes(source.read_bytes() + jsonl({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"text": "done"}]}}))
    assert ingest_file(cfg, source, memory=client)["inserted"] == 1
    source.write_bytes(source.read_bytes().replace(b"done", b"edited"))
    with pytest.raises(ClientError, match="rewritten"):
        ingest_file(cfg, source, memory=client)
    assert len(service.events) == 3


def test_unknown_types_can_change_without_mutating_session_metadata(cfg, tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_bytes(jsonl(*codex_records(tmp_path / "work")))
    service = RecordingService()
    client = connection(cfg, service)
    ingest_file(cfg, source, memory=client)
    source.write_bytes(source.read_bytes() + jsonl({"type": "future_native_type", "payload": {"x": 42}}))
    result = ingest_file(cfg, source, memory=client)
    assert result["inserted"] == 1
    assert result["unknown_types"] == ["future_native_type"]
    assert service.payloads[0]["metadata"] == service.payloads[1]["metadata"]
    assert "future_native_type" in service.payloads[1]["events"][0]["raw"]


def test_new_session_identity_is_explicit_recovery(cfg, tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_bytes(jsonl(*codex_records(tmp_path / "work")))
    service = RecordingService()
    client = connection(cfg, service)
    ingest_file(cfg, source, memory=client)
    source.write_bytes(source.read_bytes().replace(b"intact", b"changed"))
    result = ingest_file(cfg, source, session_id="reviewed-generation-2", memory=client)
    assert result["inserted"] == 2
    assert len(service.events) == 4


def test_lost_ack_retries_same_ids_without_duplicates(cfg, tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_bytes(jsonl(*codex_records(tmp_path / "work")))
    service = RecordingService()
    service.drop_receipt = True
    client = connection(cfg, service)
    with pytest.raises(httpx.ReadTimeout):
        ingest_file(cfg, source, memory=client)
    retry = ingest_file(cfg, source, memory=client)
    assert retry["inserted"] == 0
    assert retry["duplicates"] == 2
    assert len(service.events) == 2


def test_unmapped_session_cannot_upload(cfg, tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_bytes(jsonl(*codex_records(tmp_path / "private")))
    service = RecordingService()
    with pytest.raises(ClientError, match="No project mapping"):
        ingest_file(cfg, source, memory=connection(cfg, service))
    assert service.payloads == []


def test_hook_outbox_is_offline_and_revision_safe(cfg, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SessionEnd must not use HTTP")
    monkeypatch.setattr(MemoryClient, "request", forbidden)
    state = LocalState(cfg)
    payload = {"session_id": "native-1", "transcript_path": str(tmp_path / "missing.jsonl"), "cwd": str(tmp_path / "work"), "hook_event_name": "SessionEnd"}
    identifier = enqueue_hook(cfg, payload, "codex", state)
    original_job = state.due_jobs()[0]
    assert enqueue_hook(cfg, payload, "codex", state) == identifier
    state.completed(original_job)
    assert state.status()["pending_jobs"] == 1
    assert state.due_jobs()[0]["revision"] != original_job["revision"]


def test_stale_drainer_cannot_delete_or_delay_recreated_queue_job(cfg):
    state = LocalState(cfg)
    payload = {"kind": "file", "client": "codex", "path": "/source.jsonl"}
    identifier = state.enqueue(payload)
    old = state.due_jobs()[0]
    state.completed(old)
    assert state.enqueue(payload) == identifier
    state.completed(old)
    state.failed(old, ClientError("stale failure"))
    new = state.due_jobs()[0]
    assert new["revision"] != old["revision"]
    assert new["attempts"] == 0
    assert new["last_error"] is None


def test_offline_queue_survives_and_drains_on_retry(cfg, tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_bytes(jsonl(*codex_records(tmp_path / "work")))
    state = LocalState(cfg)
    enqueue_hook(cfg, {"transcript_path": str(source), "session_id": "native-1", "cwd": str(tmp_path / "work"), "hook_event_name": "Stop"}, "codex", state)
    offline = MemoryClient(cfg, transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    failed = drain_queue(cfg, state=state, memory=offline)
    assert failed["failed"] == 1
    assert LocalState(cfg).status()["pending_jobs"] == 1
    service = RecordingService()
    done = drain_queue(cfg, state=state, memory=connection(cfg, service), now=10**12)
    assert done["completed"] == 1
    assert done["pending_jobs"] == 0
    assert len(service.events) == 2


def test_state_is_separate_for_other_server(cfg):
    first = LocalState(cfg)
    first.enqueue({"kind": "file", "client": "codex", "path": "/source.jsonl"})
    cfg.url = "https://other.example.com"
    assert LocalState(cfg).status()["pending_jobs"] == 0


def test_context_cache_fallback_is_bounded_and_auth_failure_does_not_use_it(cfg, tmp_path):
    payload = {"cwd": str(tmp_path / "work")}
    online = MemoryClient(cfg, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"text": "history\n" * 5000})))
    result = hook_context(cfg, payload, budget_chars=400, memory=online)
    assert len(result["hookSpecificOutput"]["additionalContext"]) <= 400
    offline = MemoryClient(cfg, transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    result = hook_context(cfg, payload, budget_chars=400, memory=offline)
    assert "Cached" in result["hookSpecificOutput"]["additionalContext"]
    assert len(result["hookSpecificOutput"]["additionalContext"]) <= 400
    denied = MemoryClient(cfg, transport=httpx.MockTransport(lambda request: httpx.Response(403, json={})))
    with pytest.raises(ServiceError):
        hook_context(cfg, payload, memory=denied)


def test_stale_cache_expires_and_credential_change_cannot_reuse_cache(cfg, tmp_path, monkeypatch):
    state = LocalState(cfg)
    key = state.cache_key(cfg, "atlas")
    state.cache_put(key, "old history")
    offline = MemoryClient(cfg, transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    with state.connect() as db:
        db.execute("UPDATE cache SET captured_at=?", (time.time() - 8 * 24 * 3600,))
    assert hook_context(cfg, {"cwd": str(tmp_path / "work")}, memory=offline) == {}
    state.cache_put(key, "old account history")
    monkeypatch.setenv(cfg.token_env, "different-synthetic-credential")
    assert hook_context(cfg, {"cwd": str(tmp_path / "work")}, memory=offline) == {}


def test_setup_preserves_unrelated_settings_is_idempotent_and_has_no_secret(cfg, tmp_path):
    codex_home = tmp_path / "codex settings"
    claude_home = tmp_path / "claude settings"
    codex_home.mkdir()
    claude_home.mkdir()
    codex_file = codex_home / "config.toml"
    codex_file.write_text('# user comment\nmodel = "my-model"\n[mcp_servers.other]\ncommand="keep-me"\n')
    hooks_file = codex_home / "hooks.json"
    hooks_file.write_text(json.dumps({"description": "mine", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "my-existing-hook"}]}]}}))
    claude_mcp = tmp_path / "claude-app.json"
    claude_mcp.write_text(json.dumps({"somePrivateState": "preserve", "mcpServers": {"other": {"command": "keep"}}}))
    claude_settings = claude_home / "settings.json"
    claude_settings.write_text(json.dumps({"permissions": {"deny": ["Bash(rm *)"]}}))
    config_path = cfg.save(tmp_path / "client with spaces.json")
    kwargs = dict(codex_home=codex_home, claude_home=claude_home, claude_mcp_file=claude_mcp, executable=sys.executable)
    first = setup_clients(cfg, config_path, **kwargs)
    assert first["changed"]
    assert first["backups"]
    second = setup_clients(cfg, config_path, **kwargs)
    assert second["changed"] == []
    assert second["backups"] == []
    codex = tomlkit.parse(codex_file.read_text())
    assert codex["model"] == "my-model"
    assert codex["mcp_servers"]["other"]["command"] == "keep-me"
    assert "# user comment" in codex_file.read_text()
    hooks = json.loads(hooks_file.read_text())
    assert hooks["description"] == "mine"
    assert hooks["hooks"]["Stop"][0]["hooks"][0]["command"] == "my-existing-hook"
    assert len(hooks["hooks"]["Stop"]) == 2
    claude = json.loads(claude_mcp.read_text())
    assert claude["somePrivateState"] == "preserve"
    assert claude["mcpServers"]["other"]["command"] == "keep"
    settings = json.loads(claude_settings.read_text())
    assert settings["permissions"]["deny"] == ["Bash(rm *)"]
    assert settings["hooks"]["SessionStart"][0]["hooks"][0]["args"]
    for target in [codex_file, hooks_file, claude_mcp, claude_settings]:
        assert "synthetic-test-token" not in target.read_text()


def test_setup_conflict_does_not_write_other_files(cfg, tmp_path):
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    claude_mcp = tmp_path / "claude-app.json"
    claude_mcp.write_text(json.dumps({"mcpServers": {"agent-hub": {"command": "someone-else"}}}))
    with pytest.raises(ClientError, match="unrelated"):
        setup_clients(cfg, tmp_path / "client.json", codex_home=codex_home, claude_home=claude_home, claude_mcp_file=claude_mcp)
    assert not (codex_home / "config.toml").exists()


def test_native_http_configs_reference_env_only(cfg, tmp_path):
    c = tmp_path / "codex"
    a = tmp_path / "claude-app.json"
    setup_clients(cfg, tmp_path / "client.json", codex_home=c, claude_home=tmp_path / "claude", claude_mcp_file=a, transport="http", hooks=False)
    codex = tomlkit.parse((c / "config.toml").read_text())
    assert codex["mcp_servers"]["agent-hub"]["bearer_token_env_var"] == cfg.token_env
    assert json.loads(a.read_text())["mcpServers"]["agent-hub"]["headers"]["Authorization"] == "Bearer ${TEST_AGENT_HUB_TOKEN}"


def test_t3_setup_does_not_invent_native_settings(cfg, tmp_path):
    result = setup_clients(cfg, tmp_path / "client.json", clients=["t3"])
    assert result["changed"] == []
    assert "provider" in result["notes"][0]


def test_windows_hook_quoting_rejects_shell_metacharacters():
    assert _windows_hook_command([r"C:\Program Files\Python\python.exe", "-m", "agent_hub.cli"]).startswith('"C:\\Program Files\\Python\\python.exe"')
    for path in [r"C:\Work&Audit\python.exe", r"C:\%USERNAME%\python.exe", "C:\\work\\`name\\python.exe"]:
        with pytest.raises(ClientError, match="metacharacters"):
            _windows_hook_command([path, "-m", "agent_hub.cli"])


def test_codex_export_pages_full_persisted_items_and_skips_active_turns():
    calls = []
    def rpc(method, params):
        calls.append((method, params))
        if method == "thread/read":
            return {"thread": {"cwd": "/work/atlas"}}
        assert params["itemsView"] == "full"
        if "cursor" not in params:
            return {"data": [{"id": "one", "status": "completed", "itemsView": "full", "items": [{"type": "userMessage", "id": "u1", "content": [{"text": "ask"}]}]}], "nextCursor": "page2"}
        return {"data": [{"id": "two", "status": "inProgress", "items": []}], "nextCursor": None}
    result = export_codex_thread("thread-1", machine="m", rpc=rpc)
    assert len(result.events) == 1
    assert result.events[0]["text"] == "ask"
    assert result.metadata["pending_turns"] == ["two"]
    assert all(method in {"thread/read", "thread/turns/list"} for method, _ in calls)


def test_codex_export_legacy_fallback_and_repeated_cursor():
    def legacy(method, params):
        if method == "thread/turns/list":
            raise CodexRpcError(-32601)
        return {"thread": {"cwd": "/work", "turns": [{"id": "t", "status": "completed", "items": [{"id": "a", "type": "agentMessage", "text": "done"}]}]}}
    assert export_codex_thread("one", machine="m", rpc=legacy).events[0]["text"] == "done"
    def repeated(method, params):
        return {"thread": {"cwd": "/work"}} if method == "thread/read" else {"data": [], "nextCursor": "repeat"}
    with pytest.raises(AdapterError, match="repeated pagination"):
        export_codex_thread("one", machine="m", rpc=repeated)


def test_codex_tool_item_normalization_preserves_searchable_evidence():
    items = [
        {"id": "shell", "type": "commandExecution", "command": "pytest integration", "aggregatedOutput": "37 passed", "cwd": "/work", "status": "completed", "exitCode": 0},
        {"id": "mcp", "type": "mcpToolCall", "server": "project-api", "tool": "fetch_issue", "arguments": {"id": 27}, "status": "completed", "result": {"content": [{"text": "Issue detail"}]}, "error": None},
        {"id": "dynamic", "type": "dynamicToolCall", "namespace": "functions", "tool": "lookup", "arguments": {"key": "value"}, "success": True, "status": "completed", "contentItems": [{"text": "lookup result"}]},
    ]
    def rpc(method, params):
        return {"thread": {"cwd": "/work"}} if method == "thread/read" else {"data": [{"id": "turn", "status": "completed", "items": items}], "nextCursor": None}
    result = export_codex_thread("thread", machine="m", rpc=rpc)
    assert "pytest integration" in result.events[0]["text"]
    assert "37 passed" in result.events[0]["text"]
    assert "fetch_issue" in result.events[1]["text"] and "Issue detail" in result.events[1]["text"]
    assert "lookup result" in result.events[2]["text"]
    assert [json.loads(event["raw"]) for event in result.events] == items
    assert result.session_id == "thread:app-server-v2"


def test_claude_mixed_assistant_text_and_tool_calls_are_both_searchable():
    source = jsonl({"type": "assistant", "sessionId": "one", "message": {"content": [
        {"type": "text", "text": "I will inspect the code."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/work/module.py"}},
    ]}})
    event = parse_jsonl(source, machine="m", path="one.jsonl").events[0]
    assert "inspect the code" in event["text"]
    assert "Tool call: Read" in event["text"]
    assert "/work/module.py" in event["text"]


def test_client_against_real_authenticated_service_contract(cfg, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from agent_hub.config import ServerSettings
    from agent_hub.server import create_app

    app = create_app(ServerSettings(data_dir=tmp_path / "server"))
    app.state.store.create_project("atlas", "Atlas")
    _, token = app.state.auth.issue("client-contract", ["atlas"], ["read", "write"])
    monkeypatch.setenv(cfg.token_env, token)
    source = tmp_path / "session.jsonl"
    source.write_bytes(jsonl(*codex_records(tmp_path / "work")))
    with TestClient(app, base_url="http://localhost") as native:
        def forward(request):
            return native.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
        client = MemoryClient(cfg, transport=httpx.MockTransport(forward))
        assert ingest_file(cfg, source, memory=client)["inserted"] == 2
        source.write_bytes(source.read_bytes() + jsonl({"type": "future_record", "payload": {"untouched": "🧪"}}))
        assert ingest_file(cfg, source, memory=client)["inserted"] == 1
        assert ingest_file(cfg, source, memory=client)["inserted"] == 0
        context = client.context("atlas", budget_chars=256)
        assert context["project"] == "atlas" and "text" in context
        found = client.search("atlas", "Unicode")
        event_id = found[0]["event_id"]
        text_page = client.get("atlas", "event", event_id, max_chars=10)
        assert len(text_page["text"]) == 10 and "raw" not in text_page
        raw_page = client.get("atlas", "event", event_id, representation="raw", max_chars=24000)
        assert raw_page["raw"] == source.read_text().splitlines()[1]
        assert "text" not in raw_page
        with pytest.raises(ServiceError) as denied:
            client.context("harbor")
        assert denied.value.status == 403
        client.close()


def test_codex_rpc_transport_against_synthetic_process(tmp_path, monkeypatch):
    from agent_hub import adapters
    script = tmp_path / "fake_codex.py"
    script.write_text('''import json,sys
for line in sys.stdin:
    request=json.loads(line)
    if "id" not in request: continue
    method=request["method"]
    if method=="initialize": result={"userAgent":"synthetic"}
    elif method=="thread/read": result={"thread":{"cwd":"/work"}}
    elif method=="thread/turns/list": result={"data":[{"id":"t","status":"completed","itemsView":"full","items":[{"id":"a","type":"agentMessage","text":"fixture"}]}],"nextCursor":None}
    else: raise RuntimeError("Unexpected mutation or model call")
    print(json.dumps({"id":request["id"],"result":result}),flush=True)
''')
    real_popen = subprocess.Popen
    def fake_popen(argv, **kwargs):
        assert argv == ["codex-test", "app-server", "--stdio"]
        return real_popen([sys.executable, str(script)], **kwargs)
    monkeypatch.setattr(adapters.subprocess, "Popen", fake_popen)
    result = export_codex_thread("thread-test", machine="m", executable="codex-test")
    assert result.events[0]["text"] == "fixture"


def test_official_sdk_stdio_round_trip_to_http(cfg, tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            body = json.dumps({"project": "atlas", "text": "synthetic source-backed context", "truncated": False}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg.url = f"http://127.0.0.1:{server.server_port}"
    config_path = cfg.save(tmp_path / "client.json")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "agent_hub.cli", "--config", str(config_path), "mcp"], env=environment)
    async def exercise():
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {"memory_context", "memory_search", "memory_get", "memory_zoom", "memory_note"}
                response = await session.call_tool("memory_context", {"project": "atlas", "budget_chars": 1000})
                assert not response.isError
                assert "synthetic source-backed context" in str(response.content)
    try:
        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert requests[0][0].startswith("/v1/projects/atlas/context?")
    assert requests[0][1] == "Bearer synthetic-test-token"
