import hashlib
import json
from pathlib import Path

import pytest

from agent_hub.adapters import parse_jsonl
from agent_hub.client import ClientConfig, LocalState, file_key
from agent_hub.streaming import ingest_large_file, chunks
from agent_hub.store import Store


class Archive:
    def __init__(self, store):self.store=store
    def ingest(self, project, transcript, events):
        return self.store.ingest(project,transcript.client,'machine',transcript.session_id,
            [{k:v for k,v in e.items() if not k.startswith('_')} for e in events],
            {k:v for k,v in transcript.metadata.items() if k not in {'unknown_types','pending_turns'}},temporary=transcript.temporary)


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    import agent_hub.streaming as module
    original=module.chunks
    monkeypatch.setattr(module,'chunks',lambda p,s:original(p,s,budget=500))
    path=tmp_path/'native.jsonl'
    rows=[{'type':'session_meta','payload':{'id':'native','cwd':str(tmp_path)}}]
    rows += [{'type':'event_msg','payload':{'type':'user_message','message':'sample '+str(i)}} for i in range(25)]
    data=('\n'+''.join(json.dumps(row)+'\n\n' for row in rows)).encode();path.write_bytes(data)
    cfg=ClientConfig(url='http://127.0.0.1:8765',machine_id='machine',project='home',state_dir=str(tmp_path/'state'))
    store=Store(tmp_path/'db');store.create_project('home')
    return path,data,cfg,store,Archive(store)


def test_streaming_preserves_raw_ids_ordinals_blank_lines_and_checkpoint(fixture):
    path,data,cfg,store,memory=fixture
    result=ingest_large_file(cfg,path,memory=memory)
    expected=parse_jsonl(data,machine='machine',path=str(path))
    sid=store.list_sessions('home')[0]['id'];actual=store.get_session('home',sid)['events']
    assert [(e['external_event_id'],e['raw']) for e in actual]==[(e['event_id'],e['raw']) for e in expected.events]
    cp=LocalState(cfg).checkpoint(file_key(cfg,path,'auto'))
    assert cp['offset']==len(data) and cp['prefix_sha']==hashlib.sha256(data).hexdigest()
    assert ingest_large_file(cfg,path,memory=memory)['inserted']==0
    path.write_bytes(data+json.dumps({'type':'event_msg','payload':{'type':'user_message','message':'append'}}).encode()+b'\n')
    assert ingest_large_file(cfg,path,memory=memory)['inserted']==1


def test_compressed_rollouts_stream_to_their_end_like_plain_ones(fixture):
    import zstandard
    path,data,cfg,store,memory=fixture
    packed=path.with_name('rollout.jsonl.zst')
    # Several frames: the first frame's declared size is far short of the file.
    packed.write_bytes(b''.join(zstandard.ZstdCompressor().compress(data[i:i+300]) for i in range(0,len(data),300)))
    # Codex compresses a rollout after it was captured: the new path adds nothing.
    ingest_large_file(cfg,path,memory=memory)
    result=ingest_large_file(cfg,packed,memory=memory)
    expected=parse_jsonl(data,machine='machine',path=str(packed))
    assert result['source_records']==len(expected.events)==store.stats('home')['events']==result['duplicates']
    assert result['inserted']==0
    cp=LocalState(cfg).checkpoint(file_key(cfg,packed,'auto'))
    assert cp['offset']==len(data) and cp['prefix_sha']==hashlib.sha256(data).hexdigest() and cp['size']==packed.stat().st_size
    assert ingest_large_file(cfg,packed,memory=memory)['inserted']==0


def test_late_temporary_marker_and_malformed_tail_never_partially_upload(fixture):
    path,data,cfg,store,memory=fixture
    path.write_bytes(data+json.dumps({'type':'event_msg','payload':{'type':'user_message','message':'[temp] private'}}).encode()+b'\n')
    assert ingest_large_file(cfg,path,memory=memory)['inserted']==0 and store.stats('home')['events']==0
    malformed=path.with_name('malformed.jsonl');malformed.write_bytes(data+b'not json\n')
    with pytest.raises(ValueError,match='Malformed'):ingest_large_file(cfg,malformed,memory=memory)
    assert store.stats('home')['events']==0


def test_streaming_outage_restart_and_rewrite_protection(fixture):
    path,data,cfg,store,memory=fixture
    original=memory.ingest;count=0
    def fail(project,transcript,events):
        nonlocal count
        count+=1
        if count==3:raise ConnectionError('outage')
        return original(project,transcript,events)
    memory.ingest=fail
    with pytest.raises(ConnectionError):ingest_large_file(cfg,path,memory=memory)
    cp=LocalState(cfg).checkpoint(file_key(cfg,path,'auto'));assert 0<cp['offset']<len(data)
    memory.ingest=original
    ingest_large_file(cfg,path,memory=memory)
    assert store.stats('home')['events']==len(parse_jsonl(data,machine='machine',path=str(path)).events)
    path.write_bytes(data.replace(b'sample 0',b'SAMPLE 0'))
    with pytest.raises(ValueError,match='rewritten'):ingest_large_file(cfg,path,memory=memory)


def test_native_codex_parent_identity_is_not_added_to_immutable_metadata(tmp_path):
    d=json.dumps({'type':'session_meta','payload':{'id':'child','parent_thread_id':'parent','cwd':str(tmp_path)}}).encode()+b'\n'
    parsed=parse_jsonl(d,machine='machine',path='child.jsonl')
    assert parsed.parent_session_id=='parent'
    assert 'parent_session_id' not in parsed.metadata


def test_title_index_is_attributed_and_forgetting_removes_linked_label(tmp_path,monkeypatch):
    import sqlite3
    from agent_hub.codex_titles import index_title
    from agent_hub.adapters import Transcript
    source=tmp_path/'named-chat.jsonl';source.write_text('{}\n')
    db=tmp_path/'codex.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE threads(id TEXT,name TEXT,title TEXT,rollout_path TEXT)')
        c.execute('INSERT INTO threads VALUES(?,?,?,?)',('native-id','Named chat','first question',str(source)))
    config=ClientConfig(url='http://127.0.0.1:8765',machine_id='machine',project='home',codex_database=str(db))
    store=Store(tmp_path/'server');store.create_project('home')
    class Memory:
        def request(self,method,path,**kwargs):return store.ingest(**kwargs['json'])
    native=store.ingest('home','codex','machine','native-id',[{'event_id':'native','role':'user','text':'native content','raw':'{}'}])
    transcript=Transcript(client='codex',session_id='native-id',cwd=str(tmp_path))
    index_title(config,source,transcript,Memory())
    hits=store.search('home','Named chat');assert len(hits)==1
    store.set_session_privacy('home',native['session_id'],'forgotten')
    assert store.search('home','Named chat')==[]
    index_title(config,source,transcript,Memory());assert store.search('home','Named chat')==[]
    store.create_project('work')
    index_title(config,source,transcript,Memory(),project='work')
    assert store.search('work','Named chat') and store.search('home','Named chat')==[]
    # Codex keeps a compressed rollout under its original .jsonl path.
    store.create_project('compressed')
    index_title(config,source.with_name(source.name+'.zst'),transcript,Memory(),project='compressed')
    assert store.search('compressed','Named chat')
