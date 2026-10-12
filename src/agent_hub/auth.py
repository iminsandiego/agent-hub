"""High-entropy per-machine access tokens, stored only as SHA-256 digests."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


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
