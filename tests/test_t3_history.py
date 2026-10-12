import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from agent_hub.client import ClientConfig, ClientError
from agent_hub.t3_history import _COLUMNS, sync_t3


class Recorder:
    def __init__(self):
        self.events = {}
        self.calls = []
        self.fail = False

    def ingest(self, project, transcript, events):
        self.calls.append((project, transcript, events))
        if self.fail:
            raise ConnectionError('Synthetic service outage')
        inserted = 0
        for event in events:
            if event['event_id'] not in self.events:
                self.events[event['event_id']] = event
                inserted += 1
            else:
                assert self.events[event['event_id']] == event
        return {'inserted': inserted, 'duplicates': len(events)-inserted}


@pytest.fixture
def source(tmp_path):
    p = tmp_path/'t3.sqlite'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE orchestration_events (' + ','.join(
            k + (' INTEGER PRIMARY KEY' if k == 'sequence' else ' INTEGER' if k == 'stream_version' else ' TEXT') for k in _COLUMNS) + ')')
        c.execute('CREATE TABLE auth_sessions (token TEXT)')
        c.execute("INSERT INTO auth_sessions VALUES ('SECRET_NOT_CONVERSATION')")
    return p


def append(source, sequence, *, text='Synthetic 🧪 history', kind='thread.message-sent', role='assistant', aggregate='thread', thread='thread-one', streaming=False):
    row = dict.fromkeys(_COLUMNS)
    row.update(sequence=sequence, event_id=f'event-{sequence}', aggregate_kind=aggregate,
               stream_id=thread, stream_version=sequence, event_type=kind,
               occurred_at='2026-10-12T00:00:00Z', actor_kind='provider',
               payload_json=json.dumps({'threadId':thread, 'messageId':'message-one',
                                        'role':role, 'text':text, 'streaming':streaming}, ensure_ascii=False),
               metadata_json='{"source":"synthetic"}')
    with sqlite3.connect(source) as c:
        c.execute('INSERT INTO orchestration_events VALUES ('+','.join('?' for _ in _COLUMNS)+')', list(row.values()))
    return row


def config(tmp_path, **kwargs):
    return ClientConfig(url='http://127.0.0.1:8765', machine_id='test-home', project='home', **kwargs)


def test_raw_unicode_provenance_idempotency_and_read_only(source, tmp_path):
    row = append(source, 1)
    before = hashlib.sha256(source.read_bytes()).digest()
    memory = Recorder(); checkpoint = tmp_path/'checkpoint.json'
    result = sync_t3(config(tmp_path), source, checkpoint, memory=memory)
    assert result['inserted'] == 1
    project, transcript, events = memory.calls[0]
    assert project == 'home' and transcript.client == 't3' and transcript.session_id == 'thread-one'
    assert transcript.metadata['capture_surface'] == 't3'
    event = events[0]
    assert event['role'] == 'assistant' and event['text'] == 'Synthetic 🧪 history'
    assert json.loads(event['raw']) == row
    assert 'SECRET_NOT_CONVERSATION' not in event['raw']
    assert sync_t3(config(tmp_path), source, checkpoint, memory=memory)['captured'] == 0
    assert hashlib.sha256(source.read_bytes()).digest() == before


def test_outage_does_not_advance_checkpoint_and_retry_has_no_gap(source, tmp_path):
    append(source, 1, aggregate='project');append(source, 2);append(source, 3)
    memory = Recorder();memory.fail = True; checkpoint = tmp_path/'checkpoint.json'
    with pytest.raises(ConnectionError):sync_t3(config(tmp_path), source, checkpoint, memory=memory)
    assert json.loads(checkpoint.read_text())['sequence'] == 1
    failed_id = memory.calls[-1][2][0]['event_id']
    memory.fail = False
    assert sync_t3(config(tmp_path), source, checkpoint, memory=memory)['inserted'] == 2
    assert failed_id in memory.events
    assert json.loads(checkpoint.read_text())['sequence'] == 3


def test_lost_checkpoint_write_replays_same_accepted_event(source, tmp_path, monkeypatch):
    import agent_hub.t3_history as adapter
    append(source, 1);memory=Recorder();checkpoint=tmp_path/'checkpoint.json'
    original=adapter.atomic_write
    def fail(*args, **kwargs): raise OSError('Synthetic disk failure')
    monkeypatch.setattr(adapter, 'atomic_write', fail)
    with pytest.raises(OSError):sync_t3(config(tmp_path), source, checkpoint, memory=memory)
    assert not checkpoint.exists() and len(memory.events)==1
    monkeypatch.setattr(adapter, 'atomic_write', original)
    result=sync_t3(config(tmp_path), source, checkpoint, memory=memory)
    assert result['duplicates']==1 and result['inserted']==0 and len(memory.events)==1


def test_message_revisions_and_provider_switch_keep_originals(source, tmp_path):
    original=append(source,1,text='Partial',streaming=True)
    append(source,2,text='Completed answer',streaming=False)
    append(source,3,kind='thread.session-set',text='Cursor provider')
    memory=Recorder(); checkpoint=tmp_path/'checkpoint.json'
    assert sync_t3(config(tmp_path),source,checkpoint,memory=memory)['captured']==3
    assert json.loads(next(iter(memory.events.values()))['raw'])==original
    assert {call[1].session_id for call in memory.calls} == {'thread-one'}
    assert len(memory.events)==3


def test_bounded_pass_resumes_in_sequence(source, tmp_path):
    for i in range(1,5):append(source,i)
    memory=Recorder();checkpoint=tmp_path/'checkpoint.json'
    assert sync_t3(config(tmp_path),source,checkpoint,memory=memory,limit=2)['sequence']==2
    assert sync_t3(config(tmp_path),source,checkpoint,memory=memory,limit=2)['sequence']==4
    assert len(memory.events)==4


def test_schema_drift_and_missing_database_do_not_create_or_checkpoint(tmp_path):
    memory=Recorder();checkpoint=tmp_path/'checkpoint.json';source=tmp_path/'missing.sqlite'
    with pytest.raises(sqlite3.OperationalError):sync_t3(config(tmp_path),source,checkpoint,memory=memory)
    assert not source.exists() and not checkpoint.exists()
    with sqlite3.connect(source) as c:c.execute('CREATE TABLE unrelated (value TEXT)')
    with pytest.raises(ClientError,match='schema'):sync_t3(config(tmp_path),source,checkpoint,memory=memory)
    assert not memory.calls and not checkpoint.exists()


def test_source_reset_and_destination_change_are_visible(source, tmp_path):
    append(source,1);memory=Recorder();checkpoint=tmp_path/'checkpoint.json'
    sync_t3(config(tmp_path),source,checkpoint,memory=memory)
    with sqlite3.connect(source) as c:c.execute("UPDATE orchestration_events SET event_id='replacement' WHERE sequence=1")
    with pytest.raises(ClientError,match='reset'):sync_t3(config(tmp_path),source,checkpoint,memory=memory)
    other=ClientConfig(url='http://localhost:8765',machine_id='test-home',project='home')
    with pytest.raises(ClientError,match='destination'):sync_t3(other,source,checkpoint,memory=memory)
    assert json.loads(checkpoint.read_text())['event_id']=='event-1'


def test_thread_identity_mismatch_cannot_be_silently_routed(source,tmp_path):
    append(source,1)
    with sqlite3.connect(source) as c:c.execute("UPDATE orchestration_events SET stream_id='different' WHERE sequence=1")
    with pytest.raises(ClientError,match='identity'):sync_t3(config(tmp_path),source,tmp_path/'checkpoint.json',memory=Recorder())
