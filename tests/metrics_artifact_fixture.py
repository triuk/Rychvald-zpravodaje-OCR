"""Produce durable controlled process artifacts, including recovery-only epochs.

These are synthetic process-boundary observations, explicitly not AI evidence.
"""
import json
from pathlib import Path
import sys

root, rid, scenario_path = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3])
scenario = json.loads(scenario_path.read_text())
aid = scenario.get('attempt_id', 'archived-attempt')
directory = root / 'work' / rid / 'application' / scenario.get('namespace', 'codex-attempts') / aid
directory.mkdir(parents=True, exist_ok=True)
protocol = directory / 'protocol.jsonl'
protocol.write_text(''.join(json.dumps(row) + '\n' for row in scenario['rows']) + scenario.get('tail', ''))
attempt = dict(schema_version=1, operation='vision_diagnostic', attempt_id=aid, run_id=rid, root=str(root),
               state='completed', started_at='2026-10-16T10:00:00+00:00', ended_at='2026-10-16T10:00:20+00:00',
               submitted_at='2026-10-16T10:00:05+00:00', thread_id='archive-thread', turn_id='archive-turn',
               requested={'model': 'gpt-6.1-sol'}, effective={'model': 'gpt-6.1-sol'},
               prompt='Controlled artifact prompt', answer='Controlled artifact answer',
               runtime={'kind': 'controlled_process_fixture'},
               artifacts={'protocol': str(protocol.relative_to(root)), 'attempt': str((directory / 'attempt.json').relative_to(root))})
attempt.update(scenario.get('attempt', {}))
(directory / 'attempt.json').write_text(json.dumps(attempt) + '\n')
if scenario.get('preparation'):
    prep = scenario['preparation']
    local = root / 'work' / rid / 'application' / 'attempts'
    local.mkdir(parents=True, exist_ok=True)
    manifest = dict(attempt, attempt_id='local-attempt', operation='prepare', **prep.get('manifest', {}))
    (local / 'local-attempt.json').write_text(json.dumps(manifest) + '\n')
    history = root / 'work' / rid / 'application' / 'history.jsonl'
    with history.open('a') as stream:
        for event in prep['events']:
            stream.write(json.dumps(dict(event, attempt_id='local-attempt', run_id=rid)) + '\n')
