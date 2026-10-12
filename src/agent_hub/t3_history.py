"""Read-only, restartable capture of T3's persisted orchestration event stream.

This adapter targets T3 0.0.45's v1 SQLite event schema. It never reads auth,
provider credentials, mutable provider runtime state, or writes T3's database.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .adapters import Transcript, content_text, stable_event_id
from .client import ClientConfig, ClientError, MemoryClient, atomic_write

_COLUMNS = ('sequence', 'event_id', 'aggregate_kind', 'stream_id', 'stream_version',
            'event_type', 'occurred_at', 'command_id', 'causation_event_id',
            'correlation_id', 'actor_kind', 'payload_json', 'metadata_json')


def event_from_row(row: dict[str, Any], machine: str) -> tuple[Transcript, dict[str, Any]]:
    payload = json.loads(row['payload_json'])
    if not isinstance(payload, dict):
        raise ClientError('T3 event payload must be an object; source retained for retry.')
    thread = payload.get('threadId') or row['stream_id']
    if thread != row['stream_id']:
        raise ClientError('T3 thread identity disagrees with its source stream.')
    kind = row['event_type']
    role = payload.get('role', 'system')
    if role not in {'user', 'assistant', 'developer', 'system', 'tool'}:
        role = 'system'
    if kind == 'thread.message-sent':
        text = payload.get('text', '')
        if not isinstance(text, str):
            raise ClientError('T3 message text has an unsupported shape.')
    elif kind == 'thread.activity-appended':
        activity = payload.get('activity', {})
        text = content_text(activity)
    else:
        text = kind + '\n' + content_text(payload)
    raw = json.dumps(row, ensure_ascii=False, separators=(',', ':'))
    event = {'event_id': stable_event_id('t3', machine, str(thread), row['event_id']),
             'role': role, 'text': text, 'raw': raw, 'timestamp': row['occurred_at']}
    transcript = Transcript(client='t3', session_id=str(thread), cwd=None,
                            metadata={'adapter_version': 1, 'format': 't3_orchestration_v1',
                                      'source_table': 'orchestration_events',
                                      't3_thread_id': str(thread), 'capture_surface': 't3'})
    return transcript, event


def sync_t3(config: ClientConfig, database: str | Path, checkpoint: str | Path,
            *, project: str | None = None, limit: int = 200,
            memory: MemoryClient | None = None) -> dict[str, int]:
    if not 1 <= limit <= 1000:
        raise ClientError('T3 capture limit must be 1–1000 events per pass.')
    source = Path(database).expanduser().resolve()
    state_path = Path(checkpoint).expanduser().resolve()
    # A default or explicit project makes routing deliberate even when the
    # native event lacks cwd. Strict deployments should use their own profile.
    target = config.resolve_project(explicit=project)
    identity = {'schema_version': 1, 'source': str(source), 'url': config.url,
                'machine': config.machine_id, 'project': target}
    state = {**identity, 'sequence': 0, 'event_id': None}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if any(state.get(k) != v for k, v in identity.items()):
            raise ClientError('T3 checkpoint belongs to another source or destination; use a separate checkpoint.')
    connection = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    owned = memory is None
    client = memory or MemoryClient(config)
    result = {'captured': 0, 'inserted': 0, 'duplicates': 0, 'sequence': state['sequence']}
    try:
        columns = {r['name'] for r in connection.execute('PRAGMA table_info(orchestration_events)')}
        if not set(_COLUMNS).issubset(columns):
            raise ClientError('Unsupported T3 event schema; capture retained for retry. No source changes made.')
        # Pin a read snapshot while checking the anchor and fetching a bounded
        # pass. Release before any network I/O so a slow service holds no reader.
        connection.execute('BEGIN')
        if state['sequence']:
            anchor = connection.execute('SELECT event_id FROM orchestration_events WHERE sequence=?', (state['sequence'],)).fetchone()
            if not anchor or anchor['event_id'] != state['event_id']:
                raise ClientError('T3 source was reset or replaced; preserve the checkpoint and review a new source identity.')
        rows = [dict(r) for r in connection.execute(
            'SELECT ' + ','.join(_COLUMNS) + ' FROM orchestration_events WHERE sequence>? ORDER BY sequence LIMIT ?',
            (state['sequence'], limit))]
        connection.rollback()
        for row in rows:
            if row['aggregate_kind'] == 'thread':
                transcript, event = event_from_row(row, config.machine_id)
                transcript.metadata['source_database'] = str(source)
                receipt = client.ingest(target, transcript, [event])
                result['captured'] += 1
                result['inserted'] += int(receipt.get('inserted', 0))
                result['duplicates'] += int(receipt.get('duplicates', 0))
            # Never advance before the service acknowledges a thread record.
            # Lost acknowledgement retries use the same immutable event ID.
            state.update(sequence=row['sequence'], event_id=row['event_id'])
            atomic_write(state_path, (json.dumps(state, indent=2) + '\n').encode('utf-8'))
            result['sequence'] = row['sequence']
        return result
    finally:
        connection.close()
        if owned:
            client.close()
