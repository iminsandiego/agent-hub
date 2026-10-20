"""Server administration stays local; agent-facing MCP cannot approve memories."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .auth import AuthStore
from .config import ServerSettings, load_settings, write_private
from .store import Store


def output(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def settings_for(args) -> ServerSettings:
    settings = load_settings(getattr(args, "server_config", None))
    if getattr(args, "data_dir", None):
        settings = settings.model_copy(update={"data_dir": Path(args.data_dir).expanduser().resolve()})
    return settings


def common(parser):
    parser.add_argument("--server-config", help="Server settings JSON (separate from client --config)")
    parser.add_argument("--data-dir", help="Local server data directory; never a network-mounted SQLite file")


def init_server(args):
    settings = settings_for(args)
    settings.domain = args.domain or settings.domain
    selected = args.project or [settings.domain + "-personal" if settings.domain else "personal"]
    for project in selected:
        settings.check_project(project)
    if args.host:
        settings.host = args.host
    path = settings.data_dir / "server.json"
    token_path = settings.data_dir / "admin.token"
    if path.exists() or settings.auth_database.exists() or token_path.exists():
        raise ValueError("Server is already initialized; existing data and credentials were left intact")
    store = Store(settings.database)
    for project in selected:
        store.create_project(project)
    token_id, token = AuthStore(settings.auth_database).issue("local-administrator", ["*"], ["admin"])
    write_private(token_path, token + "\n")
    write_private(path, settings.model_dump_json(indent=2) + "\n")
    output({"server_config": str(path), "admin_token_file": str(token_path), "token_id": token_id,
            "projects": selected, "next": "Issue a separate scoped token for each computer"})


def serve(args):
    import uvicorn
    from .server import create_app
    settings = settings_for(args)
    if not settings.auth_database.exists() or not AuthStore(settings.auth_database).list():
        raise ValueError("Run init-server before serve; an empty server has no usable credentials")
    uvicorn.run(create_app(settings), host=args.host or settings.host,
                port=args.port or settings.port, access_log=False, log_level="info")


def projects(args):
    settings = settings_for(args)
    store = Store(settings.database)
    if args.action == "create":
        if not args.project:
            raise ValueError("project create requires a project identifier")
        settings.check_project(args.project)
        output(store.create_project(args.project, args.name))
    else:
        output(store.list_projects())


def tokens(args):
    settings = settings_for(args)
    auth = AuthStore(settings.auth_database)
    if args.action == "list":
        output(auth.list())
    elif args.action == "revoke":
        if not args.id:
            raise ValueError("token revoke requires --id")
        auth.revoke(args.id)
        output({"revoked": args.id})
    else:
        if not args.name or not args.project or not args.output:
            raise ValueError("token create requires --name, one or more --project, and --output")
        for project in args.project:
            settings.check_project(project)
            if project == "*":
                raise ValueError("Client token creation requires explicit projects; use the existing local admin token for administration")
            known = Store(settings.database).list_projects()
            if project not in {p.get("project", p.get("id")) for p in known}:
                raise ValueError("Create project before issuing its token: " + project)
        destination = Path(args.output).expanduser().resolve()
        if destination.exists():
            raise ValueError("Token output file already exists; use a new path")
        token_id, secret = auth.issue(args.name, args.project, args.permissions.split(","))
        try:
            write_private(destination, secret + "\n")
        except BaseException:
            auth.revoke(token_id)
            raise
        output({"id": token_id, "name": args.name, "projects": args.project, "token_file": str(destination)})


def review(args):
    store = Store(settings_for(args).database)
    output(store.review_memory(args.project, args.id, args.status, args.supersedes))


def backup(args):
    store = Store(settings_for(args).database)
    destination = Path(args.output).expanduser().resolve()
    if destination.exists():
        raise ValueError("Backup destination exists; choose a new filename")
    output(store.backup(destination))


def restore(args):
    settings = settings_for(args)
    source = Path(args.source).expanduser().resolve()
    if any(path.exists() for path in (settings.database, settings.auth_database,
                                     settings.data_dir / "server.json", settings.data_dir / "admin.token")):
        raise ValueError("Restore requires an empty data directory")
    if not source.is_file():
        raise ValueError("Backup does not exist")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='projects'").fetchone():
            raise ValueError("This is not an Agent Hub memory backup")
    if not args.privacy_ledger:
        raise ValueError("Restore requires --privacy-ledger pointing to the CURRENT exclusion ledger, not an old backup copy")
    ledger_source = Path(args.privacy_ledger).expanduser().resolve()
    with closing(sqlite3.connect(ledger_source.as_uri() + "?mode=ro", uri=True)) as ledger:
        if ledger.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or not ledger.execute("SELECT 1 FROM sqlite_master WHERE name='identities'").fetchone():
            raise ValueError("Invalid privacy ledger")
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    ledger_target = Path(str(settings.database) + ".privacy.sqlite3")
    if ledger_target.exists():
        raise ValueError("Restore will not overwrite an existing privacy ledger")
    write_private(settings.database, "")
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(settings.database)) as target:
                src.backup(target)
        write_private(ledger_target, "")
        with closing(sqlite3.connect(ledger_source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(ledger_target)) as target:
                src.backup(target)
        store = Store(settings.database)
        output({"restored": str(settings.database), "projects": store.list_projects(),
                "next": "Run init-server to create fresh administrative credentials; restored projects will be retained"})
    except BaseException:
        settings.database.unlink(missing_ok=True)
        ledger_target.unlink(missing_ok=True)
        raise


def _renumbering(args, change):
    """Run a position-changing store operation under the worker lock, then move
    the worker's checkpoints to the new positions (reorder and prune)."""
    settings = settings_for(args)
    import sqlite3
    from .worker import _connection as worker_ledger
    lock = sqlite3.connect(settings.data_dir / ("worker-lock-" + args.project + ".sqlite3"), timeout=0)
    try:
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise ValueError("A worker run holds this project's lock; retry when it finishes") from None
        result = change(Store(settings.database))
        mapping = result.pop("sequence_map")
        ledger = worker_ledger(settings)
        try:
            cursors = {}
            for stage, cursor in ledger.execute("SELECT stage,sequence FROM checkpoints WHERE project=?", (args.project,)).fetchall():
                # Resume just before the first record this stage had not reached; records
                # after it that were already processed are revisited idempotently.
                pending = [new for old, new in mapping.items() if old > cursor]
                cursors[stage] = (min(pending) - 1) if pending else len(mapping) - 1
                ledger.execute("UPDATE checkpoints SET sequence=? WHERE project=? AND stage=?", (cursors[stage], args.project, stage))
            for item, old in ledger.execute("SELECT item,sequence FROM blocked WHERE project=? AND stage='extract'", (args.project,)).fetchall():
                if old in mapping:
                    ledger.execute("UPDATE blocked SET sequence=? WHERE project=? AND stage='extract' AND item=?", (mapping[old], args.project, item))
                else:  # its record was pruned; the position now names another record
                    ledger.execute("DELETE FROM blocked WHERE project=? AND stage='extract' AND item=?", (args.project, item))
            # Tree positions now name different records: rediscover summary blocks.
            cleared = ledger.execute("DELETE FROM blocked WHERE project=? AND stage='summary'", (args.project,)).rowcount
            ledger.execute("DELETE FROM rejections WHERE project=? AND stage='summary'", (args.project,))
            ledger.commit()
        finally:
            ledger.close()
        return {**result, "worker_checkpoints": cursors, "summary_blocks_cleared": cleared}
    finally:
        lock.rollback()
        lock.close()


