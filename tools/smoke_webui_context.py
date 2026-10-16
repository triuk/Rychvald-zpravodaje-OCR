#!/usr/bin/env python3
"""Actual native GUI context proof, with explicit opt-in for new model turns."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.application import WebUIApplication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--run-id', action='append', required=True)
    parser.add_argument('--ocr-python', required=True)
    parser.add_argument('--context-runtime', required=True)
    parser.add_argument('--evidence-directory', required=True)
    parser.add_argument('--browser', default='Chromium')
    parser.add_argument('--browser-parameters')
    parser.add_argument('--run-diagnostics', action='store_true', help='Run missing diagnostics; completed attempts are only reloaded.')
    args = parser.parse_args()
    os.environ['RYCHVALD_CONTEXT_RUNTIME'] = str(Path(args.context_runtime).resolve())
    proof = Path(args.evidence_directory).resolve()
    proof.mkdir(parents=True, exist_ok=True)
    app = WebUIApplication(args.root, browser=args.browser, browser_parameters=args.browser_parameters,
                           process_command=[args.ocr_python, str(ROOT / 'tools/ocr_projects.py')])
    from webui import webui
    failures = []
    observations = []

    def query(script):
        result = app.window.script(script, timeout=3)
        if result.error or not result.data or result.data.strip() in ('undefined', 'null'):
            return None
        return json.loads(result.data)

    def wait(script, check):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if app.window is not None and app.window.is_shown():
                value = query(script)
                if check(value):
                    return value
            time.sleep(.2)
        raise RuntimeError('Native GUI did not reach the requested run/state.')

    def inspect():
        try:
            for index, identifier in enumerate(args.run_id):
                selector = '.run[data-run-id=' + json.dumps(identifier) + ']'
                wait('return JSON.stringify(Boolean(document.querySelector(' + json.dumps(selector) + ')));', bool)
                cleared = query('document.querySelector(' + json.dumps(selector) + ').click();'
                                'return JSON.stringify(!document.querySelector("#start-context-diagnostic"));')
                if cleared is not True:
                    raise RuntimeError('Old run actions remain available while another run is loading.')
                wait('return JSON.stringify(document.querySelector("#start-context-diagnostic")?.dataset.runId);',
                     lambda value: value == identifier)
                previous = app.api.dispatch('context_status', {'run_id': identifier})
                if not previous['ok']:
                    raise RuntimeError(str(previous['error']))
                value = previous['data']
                if value['state'] in ('starting', 'running'):
                    raise RuntimeError('Preserved attempt is nonterminal; do not resubmit an unknown task.')
                submitted = False
                if not value.get('context_verified'):
                    if not args.run_diagnostics:
                        raise RuntimeError('No completed context attempt; new model turns require --run-diagnostics.')
                    app.window.script('document.querySelector("#start-context-diagnostic").click();return true;', timeout=3)
                    wait('return JSON.stringify(document.querySelector("#context-state")?.dataset.attemptId||"");',
                         lambda current: bool(current) and current != value.get('attempt_id'))
                    submitted = True
                state = wait('return JSON.stringify(document.querySelector("#context-state")?.dataset.state);',
                             lambda current: current in ('completed', 'failed', 'interrupted', 'invalidated'))
                response = app.api.dispatch('context_status', {'run_id': identifier})
                (proof / f'run-{index + 1}.json').write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
                current = response.get('data') or {}
                summary = {'run_id': identifier, 'attempt_id': current.get('attempt_id'), 'thread_id': current.get('thread_id'),
                           'state': state, 'context_verified': current.get('context_verified'),
                           'submitted_new_diagnostic': submitted, 'error': current.get('error')}
                observations.append(summary)
                print(json.dumps(summary, ensure_ascii=False), flush=True)
                app.window.script('document.querySelector("#context-panel").scrollIntoView({block:"center"});return true;', timeout=3)
                time.sleep(1)
                screenshot = proof / f'run-{index + 1}.png'
                subprocess.run(['import', '-window', 'root', str(screenshot)], check=True)
                maximum = float(subprocess.run(['identify', '-format', '%[fx:maxima]', str(screenshot)], capture_output=True, text=True, check=True).stdout)
                if not response['ok'] or not current.get('native_runtime') or not current.get('context_verified') or state != 'completed' or maximum == 0:
                    raise RuntimeError('Native context proof failed; inspect the preserved public response/protocol.')
            if len(args.run_id) == 2:
                a, b = [json.loads((proof / f'run-{index}.json').read_text())['data'] for index in (1, 2)]
                checks = []
                for own, other in [(a, b), (b, a)]:
                    database_path = own['context_evidence']['content_database']
                    with sqlite3.connect('file:' + quote(database_path) + '?mode=ro', uri=True) as database:
                        own_count = database.execute('SELECT count(*) FROM chunks WHERE instr(content,?)>0', (own['oracle'],)).fetchone()[0]
                        foreign_count = database.execute('SELECT count(*) FROM chunks WHERE instr(content,?)>0', (other['oracle'],)).fetchone()[0]
                    with sqlite3.connect('file:' + quote(own['context_evidence']['session_database']) + '?mode=ro', uri=True) as database:
                        foreign_session = database.execute('SELECT count(*) FROM session_meta WHERE session_id=?', (other['thread_id'],)).fetchone()[0]
                    checks.append({'run_id': own['run_id'], 'own_record_present': own_count > 0,
                                   'foreign_record_count': foreign_count, 'foreign_thread_count': foreign_session})
                isolated = (a['context_paths']['workspace'] != b['context_paths']['workspace'] and
                            a['context_paths']['storage'] != b['context_paths']['storage'] and a['thread_id'] != b['thread_id'] and
                            all(row['own_record_present'] and row['foreign_record_count'] == 0 and row['foreign_thread_count'] == 0 for row in checks))
                (proof / 'isolation.json').write_text(json.dumps({'isolated': isolated, 'checks': checks}, indent=2))
                if not isolated:
                    raise RuntimeError('Run knowledge/session isolation failed.')
            (proof / 'summary.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding='utf-8')
        except BaseException as error:
            failures.append(str(error))
            print('NATIVE_FAILURE ' + str(error), flush=True)
        finally:
            webui.exit()

    worker = threading.Thread(target=inspect, daemon=True)
    worker.start()
    app.run()
    worker.join(timeout=5)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
