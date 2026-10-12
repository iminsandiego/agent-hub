"""Fail-closed domain routing and local backfill planning with synthetic data."""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from agent_hub.adapters import Transcript, parse_jsonl
from agent_hub.cli import main
from agent_hub.client import ClientConfig, ClientError, MemoryClient, ingest_file
from agent_hub.config import ServerSettings
from agent_hub.server import create_app
from agent_hub.store import Store


def config(tmp_path, **changes):
    values = dict(url='http://127.0.0.1:8765', machine_id='home-mac', domain='home',
                  allowed_projects=['home-garden','home-finance'], strict_scope=True,
                  mappings=[{'path':str(tmp_path/'garden'),'project':'home-garden'},
                            {'path':str(tmp_path/'finance'),'project':'home-finance'}],
                  state_dir=str(tmp_path/'state'))
    values.update(changes)
    return ClientConfig(**values)

@pytest.mark.parametrize('changes', [dict(domain='work'), dict(allowed_projects=[]),
    dict(project='home-garden'), dict(strict_scope='true'),
    dict(mappings=[{'path':'/work','project':'work-atlas'}])])
def test_invalid_strict_profile(changes, tmp_path):
    with pytest.raises(ClientError): config(tmp_path, **changes)

def test_explicit_project_cannot_bypass_allowlist(tmp_path):
    cfg = config(tmp_path)
    for project in ['work-atlas','home-unknown']:
        with pytest.raises(ClientError): cfg.resolve_project(str(tmp_path/'garden'), project)
    assert cfg.resolve_project(str(tmp_path/'garden'/'subdir')) == 'home-garden'

@pytest.mark.parametrize('client', ['codex','claude','jsonl'])
def test_cross_project_transcript_rejected_before_any_upload(tmp_path, client):
    cfg = config(tmp_path)
    first, other = str(tmp_path/'garden'), str(tmp_path/'finance')
    if client == 'codex':
        records = [{'type':'session_meta','payload':{'id':'native','cwd':first}},
                   {'type':'turn_context','payload':{'cwd':other}}]
    elif client == 'claude':
        records = [{'type':'user','sessionId':'native','cwd':first,'message':{'content':'hi'}},
                   {'type':'assistant','sessionId':'native','cwd':other,'message':{'content':'hi'}}]
    else:
        records = [{'role':'user','cwd':first,'text':'hi'}, {'role':'assistant','cwd':other,'text':'hi'}]
    path = tmp_path/'mixed.jsonl'; path.write_text(''.join(json.dumps(r)+'\n' for r in records))
    calls = []; memory = MemoryClient(cfg, transport=httpx.MockTransport(lambda r: calls.append(r)))
    try:
        with pytest.raises(ClientError, match='crosses project'):
            ingest_file(cfg,path,client=client,project='home-garden',memory=memory)
        assert not calls
    finally: memory.close()

def test_hook_cwd_and_missing_evidence_cannot_be_overridden(tmp_path):
    cfg = config(tmp_path)
    with pytest.raises(ClientError): cfg.check_transcript(Transcript('jsonl','s',None),'home-garden')
    with pytest.raises(ClientError):
        cfg.check_transcript(Transcript('codex','s',str(tmp_path/'garden')),'home-garden',str(tmp_path/'finance'))

def test_gateway_blocks_other_domain_before_token_or_network(tmp_path):
    cfg = config(tmp_path); calls = []
    memory = MemoryClient(cfg, transport=httpx.MockTransport(lambda r: calls.append(r)))
    try:
        with pytest.raises(ClientError): memory.context('work-atlas')
        assert not calls
    finally: memory.close()

def test_boundary_scan_preserves_original_records(tmp_path):
    raw = json.dumps({'type':'session_meta','payload':{'id':'one','cwd':str(tmp_path/'garden')}})
    transcript = parse_jsonl((raw+'\n').encode(),machine='test',path='one.jsonl')
    assert transcript.events[0]['raw'] == raw
    assert transcript.metadata['adapter_version'] == 1
    assert 'observed_cwds' not in transcript.metadata

def test_local_plan_has_no_queue_or_credentials(tmp_path):
    cfg = config(tmp_path); cp = tmp_path/'config.json'; cfg.save(cp)
    root = tmp_path/'sources'; root.mkdir()
    (root/'good.jsonl').write_text(json.dumps({'role':'user','cwd':str(tmp_path/'garden'),'text':'PRIVATE SENTINEL'})+'\n')
    (root/'unknown.jsonl').write_text(json.dumps({'role':'user','cwd':'/unmapped','text':'SECRET'})+'\n')
    report = tmp_path/'plan.json'
    args = ['--config',str(cp),'plan-import',str(root),'--client','jsonl','--output',str(report)]
    assert main(args) == 0
    result = json.loads(report.read_text())
    assert result['uploaded'] is False and result['queued'] is False
    assert result['counts'] == {'home-garden':1}
    assert sum(x['status']=='blocked' for x in result['sources']) == 1
    assert 'PRIVATE SENTINEL' not in report.read_text() and 'SECRET' not in report.read_text()
    assert not (tmp_path/'state').exists()
    assert main(args) == 1

def test_server_rejects_other_domain_even_for_admin(tmp_path):
    app = create_app(ServerSettings(data_dir=tmp_path/'server',domain='home'))
    _, token = app.state.auth.issue('admin',['*'],['admin'])
    headers = {'Authorization':'Bearer '+token}
    with TestClient(app,base_url='http://localhost') as client:
        assert client.post('/v1/projects',headers=headers,json={'project':'home-garden'}).status_code == 201
        assert client.post('/v1/projects',headers=headers,json={'project':'work-atlas'}).status_code == 403
        assert client.get('/v1/projects/work-atlas/context',headers=headers).status_code == 403
        assert client.post('/v1/ingest',headers=headers,json={'project':'work-atlas','client':'generic',
            'machine':'one','session_id':'one','events':[{'event_id':'one','role':'user','text':'secret','raw':'{}'}]}).status_code == 403
        response = client.post('/mcp',headers={**headers,'Accept':'application/json, text/event-stream'},
            json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'memory_context','arguments':{'project':'work-atlas'}}})
        assert response.json()['result']['isError'] is True
    assert len(app.state.store.list_projects()) == 1

def test_domain_server_refuses_existing_mixed_database(tmp_path):
    settings = ServerSettings(data_dir=tmp_path/'mixed',domain='home')
    Store(settings.database).create_project('work-atlas')
    with pytest.raises(ValueError,match='outside'): create_app(settings)

def test_domain_init_rejects_before_creating_storage(tmp_path):
    data = tmp_path/'server'
    assert main(['init-server','--data-dir',str(data),'--domain','home','--project','work-atlas']) == 1
    assert not data.exists()

def test_profile_configuration_roundtrip(tmp_path):
    cp = tmp_path/'home.json'
    assert main(['--config',str(cp),'configure','--url','https://home.example.com',
        '--machine-id','mac-home','--domain','home','--strict-scope','--allow-project','home-garden',
        '--map',str(tmp_path/'garden')+'=home-garden','--no-prompt']) == 0
    cfg = ClientConfig.load(cp)
    assert cfg.domain == 'home' and cfg.strict_scope and cfg.allowed_projects == ['home-garden']
