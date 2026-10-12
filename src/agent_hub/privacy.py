"""Content-free exclusions, kept separately so archive restores cannot undo them."""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path


def temporary_message(events: list[dict]) -> bool:
    return any(e.get("role") == "user" and isinstance(e.get("text"), str)
               and re.match(r"^\s*\[(?:temp|temporary)\](?:\s|$)", e["text"], re.I)
               for e in events)


class PrivacyLedger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS identities(
                    project TEXT NOT NULL, id TEXT NOT NULL, mode TEXT,
                    PRIMARY KEY(project,id), CHECK(mode IN ('temporary','forgotten')));
                CREATE TABLE IF NOT EXISTS links(
                    project TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
                    PRIMARY KEY(project,a,b));
                CREATE TABLE IF NOT EXISTS descendants(
                    project TEXT NOT NULL, parent TEXT NOT NULL, child TEXT NOT NULL,
                    PRIMARY KEY(project,parent,child));
            """)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA secure_delete=ON")
        try:
            with con:
                yield con
        finally:
            con.close()

    def observe(self, project: str, primary: str, aliases: list[str], mode: str | None = None,
                parents: list[str] | None = None):
        # The caller holds the archive's write transaction. Commit the exclusion
        # first: a crash can leave content to purge on restart, never erase policy.
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            for identifier in [primary, *aliases]:
                con.execute("INSERT OR IGNORE INTO identities(project,id) VALUES(?,?)", (project, identifier))
            for identifier in aliases:
                if identifier != primary:
                    con.execute("INSERT OR IGNORE INTO links VALUES(?,?,?)", (project, *sorted([primary, identifier])))
            for parent in parents or []:
                con.execute("INSERT OR IGNORE INTO descendants VALUES(?,?,?)", (project, parent, primary))
            # Inherit from known ancestors, without propagating a child's
            # exclusion upward to its parent or sideways to its siblings.
            inherited = {r[0] for r in con.execute("""
                WITH RECURSIVE ancestors(id) AS (
                    SELECT ? UNION SELECT d.parent FROM descendants d JOIN ancestors a ON d.child=a.id WHERE d.project=?
                    UNION SELECT CASE WHEN l.a=a.id THEN l.b ELSE l.a END FROM links l JOIN ancestors a ON (l.a=a.id OR l.b=a.id) WHERE l.project=?
                ) SELECT mode FROM identities WHERE project=? AND id IN (SELECT id FROM ancestors)
            """, (primary, project, project, project))}
            group = [r[0] for r in con.execute("""
                WITH RECURSIVE group_ids(id) AS (
                    SELECT ? UNION
                    SELECT CASE WHEN l.a=g.id THEN l.b ELSE l.a END
                    FROM links l JOIN group_ids g ON (l.a=g.id OR l.b=g.id)
                    WHERE l.project=? UNION
                    SELECT d.child FROM descendants d JOIN group_ids g ON d.parent=g.id WHERE d.project=?
                ) SELECT id FROM group_ids
            """, (primary, project, project))]
            modes = set(inherited)
            modes.add(mode)
            modes.update(inherited)
            selected = "forgotten" if "forgotten" in modes else "temporary" if "temporary" in modes else None
            if selected:
                con.executemany("INSERT INTO identities(project,id,mode) VALUES(?,?,?) ON CONFLICT(project,id) DO UPDATE SET mode=CASE WHEN identities.mode='forgotten' THEN 'forgotten' ELSE excluded.mode END", [(project, i, selected) for i in group])
            return selected, group

    def exclusions(self, project: str | None = None):
        with self.connect() as con:
            return [{"project": r[0], "id": r[1], "mode": r[2]} for r in con.execute(
                "SELECT project,id,mode FROM identities WHERE mode IS NOT NULL" + (" AND project=?" if project else "") + " ORDER BY project,id",
                (project,) if project else ())]

    def backup(self, destination: Path):
        fd, name = tempfile.mkstemp(prefix=".privacy-", dir=destination.parent)
        os.close(fd)
        try:
            target = sqlite3.connect(name)
            try:
                with self.connect() as source:
                    source.backup(target)
            finally:
                target.close()
            with open(name, "r+b") as stream:
                os.fsync(stream.fileno())
            os.replace(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)
