#!/usr/bin/env python3
"""Inspect saved original AI measurements in the real WebUI; sends no model turn."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--attempt-id', required=True)
    parser.add_argument('--expected-input', type=int, required=True)
    parser.add_argument('--expected-cached', type=int, required=True)
    parser.add_argument('--expected-output', type=int, required=True)
    parser.add_argument('--expected-reference-usd', type=float, required=True)
    parser.add_argument('--ocr-python', required=True)
    parser.add_argument('--evidence-directory', required=True)
    args = parser.parse_args()
    proof = Path(args.evidence_directory).resolve()
    proof.mkdir(parents=True, exist_ok=True)
    app = WebUIApplication(args.root, browser='Chromium', browser_parameters='--ozone-platform=x11',
        process_command=[args.ocr_python, str(ROOT / 'tools/ocr_projects.py')])
    from webui import webui
    failures = []

    def snapshot_sources():
        directory = Path(args.root) / 'work' / args.run_id / 'application' / 'codex-attempts'
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in directory.glob('*/*') if path.is_file()}

    before = snapshot_sources()

    def query(script):
        result = app.window.script(script, timeout=3)
        if result.error or not result.data or result.data.strip() in ('null', 'undefined'):
            return None
        return json.loads(result.data)

    def wait(script, predicate, timeout=60):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if app.window is not None and app.window.is_shown():
                last = query(script)
                if predicate(last):
                    return last
            time.sleep(.15)
        raise RuntimeError('Saved-data native metrics UI did not become ready: ' + repr(last))

    def inspect():
        try:
            selector = '.run[data-run-id=' + json.dumps(args.run_id) + ']'
            wait('return JSON.stringify(Boolean(document.querySelector(' + json.dumps(selector) + ')));', bool)
            app.window.script('document.querySelector(' + json.dumps(selector) + ').click();return true;', timeout=3)
            wait('return JSON.stringify(document.querySelector("#metrics-content")?.dataset.sourceHash || "");', bool)
            row = '#metrics-panel tr[data-attempt-id=' + json.dumps(args.attempt_id) + ']'
            script = 'const r=document.querySelector(' + json.dumps(row) + ');return JSON.stringify(r ? {' \
                'tokens:[...r.querySelectorAll("[data-category]")].map(n=>({category:n.dataset.category,value:n.dataset.value})),' \
                'cost:r.querySelector("[data-usd]")?.dataset.usd,' \
                'runCost:document.querySelector("#metrics-run-cost")?.textContent,' \
                'legend:document.querySelector("#metrics-cost-legend")?.textContent}:null);'
            status = wait(script, bool)
            actual = {x['category']: int(x['value']) for x in status['tokens']}
            expected = {'noncached_input': args.expected_input, 'cached_input': args.expected_cached,
                        'output': args.expected_output}
            if actual != expected or abs(float(status['cost']) - args.expected_reference_usd) > 1e-9:
                raise RuntimeError('Native displayed measurements differ from original-event expectations: ' + repr(status))
            app.window.script('document.querySelector(' + json.dumps(row) + ').querySelector("button").click();return true;', timeout=3)
            wait('return JSON.stringify(Boolean(document.querySelector(' + json.dumps(row) + ').querySelector(".metric-step-detail pre")));', bool)
            facts = query('const d=JSON.parse(document.querySelector(' + json.dumps(row) + ').querySelector(".metric-step-detail pre").textContent);'
                          'return JSON.stringify({original:Boolean(d.usage_sources?.[0]?.original),prompt:Boolean(d.attempt?.prompt)});')
            if not facts or not facts['original'] or not facts['prompt']:
                raise RuntimeError('Native detail does not expose original usage and application prompt.')
            detail_response = app.api.dispatch('step_detail', {'run_id': args.run_id, 'step_id': 'ai:' + args.attempt_id})
            if not detail_response['ok']:
                raise RuntimeError(str(detail_response['error']))
            detail = detail_response['data']
            # Collapse the opened audit JSON to capture the useful measurements.
            app.window.script('document.querySelector(' + json.dumps(row) + ').querySelector("details").open=false;'
                'document.querySelector("#metrics-panel").scrollIntoView({block:"start"});return true;', timeout=3)
            time.sleep(.7)
            candidate = proof / 'capture-candidate.png'
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'x11grab',
                            '-video_size', '1920x1400', '-i', os.environ['DISPLAY'], '-frames:v', '1',
                            str(candidate)], check=True)
            mean = float(subprocess.run(['identify', '-format', '%[fx:mean]', str(candidate)],
                                           capture_output=True, text=True, check=True).stdout)
            if mean < .01:
                raise RuntimeError('Native screenshot is almost black (a cursor does not count); evidence rejected.')
            candidate.replace(proof / 'native-metrics.png')
            public = app.api.dispatch('run_metrics', {'run_id': args.run_id})
            (proof / 'public-metrics.json').write_text(json.dumps(public, ensure_ascii=False, indent=2))
            (proof / 'public-step-detail.json').write_text(json.dumps(detail, ensure_ascii=False, indent=2))
            after = snapshot_sources()
            if before != after:
                raise RuntimeError('Original AI artifacts changed during read-only metrics verification.')
            summary = {'native_gui': status, 'new_model_turns': 0, 'run_id': args.run_id,
                       'attempt_id': args.attempt_id, 'original_sources_unchanged': True,
                       'original_sha256': before, 'screenshot_mean': mean,
                       'price_card_sha256': public['data']['price_card_sha256']}
            (proof / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
            print(json.dumps(summary, ensure_ascii=False), flush=True)
        except BaseException as error:
            failures.append(str(error))
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