def reorder(args):
    """Put a project's records in source-time order (see Store.reorder_by_time)."""
    if not args.apply:
        plan = Store(settings_for(args).database).reorder_by_time(args.project)
        output({**plan, "next": "Back up first (agent-hub backup), then run again with --apply."})
        return
    output(_renumbering(args, lambda store: store.reorder_by_time(args.project, apply=True)))


def prune(args):
    """Delete bookkeeping and excluded sessions, then close the gaps (see Store.prune)."""
    settings = settings_for(args)
    if not args.apply:
        plan = Store(settings.database).prune(args.project)
        output({**plan, "next": "Back up first (agent-hub backup), then run again with --apply."})
        return
    database = Path(settings.database)
    before = database.stat().st_size
    result = _renumbering(args, lambda store: store.prune(args.project, apply=True))
    import sqlite3
    # The deletion is committed; VACUUM only returns the space. It needs about the
    # new size in free disk space and briefly blocks writers (uploads wait and
    # retry). If it fails, the report still prints; running prune --apply again
    # removes nothing more and repeats the VACUUM.
    vacuum: dict[str, Any] = {"ok": True}
    try:
        con = sqlite3.connect(database, timeout=60)
        try:
            con.execute("PRAGMA busy_timeout=60000")
            con.execute("VACUUM")
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            con.close()
    except sqlite3.Error as exc:
        vacuum = {"ok": False, "error": str(exc), "retry": f"agent-hub prune --project {args.project} --apply"}
    output({**result, "vacuum": vacuum, "file_bytes": {"before": before, "after": database.stat().st_size}})


def rebuild(args):
    output(Store(settings_for(args).database).rebuild_tree(args.project))


def worker(args):
    import time
    from .worker import run_worker
    settings = settings_for(args)
    if not args.once and args.llm:
        raise ValueError("Model calls require --once and --max-calls; schedule bounded runs explicitly")
    if args.interval < 1:
        raise ValueError("Worker interval must be at least one second")
    while True:
        output(run_worker(settings, project=args.project, use_llm=args.llm,
                          max_calls=args.max_calls, mode=args.mode, retry_blocked=args.retry_blocked))
        if args.once:
            return
        time.sleep(args.interval)


def show_worker(args):
    from .worker import worker_status
    output(worker_status(settings_for(args), args.project))


def catalog(args):
    from .catalog import load_catalog
    value = load_catalog(Path(args.path) if args.path else None)
    output(value if args.action == "list" else {"valid": True, "entries": len(value["entries"])})


