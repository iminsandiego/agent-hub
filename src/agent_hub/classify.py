"""Which archived records are the conversation, and which are harness bookkeeping.

The archive keeps every record exactly as captured. This derived classification
only decides what the tree's excerpts, the startup context and search show: a
Codex rollout or Claude Code log is mostly event markers, token counts, metadata
and injected instructions, which otherwise crowd out what was said and done.
Classes are recomputed from the stored role, text and raw source; changing these
rules never edits a record (``agent-hub rebuild`` reapplies them).

Since 0.1.12 the server also stops archiving what has no content of its own:
bookkeeping records are discarded at ingest, and Codex approval-reviewer
threads (``excluded_session``) are not archived at all. ``agent-hub prune``
removes both from an archive captured earlier.

- (no class): what the user, assistant and tools said and did. Shown; ranked first.
- injected: harness-written text (instructions, environment blocks, developer
  messages, reasoning summaries). Hidden from the tree; ranked after.
- derived: every record of a derived thread (Codex subagent and internal
  threads such as the approval reviewer, Claude Code subagent transcripts).
  Hidden from the tree; ranked after.
- tool: a tool call or a tool's output. Hidden from the tree (its excerpts and
  any model summary describe what was said and decided); searched normally.
- title: a chat-title record. Hidden from the tree; used to name chats.
- metadata: a Codex thread's first record (its origin, cwd and settings), or a
  record of a type no parser reads yet. Kept (the first tells a derived thread
  apart; an unread type may be read by a later parser), hidden, not searched.
- bookkeeping: no content of its own (event markers, metadata, unsupported-record
  notes, empty records, Codex's second copy of a message, compaction snapshots).
  Discarded at ingest and by ``prune``.
"""

from __future__ import annotations

import json
import re
from typing import Any

CLASSIFIER_VERSION = 1

BOOKKEEPING = "bookkeeping"
INJECTED = "injected"
DERIVED = "derived"
TITLE = "title"
TOOL = "tool"
METADATA = "metadata"
UNSEARCHED = (BOOKKEEPING, METADATA)
DEMOTED = (INJECTED, DERIVED)

# Placeholder texts our own adapters write when a record has no text of its own.
_MARKER = re.compile(
    r"^(Codex event: |Codex (session_meta|turn_context|compacted) metadata\.|"
    r"Claude (system|summary|progress|queue-operation|file-history-snapshot) metadata\.)"
)
_UNSUPPORTED = re.compile(r"^Unsupported (Codex|Claude) record \(([^)]+)\)")
# A message whose content is an image, document or file has no normalized text.
_NONTEXT = re.compile(r'"type"\s*:\s*"(image|input_image|image_url|localImage|document|input_file|file)"')
_QUEUED = re.compile(r'"type"\s*:\s*"queued_command"')
# Record types the adapters do not read that are known to carry nothing worth
# keeping: request copies, counters, UI and session state. Claude attachments are
# mostly hook output (including agent-hub's own injected context); a queued
# prompt is the user's own message and is kept.
_NOISE_TYPES = {
    "Codex": {"token_usage_record", "world_state", "inter_agent_communication_metadata"},
    "Claude": {"attachment", "last-prompt", "atis-latch", "bridge-session", "agent-name", "mode", "pr-link",
               "cost-state", "file-history-delta", "api-request", "api-request-blob", "api-request-shape",
               "fork-context-ref"},
}
# Blocks clients inject into the user's turn; same shape the v2 parser recognizes.
_INJECTED = re.compile(r"^\s*(<[a-z_][a-z0-9_-]*[ >]|# AGENTS\.md|Caveat: The messages below were generated|"
                       r"Context handoff \()", re.I)
# Slash commands and subagent reports are the user's or an agent's own actions.
_KEPT_TAGS = re.compile(r"^\s*<(command-name|command-message|subagent_notification|pasted_content)[ >]", re.I)


# A Codex rollout line starts {"timestamp":..,"type":..,"payload":{"type":..}; the
# head is enough, so classifying never parses a large record.
_HEAD = re.compile(r'"type"\s*:\s*"(event_msg|response_item|session_meta|turn_context|compacted)"\s*,\s*"payload"\s*:\s*\{\s*(?:"type"\s*:\s*"([a-z_]+)")?')
# Claude Code log records that only repeat or track other records: a queued
# prompt's bookkeeping copy, file snapshots and progress ticks.
_CLAUDE_BOOKKEEPING = re.compile(r'"type"\s*:\s*"(queue-operation|file-history-snapshot|progress)"')


def _raw_kind(raw: str) -> tuple[str | None, str | None]:
    """The record type and payload type of a Codex rollout line."""
    match = _HEAD.search(raw[:400])
    return (match[1], match[2]) if match else (None, None)


