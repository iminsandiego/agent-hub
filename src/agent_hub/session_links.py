"""Only provider identity fields; never credentials, messages or runtime payloads."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def related_sessions(database: str | None, client: str, session_id: str) -> list[dict[str, str]]:
    if not database or client not in {"t3", "codex", "claude"}:
        return []
    from .client import ClientError
    path = Path(database).expanduser().resolve()
    native = session_id.removesuffix(":app-server-v2")
    try:
        con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            columns = {r[1] for r in con.execute("PRAGMA table_info(provider_session_runtime)")}
            if not {"thread_id", "provider_name", "resume_cursor_json"}.issubset(columns):
                raise ClientError("T3 provider identity schema changed; capture retained for retry")
            # Extract just threadId in SQLite. The rest of the cursor/runtime
            # record never leaves T3's database, including auth/session tokens.
            rows = con.execute("SELECT thread_id,provider_name,json_extract(resume_cursor_json,'$.threadId') FROM provider_session_runtime WHERE " +
                               ("thread_id=?" if client == "t3" else "json_extract(resume_cursor_json,'$.threadId')=?"),
                               (session_id if client == "t3" else native,)).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, OSError) as exc:
        raise ClientError("T3 provider identities unavailable; linked capture retained for retry") from exc
    aliases = []
    for thread, provider, provider_thread in rows:
        wire = {"codex": "codex", "claudeAgent": "claude"}.get(provider)
        if not wire or not isinstance(provider_thread, str) or not provider_thread:
            continue
        if client != "t3" and wire != client:
            continue
        aliases.append({"client": "t3", "session_id": thread})
        aliases.append({"client": wire, "session_id": provider_thread})
        if wire == "codex":
            aliases.append({"client": wire, "session_id": provider_thread + ":app-server-v2"})
    return list({(a["client"], a["session_id"]): a for a in aliases}.values())
