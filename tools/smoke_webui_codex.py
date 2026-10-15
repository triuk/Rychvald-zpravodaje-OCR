#!/usr/bin/env python3
"""Actual native WebUI image diagnostic or saved-result reload verification.

The trusted harness reads its independent oracle; the application/model sees
only the image and fixed diagnostic prompt. No fixture replaces Codex here.
"""
import argparse
import json
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
    parser.add_argument('--image', help='Prepared PNG/JPEG; needed for a new diagnostic.')
    parser.add_argument('--expectation', required=True, help='Independent JSON object with literal expected text.')
    parser.add_argument('--ocr-python', required=True)
    parser.add_argument('--browser', default='Chromium')
    parser.add_argument('--browser-parameters')
    parser.add_argument('--evidence-directory', required=True)
    parser.add_argument('--run-diagnostic', action='store_true', help='Authorize one new subscription image turn.')
    args = parser.parse_args()
    if args.run_diagnostic and not args.image:
        parser.error('--run-diagnostic requires --image')
    expected = json.loads(Path(args.expectation).read_text(encoding='utf-8'))['expected']
    if not isinstance(expected, str) or not expected.strip():
        parser.error('The independent expected text must be nonempty.')
    proof = Path(args.evidence_directory).resolve()
    proof.mkdir(parents=True, exist_ok=True)
    app = WebUIApplication(args.root, browser=args.browser, browser_parameters=args.browser_parameters,
                           process_command=[args.ocr_python, str(ROOT / 'tools/ocr_projects.py')])
    from webui import webui
    failures = []

    def query(script):
        result = app.window.script(script, timeout=3)
        if result.error or not result.data or result.data.strip() in ('null', 'undefined'):
            return None
        return json.loads(result.data)

    def wait(script, predicate, timeout=240):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if app.window is not None and app.window.is_shown():
                last = query(script)
                if predicate(last):
                    return last
            time.sleep(.15)
        raise RuntimeError('Native WebUI did not become ready: ' + repr(last))

    def inspect():
        try:
            selector = '.run[data-run-id=' + json.dumps(args.run_id) + ']'
            wait('return JSON.stringify(Boolean(document.querySelector(' + json.dumps(selector) + ')));', bool)
            app.window.script('document.querySelector(' + json.dumps(selector) + ').click();return true;', timeout=3)
            wait('return JSON.stringify(Boolean(document.querySelector("#codex-diagnostic-form")));', bool)
            previous = app.api.dispatch('model_diagnostic_status', {'run_id': args.run_id})
            if not previous['ok']:
                raise RuntimeError(str(previous['error']))
            old_id = previous['data'].get('attempt_id')
            if args.run_diagnostic:
                app.window.script('document.querySelector("#diagnostic-image").value=' + json.dumps(str(Path(args.image).resolve())) + ';'
                                  'document.querySelector("#codex-diagnostic-form").requestSubmit();return true;', timeout=3)
                wait('return JSON.stringify(document.querySelector("#codex-state")?.dataset.attemptId || "");',
                     lambda value: bool(value) and value != old_id)
            status = wait('return JSON.stringify({state:document.querySelector("#codex-state")?.dataset.state,'
                          'attempt:document.querySelector("#codex-state")?.dataset.attemptId,'
                          'answer:document.querySelector("#codex-answer")?.textContent});',
                          lambda value: value and value.get('state') in ('completed', 'failed', 'interrupted', 'invalidated')
                          and (args.run_diagnostic or value.get('attempt') == old_id))
            response = app.api.dispatch('model_diagnostic_status', {'run_id': args.run_id})
            (proof / 'public-result.json').write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
            value = response.get('data') or {}
            match = status.get('answer', '').strip() == expected
            summary = {'native_gui': status, 'oracle_exact_match': match,
                       'new_model_turns': int(args.run_diagnostic), 'run_id': args.run_id,
                       'attempt_id': value.get('attempt_id'), 'thread_id': value.get('thread_id'),
                       'turn_id': value.get('turn_id'), 'ocr_python': args.ocr_python}
            (proof / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            if not (response['ok'] and value.get('native_runtime') and value.get('combination_verified')
                    and value.get('state') == 'completed' and match):
                raise RuntimeError('The actual native diagnostic does not match the independent image oracle.')
            app.window.script('document.querySelector(".codex-panel").scrollIntoView({block:"center"});return true;', timeout=3)
            time.sleep(1)
            screenshot = proof / 'native-gui.png'
            subprocess.run(['import', '-window', 'root', str(screenshot)], check=True)
            maximum = float(subprocess.run(['identify', '-format', '%[fx:maxima]', str(screenshot)],
                                            capture_output=True, text=True, check=True).stdout)
            if maximum == 0:
                raise RuntimeError('Screenshot is black; launch the actual browser on the captured X11 display.')
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
