"""Optional private skills repository: clone or update it, then run its installer.

The repository is the owner's own, named only in the local client.json. Agent
Hub never stores its address in Git, never reads its contents, and only runs the
repository's root ``install.sh`` (with ``--dry-run`` for a dry run).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .client import ClientError

Runner = Callable[..., subprocess.CompletedProcess]

# scp-style SSH (git@host:owner/repo.git), ssh:// or https://. No option-like,
# transport-helper (ext::) or file:// sources.
_REMOTE = re.compile(r"^(?:[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._/-]+|(?:ssh|https)://[^\s]+)$")
_TIMEOUT = 300


def validate_skills_repo(value: str | None) -> str | None:
    """Return the value if usable. ``None`` means never asked, ``""`` means declined."""
    if value is None or value == "":
        return value
    if not isinstance(value, str) or value != value.strip() or value.startswith("-"):
        raise ClientError("skills_repo must be a git URL, an absolute local path, or empty.")
    if _REMOTE.fullmatch(value):
        if "::" in value:
            raise ClientError("skills_repo must be a git URL, an absolute local path, or empty.")
        return value
    if Path(value).expanduser().is_absolute():
        return value
    raise ClientError("skills_repo must be an SSH or HTTPS git URL, an absolute local path, or empty.")


def is_remote(value: str) -> bool:
    return bool(_REMOTE.fullmatch(value))


def checkout_path(value: str, config_path: Path) -> Path:
    """Local path for a remote is beside client.json; a local path is used as given."""
    if is_remote(value):
        return Path(config_path).expanduser().resolve().parent / "skills-repo"
    return Path(value).expanduser().resolve()


def prompt_for_repo(ask: Callable[[str], str] | None = None) -> str:
    answer = (ask or input)("Private skills repository (git URL or local path; blank to skip): ").strip()
    return validate_skills_repo(answer) or ""


def sync_skills(value: str | None, config_path: Path, *, dry_run: bool = False, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Clone or fast-forward the configured repository and run its installer."""
    if not value:
        return {"status": "skipped", "reason": "no skills repository configured" if value is None else "declined"}
    if sys.platform == "win32":
        return {"status": "skipped", "reason": "skill installers are POSIX shell scripts; not run on Windows"}
    git = shutil.which("git")
    if not git:
        return {"status": "error", "error": "git is not on PATH"}
    target = checkout_path(value, config_path)
    steps: list[str] = []
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def run(argv: list[str]) -> subprocess.CompletedProcess:
        return runner(argv, capture_output=True, text=True, timeout=_TIMEOUT, check=False, env=env)

    try:
        if is_remote(value):
            if not (target / ".git").exists():
                if target.exists():
                    return {"status": "error", "error": f"{target} exists but is not a git checkout; move it aside"}
                if dry_run:
                    return {"status": "dry_run", "checkout": str(target), "steps": ["would clone the skills repository", "would run install.sh"]}
                result = run([git, "clone", "--quiet", "--", value, str(target)])
                if result.returncode:
                    return {"status": "error", "error": "clone failed: " + _last_line(result)}
                steps.append("cloned")
            elif not dry_run:
                result = run([git, "-C", str(target), "pull", "--ff-only", "--quiet"])
                if result.returncode:
                    return {"status": "error", "checkout": str(target), "error": "update failed: " + _last_line(result)}
                steps.append("updated")
        elif not target.is_dir():
            return {"status": "error", "error": f"skills repository path does not exist: {target}"}

        installer = target / "install.sh"
        if not installer.is_file():
            return {"status": "error", "checkout": str(target), "error": "the skills repository has no install.sh at its root"}
        command = [str(installer)] if os.access(installer, os.X_OK) else ["/bin/sh", str(installer)]
        result = run(command + (["--dry-run"] if dry_run else []))
        output = [line.rstrip() for line in (result.stdout or "").splitlines() if line.strip()]
        if result.returncode:
            return {"status": "error", "checkout": str(target), "steps": steps, "output": output, "error": "install.sh failed: " + _last_line(result)}
        steps.append("ran install.sh --dry-run" if dry_run else "ran install.sh")
        return {"status": "dry_run" if dry_run else "installed", "checkout": str(target), "steps": steps, "output": output}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "checkout": str(target), "error": type(exc).__name__}


def _last_line(result: subprocess.CompletedProcess) -> str:
    text = (result.stderr or result.stdout or "").strip().splitlines()
    return text[-1][:300] if text else f"exit {result.returncode}"
