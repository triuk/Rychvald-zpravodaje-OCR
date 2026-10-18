#!/usr/bin/env python3
"""Native GUI first reading with explicit preflight and publication controls.

The source generator's independent oracle remains in its own host process.
This harness never reads expected text and never authors a confirmed review.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.application import WebUIApplication


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disclosure', type=Path, required=True)
    parser.add_argument('--disclosure-sha256', required=True)
    parser.add_argument('--case', choices=['synthetic', 'difficult'], required=True)
    parser.add_argument('--ocr-python', required=True)
    parser.add_argument('--environment')
    parser.add_argument('--browser', default='Chromium')
    parser.add_argument('--browser-parameters', default='--ozone-platform=x11')
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--prepare-local', action='store_true')
    parser.add_argument('--inspect-preparation', action='store_true', help='Read-only GUI check of the saved native preparation.')
    parser.add_argument('--retry-terminal-preflight', type=Path, help='Explicit supported terminal-state reconciliation proof for retrying a failed image preflight.')
    parser.add_argument('--run-preflights', action='store_true', help='Authorize actual image/context subscription turns for this exact run.')
    parser.add_argument('--run-reading', action='store_true', help='Authorize two actual source/accounting subscription turns for this exact run.')
    args = parser.parse_args()
    if sha(args.disclosure) != args.disclosure_sha256:
        parser.error('The concrete reviewed source disclosure changed.')
    disclosure = json.loads(args.disclosure.read_text())
    case = next(c for c in disclosure['cases'] if c['kind'] == args.case)
    if sha(Path(case['source'])) != case['source_sha256']:
        parser.error('The disclosed source changed.')
    proof = args.proof.resolve()
    proof.mkdir(parents=True, exist_ok=True)
    app = WebUIApplication(disclosure['registry'], browser=args.browser, browser_parameters=args.browser_parameters,
        process_command=[args.ocr_python, '-B', str(ROOT / 'tools/ocr_projects.py')])
    from webui import webui
    failures = []

    def query(script):
        response = app.window.script(script, timeout=3)
        if response.error or not response.data or response.data.strip() in ('null', 'undefined'):
            return None
        return json.loads(response.data)

    def wait(script, predicate, timeout=720):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if app.window is not None and app.window.is_shown():
                last = query(script)
                if predicate(last):
                    return last
            time.sleep(.15)
        raise RuntimeError('Native GUI timed out; last observation: ' + repr(last))

    def click(identifier):
        wait('const b=document.querySelector(' + json.dumps('#' + identifier) + ');'
            'if(document.querySelector("#detail")?.dataset.runId===' + json.dumps(case['run_id']) +
            '&&b&&!b.disabled&&(!b.dataset.runId||b.dataset.runId===' + json.dumps(case['run_id']) +
            ')){b.click();return JSON.stringify(true)}return JSON.stringify(false);', bool)

    def status(operation):
        value = app.api.dispatch(operation, {'run_id': case['run_id']})
        if not value['ok']:
            raise RuntimeError(str(value['error']))
        return value['data']

    def terminal(operation, previous_attempt=None):
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            value = status(operation)
            if previous_attempt is not None and value.get('attempt_id') == previous_attempt:
                time.sleep(.1)
                continue
            if value['state'] not in ('starting', 'running', 'awaiting_login', 'not_started'):
                return value
            time.sleep(.5)
        raise RuntimeError('Actual native operation did not reach a terminal state: ' + operation)

    def require_complete(value, flag=None):
        if value['state'] != 'completed' or flag and not value.get(flag):
            raise RuntimeError('Actual native operation failed: ' + json.dumps(value.get('error') or {'state': value['state']}))

    def inspect():
        try:
            selector = '.run[data-run-id=' + json.dumps(case['run_id']) + ']'
            wait('return JSON.stringify(Boolean(document.querySelector(' + json.dumps(selector) + ')));', bool)
            query('document.querySelector(' + json.dumps(selector) + ').click();return JSON.stringify(true);')
            wait('return JSON.stringify(document.querySelector("#detail")?.dataset.runId===' + json.dumps(case['run_id']) +
                '&&Boolean(document.querySelector("#reading-panel")));', bool)
            if args.prepare_local:
                prior_preparation = status('preparation_status')
                if args.environment:
                    query('document.querySelector("#preparation-environment").value=' + json.dumps(args.environment) + ';return JSON.stringify(true);')
                click('start-preparation')
                prepared = terminal('preparation_status', prior_preparation.get('attempt_id'))
                save(proof / 'native-preparation.json', prepared)
                require_complete(prepared, 'checkpoint_valid')
            work = Path(case['work'])
            packet_path = work / 'input-manifest.json'
            if not packet_path.is_file():
                raise RuntimeError('Run native preparation before actual AI preflights.')
            manifest = json.loads(packet_path.read_text())
            prepared_packet = {'case': case, 'source_disclosure_sha256': args.disclosure_sha256,
                'source_manifest_sha256': sha(packet_path), 'pages': manifest['pages'],
                'runtime': app.api.reading.runtime, 'context_runtime': app.api.reading.context_runtime,
                'model_destination': disclosure['model_destination']}
            save(proof / 'prepared-ai-disclosure.json', prepared_packet)
            if args.run_preflights:
                model = status('model_diagnostic_status')
                context = status('context_status')
                if model['state'] in ('failed', 'interrupted') and args.retry_terminal_preflight:
                    reconciliation = json.loads(args.retry_terminal_preflight.read_text())
                    if not (reconciliation['run_id'] == case['run_id'] and reconciliation['attempt_id'] == model['attempt_id'] and
                        reconciliation['thread_id'] == model['thread_id'] and reconciliation['turn_id'] == model['turn_id'] and
                        (reconciliation['terminal_status'] == 'failed' or reconciliation.get('no_original_turn_submitted')) and
                        reconciliation['no_inference_submitted']):
                        raise RuntimeError('Explicit preflight retry proof does not identify this original failed turn.')
                elif model['state'] != 'not_started':
                    raise RuntimeError('Existing image preflight requires explicit supported terminal-state reconciliation before retry.')
                if context['state'] != 'not_started':
                    raise RuntimeError('Existing preflight attempts require explicit terminal-state inspection; this harness never repeats them automatically.')
                image = work / 'raster/page-1.png'
                query('document.querySelector("#diagnostic-image").value=' + json.dumps(str(image)) + ';return JSON.stringify(true);')
                click('start-model-diagnostic')
                model = terminal('model_diagnostic_status', model.get('attempt_id'))
                save(proof / 'native-model-preflight.json', model)
                require_complete(model, 'combination_verified')
                click('start-context-diagnostic')
                context = terminal('context_status', context.get('attempt_id'))
                save(proof / 'native-context-preflight.json', context)
                require_complete(context, 'autonomous_ocr_ready')
            if args.run_reading:
                previous = status('reading_status')
                if previous['state'] != 'not_started':
                    raise RuntimeError('Existing reading attempt must be reconciled before any new inference; automatic resubmission is disabled.')
                click('start-reading')
                reading = terminal('reading_status', previous.get('attempt_id'))
                save(proof / 'native-reading.json', reading)
                require_complete(reading, 'reading_complete')
                if args.case == 'synthetic':
                    control = {'run_id': case['run_id'], 'attempt_id': reading['attempt_id'], 'reading_complete': True,
                        'review_sha256': reading['review_sha256'], 'proposal_path': reading['artifacts']['proposal'],
                        'proposal_sha256': reading['proposal_sha256'], 'source_disclosure_sha256': args.disclosure_sha256}
                    save(Path(disclosure['publication_control']), control)
            if args.inspect_preparation:
                require_complete(status('preparation_status'), 'checkpoint_valid')
            if args.run_reading or not args.prepare_local and not args.run_preflights and not args.inspect_preparation:
                reading = status('reading_status')
                save(proof / 'native-reading.json', reading)
                require_complete(reading, 'reading_complete')
                wait('return JSON.stringify(document.querySelector("#reading-state")?.dataset.state);', lambda value: value == 'completed')
                wait('return JSON.stringify(displayedReading===' + json.dumps(reading['attempt_id']) +
                    '&&!readingRequestPending&&!progressRequestPending&&document.querySelector("#reading-output")?.children.length>0);', bool)
                query('document.querySelector("#reading-panel").scrollIntoView({block:"start"});return JSON.stringify(true);')
                wait('const box=document.querySelector("#reading-panel")?.getBoundingClientRect();'
                    'return JSON.stringify(Boolean(box&&box.top>-8&&box.top<200));', bool)
                save(proof / 'native-metrics.json', app.api.dispatch('run_metrics', {'run_id': case['run_id']}))
            time.sleep(.5)
            screenshot = proof / 'native-gui.png'
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1920x1400',
                '-i', os.environ['DISPLAY'], '-frames:v', '1', '-update', '1', '-y', str(screenshot)], check=True)
            from PIL import Image, ImageStat
            with Image.open(screenshot) as image:
                mean = sum(ImageStat.Stat(image.convert('RGB')).mean) / (3 * 255)
            if mean <= .01:
                raise RuntimeError('Native GUI screenshot is black; no visual proof claimed.')
            save(proof / 'summary.json', {'case': args.case, 'run_id': case['run_id'], 'native_gui': True,
                'new_preflight_turns_requested': 3 if args.run_preflights else 0,
                'new_reading_turns_requested': 2 if args.run_reading else 0, 'screenshot_mean': mean,
                'source_disclosure_sha256': args.disclosure_sha256})
            print(json.dumps({'case': args.case, 'run_id': case['run_id'], 'native_gui': True, 'screenshot_mean': mean}), flush=True)
        except BaseException as error:
            failures.append(str(error))
            save(proof / 'failure.json', {'error': str(error)})
            print('NATIVE_FAILURE ' + str(error), flush=True)
        finally:
            webui.exit()

    thread = threading.Thread(target=inspect, daemon=True)
    thread.start()
    app.run()
    thread.join(timeout=5)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
