"""Explicit pages keep a retrieved tool result from consuming a whole context."""
from __future__ import annotations

import json

MAX_RESULT_BYTES = 160_000


def event_page(event: dict, offset: int = 0, max_chars: int = 16000, representation: str = "text") -> dict:
    if representation not in {"text", "raw"}:
        raise ValueError("Representation must be text or raw")
    if offset < 0 or not 1 <= max_chars <= 24000:
        raise ValueError("Invalid event page bounds")
    value = event.get(representation, "")
    if offset > len(value):
        raise ValueError("Event offset is beyond the captured record")
    end = min(len(value), offset + max_chars)
    result = {key: item for key, item in event.items() if key not in {"text", "raw"}}
    result.update({representation: value[offset:end], "representation": representation,
                   "offset": offset, "total_chars": len(value),
                   "next_offset": end if end < len(value) else None,
                   "truncated": offset != 0 or end < len(value), "raw_available": True})
    return result


def session_page(session: dict, offset: int) -> dict:
    result = {key: value for key, value in session.items() if key != "events"}
    # Session metadata is captured data too. Keep large metadata out of tool previews.
    metadata = result.pop("metadata", None)
    if metadata is not None:
        result["metadata_available"] = True
    events = []
    for event in session.get("events", []):
        page = event_page(event, 0, 1000)
        if len(json.dumps({**result, "events": events + [page]}, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
            break
        events.append(page)
    result["events"] = events
    total = result.get("total", result.get("total_events", len(events) + offset))
    result["next_offset"] = offset + len(events) if offset + len(events) < total else None
    result["truncated"] = result["next_offset"] is not None or any(event["truncated"] for event in events)
    return result


def bounded_result(value):
    """Do not cut serialized JSON. Fail visibly if an unforeseen shape exceeds the wire cap."""
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("Result exceeds 160000 UTF-8 bytes; request a smaller page or context budget")
    return value
