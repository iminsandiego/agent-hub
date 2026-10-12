"""Explicitly queue local Codex/Claude history, plus attributed Codex titles.

Runs once as the provider's OS user. Existing watcher drains the durable queue.
No provider source files, credentials, checkpoints or timestamps are removed.
"""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from agent_hub.adapters import Transcript
from agent_hub.client import ClientConfig, LocalState, MemoryClient


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--root',action='append',required=True)
    parser.add_argument('--prioritize-session')
    args=parser.parse_args()
    config=ClientConfig.load(args.config);state=LocalState(config)
    files=[]
    for value in args.root:
        root=Path(value).expanduser().resolve()
        if root.is_dir():
            files.extend(p.resolve() for p in root.rglob('*.jsonl') if p.is_file() and p.resolve().is_relative_to(root))
    files=sorted(set(files),key=lambda p:(p.stat().st_mtime_ns,str(p)))
    for rank,path in enumerate(files):
        identifier=state.enqueue({'kind':'file','client':'auto','path':str(path)})
        # Negative times only set ordering; all jobs are immediately due.
        priority=-len(files)+rank
        if args.prioritize_session and args.prioritize_session in path.name:priority=-len(files)-1
        with state.connect() as con:con.execute('UPDATE jobs SET next_attempt=? WHERE id=?',(priority,identifier))
    print(json.dumps({'historical_files_queued':len(files),'source_bytes':sum(p.stat().st_size for p in files),
                      'pending_jobs':state.status()['pending_jobs']}))


if __name__=='__main__':main()
