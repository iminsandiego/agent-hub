"""Optional private skills repository: validation, clone/update, installer, setup flow."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

import pytest

from agent_hub import cli
from agent_hub.client import ClientConfig, ClientError
from agent_hub.skills import checkout_path, sync_skills, validate_skills_repo

pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("git"), reason="needs git and a POSIX shell")


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                        "HOME": str(cwd or "."), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


@pytest.fixture
def skills_origin(tmp_path):
    """A synthetic skills repo whose install.sh records each run and its arguments."""
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "install.sh").write_text('#!/bin/sh\necho "ran $*" >> "$(dirname "$0")/../install.log"\necho "installer output $*"\n')
    (origin / "install.sh").chmod(0o755)
    _git("init", "-q", "-b", "main", cwd=origin)
    _git("add", ".", cwd=origin)
    _git("commit", "-q", "-m", "init", cwd=origin)
    return origin


@pytest.mark.parametrize("value", [
    None, "", "git@github.com:someone/skills.git", "ssh://git@example.com/skills.git",
    "https://example.com/someone/skills.git", "/absolute/skills",
])
def test_accepts_supported_sources(value):
    assert validate_skills_repo(value) == value


@pytest.mark.parametrize("value", [
    "relative/skills", "-uhelp", "ext::sh -c evil", "file:///tmp/skills", " git@github.com:a/b.git",
    "git@github.com:a/b.git; rm -rf /",
])
def test_rejects_unsafe_or_ambiguous_sources(value):
    with pytest.raises(ClientError):
        validate_skills_repo(value)


def test_config_round_trips_skills_repo(tmp_path):
    path = tmp_path / "client.json"
    ClientConfig(url="http://127.0.0.1:9867", machine_id="m", skills_repo="git@github.com:a/b.git").save(path)
    assert ClientConfig.load(path).skills_repo == "git@github.com:a/b.git"
    with pytest.raises(ClientError):
        ClientConfig(url="http://127.0.0.1:9867", machine_id="m", skills_repo="relative")


def test_skipped_when_unset_or_declined(tmp_path):
    assert sync_skills(None, tmp_path / "client.json")["status"] == "skipped"
    assert sync_skills("", tmp_path / "client.json")["reason"] == "declined"


def test_local_path_runs_installer_without_git_changes(skills_origin, tmp_path):
    result = sync_skills(str(skills_origin), tmp_path / "client.json")
    assert result["status"] == "installed"
    assert result["output"] == ["installer output"]
    assert (tmp_path / "install.log").read_text() == "ran \n"


def test_remote_clones_beside_config_then_updates(skills_origin, tmp_path, monkeypatch):
    # Treat the local origin as a remote by routing the https form through git's url rewrite.
    url = "https://example.invalid/someone/skills.git"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{skills_origin}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", url)
    config_path = tmp_path / "cfg" / "client.json"
    config_path.parent.mkdir()

    dry = sync_skills(url, config_path, dry_run=True)
    assert dry["status"] == "dry_run" and not checkout_path(url, config_path).exists()

    first = sync_skills(url, config_path)
    assert first["status"] == "installed" and first["steps"] == ["cloned", "ran install.sh"]
    assert checkout_path(url, config_path) == config_path.parent / "skills-repo"

    (skills_origin / "NEW").write_text("x")
    _git("add", ".", cwd=skills_origin)
    _git("commit", "-q", "-m", "more", cwd=skills_origin)
    second = sync_skills(url, config_path)
    assert second["steps"] == ["updated", "ran install.sh"]
    assert (config_path.parent / "skills-repo" / "NEW").exists()

    rehearsal = sync_skills(url, config_path, dry_run=True)
    assert rehearsal["steps"] == ["ran install.sh --dry-run"]
    assert rehearsal["output"] == ["installer output --dry-run"]


def test_errors_are_reported_not_raised(tmp_path):
    missing = sync_skills(str(tmp_path / "nope"), tmp_path / "client.json")
    assert missing["status"] == "error"
    (tmp_path / "repo").mkdir()
    no_installer = sync_skills(str(tmp_path / "repo"), tmp_path / "client.json")
    assert "install.sh" in no_installer["error"]
    blocked = tmp_path / "cfg"
    (blocked / "skills-repo").mkdir(parents=True)
    occupied = sync_skills("git@example.invalid:a/b.git", blocked / "client.json")
    assert "not a git checkout" in occupied["error"]


def _setup_args(config_path, **overrides):
    values = dict(config=str(config_path), clients=["t3"], codex_home=None, claude_home=None,
                  claude_mcp_file=None, transport="stdio", no_hooks=True, dry_run=False, skills_repo=None)
    values.update(overrides)
    return argparse.Namespace(**values)


def _write_config(path, **extra):
    ClientConfig(url="http://127.0.0.1:9867", machine_id="m", **extra).save(path)


def test_setup_prompts_once_and_remembers_the_answer(skills_origin, tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "client.json"
    _write_config(config_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: str(skills_origin))
    assert cli.setup(_setup_args(config_path)) == 0
    assert json.loads(capsys.readouterr().out)["skills"]["status"] == "installed"
    assert ClientConfig.load(config_path).skills_repo == str(skills_origin)

    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("asked again"))
    assert cli.setup(_setup_args(config_path)) == 0


def test_setup_blank_answer_is_saved_as_declined(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "client.json"
    _write_config(config_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert cli.setup(_setup_args(config_path)) == 0
    assert ClientConfig.load(config_path).skills_repo == ""


def test_setup_never_prompts_noninteractively_or_on_dry_run(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "client.json"
    _write_config(config_path)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("prompted"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert cli.setup(_setup_args(config_path)) == 0
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    assert cli.setup(_setup_args(config_path, dry_run=True)) == 0
    assert ClientConfig.load(config_path).skills_repo is None


def test_setup_flag_sets_and_none_clears(skills_origin, tmp_path, capsys):
    config_path = tmp_path / "client.json"
    _write_config(config_path)
    assert cli.setup(_setup_args(config_path, skills_repo=str(skills_origin))) == 0
    assert ClientConfig.load(config_path).skills_repo == str(skills_origin)
    assert cli.setup(_setup_args(config_path, skills_repo="none")) == 0
    assert ClientConfig.load(config_path).skills_repo == ""


def test_setup_reports_skill_failure_after_client_setup(tmp_path, capsys):
    config_path = tmp_path / "client.json"
    _write_config(config_path, skills_repo=str(tmp_path / "missing"))
    assert cli.setup(_setup_args(config_path)) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["skills"]["status"] == "error" and "changed" in result


def test_reconfigure_keeps_skills_repo(tmp_path, monkeypatch):
    config_path = tmp_path / "client.json"
    monkeypatch.setenv("AGENT_HUB_TOKEN", "synthetic")
    _write_config(config_path, skills_repo="git@example.invalid:a/b.git")
    args = cli.build_parser().parse_args(["--config", str(config_path), "configure", "--no-prompt"])
    args.func(args)
    assert ClientConfig.load(config_path).skills_repo == "git@example.invalid:a/b.git"
