"""Synthetic privacy checks across deletion, replay, aliases, queues and restores."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_hub.client import ClientConfig, LocalState, MemoryClient, drain_queue, ingest_file
from agent_hub.config import ServerSettings
from agent_hub.server import create_app
from agent_hub.store import Store
from agent_hub.session_links import related_sessions
from agent_hub.t3_history import _COLUMNS, sync_t3


def event(text='privacyCanary', role='user', identifier='one'):
    return dict(event_id=identifier, role=role, text=text, raw=json.dumps({'role':role,'text':text}))


@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'memory.sqlite3');s.create_project('home');s.create_project('work');return s


def capture(store, session='native', *, client='codex', events=None, project='home', **kw):
    return store.ingest(project,client,'machine',session,events or [event()],**kw)


@pytest.mark.parametrize('marker',['[temp]','[TEMP]','[temporary]'])
def test_temp_never_saves_question_answer_or_raw(store,marker):
    receipt=capture(store,events=[event(marker+' privacyCanary'),event('private reply','assistant','two')])
    assert receipt['suppressed']=='temporary' and receipt['inserted']==0
    assert store.stats('home')['events']==0 and store.list_sessions('home')==[]
    assert store.search('home','privacyCanary')==[]
    assert 'privacyCanary' not in store.context('home')['text']
    assert capture(store,events=[event('later answer','assistant','three')])['suppressed']=='temporary'


def test_only_direct_user_prefix_is_an_opt_out(store):
    for i,(role,text) in enumerate([('assistant','[temp] example'),('tool','[temp] output'),('user','Use [temp] next time'),('user','[template] name')]):
        assert capture(store,str(i),events=[event(text,role)])['inserted']==1


def test_forget_removes_every_live_surface_and_preserves_surviving_ids(store):
    first=capture(store)
    other=capture(store,'other',events=[event('keepCanary')])
    source=first['event_ids'][0]
    note=store.add_memory('home','privacyCanary note',source_event_ids=[source],idempotency_key='secret-key')
    store.review_memory('home',note['id'],'active')
    result=store.set_session_privacy('home',first['session_id'],'forgotten')
    assert result['removed_events']==1
    for call in [lambda:store.get_session('home',first['session_id']),lambda:store.get_event('home',source),lambda:store.get_memory('home',note['id'])]:
        with pytest.raises(KeyError):call()
    assert store.search('home','privacyCanary')==[]
    assert 'privacyCanary' not in store.context('home',100000)['text']
    assert store.stats('home')['events']==1
    assert store.get_event('home',other['event_ids'][0])['sequence']==1
    assert store.rebuild_tree('home')['events']==1
    assert capture(store,'after',events=[event('afterCanary')])['inserted']==1
    assert capture(store,events=[event('replayed changed content')])['suppressed']=='forgotten'
    assert store.set_session_privacy('home',first['session_id'],'temporary')['mode']=='forgotten'
    with store._read() as con:
        assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert con.execute('SELECT count(*) FROM memory_keys').fetchone()[0]==0


def test_late_provider_alias_and_codex_api_copy_cannot_restore(store):
    t3=capture(store,'t3-one',client='t3')
    native=capture(store,'native-one')
    store.set_session_privacy('home',t3['session_id'],'forgotten')
    aliases=[{'client':'t3','session_id':'t3-one'}, {'client':'codex','session_id':'native-one:app-server-v2'}]
    assert capture(store,'native-one',related_sessions=aliases)['suppressed']=='forgotten'
    with pytest.raises(KeyError):store.get_session('home',native['session_id'])
    assert capture(store,'native-one:app-server-v2')['suppressed']=='forgotten'
    # No text-based merging, nor exclusion of identical IDs in another project.
    assert capture(store,'unrelated')['inserted']==1
    assert capture(store,'native-one',project='work')['inserted']==1


def test_subagent_inherits_parent_exclusion_without_forgetting_parent_or_sibling(store):
    root=capture(store,'root')
    child=capture(store,'child',parent_sessions=[{'client':'codex','session_id':'root'}])
    capture(store,'sibling',parent_sessions=[{'client':'codex','session_id':'root'}])
    store.set_session_privacy('home',child['session_id'],'forgotten')
    assert capture(store,'root')['duplicates']==1
    assert capture(store,'sibling',parent_sessions=[{'client':'codex','session_id':'root'}])['duplicates']==1
    store.set_session_privacy('home',root['session_id'],'temporary')
    assert store.stats('home')['events']==0
    assert capture(store,'new-child',parent_sessions=[{'client':'codex','session_id':'root'}])['suppressed']=='temporary'
    assert capture(store,'child')['suppressed']=='forgotten'


def test_restart_restore_and_policy_commit_before_purge_failure(store,tmp_path,monkeypatch):
    receipt=capture(store)
    old=tmp_path/'old.sqlite3'; store.backup(old)
    original=store._purge
    monkeypatch.setattr(store,'_purge',lambda *args: (_ for _ in ()).throw(OSError('synthetic power failure')))
    with pytest.raises(OSError):store.set_session_privacy('home',receipt['session_id'],'forgotten')
    monkeypatch.setattr(store,'_purge',original)
    restarted=Store(store.path)
    assert restarted.stats('home')['events']==0
    restored=Store(old,privacy_path=store.privacy.path)
    assert restored.stats('home')['events']==0
    assert capture(restored)['suppressed']=='forgotten'
    assert 'privacyCanary' not in store.privacy.path.read_bytes().decode('utf-8',errors='ignore')


def test_inflight_summary_and_extraction_cannot_reintroduce_deleted_context(store):
    first=capture(store,events=[event('privacyCanary')])
    capture(store,'large',events=[event('surviving text '*100)])
    snapshot=store.events_after('home')[-1]
    task=next(t for t in store.summary_tasks('home') if t['event_id']==snapshot['id'])
    store.set_session_privacy('home',first['session_id'],'forgotten')
    with pytest.raises(ValueError,match='changed'):store.complete_summary('home',task['id'],'privacyCanary',task['source_hash'],'synthetic')
    with pytest.raises(ValueError,match='Privacy changed'):store.add_memory('home','privacyCanary',source_event_ids=[snapshot['id']],expected_privacy_revision=snapshot['privacy_revision'])


def test_concurrent_replay_and_forget_are_serialized(store):
    receipt=capture(store)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(capture,store) for _ in range(5)]
        futures.append(pool.submit(store.set_session_privacy,'home',receipt['session_id'],'forgotten'))
        [f.result() for f in futures]
    assert store.stats('home')['events']==0
    assert capture(store)['suppressed']=='forgotten'


def test_admin_only_and_cross_project_denial(tmp_path):
    app=create_app(ServerSettings(data_dir=tmp_path/'server'))
    app.state.store.create_project('home');app.state.store.create_project('work')
    _,admin=app.state.auth.issue('test-admin',['*'],['admin'])
    _,writer=app.state.auth.issue('test-uploader',['home'],['read','write'])
    result=capture(app.state.store)
    url='/v1/projects/home/sessions/'+result['session_id']+'/privacy'
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.post(url,headers={'Authorization':'Bearer '+writer},json={'mode':'forgotten'}).status_code==403
        assert client.post(url.replace('/home/','/work/'),headers={'Authorization':'Bearer '+admin},json={'mode':'forgotten'}).status_code==404
        assert client.post(url,headers={'Authorization':'Bearer '+admin},json={'mode':'forgotten'}).status_code==200


def test_native_queue_full_marker_detection_before_first_batch_and_reset(tmp_path):
    app=create_app(ServerSettings(data_dir=tmp_path/'server'));app.state.store.create_project('home')
    _,token=app.state.auth.issue('fixture',['home'],['read','write'])
    secret=tmp_path/'token';secret.write_text(token)
    cfg=ClientConfig(url='http://127.0.0.1:8765',machine_id='machine',project='home',token_file=str(secret),state_dir=str(tmp_path/'state'))
    path=tmp_path/'fixture.jsonl'
    rows=[{'sessionId':'queue-temp','type':'user','uuid':str(i),'message':{'role':'user','content':'metadata '+str(i)}} for i in range(501)]
    rows.append({'sessionId':'queue-temp','type':'user','uuid':'temp','message':{'role':'user','content':'[temp] privacyCanary'}})
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    with TestClient(app, base_url='http://127.0.0.1') as http:
        memory=MemoryClient(cfg);memory.request=lambda method,path,**kw:http.request(method,'/'+path.lstrip('/'),headers={'Authorization':'Bearer '+token},**kw).json()
        state=LocalState(cfg);state.enqueue({'kind':'file','path':str(path),'client':'claude'})
        assert drain_queue(cfg,state=state,memory=memory)['completed']==1
        assert state.status()['pending_jobs']==0 and app.state.store.stats('home')['events']==0
        # A lost local checkpoint or source append is still excluded server-side.
        with state.connect() as db:db.execute('DELETE FROM files')
        assert ingest_file(cfg,path,client='claude',state=state,memory=memory)['inserted']==0


def test_safe_t3_identity_lookup_and_source_reset_retains_exclusions(tmp_path):
    db=tmp_path/'t3.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE provider_session_runtime(thread_id TEXT,provider_name TEXT,resume_cursor_json TEXT,runtime_payload_json TEXT)')
        c.execute('INSERT INTO provider_session_runtime VALUES(?,?,?,?)',('t3-chat','codex',json.dumps({'threadId':'native-chat','token':'must not leave database'}),'SECRET'))
        c.execute('CREATE TABLE auth_sessions(token TEXT)');c.execute("INSERT INTO auth_sessions VALUES('SECRET')")
    before=db.read_bytes()
    expected=[{'client':'t3','session_id':'t3-chat'},{'client':'codex','session_id':'native-chat'},{'client':'codex','session_id':'native-chat:app-server-v2'}]
    assert related_sessions(str(db),'t3','t3-chat')==expected
    assert related_sessions(str(db),'codex','native-chat:app-server-v2')==expected
    assert db.read_bytes()==before
    assert 'SECRET' not in json.dumps(expected)


def test_t3_replay_and_native_copy_through_real_http_contract(tmp_path):
    app=create_app(ServerSettings(data_dir=tmp_path/'server'));app.state.store.create_project('home')
    _,token=app.state.auth.issue('synthetic-uploader',['home'],['read','write'])
    token_path=tmp_path/'token';token_path.write_text(token)
    db=tmp_path/'t3.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE orchestration_events ('+','.join(k+(' INTEGER PRIMARY KEY' if k=='sequence' else ' TEXT') for k in _COLUMNS)+')')
        c.execute('CREATE TABLE provider_session_runtime(thread_id TEXT,provider_name TEXT,resume_cursor_json TEXT)')
        c.execute('INSERT INTO provider_session_runtime VALUES(?,?,?)',('t3-temp','codex',json.dumps({'threadId':'native-temp'})))
        for sequence,role,text in [(1,'user','[temp] t3PrivacyCanary'),(2,'assistant','private answer')]:
            row=dict.fromkeys(_COLUMNS);row.update(sequence=sequence,event_id=str(sequence),aggregate_kind='thread',stream_id='t3-temp',stream_version=sequence,event_type='thread.message-sent',occurred_at='2026-10-12',actor_kind='provider',payload_json=json.dumps({'threadId':'t3-temp','role':role,'text':text}),metadata_json='{}')
            c.execute('INSERT INTO orchestration_events VALUES('+','.join('?' for _ in _COLUMNS)+')',list(row.values()))
    cfg=ClientConfig(url='http://127.0.0.1:8765',machine_id='machine',project='home',token_file=str(token_path),t3_database=str(db))
    checkpoint=tmp_path/'checkpoint'
    with TestClient(app,base_url='http://127.0.0.1') as http:
        memory=MemoryClient(cfg)
        def request(method,path,**kw):
            r=http.request(method,'/'+path.lstrip('/'),headers={'Authorization':'Bearer '+token},**kw);r.raise_for_status();return r.json()
        memory.request=request
        assert sync_t3(cfg,db,checkpoint,memory=memory)['sequence']==2
        assert app.state.store.stats('home')['events']==0
        checkpoint.unlink()
        assert sync_t3(cfg,db,checkpoint,memory=memory)['inserted']==0
        from agent_hub.adapters import Transcript
        native=Transcript(client='codex',session_id='native-temp',cwd=None)
        assert memory.ingest('home',native,[event('native reply')])['suppressed']=='temporary'
        assert app.state.store.search('home','t3PrivacyCanary')==[]


def test_current_ledger_required_for_cli_restore_after_forget(store,tmp_path,capsys):
    import argparse
    from agent_hub import admin
    receipt=capture(store);old=tmp_path/'snapshot.sqlite3';store.backup(old)
    store.set_session_privacy('home',receipt['session_id'],'forgotten')
    destination=tmp_path/'restored'
    args=argparse.Namespace(data_dir=destination,server_config=None,source=old,privacy_ledger=None)
    with pytest.raises(ValueError,match='CURRENT'):admin.restore(args)
    assert not destination.exists()
    args.privacy_ledger=store.privacy.path
    admin.restore(args)
    restored=Store(destination/'memory.sqlite3')
    assert restored.stats('home')['events']==0 and capture(restored)['suppressed']=='forgotten'


def test_legacy_offline_cache_is_scrubbed_on_upgrade(tmp_path):
    cfg=ClientConfig(url='http://127.0.0.1:8765',machine_id='machine',project='home',state_dir=str(tmp_path/'state'))
    state=LocalState(cfg)
    with state.connect() as db:db.execute('INSERT INTO cache VALUES(?,?,?)',('old','privacyCanary',100))
    assert state.cache_get('old')
    assert LocalState(cfg).cache_get('old') is None


def test_backup_cannot_overwrite_live_exclusion_ledger(store):
    receipt=capture(store);store.set_session_privacy('home',receipt['session_id'],'forgotten')
    before=store.privacy.path.read_bytes()
    with pytest.raises(ValueError,match='live'):store.backup(store.privacy.path)
    assert store.privacy.path.read_bytes()==before


def test_large_embedded_image_record_preserved_by_authenticated_ingest(tmp_path):
    app=create_app(ServerSettings(data_dir=tmp_path/'server',max_body_bytes=67_108_864));app.state.store.create_project('home')
    _,token=app.state.auth.issue('synthetic-large-record',['home'],['read','write'])
    raw=json.dumps({'image_data':'a'*2_100_000})
    payload={'project':'home','client':'codex','machine':'large-fixture','session_id':'image','events':[dict(event_id='image',role='assistant',text='Image attachment',raw=raw)]}
    with TestClient(app,base_url='http://127.0.0.1') as client:
        response=client.post('/v1/ingest',headers={'Authorization':'Bearer '+token},json=payload)
        assert response.status_code==200
        result=response.json()
        assert app.state.store.get_event('home',result['event_ids'][0])['raw']==raw


def test_upgrade_excludes_already_checkpointed_temporary_native_chat(tmp_path,monkeypatch):
    from agent_hub.adapters import parse_jsonl
    import agent_hub.store as module
    store=Store(tmp_path/'server');store.create_project('home')
    cfg=ClientConfig(url='http://127.0.0.1:8765',machine_id='machine',project='home',state_dir=str(tmp_path/'state'))
    path=tmp_path/'temp.jsonl';data=(json.dumps({'type':'session_meta','payload':{'id':'legacy-temp'}})+'\n'+json.dumps({'type':'event_msg','payload':{'type':'user_message','message':'[temp] oldPrivateCanary'}})+'\n').encode();path.write_bytes(data)
    transcript=parse_jsonl(data,machine='machine',path=str(path))
    detection=module.temporary_message;monkeypatch.setattr(module,'temporary_message',lambda events:False)
    legacy=store.ingest('home','codex','machine','legacy-temp',[{k:v for k,v in e.items() if not k.startswith('_')} for e in transcript.events])
    monkeypatch.setattr(module,'temporary_message',detection)
    state=LocalState(cfg)
    from agent_hub.client import file_key
    state.save_checkpoint(file_key(cfg,path,'auto'),data,len(data),'legacy-temp','home',path.stat())
    class Memory:
        def ingest(self,project,transcript,events):return store.ingest(project,'codex','machine',transcript.session_id,[{k:v for k,v in e.items() if not k.startswith('_')} for e in events],temporary=True)
    ingest_file(cfg,path,memory=Memory(),state=state)
    assert store.search('home','oldPrivateCanary')==[]
    with pytest.raises(KeyError):store.get_session('home',legacy['session_id'])
