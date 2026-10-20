#!/usr/bin/env python3
"""Native GUI proof over a disclosed existing export, never repeats source reading.

Default is read-only inspection. An explicit flag authorizes exactly one missing
post-export examination. Saved attempts cause a stop, not an automatic replay.
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
from app.output_review import OUTPUT_INSTRUCTIONS, OUTPUT_PROMPT, OUTPUT_SCHEMA


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disclosure', type=Path, required=True)
    parser.add_argument('--disclosure-sha256', required=True)
    parser.add_argument('--case', choices=['synthetic', 'difficult'], required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--ocr-python', required=True)
    parser.add_argument('--run-output-review', action='store_true')
    parser.add_argument('--inspect-completed', action='store_true')
    parser.add_argument('--webui-library', type=Path, required=True)
    parser.add_argument('--webui-library-sha256', required=True)
    args = parser.parse_args()
    # Guard before any backend import: WebUI's normal loader otherwise attempts
    # a download when its binary is absent. The selected package must be local.
    if not args.webui_library.is_file() or sha(args.webui_library) != args.webui_library_sha256:
        parser.error('Exact local WebUI library is required before backend import; no download.')
    if sha(args.disclosure) != args.disclosure_sha256:
        parser.error('Reviewed disclosure changed')
    disclosure = json.loads(args.disclosure.read_text())
    case = next(row for row in disclosure['cases'] if row['kind'] == args.case)
    if disclosure['agent_instructions'] != OUTPUT_INSTRUCTIONS:
        parser.error('Reviewed isolated instructions changed')
    if json.loads(Path(disclosure['schema']['path']).read_text()) != OUTPUT_SCHEMA:
        parser.error('Reviewed model schema changed')
    for path, digest in disclosure['implementation'].items():
        if sha(path) != digest:
            parser.error('Reviewed implementation changed: ' + path)
    if not args.inspect_completed:
        for key in ('output_manifest', 'preparation', 'prompt'):
            if sha(case[key]['path']) != case[key]['sha256']:
                parser.error('Disclosed current export/preparation/prompt changed')
        packet = json.loads(Path(case['preparation']['path']).read_text())
        packet['preparation_sha256'] = case['preparation']['sha256']
        if (OUTPUT_PROMPT + json.dumps(packet, ensure_ascii=False)) != Path(case['prompt']['path']).read_text():
            parser.error('Actual model prompt differs from concrete reviewed bytes')
        for image in case['images']:
            if sha(image['path']) != image['sha256']:
                parser.error('Disclosed image changed')
    proof = args.proof.resolve(); proof.mkdir(parents=True, exist_ok=True)
    app = WebUIApplication(disclosure['registry'], browser='Chromium', browser_parameters='--ozone-platform=x11',
        process_command=[args.ocr_python, '-B', str(ROOT / 'tools/ocr_projects.py')])
    from webui import webui
    from webui import load_library
    if Path(load_library._get_library_path()).resolve() != args.webui_library.resolve():
        parser.error('Imported backend uses another WebUI binary')
    failures = []

    def query(script):
        response = app.window.script(script, timeout=3)
        return None if response.error or not response.data or response.data.strip() in ('null', 'undefined') else json.loads(response.data)

    def wait(script, predicate=bool, timeout=120):
        deadline, last = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            if app.window is not None and app.window.is_shown():
                last = query(script)
                if predicate(last):
                    return last
            time.sleep(.2)
        raise RuntimeError('Native export GUI timeout: ' + repr(last))

    def status(operation):
        response = app.api.dispatch(operation, {'run_id': case['run_id']})
        if not response['ok']:
            raise RuntimeError(str(response['error']))
        return response['data']

    def inspect():
        try:
            selector = '.run[data-run-id=' + json.dumps(case['run_id']) + ']'
            wait('return JSON.stringify(Boolean(document.querySelector(' + json.dumps(selector) + ')));')
            query('document.querySelector(' + json.dumps(selector) + ').click();return JSON.stringify(true);')
            wait('return JSON.stringify(document.querySelector("#detail")?.dataset.runId===' + json.dumps(case['run_id']) +
                '&&Boolean(document.querySelector("#export-panel")));')
            previous = status('output_review_status')
            save(proof / 'before-operation.json', {'output_review': previous, 'autonomous': status('autonomous_status')})
            wait('return JSON.stringify(displayedReading!==null&&displayedGeometry!==null&&'
                '!readingRequestPending&&!geometryRequestPending&&!progressRequestPending);')
            if args.run_output_review:
                if previous['state'] != 'not_started':
                    raise RuntimeError('Saved output review requires explicit reconciliation; never duplicate an actual turn')
                wait('const b=document.querySelector("#resume-first-export");return JSON.stringify(Boolean(b&&b.dataset.manifestSha256===' +
                    json.dumps(case['output_manifest']['sha256']) + '&&b.dataset.preparationSha256===' +
                    json.dumps(case['preparation']['sha256']) + '));')
                query('document.querySelector("#resume-first-export").click();return JSON.stringify(true);')
                deadline = time.monotonic() + 1200
                while time.monotonic() < deadline:
                    value = status('autonomous_status')
                    save(proof / 'autonomous-current.json', value)
                    save(proof / 'output-review-current.json', status('output_review_status'))
                    if value['state'] not in ('not_started', 'starting', 'running'):
                        break
                    time.sleep(.8)
                else:
                    raise RuntimeError('Actual output examination did not finish')
                if value['state'] != 'completed':
                    raise RuntimeError('Actual output cycle failed: ' + str(value.get('error')))
            result = status('output_results')
            output = status('output_review_status')
            save(proof / 'output-results.json', result)
            save(proof / 'output-review.json', output)
            save(proof / 'native-metrics.json', app.api.dispatch('run_metrics', {'run_id': case['run_id']}))
            if (args.run_output_review or args.inspect_completed) and (not output.get('output_review_complete') or
                    result['report_provenance']['status'] != 'original_turn_verified'):
                raise RuntimeError('Original actual model report is not validly published')
            wait('const r=document.querySelector("#export-results");return JSON.stringify(Boolean(r&&r.querySelector("table")&&'
                'r.querySelector("button")&&r.textContent.includes(' + json.dumps(result['project']['validation']) + ')));')
            if args.run_output_review or args.inspect_completed:
                wait('return JSON.stringify(document.querySelector("#autonomous-state")?.dataset.state==="completed");')
            save(proof / 'native-dom.json', query('return JSON.stringify({run_id:selectedRun,'
                'state:document.querySelector("#autonomous-state")?.textContent,'
                'findings:[...document.querySelectorAll("#export-results table tr")].slice(1).map(e=>({'
                'id:e.children[0].textContent,status:e.children[1].textContent,'
                'reason_excerpt:e.children[2].textContent.slice(0,160),reason_characters:e.children[2].textContent.length})),'
                'external_buttons:[...document.querySelectorAll("#export-results button")].map(e=>e.textContent)});'))
            query('document.querySelector("#export-panel").scrollIntoView({block:"start"});return JSON.stringify(true);')
            wait('const p=document.querySelector("#export-panel")?.getBoundingClientRect();return JSON.stringify(Boolean(p&&p.top>-8&&p.top<200));')
            time.sleep(.5)
            query('document.querySelector("#export-panel").scrollIntoView({block:"start"});return JSON.stringify(true);')
            screenshot = proof / 'native-gui.png'
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1920x1400',
                '-i', os.environ['DISPLAY'], '-frames:v', '1', '-update', '1', '-y', str(screenshot)], check=True)
            for name, script in [('native-findings.png',
                    'document.querySelector("#export-results table").scrollIntoView({block:"start"});'),
                    ('native-open-items.png', 'document.querySelector("#export-results table tr:last-child").scrollIntoView({block:"end"});')]:
                query(script + 'return JSON.stringify(true);')
                time.sleep(.3)
                subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', '1920x1400',
                    '-i', os.environ['DISPLAY'], '-frames:v', '1', '-update', '1', '-y', str(proof / name)], check=True)
            from PIL import Image, ImageStat
            with Image.open(screenshot) as image:
                mean = sum(ImageStat.Stat(image.convert('RGB')).mean) / (3 * 255)
            if mean <= .01:
                raise RuntimeError('Black screenshot cannot prove native GUI')
            save(proof / 'summary.json', {'native_gui': True, 'run_id': case['run_id'], 'case': args.case,
                'attempt_id': output.get('attempt_id'), 'new_source_turns': 0, 'new_geometry_turns': 0,
                'new_postexport_requested': args.run_output_review, 'output_review_complete': output.get('output_review_complete', False),
                'validation': result['project']['validation'], 'acceptance': result['project']['acceptance'], 'screenshot_mean': mean})
            print(json.dumps({'case': args.case, 'native_gui': True, 'attempt_id': output.get('attempt_id'),
                'output_review_complete': output.get('output_review_complete', False)}), flush=True)
        except BaseException as error:
            failures.append(str(error)); save(proof / 'failure.json', {'error': str(error)})
            print('NATIVE_FAILURE ' + str(error), flush=True)
        finally:
            webui.exit()
    thread = threading.Thread(target=inspect, daemon=True); thread.start()
    app.run(); thread.join(timeout=5)
    if thread.is_alive():
        failures.append('Native GUI closed before its proof worker completed; partial files are not a successful GUI proof.')
        save(proof / 'failure.json', {'error': failures[-1]})
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