def set_password(args):
    settings = settings_for(args)
    auth = AuthStore(settings.auth_database)
    if args.disable:
        auth.clear_password()
        output({"browser_password": "disabled", "browser_sessions": "signed out"})
        return
    if args.stdin:
        import sys
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        import getpass
        password = getpass.getpass("New browser password: ")
        if getpass.getpass("Repeat it: ") != password:
            raise ValueError("The passwords did not match; nothing was changed")
    auth.set_password(password)
    output({"browser_password": "set", "auth_database": str(settings.auth_database),
            "browser_sessions": "earlier sign-ins were signed out"})


def register_commands(subparsers):
    init = subparsers.add_parser("init-server", help="Initialize private server storage and credentials")
    common(init)
    init.add_argument("--project", action="append")
    init.add_argument("--host")
    init.add_argument("--domain", choices=["home", "work"])
    init.set_defaults(func=init_server)
    server = subparsers.add_parser("serve", help="Serve the REST API, memory browser and MCP")
    common(server)
    server.add_argument("--host")
    server.add_argument("--port", type=int)
    server.set_defaults(func=serve)
    project = subparsers.add_parser("project", help="Manage memory scopes locally")
    common(project)
    project.add_argument("action", choices=["list", "create"])
    project.add_argument("project", nargs="?")
    project.add_argument("--name", default="")
    project.set_defaults(func=projects)
    password = subparsers.add_parser("set-password", help="Set the memory browser's sign-in password (administrator access)")
    common(password)
    password.add_argument("--stdin", action="store_true", help="Read the password from the first line of standard input")
    password.add_argument("--disable", action="store_true", help="Remove the password and sign out every browser")
    password.set_defaults(func=set_password)
    token = subparsers.add_parser("token", help="Issue or revoke per-computer credentials")
    common(token)
    token.add_argument("action", choices=["list", "create", "revoke"])
    token.add_argument("--name")
    token.add_argument("--project", action="append")
    token.add_argument("--permissions", default="read,write", choices=["read", "write", "read,write"])
    token.add_argument("--output")
    token.add_argument("--id")
    token.set_defaults(func=tokens)
    review_parser = subparsers.add_parser("review", help="Review a candidate memory, preserving its history")
    common(review_parser)
    review_parser.add_argument("--project", required=True)
    review_parser.add_argument("--id", required=True)
    review_parser.add_argument("--status", required=True, choices=["active", "rejected"])
    review_parser.add_argument("--supersedes")
    review_parser.set_defaults(func=review)
    backup_parser = subparsers.add_parser("backup", help="Create an online snapshot of raw memory and indexes")
    common(backup_parser)
    backup_parser.add_argument("--output", required=True)
    backup_parser.set_defaults(func=backup)
    restore_parser = subparsers.add_parser("restore", help="Restore memory into an empty server data directory")
    common(restore_parser)
    restore_parser.add_argument("--source", required=True)
    restore_parser.add_argument("--privacy-ledger", help="Required current exclusion ledger; prevents restoration of forgotten chats")
    restore_parser.set_defaults(func=restore)
    reorder_parser = subparsers.add_parser("reorder", help="Renumber a project's records in source-time order and rebuild its tree")
    common(reorder_parser)
    reorder_parser.add_argument("--project", required=True)
    reorder_parser.add_argument("--apply", action="store_true", help="Write the new order (default: report what would change)")
    reorder_parser.set_defaults(func=reorder)
    prune_parser = subparsers.add_parser("prune", help="Delete records with no content of their own (bookkeeping, approval-reviewer threads)")
    common(prune_parser)
    prune_parser.add_argument("--project", required=True)
    prune_parser.add_argument("--apply", action="store_true", help="Delete and compact (default: report what would be removed)")
    prune_parser.set_defaults(func=prune)
    rebuild_parser = subparsers.add_parser("rebuild", help="Rebuild lossy summary cache from original records")
    common(rebuild_parser)
    rebuild_parser.add_argument("--project", required=True)
    rebuild_parser.set_defaults(func=rebuild)
    work = subparsers.add_parser("worker", help="Extract candidates locally; optionally run bounded LLM enrichment")
    common(work)
    work.add_argument("--project", required=True)
    work.add_argument("--once", action="store_true")
    work.add_argument("--llm", action="store_true")
    work.add_argument("--max-calls", type=int, default=10)
    work.add_argument("--mode", choices=["both", "summaries", "memories"], default="both")
    work.add_argument("--retry-blocked", action="store_true", help="Reconsider previously oversized inputs after changing enrichment configuration")
    work.add_argument("--interval", type=int, default=30)
    work.set_defaults(func=worker)
    work_status = subparsers.add_parser("worker-status", help="Show persisted enrichment checkpoints and blocked inputs")
    common(work_status)
    work_status.add_argument("--project", required=True)
    work_status.set_defaults(func=show_worker)
    cat = subparsers.add_parser("catalog", help="Inspect or validate the shared integration catalog")
    cat.add_argument("action", choices=["list", "validate"])
    cat.add_argument("--path")
    cat.set_defaults(func=catalog)
