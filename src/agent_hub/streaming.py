"""Bounded-memory historical JSONL ingestion with unchanged native event IDs."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .adapters import parse_jsonl, tail_settled
from .privacy import temporary_message
from .sources import compressed, open_transcript


def chunks(source: Path, size: int | None, budget: int = 512_000):
    """Whole-line chunks of the first ``size`` bytes, or of all of them (None)."""
    size = float("inf") if size is None else size
    base = ordinal = 0
    with open_transcript(source) as stream:
        while base < size:
            lines = []; length = 0
            while base + length < size:
                line = stream.readline(min(size - base - length, 67_108_865))
                if not line:
                    break
                if len(line) > 67_108_864:
                    raise ValueError("A source record exceeds 64 MiB; source retained for explicit review")
                lines.append(line); length += len(line)
                if length >= budget:
                    break
            if not lines:
                break
            yield base, ordinal, b"".join(lines)
            base += length; ordinal += len(lines)


def ingest_large_file(config, source, *, client="auto", project=None, cwd=None,
                      session_id=None, final=False, memory=None, state=None, adapter_version=1):
    from .client import ClientError, LocalState, MemoryClient, _batches, file_key
    state = state or LocalState(config)
    stat = source.stat()
    length = None if compressed(source) else stat.st_size  # a compressed file is read to its end
    key = file_key(config, source, client, session_id)
    previous = state.checkpoint(key)
    offset = previous["offset"] if previous else 0
    if length is not None and offset > length:
        raise ClientError("Transcript was truncated; source retained for review")
    base_transcript = None; target = None; identity = session_id
    prior_hash = hashlib.sha256(); unknown = set(); record_count = 0
    pending_bytes = complete_bytes = 0; first_event = None
    # Preflight the whole snapshot before uploading: malformed records, routing
    # violations and a temporary marker near the end cannot cause partial capture.
    for base, ordinal, data in chunks(source, length):
        part = parse_jsonl(data, client=client if base_transcript is None else base_transcript.client,
                           machine=config.machine_id, path=str(source), session_id=identity,
                           cwd=cwd if base_transcript is None else base_transcript.cwd,
                           final=final, start_line=ordinal, adapter_version=adapter_version, settled=tail_settled(stat))
        if base_transcript is None:
            base_transcript = part
            target = config.resolve_project(part.cwd, project)
            identity = part.metadata.get("parent_session_id") or part.session_id
            first_event = part.events[0] if part.events else None
            if previous and (previous["session_id"] != part.session_id or previous["project"] != target):
                raise ClientError("The transcript session or project assignment changed after capture")
        config.check_transcript(part, target, cwd)
        base_transcript.temporary |= temporary_message(part.events)
        if base < offset:
            prior_hash.update(data[:min(len(data), offset - base)])
        record_count += len(part.events); unknown.update(part.unknown_types)
        complete_bytes = base + part.complete_bytes; pending_bytes = part.pending_bytes
        part.events = []
    if base_transcript is None:
        raise ClientError("Empty transcript; source retained for retry")
    if previous and prior_hash.hexdigest() != previous["prefix_sha"]:
        raise ClientError("Transcript was rewritten; preserve the source and review its identity")
    connection = memory or MemoryClient(config, timeout=120)
    inserted = duplicates = 0
    suppressed = False
    digest = hashlib.sha256()
    original_offset = offset
    prefix_checked = not previous
    try:
        if base_transcript.temporary and first_event:
            # Establish the durable exclusion even if no records are pending.
            receipt = connection.ingest(target, base_transcript, [first_event])
            suppressed = bool(receipt.get("suppressed"))
        for base, ordinal, data in chunks(source, length):
            part = parse_jsonl(data, client=base_transcript.client, machine=config.machine_id,
                               path=str(source), session_id=identity, cwd=base_transcript.cwd,
                               final=final, start_line=ordinal, adapter_version=adapter_version, settled=tail_settled(stat))
            hashed = 0
            for e in part.events:
                e["_end_offset"] += base
            pending = [e for e in part.events if e["_end_offset"] > offset]
            if not prefix_checked and base <= original_offset <= base + len(data):
                check = digest.copy(); check.update(data[:original_offset - base])
                if check.hexdigest() != previous["prefix_sha"]:
                    raise ClientError("Transcript was rewritten during preflight; preserve source for review")
                prefix_checked = True
            for batch in _batches(pending):
                receipt = {"inserted": 0, "duplicates": 0} if suppressed else connection.ingest(target, base_transcript, batch)
                suppressed |= bool(receipt.get("suppressed") or receipt.get("excluded"))
                inserted += int(receipt.get("inserted", 0)); duplicates += int(receipt.get("duplicates", 0))
                end = batch[-1]["_end_offset"] - base
                digest.update(data[hashed:end]); hashed = end; offset = base + end
                state.save_checkpoint_hash(key, digest.hexdigest(), offset, base_transcript.session_id, target, stat,
                                           adapter_version=adapter_version)
            digest.update(data[hashed:part.complete_bytes])
        state.save_checkpoint_hash(key, digest.hexdigest(), complete_bytes, base_transcript.session_id, target, stat,
                                   adapter_version=adapter_version)
        from .codex_titles import index_title
        index_title(config, source, base_transcript, connection, project=target)
    finally:
        if memory is None:
            connection.close()
    return {"path": str(source), "project": target, "session_id": base_transcript.session_id,
            "inserted": inserted, "duplicates": duplicates, "pending_bytes": pending_bytes,
            "unknown_types": sorted(unknown), "source_records": record_count}
