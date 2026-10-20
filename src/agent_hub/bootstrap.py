"""Idempotent, reversible client setup that preserves unrelated settings."""

from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import ClientConfig, ClientError, atomic_write


@dataclass
class FileChange:
    path: Path
    before: bytes | None
    after: bytes


def _json_file(path: Path) -> tuple[dict[str, Any], bytes | None]:
    if not path.exists():
        return {}, None
    original = path.read_bytes()
    try:
        value = json.loads(original)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ClientError(f"Cannot merge invalid JSON: {path}; the file was not changed.") from exc
    if not isinstance(value, dict):
        raise ClientError(f"Expected a JSON object in {path}; the file was not changed.")
    return value, original


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def launch_arguments(config_path: Path) -> list[str]:
    return ["-m", "agent_hub.cli", "--config", str(config_path.resolve()), "mcp"]


def _server_entry(client: str, config: ClientConfig, config_path: Path, executable: str, transport: str) -> dict[str, Any]:
    if transport == "stdio":
        entry: dict[str, Any] = {"command": executable, "args": launch_arguments(config_path)}
        if client == "codex":
            entry["env_vars"] = [config.token_env]
        else:
            entry["type"] = "stdio"
        return entry
    if client == "codex":
        return {"url": config.url + "/mcp", "bearer_token_env_var": config.token_env}
    return {"type": "http", "url": config.url + "/mcp", "headers": {"Authorization": "Bearer ${" + config.token_env + "}"}}


def _windows_hook_command(argv: list[str]) -> str:
    # Native Codex can launch command strings through cmd.exe or a configured
    # shell. list2cmdline alone does not escape shell metacharacters. Refuse
    # ambiguous paths instead of producing a command that changes their meaning.
    forbidden = set('&|<>^%!"\r\n\t`$;(){}')
    if any(any(character in forbidden for character in argument) for argument in argv):
        raise ClientError("Windows Codex hook paths contain shell metacharacters. Use plain installation/config paths, or --no-hooks with explicit transcript capture paths.")
    return subprocess.list2cmdline(argv)


def _hook_handler(client: str, config_path: Path, executable: str, event: str) -> dict[str, Any]:
    argv = ["-m", "agent_hub.cli", "--config", str(config_path.resolve()), "hook", "--client", client]
    handler: dict[str, Any] = {"type": "command", "timeout": {"SessionStart": 2, "UserPromptSubmit": 3}.get(event, 1)}
    if client == "claude":
        # Current Claude exec-form hooks never reparse paths through a shell.
        handler.update(command=executable, args=argv)
    else:
        # Codex's documented command schema has no args array. Setup chooses
        # quoting for the machine on which the generated hook will execute.
        command = _windows_hook_command([executable, *argv]) if os.name == "nt" else shlex.join([executable, *argv])
        handler["command"] = command
        if os.name == "nt":
            handler["commandWindows"] = command
        if event in {"SessionStart", "UserPromptSubmit"}:
            # Codex counts this limit in tokens and, past it, keeps the start and
            # end of the text (default about 2,500; measured with 0.163.0). The
            # client sends at most HOOK_CONTEXT_CHARS (9,500) characters; code- and
            # JSON-heavy history runs about 2.2 characters per token (4,300 tokens).
            handler["additionalContextLimit"] = 6000
    return handler


def _our_hook(handler: Any, client: str) -> bool:
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    argv = handler.get("args")
    if isinstance(argv, list):
        return "agent_hub.cli" in argv and "hook" in argv and client in argv
    command = handler.get("command", "")
    return isinstance(command, str) and "agent_hub.cli" in command and " hook " in command and f"--client {client}" in command


def _merge_hooks(value: dict[str, Any], client: str, config_path: Path, executable: str) -> None:
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ClientError("Existing hooks must be an object; setup did not overwrite them.")
    events = ["SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"]
    if client == "claude":
        events.append("SubagentStop")
    for event in events:
        original = hooks.get(event, [])
        if not isinstance(original, list):
            raise ClientError(f"Existing {event} hooks have an unsupported shape.")
        groups = []
        for group in original:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ClientError(f"Existing {event} matcher group has an unsupported shape.")
            preserved = [h for h in group["hooks"] if not _our_hook(h, client)]
            if preserved:
                copied = copy.deepcopy(group)
                copied["hooks"] = preserved
                groups.append(copied)
        group = {"hooks": [_hook_handler(client, config_path, executable, event)]}
        if event == "SessionStart":
            group["matcher"] = "startup|resume|clear|compact" + ("|fork" if client == "claude" else "")
        groups.append(group)
        hooks[event] = groups


def _may_replace(path: Path, current: Any, expected: dict[str, Any], managed: dict[str, Any]) -> None:
    previous = managed.get(str(path), {}).get("server")
    if current is not None and current != expected and current != previous:
        raise ClientError(f"An unrelated or manually changed MCP named agent-hub already exists in {path}; rename it or resolve the conflict before setup.")


