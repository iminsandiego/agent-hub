"""Deterministic, rebuildable dyadic summaries of an immutable event sequence.

The default compressor only copies excerpts.  It does not infer facts or pretend
to be a semantic summary.  Every node identifies an inclusive sequence range;
the original events remain the authoritative archive.  The forest is complete
even when the event count is not a power of two.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

SUMMARY_BYTES = 512


def event_source(text: str, role: str | None = None) -> str:
    """Keep speaker identity attached to normalized text during compaction.

    JSON quoting makes instruction-like historical strings clearly data. Raw
    event storage is separate and is never replaced by this representation.
    """
    if role is None:
        return text
    return json.dumps({"role": role, "text": text}, ensure_ascii=False, separators=(",", ":"))


def clip_utf8(text: str, limit: int, *, marker: str = "…") -> str:
    """Return valid UTF-8 of at most ``limit`` bytes, with a loss marker."""
    if limit <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    suffix = marker.encode("utf-8")
    if len(suffix) > limit:
        return encoded[:limit].decode("utf-8", errors="ignore")
    return encoded[: limit - len(suffix)].decode("utf-8", errors="ignore") + marker


def clip_utf8_tail(text: str, limit: int, *, marker: str = "…") -> str:
    """Return valid UTF-8 of at most ``limit`` bytes from the end, with a loss marker."""
    if limit <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    prefix = marker.encode("utf-8")
    if len(prefix) > limit:
        return encoded[-limit:].decode("utf-8", errors="ignore")
    return marker + encoded[len(encoded) - (limit - len(prefix)):].decode("utf-8", errors="ignore")


def compact_excerpts(parts: Iterable[str], limit: int = SUMMARY_BYTES) -> str:
    """Copy bounded excerpts from both ends rather than silently favoring one:
    the start of the first part and the end of the last (of a single long part,
    its start and its end), so a range shows its earliest and latest material.

    The ellipses and separator are presentation, not generated source text.
    This function is intentionally deterministic and contains no model calls.
    """
    values = list(parts)
    if not values or limit <= 0:
        return ""
    joined = "\n\n".join(values)
    if len(joined.encode("utf-8")) <= limit:
        return joined
    if limit < 16:
        return clip_utf8(joined, limit)
    separator = "\n[…]\n"
    remaining = max(0, limit - len(separator.encode("utf-8")))
    left_budget = remaining // 2
    right_budget = remaining - left_budget
    return (
        clip_utf8(values[0], left_budget)
        + separator
        + clip_utf8_tail(values[-1], right_budget)
    )


def node_id(project: str, lo: int, hi: int) -> str:
    if lo < 0 or hi < lo:
        raise ValueError("Invalid inclusive node range")
    scope = hashlib.sha256(project.encode("utf-8")).hexdigest()
    return f"n_{scope}_{lo}_{hi}"


def make_leaf(
    project: str,
    sequence: int,
    text: str,
    *,
    event_id: str | None = None,
    role: str | None = None,
    summary_bytes: int = SUMMARY_BYTES,
) -> dict[str, Any]:
    source = event_source(text, role)
    complete = len(source.encode("utf-8")) <= summary_bytes
    return {
        "id": node_id(project, sequence, sequence),
        "lo": sequence,
        "hi": sequence,
        "summary": source if complete else compact_excerpts([source], summary_bytes),
        "mode": "verbatim" if complete else "extractive",
        "children": [],
        "event_id": event_id,
        "original_verbatim": complete,
    }


def merge_nodes(
    project: str,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    summary_bytes: int = SUMMARY_BYTES,
) -> dict[str, Any]:
    span = left["hi"] - left["lo"] + 1
    if (
        span <= 0
        or span & (span - 1)
        or right["hi"] - right["lo"] + 1 != span
        or left["hi"] + 1 != right["lo"]
        or left["lo"] % (2 * span)
    ):
        raise ValueError("Children must be adjacent, aligned equal dyadic ranges")
    original = bool(left.get("original_verbatim")) and bool(
        right.get("original_verbatim")
    )
    source = left["summary"] + "\n\n" + right["summary"]
    complete = original and len(source.encode("utf-8")) <= summary_bytes
    return {
        "id": node_id(project, left["lo"], right["hi"]),
        "lo": left["lo"],
        "hi": right["hi"],
        "summary": source if complete else compact_excerpts(
            [left["summary"], right["summary"]], summary_bytes
        ),
        "mode": "verbatim" if complete else "extractive",
        "children": [left["id"], right["id"]],
        "event_id": None,
        "original_verbatim": complete,
    }


def build_tree(
    project: str,
    events: Iterable[Mapping[str, Any]],
    *,
    summary_bytes: int = SUMMARY_BYTES,
) -> list[dict[str, Any]]:
    """Build all nodes in append order with O(n) total work and storage."""
    nodes: list[dict[str, Any]] = []
    by_range: dict[tuple[int, int], dict[str, Any]] = {}
    for expected, event in enumerate(events):
        sequence = event.get("sequence", expected)
        if sequence != expected:
            raise ValueError("Events must have contiguous zero-based sequences")
        current = make_leaf(
            project,
            sequence,
            event["text"],
            event_id=event.get("id", event.get("event_id")),
            role=event.get("role"),
            summary_bytes=summary_bytes,
        )
        nodes.append(current)
        by_range[(sequence, sequence)] = current
        span = 1
        while current["lo"] % (span * 2) == span:
            left = by_range[(current["lo"] - span, current["lo"] - 1)]
            current = merge_nodes(project, left, current, summary_bytes=summary_bytes)
            nodes.append(current)
            by_range[(current["lo"], current["hi"])] = current
            span *= 2
    return nodes


def select_frontier(
    nodes: Iterable[Mapping[str, Any]], max_nodes: int = 32
) -> list[dict[str, Any]]:
    """Select a disjoint covering view, refining the most recent ranges first.

    ``max_nodes`` is a refinement target.  A dyadic forest requires
    ``event_count.bit_count()`` roots.  When that minimum exceeds the target we
    return all roots, preserving coverage instead of dropping old history.
    """
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 1:
        raise ValueError("max_nodes must be a positive integer")
    by_id = {node["id"]: dict(node) for node in nodes}
    if not by_id:
        return []
    children = {child for node in by_id.values() for child in node["children"]}
    frontier = sorted(
        (node for identifier, node in by_id.items() if identifier not in children),
        key=lambda node: node["lo"],
    )
    end = -1
    for node in frontier:
        if node["lo"] != end + 1:
            raise ValueError("Tree roots must completely cover a contiguous sequence")
        end = node["hi"]
    while len(frontier) < max_nodes:
        index = next(
            (i for i in range(len(frontier) - 1, -1, -1) if frontier[i]["children"]),
            None,
        )
        if index is None:
            break
        current = frontier[index]
        if len(current["children"]) != 2:
            raise ValueError("Non-leaf dyadic nodes must have exactly two children")
        try:
            replacements = [by_id[child] for child in current["children"]]
        except KeyError as exc:
            raise ValueError("Missing tree child") from exc
        frontier[index : index + 1] = replacements
    return frontier
