"""Serve synthetic data for browser verification, never real user sessions."""
from __future__ import annotations

import argparse
import json
import secrets
import tempfile
from pathlib import Path

import uvicorn

from agent_hub.config import ServerSettings, write_private
from agent_hub.server import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--info-file", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="agent-hub-synthetic-") as directory:
        root = Path(directory)
        settings = ServerSettings(data_dir=root, port=args.port,
                                  allowed_origins=[f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"])
        app = create_app(settings)
        store = app.state.store
        store.create_project("demo", "Demo project")
        store.create_project("empty", "Empty project")
        contents = [
            ("user", "Decision: preserve original source records separately from derived summaries."),
            ("assistant", "The proposed implementation gives each record a stable source identity and timestamps."),
            ("tool", "Synthetic command fixture: read architecture.md; this is not a real engineering run."),
            ("assistant", "A retry with the same source identity should be acknowledged without duplicating history."),
            ("user", "Never describe a proposed check as an executed result."),
            ("assistant", "The review will retain observed, proposed, and unresolved work with source references."),
            ("tool", "Synthetic result: <img src=x onerror=window.fixture_xss=1> & unusual Unicode 雪."),
            ("user", "Question: which source should be checked before the next implementation step?"),
            ("assistant", "Inspect the captured record and then the identified current source; historical context is not current evidence."),
            ("user", "Decision: route native clients to the same scoped service on the execution host."),
            ("assistant", "This fixture creates a candidate note for browser review; no user history is loaded."),
            ("tool", "Fixture complete. These records are synthetic browser-test data."),
        ]
        events = [{"event_id": str(index), "role": role, "text": text,
                   "raw": json.dumps({"type": role, "content": text}, ensure_ascii=False),
                   "timestamp": "2026-10-07T13:00:00Z"} for index, (role, text) in enumerate(contents)]
        captured = store.ingest("demo", "generic", "synthetic-browser-test", "fixture-session", events,
                                {"synthetic": True, "purpose": "browser verification"})
        first = store.add_memory("demo", contents[0][1], "decision", [captured["event_ids"][0]])
        store.review_memory("demo", first["id"], "active", actor="synthetic-review")
        candidate = store.add_memory("demo", contents[9][1], "decision", [captured["event_ids"][9]])
        _, token = app.state.auth.issue("Browser verification", ["*"], ["admin"])
        token_path = root / "test.token"
        write_private(token_path, token)
        # Synthetic browser password, generated per run and kept in the private temporary directory.
        password_path = root / "test.password"
        write_private(password_path, "synthetic-" + secrets.token_urlsafe(18))
        app.state.auth.set_password(password_path.read_text())
        write_private(args.info_file, json.dumps({"url": f"http://127.0.0.1:{args.port}", "token_file": str(token_path),
                                                 "password_file": str(password_path), "candidate": candidate["id"]}), overwrite=True)
        print(json.dumps({"synthetic_fixture": True, "info_file": str(args.info_file)}), flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