def setup_clients(
    config: ClientConfig,
    config_path: str | Path,
    *,
    clients: list[str] | tuple[str, ...] = ("codex", "claude"),
    codex_home: str | Path | None = None,
    claude_home: str | Path | None = None,
    claude_mcp_file: str | Path | None = None,
    executable: str | None = None,
    transport: str = "stdio",
    hooks: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    import tomlkit

    if transport not in {"stdio", "http"}:
        raise ClientError("transport must be stdio or http.")
    unknown = set(clients) - {"codex", "claude", "t3"}
    if unknown:
        raise ClientError("Unknown client selection.")
    requested = list(dict.fromkeys(clients))
    notes = []
    if "t3" in requested:
        requested.remove("t3")
        notes.append("T3 Code uses its provider configuration on the execution host. Select codex and/or claude for the actual provider; there is no separate T3 memory hook installed.")
    if not requested:
        return {"changed": [], "backups": [], "notes": notes}
    if transport == "http" and config.token_file:
        notes.append(f"Direct HTTP MCP reads {config.token_env}; native clients cannot read Agent Hub's token_file. The local hooks still use token_file. Use stdio to avoid relying on desktop environment inheritance.")
    config_path = Path(config_path).expanduser().resolve()
    executable = executable or sys.executable
    if not Path(executable).is_absolute() and not (len(executable) > 2 and executable[1] == ":"):
        raise ClientError("Setup needs an absolute Python executable path.")
    state_path = config.local_state_dir() / "setup-managed.json"
    managed, state_before = _json_file(state_path)
    plans: list[FileChange] = []

    if "codex" in requested:
        home = Path(codex_home or os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        target = home / "config.toml"
        original = target.read_bytes() if target.exists() else None
        try:
            document = tomlkit.parse(original.decode("utf-8")) if original is not None else tomlkit.document()
        except Exception as exc:
            raise ClientError(f"Cannot merge invalid TOML: {target}; the file was not changed.") from exc
        if "mcp_servers" not in document:
            document["mcp_servers"] = tomlkit.table()
        servers = document["mcp_servers"]
        if not isinstance(servers, dict):
            raise ClientError("Existing Codex mcp_servers must be a TOML table.")
        entry = _server_entry("codex", config, config_path, executable, transport)
        current = servers.get("agent-hub")
        current_value = current.unwrap() if hasattr(current, "unwrap") else current
        _may_replace(target, current_value, entry, managed)
        if current_value != entry:
            servers["agent-hub"] = tomlkit.item(entry)
        plans.append(FileChange(target, original, tomlkit.dumps(document).encode("utf-8")))
        managed[str(target)] = {"server": entry}
        if hooks:
            hook_path = home / "hooks.json"
            hook_config, hook_original = _json_file(hook_path)
            _merge_hooks(hook_config, "codex", config_path, executable)
            plans.append(FileChange(hook_path, hook_original, _json_bytes(hook_config)))
            notes.append("In Codex, review and trust the generated hooks using /hooks. Setup does not bypass hook trust or managed policy.")

    if "claude" in requested:
        overridden = claude_home is not None or bool(os.environ.get("CLAUDE_CONFIG_DIR"))
        home = Path(claude_home or os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()
        if claude_mcp_file:
            mcp_path = Path(claude_mcp_file).expanduser()
        elif overridden and home != Path.home() / ".claude":
            # Avoid guessing where a particular Claude version stores global
            # application state for custom profiles. Its CLI can install user
            # MCP configs, or the caller can supply the verified file path.
            raise ClientError("For a custom Claude profile, pass --claude-mcp-file with its verified global MCP configuration file. This prevents modifying another account's settings.")
        else:
            mcp_path = Path.home() / ".claude.json"
        document, original = _json_file(mcp_path)
        servers = document.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise ClientError("Existing Claude mcpServers must be a JSON object.")
        entry = _server_entry("claude", config, config_path, executable, transport)
        _may_replace(mcp_path, servers.get("agent-hub"), entry, managed)
        servers["agent-hub"] = entry
        plans.append(FileChange(mcp_path, original, _json_bytes(document)))
        managed[str(mcp_path)] = {"server": entry}
        if hooks:
            hook_path = home / "settings.json"
            hook_config, hook_original = _json_file(hook_path)
            _merge_hooks(hook_config, "claude", config_path, executable)
            plans.append(FileChange(hook_path, hook_original, _json_bytes(hook_config)))
            notes.append("Restart Claude Code and inspect /mcp and /hooks. Workspace trust and organization policies still apply.")

    plans.append(FileChange(state_path, state_before, _json_bytes(managed)))
    changes = [change for change in plans if change.before != change.after]
    if dry_run:
        return {"changed": [str(change.path) for change in changes], "backups": [], "dry_run": True, "notes": notes}
    backups = []
    # Validate all existing content before any mutation. Repeated setup normally
    # has no writes and never duplicates its own hook handlers.
    for change in changes:
        live = change.path.read_bytes() if change.path.exists() else None
        if live != change.before:
            raise ClientError(f"Settings changed concurrently: {change.path}; rerun setup after the client finishes saving.")
    for change in changes:
        if change.before is not None:
            backup = change.path.with_name(change.path.name + f".agent-hub-backup-{time.time_ns()}")
            atomic_write(backup, change.before)
            backups.append(str(backup))
        atomic_write(change.path, change.after)
    notes.append("Run agent-hub watch as a background service to drain capture jobs. Hooks alone do not upload transcripts.")
    return {"changed": [str(change.path) for change in changes], "backups": backups, "notes": notes}
