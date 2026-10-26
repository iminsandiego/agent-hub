"""Single entry point for server administration and portable clients."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import AdapterError, parse_jsonl
from .client import (
    ClientConfig, ClientError, LocalState, MemoryClient, atomic_write,
    bounded_context, create_gateway, default_config_path, discover_paths, drain_queue,
    enqueue_hook, hook_context, ingest_codex_thread, ingest_file, prompt_context,
)


def output(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def config_for(args: argparse.Namespace) -> ClientConfig:
    return ClientConfig.load(args.config)


def configure(args: argparse.Namespace) -> int:
    target = (Path(args.config).expanduser() if args.config else default_config_path()).resolve()
    existing = ClientConfig.load(target) if target.exists() else None
    mapping = {entry["path"]: entry["project"] for entry in existing.mappings} if existing else {}
    for value in args.map or []:
        if "=" not in value:
            raise ClientError("Use --map 'ABSOLUTE_PATH=PROJECT'.")
        path, project = value.rsplit("=", 1)
        if not path or not project:
            raise ClientError("Each --map needs a path and a project.")
        mapping[path] = project
    env_name = args.token_env or (existing.token_env if existing else "AGENT_HUB_TOKEN")
    token_file = args.token_file or (existing.token_file if existing else None)
    if token_file:
        token_file = str(Path(token_file).expanduser().resolve())
    save_token = args.save_token or (not token_file and not os.environ.get(env_name) and not args.no_prompt)
    if save_token:
        token_file = token_file or str(target.parent / "machine.token")
    if token_file and Path(token_file).resolve() == target:
        raise ClientError("The token file must be separate from client.json.")
    paths = list(dict.fromkeys((existing.capture_paths if existing else []) + (args.capture_path or [])))
    config = ClientConfig(
        url=args.url or (existing.url if existing else ""),
        machine_id=args.machine_id or (existing.machine_id if existing else "machine-" + uuid.uuid4().hex[:16]),
        token_env=env_name, token_file=token_file,
        project=args.project if args.project is not None else (existing.project if existing else None),
        mappings=[{"path": path, "project": project} for path, project in mapping.items()],
        capture_paths=paths,
        state_dir=args.state_dir or (existing.state_dir if existing else str(target.parent / "state")),
        domain=args.domain or (existing.domain if existing else None),
        allowed_projects=args.allow_project if args.allow_project is not None else (existing.allowed_projects if existing else []),
        strict_scope=args.strict_scope or (existing.strict_scope if existing else False),
        t3_database=args.t3_database or (existing.t3_database if existing else None),
        codex_database=args.codex_database or (existing.codex_database if existing else None),
        skills_repo=existing.skills_repo if existing else None,
    )
    # Validate the entire prospective configuration before rotating a credential.
    # An invalid URL or project mapping must leave a working installation intact.
    if save_token:
        if not sys.stdin.isatty() and not os.environ.get(config.token_env):
            raise ClientError("No token available in this noninteractive shell. Set the token environment variable, supply --token-file, or configure interactively.")
        token = (os.environ.get(config.token_env) or getpass.getpass("Agent Hub machine token (hidden): ")).strip()
        if not token or "\n" in token or "\r" in token:
            raise ClientError("Enter a nonempty single-line token; configuration was not saved.")
        atomic_write(Path(config.token_file), (token + "\n").encode("utf-8"))
    config.save(target)
    output({"config": str(target), "machine_id": config.machine_id, "mappings": config.mappings, "capture_paths": config.capture_paths, "credential": "file" if token_file else "environment", "next": "Run agent-hub setup, doctor, and watch."})
    return 0


def setup(args: argparse.Namespace) -> int:
    from .bootstrap import setup_clients
    from .skills import prompt_for_repo, sync_skills, validate_skills_repo
    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    config = config_for(args)
    result = setup_clients(
        config, config_path, clients=args.clients,
        codex_home=args.codex_home, claude_home=args.claude_home,
        claude_mcp_file=args.claude_mcp_file, cursor_home=args.cursor_home, transport=args.transport,
        hooks=not args.no_hooks, dry_run=args.dry_run,
    )
    # Skills come last, so a missing or unreachable repository never blocks the
    # MCP and hook setup above. The address is kept only in client.json.
    repo = config.skills_repo
    if args.skills_repo is not None:
        repo = "" if args.skills_repo == "none" else validate_skills_repo(args.skills_repo)
    elif repo is None and not args.dry_run and sys.stdin.isatty():
        repo = prompt_for_repo()
    if repo != config.skills_repo and not args.dry_run:
        config.skills_repo = repo
        config.save(config_path)
    result["skills"] = sync_skills(repo, config_path, dry_run=args.dry_run)
    output(result)
    return 1 if result["skills"]["status"] == "error" else 0


def doctor(args: argparse.Namespace) -> int:
    config = config_for(args)
    report: dict[str, Any] = {"url": config.url, "machine_id": config.machine_id, "tls_verification": True, "versions": {}}
    ok = True
    try:
        config.token()
        report["credential_available"] = True
    except ClientError as exc:
        report["credential_available"] = False
        report["credential_error"] = str(exc)
        ok = False
    for command in ("codex", "claude"):
        executable = shutil.which(command)
        if not executable:
            report["versions"][command] = "not found on PATH"
            continue
        try:
            result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5, check=False)
            report["versions"][command] = result.stdout.strip().splitlines()[0][:150] if result.stdout.strip() else f"version probe exit {result.returncode}"
        except (OSError, subprocess.TimeoutExpired):
            report["versions"][command] = "version probe unavailable"
    report["queue"] = LocalState(config).status()
    report["capture_paths"] = [{"path": path, "exists": Path(path).expanduser().exists()} for path in config.capture_paths]
    if not args.offline:
        connection = MemoryClient(config, timeout=5)
        try:
            report["health"] = connection.request("GET", "health", auth=False)
            report["authorized_projects"] = connection.request("GET", "v1/projects")
        except Exception as exc:
            report["service_error"] = str(exc) if isinstance(exc, ClientError) else type(exc).__name__
            ok = False
        finally:
            connection.close()
    report["notes"] = [
        "Client configuration is not proof that hooks are trusted or a watcher is running. Check /hooks and /mcp in the actual client.",
        "Codex JSONL is a version-dependent source; a null transcript_path is handled through read-only app-server export.",
        "T3 Code uses the provider configuration on its execution host. Recheck custom CODEX_HOME/CLAUDE_CONFIG_DIR profiles.",
    ]
    output(report)
    return 0 if ok else 1


def ingest(args: argparse.Namespace) -> int:
    config = config_for(args)
    if args.client == "codex-app-server":
        if not args.thread:
            raise ClientError("Codex app-server export requires --thread THREAD_ID.")
        output(ingest_codex_thread(config, args.thread, project=args.project, executable=args.codex_bin))
        return 0
    if args.thread:
        raise ClientError("--thread is only used with --client codex-app-server.")
    if not args.paths:
        raise ClientError("Supply one or more transcript paths.")
    paths: list[Path] = []
    for name in args.paths:
        path = Path(name).expanduser()
        if path.is_dir():
            if not args.recursive:
                raise ClientError("Directory imports require --recursive.")
            paths.extend(sorted(path.rglob("*.jsonl")))
        else:
            paths.append(path)
    if args.session_id and len(paths) != 1:
        raise ClientError("--session-id is only allowed when importing one source file.")
    state = LocalState(config)
    errors = []
    results = []
    for path in paths:
        payload = {"kind": "file", "client": args.client, "path": str(path.resolve()), "project": args.project, "session_id": args.session_id, "final": args.final}
        if args.queue:
            results.append({"path": str(path), "queued": state.enqueue(payload)})
            continue
        try:
            results.append(ingest_file(config, path, client=args.client, project=args.project, session_id=args.session_id, final=args.final, state=state))
        except Exception as exc:
            state.enqueue(payload)
            errors.append({"path": str(path), "error": str(exc) if isinstance(exc, (ClientError, AdapterError)) else type(exc).__name__, "queued_for_retry": True})
    output({"results": results, "errors": errors})
    return 1 if errors else 0


def plan_import(args: argparse.Namespace) -> int:
    """Inventory selected files locally, without tokens, queue writes or uploads."""
    import hashlib
    config = config_for(args)
    paths = set()
    for selected in args.paths:
        root = Path(selected).expanduser().resolve()
        candidates = root.rglob("*.jsonl") if root.is_dir() else [root]
        for path in candidates:
            resolved = path.resolve()
            if root.is_dir() and not resolved.is_relative_to(root):
                continue
            paths.add(resolved)
    records = []
    counts = {}
    for path in sorted(paths):
        entry = {"path": str(path), "status": "blocked"}
        try:
            data = path.read_bytes()
            entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            transcript = parse_jsonl(data, client=args.client, machine=config.machine_id,
                                     path=str(path), final=args.final)
            project = config.resolve_project(transcript.cwd)
            config.check_transcript(transcript, project)
            entry.update(project=project, session_id=transcript.session_id,
                         records=len(transcript.events), pending_bytes=transcript.pending_bytes,
                         unknown_types=transcript.unknown_types,
                         status="pending" if transcript.pending_bytes else "ready")
            counts[project] = counts.get(project, 0) + 1
        except (OSError, ClientError, AdapterError) as exc:
            entry["reason"] = str(exc) if isinstance(exc, (ClientError, AdapterError)) else type(exc).__name__
        records.append(entry)
    report = {"uploaded": False, "queued": False, "domain": config.domain,
              "counts": counts, "sources": records}
    if args.output:
        from .config import write_private
        write_private(Path(args.output).expanduser().resolve(), json.dumps(report, indent=2) + "\n")
        output({"report": str(Path(args.output).expanduser().resolve()), "counts": counts,
                "blocked": sum(r["status"] == "blocked" for r in records), "uploaded": False})
    else:
        output(report)
    return 0


def sync_t3_command(args: argparse.Namespace) -> int:
    from .t3_history import sync_t3
    config = config_for(args)
    try:
        while True:
            result = sync_t3(config, args.database, args.checkpoint, project=args.project)
            if result["captured"] or args.once:
                output(result)
                sys.stdout.flush()
            if args.once:
                return 0
            time.sleep(10)
    except KeyboardInterrupt:
        return 0


def watch(args: argparse.Namespace) -> int:
    config = config_for(args)
    if not 1 <= args.poll_seconds <= 60:
        raise ClientError("--poll-seconds must be between 1 and 60.")
    state = LocalState(config)
    try:
        while True:
            discovered = 0 if args.no_scan else discover_paths(config, state)
            result = drain_queue(config, state=state)
            if args.once or discovered or result["completed"] or result["failed"]:
                output({"discovered": discovered, **result})
                sys.stdout.flush()
            if args.once:
                return 1 if result["failed"] else 0
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return 0


def queue_command(args: argparse.Namespace) -> int:
    state = LocalState(config_for(args))
    if args.action == "list":
        jobs = []
        for job in state.source_gone():
            payload = json.loads(job["payload"])
            jobs.append({"id": job["id"], "kind": payload.get("kind"), "client": payload.get("client"),
                         "source": payload.get("path") or payload.get("session_id"), "last_error": job["last_error"],
                         "attempts": job["attempts"], "parked_at": _iso(job["parked_at"])})
        output({"source_gone": jobs})
        return 0
    if not args.ids and not args.all:
        raise ClientError("Name job IDs to requeue, or use --all.")
    if args.ids and args.all:
        raise ClientError("Use job IDs or --all, not both.")
    output({"requeued": state.requeue(None if args.all else args.ids)})
    return 0


def _iso(timestamp: float | None) -> str | None:
    return None if timestamp is None else datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def hook(args: argparse.Namespace) -> int:
    # Hooks are advisory. Failure must remain visible without blocking editing.
    try:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ClientError("Hook input is too large.")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ClientError("Hook input must be a JSON object.")
        config = config_for(args)
        name = payload.get("hook_event_name")
        if name in {"SessionStart", "Stop", "SessionEnd", "SubagentStop"}:
            enqueue_hook(config, payload, args.client)
        if name == "SessionStart":
            print(json.dumps(hook_context(config, payload), ensure_ascii=False))
        if name == "UserPromptSubmit":
            print(json.dumps(prompt_context(config, payload), ensure_ascii=False))
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ClientError, AdapterError)) else type(exc).__name__
        print("Agent Hub hook: " + message, file=sys.stderr)
    return 0


def context(args: argparse.Namespace) -> int:
    config = config_for(args)
    project = config.resolve_project(args.cwd or os.getcwd(), args.project)
    connection = MemoryClient(config)
    try:
        result = connection.context(project, args.budget_chars, args.query)
        state = LocalState(config)
        state.cache_put(state.cache_key(config, project), bounded_context(str(result.get("text", "")), 8000))
        output(result) if args.json else print(result.get("text", ""))
    finally:
        connection.close()
    return 0


def search(args: argparse.Namespace) -> int:
    config = config_for(args)
    project = config.resolve_project(args.cwd or os.getcwd(), args.project)
    connection = MemoryClient(config)
    try:
        output(connection.search(project, args.query, args.limit))
    finally:
        connection.close()
    return 0


def mcp(args: argparse.Namespace) -> int:
    create_gateway(config_for(args)).run(transport="stdio")
    return 0


def register_commands(subparsers) -> None:
    configure_parser = subparsers.add_parser("configure", help="Configure this computer's memory service connection")
    configure_parser.add_argument("--url")
    configure_parser.add_argument("--machine-id")
    configure_parser.add_argument("--token-env")
    configure_parser.add_argument("--token-file")
    configure_parser.add_argument("--save-token", action="store_true", help="Save the environment token or hidden prompt input in a separate private file")
    configure_parser.add_argument("--no-prompt", action="store_true")
    configure_parser.add_argument("--project", help="Explicit default project; otherwise unmatched paths fail closed")
    configure_parser.add_argument("--map", action="append", metavar="PATH=PROJECT")
    configure_parser.add_argument("--capture-path", action="append")
    configure_parser.add_argument("--state-dir")
    configure_parser.add_argument("--t3-database", help="T3 execution-host database for provider identity linking")
    configure_parser.add_argument("--codex-database", help="Optional local Codex title database for named-chat discovery")
    configure_parser.add_argument("--domain", choices=["home", "work"])
    configure_parser.add_argument("--allow-project", action="append", help="Replace the profile project allowlist; repeat for every allowed project")
    configure_parser.add_argument("--strict-scope", action="store_true", help="Require mapped source cwd evidence throughout each transcript")
    configure_parser.set_defaults(func=configure)
    setup_parser = subparsers.add_parser("setup", help="Merge MCP configuration and lifecycle hooks into local clients")
    setup_parser.add_argument("--clients", nargs="+", choices=["codex", "claude", "cursor", "t3"], default=["codex", "claude"])
    setup_parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    setup_parser.add_argument("--codex-home")
    setup_parser.add_argument("--claude-home")
    setup_parser.add_argument("--claude-mcp-file")
    setup_parser.add_argument("--cursor-home", help="Cursor's settings folder (default ~/.cursor)")
    setup_parser.add_argument("--no-hooks", action="store_true")
    setup_parser.add_argument("--dry-run", action="store_true")
    setup_parser.add_argument("--skills-repo", metavar="URL_OR_PATH", help="Private skills repository to clone/update and install from (saved in client.json); 'none' to stop asking")
    setup_parser.set_defaults(func=setup)
    check = subparsers.add_parser("doctor", help="Inspect credentials, service reachability, versions, and capture queue")
    check.add_argument("--offline", action="store_true")
    check.set_defaults(func=doctor)
    importer = subparsers.add_parser("ingest", help="Import or queue existing native transcripts")
    importer.add_argument("paths", nargs="*")
    importer.add_argument("--client", choices=["auto", "codex", "claude", "cursor", "jsonl", "codex-app-server"], default="auto")
    importer.add_argument("--recursive", action="store_true")
    importer.add_argument("--project")
    importer.add_argument("--session-id")
    importer.add_argument("--final", action="store_true", help="Accept a valid complete final JSON record without a newline")
    importer.add_argument("--queue", action="store_true")
    importer.add_argument("--thread")
    importer.add_argument("--codex-bin", default="codex")
    importer.set_defaults(func=ingest)
    planner = subparsers.add_parser("plan-import", help="Inventory selected JSONL sources locally without queueing or uploading")
    planner.add_argument("paths", nargs="+")
    planner.add_argument("--client", choices=["auto", "codex", "claude", "cursor", "jsonl"], default="auto")
    planner.add_argument("--final", action="store_true")
    planner.add_argument("--output", help="Write a new private inventory file; existing files are preserved")
    planner.set_defaults(func=plan_import)
    t3_sync = subparsers.add_parser("sync-t3", help="Capture T3's saved conversation events read-only across all providers")
    t3_sync.add_argument("--database", required=True)
    t3_sync.add_argument("--checkpoint", required=True)
    t3_sync.add_argument("--project")
    t3_sync.add_argument("--once", action="store_true")
    t3_sync.set_defaults(func=sync_t3_command)
    watcher = subparsers.add_parser("watch", help="Drain durable capture jobs and watch configured transcript paths")
    watcher.add_argument("--once", action="store_true")
    watcher.add_argument("--no-scan", action="store_true")
    watcher.add_argument("--poll-seconds", type=float, default=5)
    watcher.set_defaults(func=watch)
    queue_parser = subparsers.add_parser("queue", help="List capture jobs set aside because their source is gone, or requeue them")
    queue_parser.add_argument("action", choices=["list", "requeue"])
    queue_parser.add_argument("ids", nargs="*", help="Job IDs to requeue (from queue list)")
    queue_parser.add_argument("--all", action="store_true", help="Requeue every set-aside job")
    queue_parser.set_defaults(func=queue_command)
    hook_parser = subparsers.add_parser("hook", help="Read a native hook JSON payload from stdin")
    hook_parser.add_argument("--client", choices=["codex", "claude"], required=True)
    hook_parser.set_defaults(func=hook)
    context_parser = subparsers.add_parser("context", help="Load live project context")
    context_parser.add_argument("--project")
    context_parser.add_argument("--cwd")
    context_parser.add_argument("--budget-chars", type=int, default=8000)
    context_parser.add_argument("--query")
    context_parser.add_argument("--json", action="store_true")
    context_parser.set_defaults(func=context)
    search_parser = subparsers.add_parser("search", help="Search project history")
    search_parser.add_argument("query")
    search_parser.add_argument("--project")
    search_parser.add_argument("--cwd")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.set_defaults(func=search)
    gateway = subparsers.add_parser("mcp", help="Run the official SDK stdio gateway to the remote service")
    gateway.set_defaults(func=mcp)


def build_parser(*, include_admin: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-hub")
    parser.add_argument("--config", help="Client JSON configuration; distinct from --server-config")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_commands(subparsers)
    if include_admin:
        from . import admin
        admin.register_commands(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    # SessionEnd only needs lightweight stdlib+client imports, keeping enqueue
    # inside native hook deadlines without importing server/LLM dependencies.
    parser = build_parser(include_admin="hook" not in arguments)
    args = parser.parse_args(arguments)
    try:
        result = args.func(args)
        return result if isinstance(result, int) else 0
    except (ClientError, AdapterError, ValueError, OSError) as exc:
        print(f"agent-hub: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        import httpx
        if not isinstance(exc, httpx.TransportError):
            raise
        print(f"agent-hub: service connection failed ({type(exc).__name__}). Check agent-hub doctor.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
