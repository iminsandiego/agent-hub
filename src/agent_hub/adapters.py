"""Version-aware, loss-preserving import adapters.

Native transcripts are data, never instructions. Each complete JSONL record is
retained, even when the adapter cannot interpret its type. IDs deliberately do
not contain content hashes: a changed record must conflict, not become a second
piece of apparent evidence.
"""

from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class AdapterError(ValueError):
    """A source needs attention before it can be safely imported."""


def stable_event_id(client: str, machine: str, session: str, key: str) -> str:
    value = json.dumps([client, machine, session, key], ensure_ascii=False)
    return "evt_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_text(value: Any) -> str:
    """Extract display text without replacing the retained raw record."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (content_text(item) for item in value)))
    if isinstance(value, dict):
        if value.get("type") == "tool_use":
            return "Tool call: " + str(value.get("name", "unknown")) + "\n" + json.dumps(value.get("input", {}), ensure_ascii=False, sort_keys=True)
        for key in ("text", "output", "content", "message", "arguments"):
            if key in value:
                result = content_text(value[key])
                if result:
                    return result
        return ""
    return "" if value is None else str(value)


def codex_item_text(item: dict[str, Any]) -> str:
    """Index the useful fields of persisted native app-server item variants."""
    kind = item.get("type", "unknown")
    fields: tuple[str, ...] = ()
    if kind == "commandExecution":
        fields = ("command", "cwd", "status", "exitCode", "aggregatedOutput")
    elif kind == "mcpToolCall":
        fields = ("server", "tool", "arguments", "status", "result", "error")
    elif kind == "dynamicToolCall":
        fields = ("namespace", "tool", "arguments", "status", "success", "contentItems")
    if fields:
        lines = ["Codex " + str(kind)]
        for key in fields:
            if item.get(key) is None:
                continue
            value = item[key]
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
            lines.append(key + ": " + rendered)
        return "\n".join(lines)
    return content_text(item) or f"Codex persisted item: {kind}"


@dataclass
class Transcript:
    client: str
    session_id: str
    cwd: str | None
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_bytes: int = 0
    complete_bytes: int = 0
    complete_lines: int = 0
    unknown_types: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_session_id: str | None = None
    temporary: bool = False
    observed_cwds: list[str] = field(default_factory=list)


def _detect_client(records: list[tuple[int, int, str, Any]]) -> str:
    for _, _, _, item in records[:30]:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "session_meta" and isinstance(item.get("payload"), dict):
            return "codex"
        if "sessionId" in item and item.get("type") in {
            "user", "assistant", "system", "progress", "summary", "queue-operation"
        }:
            return "claude"
    raise AdapterError("Unrecognized transcript format; specify --client jsonl for an explicit generic import.")


def _normalize(item: Any, client: str) -> tuple[str, str, bool]:
    if not isinstance(item, dict):
        return "system", "Unsupported JSON value retained in raw source.", False
    kind = str(item.get("type", "unknown"))
    if client == "codex":
        payload = item.get("payload")
        if not isinstance(payload, dict):
            return "system", f"Unsupported Codex record ({kind}); raw source retained.", False
        if kind == "response_item":
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role", "system")
                return role if role in {"user", "assistant", "developer", "system"} else "system", content_text(payload.get("content")), True
            if ptype in {"function_call", "custom_tool_call", "local_shell_call", "web_search_call"}:
                name = payload.get("name", ptype)
                return "assistant", f"Tool call: {name}\n{content_text(payload)}", True
            if ptype in {"function_call_output", "custom_tool_call_output"}:
                return "tool", content_text(payload), True
            if ptype == "reasoning":
                # Only persist what the client actually wrote. Do not reconstruct reasoning.
                return "system", content_text(payload.get("summary")), True
        if kind == "event_msg":
            ptype = payload.get("type")
            if ptype in {"user_message", "agent_message"}:
                return "user" if ptype == "user_message" else "assistant", content_text(payload), True
            return "system", content_text(payload) or f"Codex event: {ptype}", True
        if kind in {"session_meta", "turn_context", "compacted"}:
            return "system", content_text(payload) or f"Codex {kind} metadata.", True
        return "system", f"Unsupported Codex record ({kind}); raw source retained.", False
    if client == "claude":
        if kind in {"user", "assistant"}:
            message = item.get("message", {})
            parts = message.get("content") if isinstance(message, dict) else message
            role = kind
            if isinstance(parts, list) and parts and all(
                isinstance(p, dict) and p.get("type") == "tool_result" for p in parts
            ):
                role = "tool"
            rendered = content_text(parts)
            if not rendered and isinstance(parts, list):
                rendered = "\n".join(
                    "Tool call: " + str(p.get("name", "unknown"))
                    for p in parts if isinstance(p, dict) and p.get("type") == "tool_use"
                )
            return role, rendered, True
        if kind in {"system", "summary", "progress", "queue-operation", "file-history-snapshot"}:
            return "system", content_text(item) or f"Claude {kind} metadata.", True
        return "system", f"Unsupported Claude record ({kind}); raw source retained.", False
    role = item.get("role", "system")
    if role not in {"user", "assistant", "developer", "tool", "system"}:
        role = "system"
    return role, content_text(item), True


def parse_jsonl(
    data: bytes,
    *,
    client: str = "auto",
    machine: str,
    path: str,
    session_id: str | None = None,
    cwd: str | None = None,
    final: bool = False,
    start_line: int = 0,
) -> Transcript:
    """Parse complete records, preserving raw JSON text exactly.

    Watching defers an unterminated final record, even if currently valid JSON,
    since the writer may still append to it. An explicit final import accepts a
    valid final record without a newline. Invalid complete lines fail visibly.
    Blank separator lines count toward source ordinals, but are not events.
    """
    records: list[tuple[int, int, str, Any]] = []
    offset = 0
    complete_lines = 0
    pending = 0
    errors: list[str] = []
    for ordinal, line in enumerate(data.splitlines(keepends=True), start=start_line + 1):
        terminated = line.endswith(b"\n")
        if not terminated and not final:
            pending = len(line)
            break
        try:
            # The JSONL separator is not part of its record. Other whitespace is.
            raw = line[:-1] if terminated else line
            if terminated and raw.endswith(b"\r"):
                raw = raw[:-1]
            text = raw.decode("utf-8")
            if ordinal == 1 and text.startswith("\ufeff"):
                item = json.loads(text[1:])
            elif not text.strip():
                offset += len(line)
                complete_lines = ordinal - start_line
                continue
            else:
                item = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if not terminated:
                pending = len(line)
                break
            errors.append(f"line {ordinal}: {type(exc).__name__}")
            offset += len(line)
            complete_lines = ordinal - start_line
            continue
        offset += len(line)
        complete_lines = ordinal - start_line
        records.append((ordinal, offset, text, item))
    if errors:
        raise AdapterError("Malformed complete transcript records: " + "; ".join(errors[:20]))
    if client == "auto":
        client = _detect_client(records)
    if client not in {"codex", "claude", "jsonl"}:
        raise AdapterError(f"Unsupported JSONL client: {client}")

    native_session = None
    native_cwd = None
    for _, _, _, item in records:
        if not isinstance(item, dict):
            continue
        if client == "codex" and item.get("type") == "session_meta":
            payload = item.get("payload", {})
            if isinstance(payload, dict):
                native_session = payload.get("id") or native_session
                native_cwd = payload.get("cwd") or native_cwd
                break
        if client == "claude":
            native_session = native_session or item.get("sessionId")
            native_cwd = native_cwd or item.get("cwd")
            if native_session and native_cwd:
                break
        if client == "jsonl":
            native_session = native_session or item.get("session_id")
            native_cwd = native_cwd or item.get("cwd")
    resolved_session = str(session_id or native_session or Path(path).stem)
    parts = path.replace("\\", "/").split("/")
    parent_session = None
    if client == "claude" and "subagents" in parts:
        parent_session = resolved_session
        resolved_session += ":subagent:" + Path(parts[-1]).stem
    result = Transcript(
        client=client,
        session_id=resolved_session,
        cwd=str(native_cwd or cwd) if native_cwd or cwd else None,
        pending_bytes=pending,
        complete_bytes=offset,
        complete_lines=complete_lines,
        metadata={"adapter_version": 1, "format": f"{client}_jsonl", "source_path": path},
    )
    if parent_session:
        result.metadata["parent_session_id"] = parent_session
        result.parent_session_id = parent_session
    if client == "codex":
        for _, _, _, record in records:
            if isinstance(record, dict) and record.get("type") == "session_meta":
                payload = record.get("payload", {})
                if isinstance(payload, dict) and isinstance(payload.get("parent_thread_id"), str):
                    result.parent_session_id = payload["parent_thread_id"]

    unknown: set[str] = set()
    for ordinal, end, raw, item in records:
        # Inspect only native metadata fields, never recursively interpret quoted
        # documents or tool output as routing instructions. Keep raw unchanged.
        directories = []
        if isinstance(item, dict):
            directories.append(item.get("cwd"))
            if client == "codex" and item.get("type") in {"session_meta", "turn_context"}:
                payload = item.get("payload", {})
                if isinstance(payload, dict):
                    directories.append(payload.get("cwd"))
        for directory in directories:
            if isinstance(directory, str) and directory and directory not in result.observed_cwds:
                result.observed_cwds.append(directory)
        role, text, known = _normalize(item, client)
        if not known:
            unknown.add(str(item.get("type", "unknown")) if isinstance(item, dict) else "non_object")
        event = {
            "event_id": stable_event_id(client, machine, resolved_session, f"line:{ordinal}"),
            "role": role,
            "text": text,
            "raw": raw,
            "_end_offset": end,
            "_line": ordinal,
        }
        if isinstance(item, dict) and isinstance(item.get("timestamp"), str):
            event["timestamp"] = item["timestamp"]
        result.events.append(event)
    result.unknown_types = sorted(unknown)
    result.metadata["unknown_types"] = result.unknown_types
    return result


class CodexRpcError(AdapterError):
    def __init__(self, code: int | None):
        self.code = code
        super().__init__(f"Codex app-server request failed (code {code}); check the installed protocol version.")


class CodexRpc:
    """Read-only app-server client; no model turns, resume, or login calls."""

    def __init__(self, executable: str = "codex", timeout: float = 15):
        self.timeout = timeout
        self.process = subprocess.Popen(
            [executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", bufsize=1,
        )
        self.inbox: queue.Queue[str | None] = queue.Queue()
        self.counter = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self.inbox.put(line)
        finally:
            self.inbox.put(None)

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.counter += 1
        self._send({"id": self.counter, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                line = self.inbox.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise AdapterError("Codex app-server timed out; no session was resumed.") from exc
            if line is None:
                raise AdapterError("Codex app-server exited before returning its read-only response.")
            message = json.loads(line)
            if message.get("id") != self.counter:
                continue
            if "error" in message:
                raise CodexRpcError(message["error"].get("code"))
            return message.get("result", {})

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def initialize(self) -> None:
        self.call("initialize", {
            "clientInfo": {"name": "agent-hub-export", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True},
        })
        self._send({"method": "initialized", "params": {}})

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.process.stdout:
            self.process.stdout.close()


def export_codex_thread(
    thread_id: str,
    *,
    machine: str,
    executable: str = "codex",
    rpc: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> Transcript:
    """Export persisted completed/failed/interrupted turns through native APIs.

    The export preserves returned item JSON, not nonexistent original JSONL.
    Active turns remain pending, preventing mutable items from being archived as
    immutable history. The caller should repeat the export after the turn ends.
    """
    process = None
    if rpc is None:
        process = CodexRpc(executable)
        try:
            process.initialize()
        except Exception:
            process.close()
            raise
        rpc = process.call
    try:
        thread = rpc("thread/read", {"threadId": thread_id, "includeTurns": False}).get("thread", {})
        turns: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = None
        try:
            while True:
                params: dict[str, Any] = {
                    "threadId": thread_id, "limit": 100,
                    "sortDirection": "asc", "itemsView": "full",
                }
                if cursor is not None:
                    params["cursor"] = cursor
                page = rpc("thread/turns/list", params)
                turns.extend(page.get("data", []))
                cursor = page.get("nextCursor")
                if cursor is None:
                    break
                if cursor in seen:
                    raise AdapterError("Codex returned a repeated pagination cursor; export stopped.")
                seen.add(cursor)
        except CodexRpcError as exc:
            if exc.code not in {-32601, -32602}:
                raise
            legacy = rpc("thread/read", {"threadId": thread_id, "includeTurns": True})
            turns = legacy.get("thread", {}).get("turns", [])
        result = Transcript(
            client="codex-app-server", session_id=thread_id + ":app-server-v2",
            cwd=thread.get("cwd"), metadata={
                "adapter_version": 1, "format": "codex_app_server_v2",
                "native_session_id": thread_id,
                "source_fidelity": "persisted API item JSON; external files and omitted native data are not captured",
                "pending_turns": [],
            },
        )
        for turn in turns:
            if isinstance(turn.get("cwd"), str) and turn["cwd"]:
                result.observed_cwds.append(turn["cwd"])
            turn_id = str(turn.get("id", ""))
            if not turn_id:
                raise AdapterError("A Codex turn has no stable ID.")
            if turn.get("status") not in {"completed", "interrupted", "failed"}:
                result.metadata["pending_turns"].append(turn_id)
                continue
            if turn.get("itemsView") not in {None, "full"}:
                raise AdapterError("Codex returned summarized items despite requesting full history.")
            for ordinal, item in enumerate(turn.get("items", [])):
                if not isinstance(item, dict):
                    raise AdapterError("A Codex persisted item is not a JSON object.")
                item_id = item.get("id") or f"ordinal:{ordinal}"
                kind = item.get("type", "unknown")
                if kind == "commandExecution" and isinstance(item.get("cwd"), str) and item["cwd"]:
                    result.observed_cwds.append(item["cwd"])
                role = "system"
                if kind == "userMessage":
                    role = "user"
                elif kind == "agentMessage":
                    role = "assistant"
                elif kind in {"commandExecution", "mcpToolCall", "dynamicToolCall", "webSearch"}:
                    role = "tool"
                result.events.append({
                    "event_id": stable_event_id(result.client, machine, thread_id, f"turn:{turn_id}:item:{item_id}"),
                    "role": role,
                    "text": codex_item_text(item),
                    "raw": json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                })
        return result
    finally:
        if process is not None:
            process.close()
