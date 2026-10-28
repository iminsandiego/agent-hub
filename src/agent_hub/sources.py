"""Transcript files on disk, plain or zstd-compressed.

Codex compresses finished rollouts in place (``rollout-*.jsonl.zst``) when it
moves a thread to paginated history. The decompressed bytes are the original
JSONL, so they are parsed, checkpointed and hashed exactly like a plain file;
the checkpoint's size and mtime are the compressed file's, which is what a scan
compares.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO, Iterator

TRANSCRIPT_PATTERNS = ("*.jsonl", "*.jsonl.zst")


def compressed(path: str | Path) -> bool:
    return str(path).endswith(".zst")


def transcript_files(root: Path) -> Iterator[Path]:
    """Transcripts under a directory, plain and compressed."""
    for pattern in TRANSCRIPT_PATTERNS:
        yield from root.rglob(pattern)


def open_transcript(path: Path) -> BinaryIO:
    """A binary stream of the transcript's JSONL bytes."""
    if not compressed(path):
        return path.open("rb")
    import zstandard
    reader = zstandard.ZstdDecompressor().stream_reader(path.open("rb"), read_across_frames=True, closefd=True)
    return io.BufferedReader(reader, buffer_size=1 << 20)


def read_transcript(path: Path) -> bytes:
    with open_transcript(path) as stream:
        return stream.read()


def size_hint(path: Path) -> int:
    """Roughly how many JSONL bytes the transcript holds, to choose in-memory or
    streamed capture. A compressed file's is its first frame's declared size (or
    its compressed size), so it never bounds a read: compressed files are read to
    the end."""
    size = path.stat().st_size
    if not compressed(path):
        return size
    import zstandard
    with path.open("rb") as stream:
        try:
            declared = zstandard.frame_content_size(stream.read(18))
        except zstandard.ZstdError:
            declared = -1  # not zstd: reading it reports the error
    return max(declared, size)
