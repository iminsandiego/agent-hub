"""Browser password sign-in: HttpOnly session cookies for the REST API only.

Real middleware, auth database and routes; temporary data; no external requests.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from agent_hub.auth import AuthStore
from agent_hub.config import ServerSettings
from agent_hub.server import SESSION_COOKIE, cookie_name, create_app

PASSWORD = "correct horse battery staple"
ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture
def app(tmp_path):
    application = create_app(ServerSettings(data_dir=tmp_path / "data"))
    application.state.store.create_project("atlas", "Atlas")
    return application


@pytest.fixture
def client(app):
    app.state.auth.set_password(PASSWORD)
    with TestClient(app, base_url="http://localhost") as value:
        yield value


def sign_in(client, password=PASSWORD, headers=ORIGIN):
    return client.post("/auth/login", json={"password": password}, headers=headers)


def test_login_is_refused_until_a_password_is_set(app):
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/health").json()["password_login"] is False
        response = sign_in(client)
    assert response.status_code == 403
    assert "set-password" in response.json()["detail"]


def test_password_sign_in_sets_a_strict_http_only_cookie_and_grants_admin(client):
    assert client.get("/health").json()["password_login"] is True
    assert sign_in(client, "wrong password here").status_code == 401
    response = sign_in(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert SESSION_COOKIE in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "secure" not in cookie  # plain-HTTP tunnel page
    assert "ahs_" not in response.text  # the secret is never in a readable body
    me = client.get("/v1/me").json()
    assert me["admin"] is True and me["projects"] == ["*"]
    assert client.get("/v1/projects/atlas/stats").status_code == 200


def test_https_pages_get_a_secure_cookie(client):
    response = sign_in(client, headers={"Origin": "https://localhost"})
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_session_cookie_never_authorizes_mcp(client):
    sign_in(client)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                           headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401


def test_cookie_writes_need_an_allowed_origin(client):
    sign_in(client)
    note = {"statement": "Written from a signed-in browser"}
    assert client.post("/v1/projects/atlas/memories", json=note).status_code == 403
    assert client.post("/v1/projects/atlas/memories", json=note,
                       headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.post("/v1/projects/atlas/memories", json=note, headers=ORIGIN).status_code == 201


def test_sign_in_requires_an_origin_header(client):
    assert sign_in(client, headers={}).status_code == 403
    assert sign_in(client, headers={"Origin": "https://attacker.invalid"}).status_code == 403


def test_an_explicit_bearer_header_never_falls_back_to_the_cookie(client):
    sign_in(client)
    assert client.get("/v1/me", headers={"Authorization": "Bearer ah_" + "x" * 50}).status_code == 401


def test_sign_out_and_password_change_revoke_sessions(app, client):
    sign_in(client)
    assert client.get("/v1/me").status_code == 200
    assert client.post("/auth/logout", headers=ORIGIN).status_code == 200
    assert client.get("/v1/me").status_code == 401

    sign_in(client)
    secret = client.cookies.get(cookie_name("localhost"))
    app.state.auth.set_password("a different long password")
    assert client.get("/v1/me").status_code == 401
    assert app.state.auth.session_principal(secret) is None


def test_disabling_the_password_signs_everyone_out(app, client):
    sign_in(client)
    app.state.auth.clear_password()
    assert client.get("/v1/me").status_code == 401
    assert client.get("/health").json()["password_login"] is False


def test_expired_sessions_are_rejected(app, client):
    sign_in(client)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(app.state.settings.auth_database) as connection:
        connection.execute("UPDATE browser_sessions SET expires_at=?", (past,))
    assert client.get("/v1/me").status_code == 401


def test_repeated_wrong_passwords_are_throttled(client):
    for _ in range(5):
        assert sign_in(client, "not the password").status_code == 401
    blocked = sign_in(client)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1


def test_password_rules_and_storage(tmp_path):
    auth = AuthStore(tmp_path / "auth.sqlite3")
    with pytest.raises(ValueError):
        auth.set_password("short")
    auth.set_password(PASSWORD)
    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        stored = connection.execute("SELECT hash, salt FROM browser_password").fetchone()
    assert PASSWORD not in "".join(stored)
    assert auth.check_password(PASSWORD) and not auth.check_password(PASSWORD + "!")
    assert auth.session_principal("ahs_not-a-session") is None


def test_set_password_command(tmp_path):
    def run(*args, stdin=""):
        return subprocess.run([sys.executable, "-m", "agent_hub.cli", "set-password", "--data-dir", str(tmp_path), *args],
                              input=stdin, capture_output=True, text=True)
    assert run("--stdin", stdin="short\n").returncode != 0
    assert run("--stdin", stdin=PASSWORD + "\n").returncode == 0
    assert AuthStore(tmp_path / "auth.sqlite3").check_password(PASSWORD)
    assert run("--disable").returncode == 0
    assert not AuthStore(tmp_path / "auth.sqlite3").password_enabled()


def test_cookie_names_are_per_port_so_home_and_work_tunnels_coexist(app, client):
    assert cookie_name("127.0.0.1:18765") != cookie_name("127.0.0.1:18766")
    assert cookie_name("memory.example.test", secure=True) == SESSION_COOKIE + "_443"
    sign_in(client)
    secret = client.cookies.get(cookie_name("localhost"))
    other = TestClient(app, base_url="http://localhost:18766")
    other.cookies.set(cookie_name("localhost"), secret)  # the port-80 cookie sent to another port
    assert other.get("/v1/me", headers={"Host": "localhost:18766"}).status_code == 401
