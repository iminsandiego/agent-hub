"""Server settings. Runtime credentials and history never belong in the repo."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    domain: Literal["home", "work"] | None = None
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".local/share/agent-hub")
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "[::1]"]
    allowed_origins: list[str] = ["http://127.0.0.1:8765", "http://localhost:8765"]
    max_body_bytes: int = Field(default=4_194_304, ge=1024, le=67_108_864)

    @field_validator("schema_version")
    @classmethod
    def known_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("Unsupported server configuration version")
        return value

    @field_validator("data_dir")
    @classmethod
    def absolute_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("allowed_hosts", "allowed_origins")
    @classmethod
    def explicit_allowlist(cls, value: list[str]) -> list[str]:
        if any("*" in item or not item for item in value):
            raise ValueError("Use explicit hosts/origins; wildcard access is not supported")
        return value

    @property
    def database(self) -> Path:
        return self.data_dir / "memory.sqlite3"

    def check_project(self, project: str) -> None:
        if self.domain and not project.startswith(self.domain + "-"):
            raise ValueError("Project is outside this server's domain")

    @property
    def auth_database(self) -> Path:
        return self.data_dir / "auth.sqlite3"


def load_settings(path: str | Path | None = None) -> ServerSettings:
    selected = path or os.environ.get("AGENT_HUB_SERVER_CONFIG")
    if selected:
        return ServerSettings.model_validate(json.loads(Path(selected).expanduser().read_text()))
    return ServerSettings(data_dir=os.environ.get("AGENT_HUB_DATA_DIR", str(Path.home() / ".local/share/agent-hub")))


def write_private(path: Path, text: str, *, overwrite: bool = False) -> None:
    """Create a private file, fsync it, and never clobber an existing secret by default."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if overwrite:
        descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
