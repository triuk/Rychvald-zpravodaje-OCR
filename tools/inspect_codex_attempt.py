#!/usr/bin/env python3
"""Read the exact saved diagnostic thread/turn before an explicit retry; no inference."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application
from app.codex import RpcProcess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--proof', type=Path, required=True)
    args = parser.parse_args()
    proof = args.proof.resolve()
    proof.mkdir(parents=True, exist_ok=True)
    app = Application(args.root)
    saved = app.dispatch('model_diagnostic_status', {'run_id': args.run_id})
    if not saved['ok']:
        raise RuntimeError(str(saved['error']))
    attempt = saved['data']
    if attempt.get('state') not in ('failed', 'interrupted', 'completed') or not attempt.get('turn_id'):
        raise RuntimeError('A concrete saved native turn with a terminal state is required.')
    for item in app.codex.runtime['files']:
        from app.jobs import sha
        if sha(Path(item['path'])) != item['sha256']:
            raise RuntimeError('Pinned inspection runtime changed.')

    def record(direction, message):
        from app.codex import scrub
        with (proof / 'protocol.jsonl').open('a') as stream:
            stream.write(json.dumps({'direction': direction, 'message': scrub(message)}) + '\n')

    def notify(message):
        if 'id' in message:
            raise RuntimeError('Read-only inspection does not execute tools or approvals.')

    with (proof / 'stderr.log').open('w') as stderr:
        rpc = RpcProcess(app.codex.runtime['command'], proof, stderr, record, lambda: False)
        try:
            rpc.request('initialize', {'clientInfo': {'name': 'rychvald-read-only-inspection', 'version': '1.0'},
                'capabilities': {'experimentalApi': True}}, notify)
            rpc.send({'method': 'initialized'})
            response = rpc.request('thread/read', {'threadId': attempt['thread_id'], 'includeTurns': True}, notify)
            turns = response['thread']['turns']
            turn = next(t for t in turns if t['id'] == attempt['turn_id'])
            if turn['status'] not in ('failed', 'interrupted', 'completed'):
                raise RuntimeError('The original submitted turn is still active; never resubmit it.')
            limits = rpc.request('account/rateLimits/read', {}, notify)
            summary = {'run_id': args.run_id, 'attempt_id': attempt['attempt_id'], 'thread_id': attempt['thread_id'],
                'turn_id': turn['id'], 'terminal_status': turn['status'], 'terminal_error': turn.get('error'),
                'no_inference_submitted': True, 'rate_limits': limits}
            (proof / 'thread-read.json').write_text(json.dumps(response, ensure_ascii=False, indent=2))
            (proof / 'reconciliation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
            print(json.dumps(summary, ensure_ascii=False))
        finally:
            rpc.close()
            app.close()


if __name__ == '__main__':
    main()
