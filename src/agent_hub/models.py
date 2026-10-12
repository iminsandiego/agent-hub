"""Bounded, explicit wire contracts for ingestion and memory operations."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventInput(WireModel):
    event_id: str = Field(min_length=1, max_length=256)
    role: str = Field(min_length=1, max_length=40)
    text: str = Field(max_length=1_000_000)
    raw: str = Field(max_length=67_108_864)
    timestamp: str | None = Field(default=None, max_length=100)


class RelatedSession(WireModel):
    client: Literal["codex", "claude", "t3", "generic", "chatgpt"]
    session_id: str = Field(min_length=1, max_length=256)


class SessionPrivacyInput(WireModel):
    mode: Literal["temporary", "forgotten"]


class IngestInput(WireModel):
    project: ProjectID
    client: Literal["codex", "claude", "t3", "generic", "chatgpt"]
    machine: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=256)
    events: list[EventInput] = Field(min_length=1, max_length=500)
    metadata: dict = Field(default_factory=dict)
    related_sessions: list[RelatedSession] = Field(default_factory=list, max_length=32)
    temporary: bool = False
    parent_sessions: list[RelatedSession] = Field(default_factory=list, max_length=8)

    @field_validator("metadata")
    @classmethod
    def small_metadata(cls, value: dict) -> dict:
        import json
        if len(json.dumps(value).encode("utf-8")) > 16_384:
            raise ValueError("Session metadata exceeds 16 KiB")
        return value


class MemoryInput(WireModel):
    statement: str = Field(min_length=1, max_length=8000)
    kind: Literal["decision", "instruction", "observation", "procedure", "failure", "question", "preference"] = "observation"
    source_event_ids: list[str] = Field(default_factory=list, max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=256)


class LoginInput(WireModel):
    password: str = Field(min_length=1, max_length=1024)


class ReviewInput(WireModel):
    status: Literal["active", "rejected"]
    supersedes: str | None = Field(default=None, max_length=128)


class ProjectInput(WireModel):
    project: ProjectID
    name: str = Field(default="", max_length=200)
