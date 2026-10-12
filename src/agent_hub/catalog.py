"""A versioned inventory, not an implicit installer or arbitrary command runner."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: Literal["mcp", "plugin", "skill"]
    description: str
    status: Literal["built-in", "planned", "external"]
    source: str
    clients: list[str] = Field(default_factory=list)
    credentials: list[str] = Field(default_factory=list)


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    entries: list[Entry]


def load_catalog(path: Path | None = None) -> dict:
    path = path or Path(__file__).with_name("catalog.json")
    catalog = Catalog.model_validate(json.loads(path.read_text(encoding="utf-8")))
    identifiers = [entry.id for entry in catalog.entries]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Catalog entry identifiers must be unique")
    return catalog.model_dump()
