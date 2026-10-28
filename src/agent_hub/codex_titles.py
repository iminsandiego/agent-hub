"""Attributed name discovery after native capture, with the same privacy group."""
import hashlib
import json
import sqlite3
from pathlib import Path


def index_title(config, source: Path, transcript, memory, *, project=None):
    if not config.codex_database or transcript.client != 'codex':return
    database=Path(config.codex_database).expanduser().resolve()
    con=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
    try:
        # Codex keeps a compressed rollout's original .jsonl path.
        named=str(source).removesuffix('.zst')
        row=con.execute('SELECT id,name,title FROM threads WHERE id=? AND rollout_path IN (?,?)',
                        (transcript.session_id,str(source),named)).fetchone()
    finally:con.close()
    if not row or not (row[1] or row[2]):return
    native,name,title=row
    record={'id':native,'name':name,'title':title,'source':'Codex local threads table'}
    raw=json.dumps(record,ensure_ascii=False,sort_keys=True)
    target=config.resolve_project(transcript.cwd, explicit=project)
    from .store import _hash
    archive_id='s_'+_hash([target,'codex',config.machine_id,native])
    memory.request('POST','v1/ingest',json={'project':target,'client':'generic','machine':config.machine_id,
        'session_id':'codex-title-v1:'+native,
        'metadata':{'format':'codex_sqlite_title_v1','source_database':str(database),'source_table':'threads'},
        'related_sessions':[{'client':'codex','session_id':native},{'client':'codex','session_id':native+':app-server-v2'}],
        'events':[{'event_id':'title-v1:'+hashlib.sha256(raw.encode()).hexdigest(),'role':'system',
                   'text':'Codex chat title: '+(name or title)+'\nNative session: '+native+'\nAgent Hub original session: '+archive_id,'raw':raw}]})
