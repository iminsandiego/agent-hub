"""Credentials: per-machine access tokens and one browser password.

Tokens are high-entropy and stored only as SHA-256 digests. The browser password
is stored as a salted scrypt hash and exchanges for a revocable session whose
secret lives only in an HttpOnly cookie; the database keeps its digest.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

SESSION_DAYS = 30
MIN_PASSWORD_CHARS = 12
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


@dataclass(frozen=True)
class Principal:
    id: str
    name: str
    projects: tuple[str, ...]
    permissions: tuple[str, ...]

    def allows(self, project: str, permission: str = "read") -> bool:
        return (project in self.projects or "*" in self.projects) and (
            permission in self.permissions or "admin" in self.permissions
        )

    @property
    def admin(self) -> bool:
        return "admin" in self.permissions


class AuthStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
        with self.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS access_tokens (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, digest TEXT UNIQUE NOT NULL,
                projects TEXT NOT NULL, permissions TEXT NOT NULL,
                created_at TEXT NOT NULL, revoked_at TEXT
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS browser_password (
                id INTEGER PRIMARY KEY CHECK (id = 1), hash TEXT NOT NULL, salt TEXT NOT NULL,
                params TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS browser_sessions (
                id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, revoked_at TEXT
            )""")
        if os.name != "nt":
            self.path.chmod(0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def issue(self, name: str, projects: list[str], permissions: list[str]) -> tuple[str, str]:
        if not name or len(name) > 100 or not projects or not permissions:
            raise ValueError("Token requires a name, project scopes and permissions")
        if set(permissions) - {"read", "write", "admin"}:
            raise ValueError("Unknown token permission")
        if any(not item or len(item) > 80 for item in projects):
            raise ValueError("Invalid token project scope")
        if "admin" in permissions and projects != ["*"]:
            raise ValueError("Administrative tokens must explicitly use '*' scope")
        token = "ah_" + secrets.token_urlsafe(32)
        token_id = secrets.token_hex(8)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO access_tokens VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (token_id, name, hashlib.sha256(token.encode()).hexdigest(),
                 json.dumps(sorted(set(projects))), json.dumps(sorted(set(permissions))),
                 datetime.now(timezone.utc).isoformat()),
            )
        return token_id, token

    def authenticate(self, token: str) -> Principal | None:
        if not token.startswith("ah_") or len(token) < 40 or len(token) > 200:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM access_tokens WHERE digest=? AND revoked_at IS NULL", (digest,)
            ).fetchone()
        if row is None:
            return None
        return Principal(row["id"], row["name"], tuple(json.loads(row["projects"])),
                         tuple(json.loads(row["permissions"])))

    def list(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,name,projects,permissions,created_at,revoked_at FROM access_tokens ORDER BY created_at"
            ).fetchall()
        return [{**dict(row), "projects": json.loads(row["projects"]),
                 "permissions": json.loads(row["permissions"])} for row in rows]

    def revoke(self, token_id: str) -> None:
        with self.connect() as connection:
            result = connection.execute(
                "UPDATE access_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), token_id),
            )
            if not result.rowcount:
                raise KeyError("Active token not found")


    # ------------------------------------------------------------ browser login

    def set_password(self, password: str) -> None:
        """Replace the browser password and sign out every existing browser session."""
        if len(password) < MIN_PASSWORD_CHARS or len(password) > 1024:
            raise ValueError(f"Use a password of at least {MIN_PASSWORD_CHARS} characters")
        salt = secrets.token_bytes(16)
        digest = _scrypt(password, salt, SCRYPT)
        now = _now()
        with self.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO browser_password VALUES (1, ?, ?, ?, ?)",
                               (digest.hex(), salt.hex(), json.dumps(SCRYPT), now))
            connection.execute("UPDATE browser_sessions SET revoked_at=? WHERE revoked_at IS NULL", (now,))

    def clear_password(self) -> None:
        now = _now()
        with self.connect() as connection:
            connection.execute("DELETE FROM browser_password")
            connection.execute("UPDATE browser_sessions SET revoked_at=? WHERE revoked_at IS NULL", (now,))

    def password_enabled(self) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM browser_password").fetchone() is not None

    def check_password(self, password: str) -> bool:
        if not password or len(password) > 1024:
            return False
        with self.connect() as connection:
            row = connection.execute("SELECT hash,salt,params FROM browser_password").fetchone()
        if row is None:
            return False
        actual = _scrypt(password, bytes.fromhex(row["salt"]), json.loads(row["params"]))
        return secrets.compare_digest(actual.hex(), row["hash"])

    def start_session(self) -> tuple[str, datetime]:
        secret = "ahs_" + secrets.token_urlsafe(32)
        created = datetime.now(timezone.utc)
        expires = created + timedelta(days=SESSION_DAYS)
        with self.connect() as connection:
            connection.execute("INSERT INTO browser_sessions VALUES (?, ?, ?, ?, NULL)",
                               (secrets.token_hex(8), hashlib.sha256(secret.encode()).hexdigest(),
                                created.isoformat(), expires.isoformat()))
        return secret, expires

    def session_principal(self, secret: str) -> Principal | None:
        if not secret.startswith("ahs_") or len(secret) > 200:
            return None
        digest = hashlib.sha256(secret.encode()).hexdigest()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id,expires_at FROM browser_sessions WHERE digest=? AND revoked_at IS NULL", (digest,)
            ).fetchone()
            if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                return None
            if connection.execute("SELECT 1 FROM browser_password").fetchone() is None:
                return None
        # The password is the server administrator's browser credential.
        return Principal("browser-" + row["id"], "Browser sign-in", ("*",), ("admin",))

    def end_session(self, secret: str) -> None:
        digest = hashlib.sha256(secret.encode()).hexdigest()
        with self.connect() as connection:
            connection.execute("UPDATE browser_sessions SET revoked_at=? WHERE digest=? AND revoked_at IS NULL",
                               (_now(), digest))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scrypt(password: str, salt: bytes, params: dict) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=params["n"], r=params["r"], p=params["p"],
                          maxmem=128 * params["n"] * params["r"] * 2, dklen=32)
