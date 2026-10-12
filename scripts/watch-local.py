"""Capture changed local transcripts and drain Agent Hub's durable outbox.

First run records a baseline instead of importing old history. Resumed files and
new files are captured on later passes. Native hooks remain an independent queue
source. Run with the installed Agent Hub Python as the native client's OS user.
"""
import argparse
import json
import time
from pathlib import Path
from agent_hub.client import ClientConfig, LocalState, atomic_write, drain_queue


def scan(roots):
    result = {}
    for root in roots:
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            continue
        for candidate in root.rglob('*.jsonl'):
            try:
                resolved = candidate.resolve()
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    continue
                stat = resolved.stat()
                result[str(resolved)] = [stat.st_mtime_ns, stat.st_size]
            except OSError:
                continue
    return result


def run(config_path, roots, baseline_path, once=False):
    config = ClientConfig.load(config_path)
    state = LocalState(config)
    baseline_path = Path(baseline_path).expanduser()
    if baseline_path.exists():
        previous = json.loads(baseline_path.read_text(encoding='utf-8'))
    else:
        previous = scan(roots)
        atomic_write(baseline_path, json.dumps(previous).encode('utf-8'))
        print(json.dumps({'baseline_sources': len(previous), 'historical_import': False}), flush=True)
    while True:
        current = scan(roots)
        queued = 0
        for path, signature in current.items():
            if previous.get(path) != signature:
                state.enqueue({'kind': 'file', 'client': 'auto', 'path': path})
                queued += 1
        # Persist only after every change has entered the durable queue.
        previous.update(current)
        atomic_write(baseline_path, json.dumps(previous).encode('utf-8'))
        result = drain_queue(config, state=state)
        if queued or result['completed'] or result['failed'] or once:
            print(json.dumps({'queued_changes': queued, **{k:v for k,v in result.items() if k != 'results'}}), flush=True)
        if once:
            return
        time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--root', action='append', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    run(args.config, args.root, args.baseline, args.once)
