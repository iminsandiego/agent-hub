"""Local administration integration tests with isolated directories and secrets."""

import argparse
import json
import os
import sqlite3
from pathlib import Path

import pytest

from agent_hub import admin
from agent_hub.auth import AuthStore
from agent_hub.config import ServerSettings
from agent_hub.store import Store


def run_admin(*arguments):
    parser = argparse.ArgumentParser()
    admin.register_commands(parser.add_subparsers(required=True))
    args = parser.parse_args([str(argument) for argument in arguments])
    return args.func(args)


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    monkeypatch.delenv("AGENT_HUB_SERVER_CONFIG", raising=False)
    monkeypatch.delenv("AGENT_HUB_DATA_DIR", raising=False)


@pytest.fixture
def initialized(tmp_path, capsys):
    data = tmp_path / "server"
    run_admin("init-server", "--data-dir", data, "--project", "alpha", "--project", "beta")
    capsys.readouterr()
    return ServerSettings(data_dir=data)


def test_init_writes_private_credentials_but_never_prints_the_secret(tmp_path, capsys):
    data = tmp_path / "new-server"
    run_admin("init-server", "--data-dir", data, "--project", "alpha")
    output = capsys.readouterr()
    result = json.loads(output.out)
    secret = (data / "admin.token").read_text().strip()
    assert secret not in output.out + output.err
    assert result["admin_token_file"] == str(data / "admin.token")
    assert result["projects"] == ["alpha"]
    principal = AuthStore(data / "auth.sqlite3").authenticate(secret)
    assert principal is not None and principal.admin
    assert principal.projects == ("*",)
    settings = json.loads((data / "server.json").read_text())
    assert settings["data_dir"] == str(data)
    if os.name == "posix":
        assert (data / "admin.token").stat().st_mode & 0o777 == 0o600
        assert (data / "server.json").stat().st_mode & 0o777 == 0o600


def test_reinitialization_preserves_existing_config_credentials_and_projects(initialized, capsys):
    config = initialized.data_dir / "server.json"
    original_config = config.read_bytes()
    original_token = (initialized.data_dir / "admin.token").read_bytes()
    auth = AuthStore(initialized.auth_database)
    original_grants = auth.list()
    with pytest.raises(ValueError, match="already initialized"):
        run_admin("init-server", "--data-dir", initialized.data_dir, "--project", "new-project")
    assert config.read_bytes() == original_config
    assert (initialized.data_dir / "admin.token").read_bytes() == original_token
    assert auth.list() == original_grants
    assert {row["id"] for row in Store(initialized.database).list_projects()} == {"alpha", "beta"}
    assert not capsys.readouterr().out


def test_existing_admin_token_is_refused_before_issuing_an_unrecoverable_grant(tmp_path):
    data = tmp_path / "partial-server"
    data.mkdir()
    token = data / "admin.token"
    token.write_text("existing credential must survive\n")
    with pytest.raises((ValueError, FileExistsError)):
        run_admin("init-server", "--data-dir", data, "--project", "alpha")
    assert token.read_text() == "existing credential must survive\n"
    assert not (data / "auth.sqlite3").exists(), "Preflight must happen before creating an inaccessible admin grant"


def test_scoped_provisioning_listing_and_revocation_without_secret_stdout(initialized, tmp_path, capsys):
    token_path = tmp_path / "client.token"
    run_admin("token", "--data-dir", initialized.data_dir, "create", "--name", "new-laptop", "--project", "alpha", "--output", token_path)
    output = capsys.readouterr()
    result = json.loads(output.out)
    secret = token_path.read_text().strip()
    assert secret not in output.out + output.err
    auth = AuthStore(initialized.auth_database)
    principal = auth.authenticate(secret)
    assert principal is not None and principal.allows("alpha", "read") and principal.allows("alpha", "write")
    assert not principal.allows("beta")
    assert not principal.admin
    run_admin("token", "--data-dir", initialized.data_dir, "list")
    listing = capsys.readouterr()
    assert secret not in listing.out + listing.err
    assert all("digest" not in record for record in json.loads(listing.out))
    run_admin("token", "--data-dir", initialized.data_dir, "revoke", "--id", result["id"])
    revoked = capsys.readouterr()
    assert secret not in revoked.out + revoked.err
    assert auth.authenticate(secret) is None


def test_client_token_cannot_gain_all_project_or_admin_scope(initialized, tmp_path):
    before = AuthStore(initialized.auth_database).list()
    with pytest.raises(ValueError, match="explicit projects"):
        run_admin("token", "--data-dir", initialized.data_dir, "create", "--name", "unsafe", "--project", "*", "--output", tmp_path / "wildcard.token")
    with pytest.raises(SystemExit):
        run_admin("token", "--data-dir", initialized.data_dir, "create", "--name", "unsafe", "--project", "alpha", "--permissions", "admin", "--output", tmp_path / "admin-client.token")
    assert AuthStore(initialized.auth_database).list() == before