def classify_event(role: str, text: str, raw: str = "") -> str | None:
    """An event's own class, or None for the conversation itself."""
    kind, payload_kind = _raw_kind(raw) if raw else (None, None)
    if kind == "session_meta":
        return METADATA
    if kind == "turn_context":
        return BOOKKEEPING
    if kind == "compacted":
        # A compaction's own summary is harness-written context; without one the
        # record is only a copy of the history before it.
        return BOOKKEEPING if not text.strip() or _MARKER.match(text) else INJECTED
    if role == "system" and chat_title(text, raw):
        return TITLE
    if not text.strip():
        # Empty text is bookkeeping unless the record carries a non-text payload
        # (an image-only message); a user record with no text is kept regardless.
        return METADATA if role == "user" or _NONTEXT.search(raw) else BOOKKEEPING
    unsupported = _UNSUPPORTED.match(text) if role == "system" else None
    if unsupported:
        noise = unsupported[2] in _NOISE_TYPES.get(unsupported[1], set())
        return BOOKKEEPING if noise and not _QUEUED.search(raw) else METADATA
    if role == "system" and text.startswith("Unsupported JSON value retained"):
        return METADATA
    if kind == "event_msg" and role not in {"user", "assistant"}:
        # Status events. (Parser version 1 kept a message's event copy as the
        # message itself; some logs have only that copy, so it stays. Version 2
        # writes a placeholder for the copy, which the marker rule below drops.)
        return BOOKKEEPING
    if role == "system" and raw and _CLAUDE_BOOKKEEPING.search(raw[:400]):
        return BOOKKEEPING
    if role == "system" and _MARKER.match(text):
        return BOOKKEEPING
    if kind == "response_item" and payload_kind == "reasoning":
        return INJECTED
    if role == "developer":
        return INJECTED
    if role in {"user", "system"} and _INJECTED.match(text) and not _KEPT_TAGS.match(text) and _all_blocks_injected(raw):
        return INJECTED
    if role == "tool" or (role == "assistant" and text.startswith("Tool call:")):
        return TOOL
    return None


def excluded_session(client: str, metadata: dict[str, Any], first_raw: str | None = None) -> str | None:
    """Why a session is not archived at all, or None.

    Codex's approval reviewer ("guardian") gets a copy of the parent chat with
    every action it judges, so its threads repeat the conversation many times
    over (782 threads and an eighth of one home archive's bytes).
    """
    if first_raw:
        try:
            value = json.loads(first_raw)
        except ValueError:
            value = None
        if isinstance(value, dict):
            payload = value.get("payload") if value.get("type") == "session_meta" else value
            source = payload.get("source") if isinstance(payload, dict) else None
            subagent = source.get("subagent") if isinstance(source, dict) else None
            if isinstance(subagent, dict) and subagent.get("other") == "guardian":
                return "codex approval reviewer"
            if client == "generic" and metadata.get("format") == "codex_sqlite_title_v1" and \
                    "guardian review" in {str(value.get("name") or "").strip().lower(), str(value.get("title") or "").strip().lower()}:
                return "codex approval reviewer"
    return None


_CODEX_TITLE = re.compile(r"Codex chat title: (.*)\n(?:.*\n)*?Agent Hub original session: (s_[0-9a-f]+)")


def chat_title(text: str, raw: str) -> tuple[str, str, str | None] | None:
    """A title a record gives a chat: (title, source, session) or None.

    Claude Code writes ``custom-title`` (the user's rename) and ``ai-title``
    records into its log; agent-hub records Codex's thread names as separate
    one-record sessions naming the chat they belong to (``session``).
    """
    if text.startswith(("Unsupported Claude record (custom-title)", "Unsupported Claude record (ai-title)")):
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        if isinstance(value, dict):
            title = value.get("customTitle") or value.get("aiTitle") or value.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip(), "custom" if value.get("type") == "custom-title" else "ai", None
        return None
    match = _CODEX_TITLE.match(text)
    if match and match[1].strip():
        return match[1].strip(), "codex", match[2]
    return None


def _all_blocks_injected(raw: str) -> bool:
    """Whether every text block of a message is client-injected (not only the first).

    A message whose first block is an environment or instruction block can still
    carry the user's own words in a later block; only an all-injected message is
    injected. A record whose blocks cannot be read is judged by its joined text.
    """
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return True
    if not isinstance(value, dict):
        return True
    holder = value.get("message") if isinstance(value.get("message"), dict) else value.get("payload")
    content = holder.get("content") if isinstance(holder, dict) else None
    if not isinstance(content, list):
        return True
    texts = [block.get("text") for block in content if isinstance(block, dict) and isinstance(block.get("text"), str)]
    return all(_INJECTED.match(text) and not _KEPT_TAGS.match(text) for text in texts if text.strip())


def needs_whole_source(role: str, text: str) -> bool:
    """Whether classifying this record reads past its first 400 raw characters."""
    return not text.strip() or text.startswith("Unsupported ") or (role in {"user", "system"} and bool(_INJECTED.match(text)))


def classify_session(client: str, metadata: dict[str, Any], first_raw: str | None = None) -> str | None:
    """A session's class from its metadata and, for Codex, its first record."""
    if client == "generic" and metadata.get("format") == "codex_sqlite_title_v1":
        return TITLE
    if "/subagents/" in str(metadata.get("source_path", "")).replace("\\", "/"):
        return DERIVED
    if first_raw:
        try:
            value = json.loads(first_raw)
        except ValueError:
            value = None
        if isinstance(value, dict) and value.get("type") == "session_meta" and isinstance(value.get("payload"), dict):
            payload = value["payload"]
            source = payload.get("source")
            if payload.get("thread_source") == "subagent" or (isinstance(source, dict) and ({"subagent", "internal"} & set(source))):
                return DERIVED
    return None
