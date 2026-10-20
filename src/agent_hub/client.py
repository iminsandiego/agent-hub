"""Local configuration, durable capture queue, and the remote memory client."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import ntpath
import os
import re
import sqlite3
import ssl
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from .adapters import ADAPTER_VERSION, AdapterError, SourceUnavailable, Transcript, export_codex_thread, parse_jsonl


class ClientError(ValueError):
    pass


class ServiceError(ClientError):
    def __init__(self, status: int, detail: str = ""):
        self.status = status
        self.detail = detail
        super().__init__(f"Memory service returned HTTP {status}." + (f" {detail[:300]}" if detail else ""))


def validate_project(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise ClientError("Project IDs start with a lowercase letter and use at most 64 lowercase letters, digits, underscores, or hyphens.")
    return value


def default_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "agent-hub" / "client.json"


def validate_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ClientError("The service URL must not contain credentials, a query, or a fragment.")
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ClientError("Use an absolute HTTPS service URL.")
    try:
        parsed.port
    except ValueError as exc:
        raise ClientError("Invalid service URL port.") from exc
    loopback = parsed.hostname.lower() == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not loopback:
        raise ClientError("HTTPS is required except for a loopback address. Use a verified TLS endpoint or SSH tunnel.")
    return value.rstrip("/")


def atomic_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".agent-hub-", dir=path.parent)
    try:
        os.chmod(name, mode)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _normalized_path(value: str) -> str:
    if PureWindowsPath(value).drive:
        if os.name == "nt":
            value = str(Path(value).expanduser().resolve())
        return ntpath.normpath(value).replace("\\", "/").rstrip("/").casefold()
    return str(Path(value).expanduser().resolve()).replace("\\", "/").rstrip("/") or "/"


@dataclass
class ClientConfig:
    url: str
    machine_id: str
    schema_version: int = 1
    token_env: str = "AGENT_HUB_TOKEN"
    token_file: str | None = None
    project: str | None = None
    mappings: list[dict[str, str]] = field(default_factory=list)
    capture_paths: list[str] = field(default_factory=list)
    state_dir: str | None = None
    domain: str | None = None
    allowed_projects: list[str] = field(default_factory=list)
    strict_scope: bool = False
    t3_database: str | None = None
    codex_database: str | None = None

    def __post_init__(self) -> None:
        if self.t3_database is not None and (not isinstance(self.t3_database, str) or not self.t3_database or not Path(self.t3_database).expanduser().is_absolute()):
            raise ClientError("t3_database must be an absolute SQLite path or null")
        if self.codex_database is not None and (not isinstance(self.codex_database, str) or not self.codex_database or not Path(self.codex_database).expanduser().is_absolute()):
            raise ClientError("codex_database must be an absolute SQLite path or null")
        if self.schema_version != 1:
            raise ClientError("Unsupported client configuration schema_version.")
        if not isinstance(self.strict_scope, bool):
            raise ClientError("strict_scope must be a boolean.")
        if self.domain is not None and self.domain not in {"home", "work"}:
            raise ClientError("domain must be home, work, or null.")
        if not isinstance(self.allowed_projects, list):
            raise ClientError("allowed_projects must be a list.")
        for allowed in self.allowed_projects:
            validate_project(allowed)
            if self.domain and not allowed.startswith(self.domain + "-"):
                raise ClientError("Allowed projects must use the profile domain prefix.")
        if self.strict_scope and (not self.domain or not self.allowed_projects or self.project):
            raise ClientError("Strict profiles require a domain, explicit allowed_projects, and no default project.")
        self.url = validate_url(self.url)
        if not isinstance(self.machine_id, str) or not self.machine_id.strip() or len(self.machine_id) > 128:
            raise ClientError("Set a stable, nonempty machine_id for this installation.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.token_env):
            raise ClientError("token_env must be an environment variable name.")
        if self.project is not None and (not isinstance(self.project, str) or not self.project):
            raise ClientError("project must be a nonempty project ID or null.")
        if self.project is not None:
            validate_project(self.project)
        if not isinstance(self.mappings, list) or any(
            not isinstance(m, dict) or not isinstance(m.get("path"), str)
            or not m["path"] or not isinstance(m.get("project"), str) or not m["project"]
            for m in self.mappings
        ):
            raise ClientError("Each project mapping needs nonempty path and project strings.")
        if not isinstance(self.capture_paths, list) or any(not isinstance(p, str) for p in self.capture_paths):
            raise ClientError("capture_paths must be a list of directory or JSONL file paths.")
        for mapping in self.mappings:
            validate_project(mapping["project"])
            self.check_project(mapping["project"])
            path = mapping["path"]
            if not Path(path).expanduser().is_absolute() and not PureWindowsPath(path).is_absolute():
                raise ClientError("Project mapping paths must be absolute (or start with ~).")
        for path in self.capture_paths:
            if not path or not Path(path).expanduser().is_absolute() and not PureWindowsPath(path).is_absolute():
                raise ClientError("Capture paths must be nonempty absolute paths (or start with ~).")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ClientConfig":
        target = Path(path).expanduser() if path else default_config_path()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return cls(**data)
        except FileNotFoundError as exc:
            raise ClientError(f"Client configuration not found: {target}. Run agent-hub configure.") from exc
        except (TypeError, json.JSONDecodeError) as exc:
            raise ClientError(f"Invalid client configuration: {target}.") from exc

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path).expanduser() if path else default_config_path()
        atomic_write(target, (json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        return target

    def token(self) -> str:
        value = os.environ.get(self.token_env, "").strip()
        if not value and self.token_file:
            try:
                value = Path(self.token_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ClientError("Cannot read the configured token file.") from exc
        if not value:
            raise ClientError(f"Set {self.token_env} or configure a token_file.")
        if "\n" in value or "\r" in value:
            raise ClientError("The token must be a single line.")
        return value

    def resolve_project(self, cwd: str | None = None, explicit: str | None = None) -> str:
        if explicit:
            return self.check_project(explicit)
        if cwd:
            current = _normalized_path(cwd)
            matches: list[tuple[int, str]] = []
            for mapping in self.mappings:
                prefix = _normalized_path(mapping["path"])
                if current == prefix or current.startswith(prefix.rstrip("/") + "/"):
                    matches.append((len(prefix), mapping["project"]))
            if matches:
                longest = max(length for length, _ in matches)
                projects = {project for length, project in matches if length == longest}
                if len(projects) != 1:
                    raise ClientError("Conflicting equally specific project mappings; correct client.json.")
                return self.check_project(projects.pop())
        if self.project:
            return self.check_project(self.project)
        raise ClientError("No project mapping matches this session; add an explicit mapping or pass --project.")

    def check_project(self, project: str) -> str:
        validate_project(project)
        if self.domain and not project.startswith(self.domain + "-"):
            raise ClientError("Project is outside this profile's domain.")
        if self.allowed_projects and project not in self.allowed_projects:
            raise ClientError("Project is outside this profile's allowlist.")
        return project

    def check_transcript(self, transcript: Transcript, target: str, hook_cwd: str | None = None) -> None:
        self.check_project(target)
        if not self.strict_scope:
            return
        observed = set(transcript.observed_cwds)
        if transcript.cwd:
            observed.add(transcript.cwd)
        if hook_cwd:
            observed.add(hook_cwd)
        if not observed:
            raise ClientError("Strict capture requires mapped source working-directory evidence.")
        for directory in observed:
            if self.resolve_project(directory) != target:
                raise ClientError("Transcript crosses project boundaries; preserve it for review before importing.")

    def local_state_dir(self) -> Path:
        return Path(self.state_dir).expanduser() if self.state_dir else default_config_path().parent / "state"


class MemoryClient:
    def __init__(self, config: ClientConfig, *, timeout: float = 15, transport: Any = None):
        import httpx

        self.config = config
        hostname = urlsplit(config.url).hostname or ""
        loopback = hostname.lower() == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            pass
        # Loopback traffic must not go through a corporate/external proxy.
        # Explicit CA settings still apply to HTTPS loopback endpoints.
        verify = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE"), capath=os.environ.get("SSL_CERT_DIR")) if loopback else True
        self.http = httpx.Client(
            base_url=config.url + "/", timeout=timeout, verify=verify,
            follow_redirects=False, transport=transport, trust_env=not loopback,
        )

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Any:
        headers = {"Authorization": "Bearer " + self.config.token()} if auth else {}
        response = self.http.request(method, path.lstrip("/"), headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            detail = ""
            try:
                body = response.json()
                value = body.get("detail", body.get("error", "")) if isinstance(body, dict) else ""
                detail = value if isinstance(value, str) else ""
            except ValueError:
                pass
            raise ServiceError(response.status_code, detail)
        return response.json()

    def project_path(self, project: str, suffix: str) -> str:
        self.config.check_project(project)
        return f"v1/projects/{quote(project, safe='')}/{suffix}"

    def context(self, project: str, budget_chars: int = 8000, query: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"budget_chars": max(512, min(budget_chars, 24000))}
        if query:
            params["query"] = query
        return self.request("GET", self.project_path(project, "context"), params=params)

    def search(self, project: str, query: str, limit: int = 10) -> Any:
        return self.request("GET", self.project_path(project, "search"), params={"query": query, "limit": limit})

    def get(self, project: str, kind: str, identifier: str, offset: int = 0, limit: int = 20, representation: str = "text", max_chars: int = 16000) -> Any:
        paths = {"event": "events", "memory": "memories", "session": "sessions"}
        if kind not in paths:
            raise ClientError("kind must be event, memory, or session.")
        path = self.project_path(project, paths[kind] + "/" + quote(identifier, safe=""))
        return self.request("GET", path, params={"offset": offset, "limit": limit, "representation": representation, "max_chars": max_chars})

    def ingest(self, project: str, transcript: Transcript, events: list[dict[str, Any]]) -> Any:
        self.config.check_transcript(transcript, project)
        clean = [{k: v for k, v in event.items() if not k.startswith("_")} for event in events]
        wire_client = {"jsonl": "generic", "codex-app-server": "codex"}.get(transcript.client, transcript.client)
        from .privacy import temporary_message
        from .session_links import related_sessions
        aliases = related_sessions(self.config.t3_database, wire_client, transcript.session_id)
        if wire_client == "codex":
            native_id = transcript.session_id.removesuffix(":app-server-v2")
            aliases.extend([{"client": "codex", "session_id": native_id},
                            {"client": "codex", "session_id": native_id + ":app-server-v2"}])
        return self.request("POST", "v1/ingest", json={
            "project": project, "client": wire_client, "machine": self.config.machine_id,
            "session_id": transcript.session_id, "events": clean,
            "metadata": {k: v for k, v in transcript.metadata.items() if k not in {"pending_turns", "unknown_types"}},
            "related_sessions": aliases,
            "temporary": transcript.temporary or temporary_message(transcript.events or events),
            "parent_sessions": ([{"client": wire_client, "session_id": transcript.parent_session_id or transcript.metadata["parent_session_id"]}]
                                if transcript.parent_session_id or transcript.metadata.get("parent_session_id") else []),
        })


# A job whose source stays gone this long is set aside instead of retried forever.
SOURCE_GONE_GRACE_SECONDS = 24 * 3600


class LocalState:
    """A local outbox and append checkpoints; no network runs in enqueue()."""

    def __init__(self, config: ClientConfig):
        scope = hashlib.sha256(json.dumps([config.url, config.machine_id]).encode()).hexdigest()[:20]
        directory = config.local_state_dir() / scope
        directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            directory.chmod(0o700)
        self.path = directory / "client.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA secure_delete=ON;
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT,
                    revision TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY, offset INTEGER NOT NULL, prefix_sha TEXT NOT NULL,
                    session_id TEXT NOT NULL, project TEXT NOT NULL, mtime_ns INTEGER NOT NULL,
                    size INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cache (
                    id TEXT PRIMARY KEY, text TEXT NOT NULL, captured_at REAL NOT NULL
                );
            """)
            # Capture parser version per file; files captured before 0.1.9 stay on version 1.
            if "adapter_version" not in {row[1] for row in db.execute("PRAGMA table_info(files)")}:
                db.execute("ALTER TABLE files ADD COLUMN adapter_version INTEGER NOT NULL DEFAULT 1")
            # 0.1.11: when a job's source was first found gone, and when it was set aside.
            job_columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            for column in ("gone_since", "parked_at"):
                if column not in job_columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {column} REAL")
            db.execute("DELETE FROM cache")
        if os.name != "nt":
            self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=0.3)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def enqueue(self, payload: dict[str, Any]) -> str:
        key = json.dumps([payload.get("client"), payload.get("path"), payload.get("session_id"), payload.get("project")])
        identifier = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with self.connect() as db:
            db.execute(
                # New work for the same source revives a set-aside job.
                "INSERT INTO jobs(id,payload,revision) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "payload=excluded.payload,revision=excluded.revision,gone_since=NULL,parked_at=NULL",
                (identifier, json.dumps(payload, ensure_ascii=False), uuid.uuid4().hex),
            )
        return identifier

    def due_jobs(self, *, now: float | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs WHERE parked_at IS NULL AND next_attempt<=? ORDER BY next_attempt,rowid LIMIT ?", (time.time() if now is None else now, limit)).fetchall()
        return [dict(row) for row in rows]

    def completed(self, job: dict[str, Any]) -> None:
        # A hook may enqueue the same path while its upload is in flight. Only
        # acknowledge the revision actually processed, retaining the new work.
        with self.connect() as db:
            db.execute("DELETE FROM jobs WHERE id=? AND revision=?", (job["id"], job["revision"]))

    def failed(self, job: dict[str, Any], error: Exception, *, now: float | None = None) -> None:
        attempts = job["attempts"] + 1
        now = time.time() if now is None else now
        # Exception classes and controlled error messages do not expose payloads.
        message = str(error) if isinstance(error, (ClientError, AdapterError)) else type(error).__name__
        gone = isinstance(error, SourceUnavailable)
        with self.connect() as db:
            # A source gone for the whole grace period is set aside (kept, not
            # deleted); any other outcome restarts the gone clock.
            db.execute(
                "UPDATE jobs SET attempts=?,next_attempt=?,last_error=?,"
                "gone_since=CASE WHEN ? THEN COALESCE(gone_since,?) END,"
                "parked_at=CASE WHEN ? AND COALESCE(gone_since,?)<=? THEN ? END WHERE id=? AND revision=?",
                (attempts, now + min(300, 2 ** min(attempts, 8)), message[:500], gone, now,
                 gone, now, now - SOURCE_GONE_GRACE_SECONDS, now, job["id"], job["revision"]))

    def source_gone(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT id,payload,attempts,last_error,gone_since,parked_at FROM jobs "
                              "WHERE parked_at IS NOT NULL ORDER BY parked_at,rowid").fetchall()
        return [dict(row) for row in rows]

    def requeue(self, identifiers: list[str] | None = None) -> int:
        """Return set-aside jobs to the queue: all of them, or the given IDs."""
        with self.connect() as db:
            reset = "UPDATE jobs SET parked_at=NULL,gone_since=NULL,attempts=0,next_attempt=0,last_error=NULL WHERE parked_at IS NOT NULL"
            if identifiers is None:
                return db.execute(reset).rowcount
            return sum(db.execute(reset + " AND id=?", (identifier,)).rowcount for identifier in identifiers)

    def checkpoint(self, identifier: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM files WHERE id=?", (identifier,)).fetchone()
        return dict(row) if row else None

    def save_checkpoint(self, identifier: str, data: bytes, offset: int, session: str, project: str, stat: os.stat_result,
                        *, adapter_version: int = 1) -> None:
        self.save_checkpoint_hash(identifier, hashlib.sha256(data[:offset]).hexdigest(), offset, session, project, stat,
                                  size=len(data), adapter_version=adapter_version)

    def save_checkpoint_hash(self, identifier: str, prefix_sha: str, offset: int, session: str,
                             project: str, stat: os.stat_result, *, size: int | None = None, adapter_version: int = 1) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO files(id,offset,prefix_sha,session_id,project,mtime_ns,size,adapter_version) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "offset=excluded.offset,prefix_sha=excluded.prefix_sha,session_id=excluded.session_id,"
                "project=excluded.project,mtime_ns=excluded.mtime_ns,size=excluded.size,adapter_version=excluded.adapter_version "
                "WHERE excluded.offset>=files.offset", (
                identifier, offset, prefix_sha, session,
                project, stat.st_mtime_ns, stat.st_size if size is None else size, adapter_version,
            ))

    def status(self) -> dict[str, Any]:
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE parked_at IS NULL").fetchone()[0]
            errors = [dict(row) for row in db.execute("SELECT id,attempts,last_error FROM jobs WHERE parked_at IS NULL AND last_error IS NOT NULL ORDER BY attempts DESC LIMIT 20")]
            gone = db.execute("SELECT COUNT(*) FROM jobs WHERE parked_at IS NOT NULL").fetchone()[0]
            files = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return {"pending_jobs": count, "tracked_files": files, "errors": errors, "source_gone": gone}

    def cache_key(self, config: ClientConfig, project: str) -> str:
        # Do not reuse another credential's local cache after changing accounts.
        material = json.dumps([config.url, project, hashlib.sha256(config.token().encode()).hexdigest()])
        return hashlib.sha256(material.encode()).hexdigest()

    def cache_put(self, key: str, text: str) -> None:
        # Memory is always retrieved live. Persisting it could resurrect a
        # forgotten source during an outage, without a privacy revision check.
        pass

    def cache_get(self, key: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT text,captured_at FROM cache WHERE id=?", (key,)).fetchone()
        return dict(row) if row else None


def file_key(config: ClientConfig, path: Path, client: str, session_id: str | None = None) -> str:
    value = json.dumps([config.url, config.machine_id, client, str(path.resolve()), session_id])
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _batches(events: list[dict[str, Any]], max_bytes: int = 512_000):
    batch: list[dict[str, Any]] = []
    size = 0
    for event in events:
        event_size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
        if batch and (size + event_size > max_bytes or len(batch) >= 400):
            yield batch
            batch, size = [], 0
        batch.append(event)
        size += event_size
    if batch:
        yield batch


def ingest_file(
    config: ClientConfig, path: str | Path, *, client: str = "auto",
    project: str | None = None, cwd: str | None = None,
    session_id: str | None = None, final: bool = False,
    memory: MemoryClient | None = None, state: LocalState | None = None,
) -> dict[str, Any]:
    """Capture a transcript with the parser version its session was first captured with.

    A file with a checkpoint keeps its recorded version. A new file uses the current
    version, unless the server already holds the session under version 1 (a lost
    checkpoint or a moved file): its metadata then conflicts, and the file is read
    again with version 1 so archived records match exactly.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise SourceUnavailable("The queued transcript no longer exists; it is retried for a day, then set aside.")
    state = state or LocalState(config)
    previous = state.checkpoint(file_key(config, source, client, session_id))
    version = int(previous.get("adapter_version") or 1) if previous else ADAPTER_VERSION
    arguments = dict(client=client, project=project, cwd=cwd, session_id=session_id, final=final, memory=memory, state=state)
    try:
        return _ingest_file_version(config, source, version, **arguments)
    except ServiceError as exc:
        if previous is None and version > 1 and exc.status == 409 and "metadata" in exc.detail.lower():
            return _ingest_file_version(config, source, 1, **arguments)
        raise


def _ingest_file_version(
    config: ClientConfig, source: Path, adapter_version: int, *, client: str, project: str | None, cwd: str | None,
    session_id: str | None, final: bool, memory: MemoryClient | None, state: LocalState,
) -> dict[str, Any]:
    if source.stat().st_size > 16_000_000:
        from .streaming import ingest_large_file
        return ingest_large_file(config, source, client=client, project=project, cwd=cwd, session_id=session_id,
                                 final=final, memory=memory, state=state, adapter_version=adapter_version)
    data = source.read_bytes()
    stat = source.stat()
    transcript = parse_jsonl(data, client=client, machine=config.machine_id, path=str(source), session_id=session_id,
                             cwd=cwd, final=final, adapter_version=adapter_version)
    target = config.resolve_project(transcript.cwd, project)
    config.check_transcript(transcript, target, cwd)
    identifier = file_key(config, source, client, session_id)
    previous = state.checkpoint(identifier)
    offset = previous["offset"] if previous else 0
    if previous:
        if len(data) < offset or hashlib.sha256(data[:offset]).hexdigest() != previous["prefix_sha"]:
            raise ClientError("Transcript was truncated or rewritten. Capture is blocked; preserve the source and import a deliberate new session identity after review.")
        if previous["session_id"] != transcript.session_id or previous["project"] != target:
            raise ClientError("The transcript session or project assignment changed after capture; review before remapping.")
    pending = [event for event in transcript.events if event["_end_offset"] > offset]
    owned = memory is None
    connection = memory or MemoryClient(config)
    inserted = duplicates = 0
    try:
        from .privacy import temporary_message
        if temporary_message(transcript.events) and transcript.events and not pending:
            connection.ingest(target, transcript, [transcript.events[0]])
        for batch in _batches(pending):
            receipt = connection.ingest(target, transcript, batch)
            inserted += int(receipt.get("inserted", 0))
            duplicates += int(receipt.get("duplicates", 0))
            offset = batch[-1]["_end_offset"]
            state.save_checkpoint(identifier, data, offset, transcript.session_id, target, stat, adapter_version=adapter_version)
            if receipt.get("suppressed"):
                break
        # Blank separator lines are safe to checkpoint after all events commit.
        state.save_checkpoint(identifier, data, transcript.complete_bytes, transcript.session_id, target, stat, adapter_version=adapter_version)
        from .codex_titles import index_title
        index_title(config, source, transcript, connection, project=target)
    finally:
        if owned:
            connection.close()
    return {
        "path": str(source), "project": target, "session_id": transcript.session_id,
        "inserted": inserted, "duplicates": duplicates, "pending_bytes": transcript.pending_bytes,
        "unknown_types": transcript.unknown_types, "source_records": len(transcript.events),
    }


def ingest_codex_thread(config: ClientConfig, thread_id: str, *, project: str | None = None, executable: str = "codex", memory: MemoryClient | None = None) -> dict[str, Any]:
    transcript = export_codex_thread(thread_id, machine=config.machine_id, executable=executable)
    target = config.resolve_project(transcript.cwd, project)
    config.check_transcript(transcript, target)
    owned = memory is None
    connection = memory or MemoryClient(config)
    inserted = duplicates = 0
    try:
        for batch in _batches(transcript.events):
            receipt = connection.ingest(target, transcript, batch)
            inserted += int(receipt.get("inserted", 0))
            duplicates += int(receipt.get("duplicates", 0))
    finally:
        if owned:
            connection.close()
    return {"session_id": thread_id, "project": target, "inserted": inserted, "duplicates": duplicates, "pending_turns": transcript.metadata["pending_turns"]}


def enqueue_hook(config: ClientConfig, payload: dict[str, Any], client: str, state: LocalState | None = None) -> str:
    state = state or LocalState(config)
    path = payload.get("agent_transcript_path") if payload.get("hook_event_name") == "SubagentStop" else payload.get("transcript_path")
    return state.enqueue({
        "kind": "file" if path else "codex-thread" if client == "codex" else "unavailable",
        "client": client, "path": path, "cwd": payload.get("cwd"),
        # Native metadata determines file identity, keeping hooks and manual
        # backfill consistent. The hook session ID is needed for API export.
        "session_id": None if path else payload.get("session_id"),
    })


def hook_context(config: ClientConfig, payload: dict[str, Any], *, budget_chars: int = 8000, memory: MemoryClient | None = None) -> dict[str, Any]:
    state = LocalState(config)
    project = config.resolve_project(payload.get("cwd"))
    key = state.cache_key(config, project)
    owned = memory is None
    connection = memory or MemoryClient(config, timeout=0.6)
    try:
        try:
            result = connection.context(project, budget_chars=budget_chars)
            text = bounded_context(str(result.get("text", "")), budget_chars)
            state.cache_put(key, text)
        except ServiceError as exc:
            if exc.status in {401, 403, 404}:
                raise
            text = cached_context(state, key)
        except (OSError, TimeoutError) as exc:
            text = cached_context(state, key)
        except Exception as exc:
            # httpx is imported lazily to keep SessionEnd enqueue startup small.
            import httpx
            if not isinstance(exc, httpx.TransportError):
                raise
            text = cached_context(state, key)
    finally:
        if owned:
            connection.close()
    if not text:
        return {}
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": bounded_context(text, budget_chars)}}


def bounded_context(text: str, budget: int) -> str:
    """Keep source lines intact when fitting historical context into a hook."""
    budget = max(256, min(budget, 8000))
    if len(text) <= budget:
        return text
    suffix = "\n[Additional history omitted; retrieve it with memory tools.]"
    prefix = text[:budget - len(suffix)]
    boundary = prefix.rfind("\n")
    return (prefix[:boundary] if boundary >= 0 else "[An oversized history entry was omitted.]") + suffix


def cached_context(state: LocalState, key: str) -> str:
    return ""


def _oldest_first(paths) -> list[Path]:
    """Queue discovered transcripts by age so backfilled history keeps its order."""
    def age(path: Path):
        try:
            return (path.stat().st_mtime_ns, str(path))
        except OSError:
            return (0, str(path))
    return sorted(paths, key=age)


def discover_paths(config: ClientConfig, state: LocalState) -> int:
    queued = 0
    for configured in config.capture_paths:
        root = Path(configured).expanduser().resolve()
        candidates = [root] if root.is_file() else _oldest_first(root.rglob("*.jsonl")) if root.is_dir() else []
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                # Do not follow a symlink out of an explicitly configured root.
                if root.is_dir() and not resolved.is_relative_to(root):
                    continue
                stat = resolved.stat()
                prior = state.checkpoint(file_key(config, resolved, "auto"))
                if prior and prior["mtime_ns"] == stat.st_mtime_ns and prior["size"] == stat.st_size:
                    continue
                state.enqueue({"kind": "file", "path": str(resolved), "client": "auto"})
                queued += 1
            except OSError:
                continue
    return queued


def drain_queue(config: ClientConfig, *, state: LocalState | None = None, memory: MemoryClient | None = None, now: float | None = None) -> dict[str, Any]:
    state = state or LocalState(config)
    done = failed = 0
    results = []
    for job in state.due_jobs(now=now):
        payload = json.loads(job["payload"])
        try:
            if payload["kind"] == "file":
                result = ingest_file(config, payload["path"], client=payload.get("client", "auto"), project=payload.get("project"), cwd=payload.get("cwd"), session_id=payload.get("session_id"), final=payload.get("final", False), state=state, memory=memory)
            elif payload["kind"] == "codex-thread" and payload.get("session_id"):
                result = ingest_codex_thread(config, payload["session_id"], project=payload.get("project"), memory=memory)
                if result["pending_turns"]:
                    raise ClientError("A Codex turn is still active; completed history was captured and export will retry.")
            else:
                raise ClientError("This client did not supply a transcript path. Capture is pending; use an explicit supported export.")
            if result.get("pending_bytes"):
                # Retain an active file even if no final SessionEnd is observed.
                raise ClientError("The last JSONL record is incomplete; complete records were captured and the tail will retry.")
            state.completed(job)
            results.append(result)
            done += 1
        except Exception as exc:
            state.failed(job, exc, now=now)
            failed += 1
            # A service outage should not cost one network timeout per file.
            import httpx
            if isinstance(exc, httpx.TransportError) or isinstance(exc, ServiceError) and exc.status >= 500:
                break
    return {"completed": done, "failed": failed, "results": results, **state.status()}


def create_gateway(config: ClientConfig, *, memory: MemoryClient | None = None):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    client = memory or MemoryClient(config)
    mcp = FastMCP("Agent Hub", instructions="Retrieve project-scoped historical context. Verify source evidence before relying on past claims. New notes are candidates requiring review.")
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @mcp.tool(annotations=read)
    def memory_context(project: str, budget_chars: int = 8000, query: str | None = None) -> dict[str, Any]:
        """Get a bounded project memory overview with source references."""
        return client.context(project, budget_chars, query)

    @mcp.tool(annotations=read)
    def memory_search(project: str, query: str, limit: int = 10) -> Any:
        """Find relevant historical events and reviewed memories."""
        return client.search(project, query, limit)

    @mcp.tool(annotations=read)
    def memory_get(project: str, kind: Literal["event", "memory", "session"], id: str, offset: int = 0, limit: int = 20, representation: Literal["text", "raw"] = "text", max_chars: int = 16000) -> Any:
        """Read evidence. Event offset counts characters; session offset counts records."""
        return client.get(project, kind, id, offset, limit, representation, max_chars)

    @mcp.tool(annotations=read)
    def memory_zoom(project: str, node_id: str) -> Any:
        """Expand a summary node into its children or original event."""
        return client.request("GET", client.project_path(project, "nodes/" + quote(node_id, safe="")))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def memory_note(project: str, statement: str, kind: str, source_event_ids: list[str], idempotency_key: str | None = None) -> Any:
        """Propose a sourced memory candidate; this never activates a memory."""
        payload: dict[str, Any] = {"statement": statement, "kind": kind, "source_event_ids": source_event_ids}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return client.request("POST", client.project_path(project, "memories"), json=payload)

    return mcp
