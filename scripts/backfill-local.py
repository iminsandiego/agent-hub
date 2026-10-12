"""Explicitly queue local Codex/Claude history, plus attributed Codex titles.

Runs once as the provider's OS user. Existing watcher drains the durable queue.
No provider source files, credentials, checkpoints or timestamps are removed.
"""
import argparse
import json
from pathlib import Path

from agent_hub.client import ClientConfig, LocalState


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
        # All are due, but ordinary live-capture jobs (0) run before backfill.
        priority=rank+1
        if args.prioritize_session and args.prioritize_session in path.name:priority=-1
        with state.connect() as con:con.execute('UPDATE jobs SET next_attempt=? WHERE id=?',(priority,identifier))
    print(json.dumps({'historical_files_queued':len(files),'source_bytes':sum(p.stat().st_size for p in files),
                      'pending_jobs':state.status()['pending_jobs']}))


if __name__=='__main__':main()