def test_unknown_project_and_duplicate_output_do_not_create_extra_grants(initialized, tmp_path):
    path = tmp_path / "existing.token"
    path.write_text("do not replace this existing client credential\n")
    before = AuthStore(initialized.auth_database).list()
    for project, destination in [("alpha", path), ("unknown", tmp_path / "unknown.token")]:
        with pytest.raises(ValueError):
            run_admin("token", "--data-dir", initialized.data_dir, "create", "--name", "new-machine", "--project", project, "--output", destination)
    assert path.read_text() == "do not replace this existing client credential\n"
    assert AuthStore(initialized.auth_database).list() == before


def test_failed_token_file_write_revokes_the_new_grant(initialized, tmp_path, monkeypatch, capsys):
    auth = AuthStore(initialized.auth_database)
    existing_active = {record["id"] for record in auth.list() if record["revoked_at"] is None}

    def failed_write(*args, **kwargs):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(admin, "write_private", failed_write)
    with pytest.raises(OSError, match="disk write"):
        run_admin("token", "--data-dir", initialized.data_dir, "create", "--name", "failed-machine", "--project", "alpha", "--output", tmp_path / "new.token")
    assert {record["id"] for record in auth.list() if record["revoked_at"] is None} == existing_active
    assert not capsys.readouterr().out


def test_admin_backup_and_fresh_restore_preserve_memory_but_require_new_credentials(initialized, tmp_path, capsys):
    store = Store(initialized.database)
    archived = store.ingest("alpha", "codex", "test", "session", [{"event_id": "one", "role": "user", "text": "A durable original source", "raw": '{ "exact": "raw record" }\n'}])
    note = store.add_memory("alpha", "A reviewed decision", source_event_ids=archived["event_ids"])
    store.review_memory("alpha", note["id"], "active", actor="test-admin")
    old_token = (initialized.data_dir / "admin.token").read_text().strip()
    backup_path = tmp_path / "backups" / "memory.sqlite3"
    run_admin("backup", "--data-dir", initialized.data_dir, "--output", backup_path)
    capsys.readouterr()
    target = tmp_path / "restored-server"
    run_admin("restore", "--data-dir", target, "--source", backup_path)
    restore_output = capsys.readouterr()
    assert old_token not in restore_output.out + restore_output.err
    assert not (target / "auth.sqlite3").exists()
    assert not (target / "admin.token").exists()
    restored = Store(target / "memory.sqlite3")
    assert restored.get_session("alpha", archived["session_id"]) == store.get_session("alpha", archived["session_id"])
    assert restored.get_memory("alpha", note["id"]) == store.get_memory("alpha", note["id"])
    assert restored.view("alpha") == store.view("alpha")
    run_admin("init-server", "--data-dir", target, "--project", "alpha")
    init_output = capsys.readouterr()
    new_token = (target / "admin.token").read_text().strip()
    assert new_token != old_token
    assert new_token not in init_output.out + init_output.err
    assert AuthStore(target / "auth.sqlite3").authenticate(old_token) is None
    assert {row["id"] for row in Store(target / "memory.sqlite3").list_projects()} == {"alpha", "beta"}


def test_restore_refuses_existing_server_and_preserves_its_files(initialized, tmp_path):
    backup_path = tmp_path / "backup.sqlite3"
    Store(initialized.database).backup(backup_path)
    config = (initialized.data_dir / "server.json").read_bytes()
    token = (initialized.data_dir / "admin.token").read_bytes()
    history = Store(initialized.database).stats("alpha")
    with pytest.raises(ValueError, match="empty"):
        run_admin("restore", "--data-dir", initialized.data_dir, "--source", backup_path)
    assert (initialized.data_dir / "server.json").read_bytes() == config
    assert (initialized.data_dir / "admin.token").read_bytes() == token
    assert Store(initialized.database).stats("alpha") == history


@pytest.mark.parametrize("existing_file", ["server.json", "admin.token"])
def test_restore_refuses_existing_configuration_or_credential_files(initialized, tmp_path, existing_file):
    backup_path = tmp_path / "backup.sqlite3"
    Store(initialized.database).backup(backup_path)
    target = tmp_path / "partial-server"
    target.mkdir()
    existing = target / existing_file
    existing.write_text("Existing configuration or credential must be retained\n")
    with pytest.raises(ValueError, match="empty"):
        run_admin("restore", "--data-dir", target, "--source", backup_path)
    assert existing.read_text() == "Existing configuration or credential must be retained\n"
    assert not (target / "memory.sqlite3").exists()


def test_restore_closes_all_sqlite_connections_explicitly(initialized, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.sqlite3"
    Store(initialized.database).backup(backup_path)
    original_connect = sqlite3.connect
    opened = []

    class ObservedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            return super().close()

    def observed_connect(*args, **kwargs):
        connection = original_connect(*args, factory=ObservedConnection, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    try:
        run_admin("restore", "--data-dir", tmp_path / "restored", "--source", backup_path)
        assert opened and all(connection.closed for connection in opened)
    finally:
        for connection in opened:
            connection.close()
