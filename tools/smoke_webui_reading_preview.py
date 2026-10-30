"""Actual WebUI view of first reading or geometry after a controlled correction.

The external AI peer is deliberately synthetic. Local preparation, PDF export,
correction and the native WebUI/Chromium view are real; no live model is called.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from app.application import WebUIApplication
from test_webui_reading_preview import ReadingPreviewTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--phase', choices=['reading', 'geometry'], default='reading')
    args = parser.parse_args()
    case = ReadingPreviewTests('test_first_reading_remains_original_after_controlled_correction_restart_and_legacy_lookup')
    failures = []
    try:
        case.setUp(); case.start()
        original = case.app.dispatch('phase_preview', {'run_id': case.identifier, 'phase': args.phase, 'page': 1})['data']
        status = case.correction()
        if status['state'] != 'completed':
            raise RuntimeError(str(status))
        case.app.close()
        browser_profile = tempfile.TemporaryDirectory(prefix='Native phase browser ')
        case.addCleanup(browser_profile.cleanup)
        adapter = WebUIApplication(case.root, browser='Chromium',
            browser_parameters='--headless --no-sandbox --disable-gpu' if args.headless else '--no-sandbox --ozone-platform=x11',
            browser_profile=Path(browser_profile.name))
        case.app = adapter.api
        from webui import webui

        def query(code):
            response = adapter.window.script(code, timeout=3)
            if response.error or not response.data or response.data in ('undefined', 'null'):
                return None
            return json.loads(response.data)

        def wait(code, expected=True):
            deadline = time.monotonic() + 30
            value = None
            while time.monotonic() < deadline:
                if adapter.window is not None and adapter.window.is_shown():
                    value = query(code)
                    if value == expected:
                        return value
                time.sleep(.1)
            raise AssertionError(f'Expected {expected!r}, observed {value!r}: {code}')

        def inspect():
            try:
                selector = f'.run[data-run-id="{case.identifier}"]'
                wait(f'return JSON.stringify(Boolean(document.querySelector({json.dumps(selector)})));')
                query(f'document.querySelector({json.dumps(selector)}).click();return JSON.stringify(true);')
                wait(f"return JSON.stringify(Boolean(document.querySelector('#tab-{args.phase}')));")
                query(f"document.querySelector('#tab-{args.phase}').click();return JSON.stringify(true);")
                wait("return JSON.stringify(document.querySelector('.preview-state')?.dataset.state);", 'available')
                wait("return JSON.stringify([...document.querySelectorAll('.preview-overlay')].map(x=>x.textContent));", ['1. AXC'] if args.phase == 'geometry' else ['AXC'])
                if args.phase == 'geometry':
                    wait("return JSON.stringify(document.querySelectorAll('.preview-character').length>0);")
                    wait("return JSON.stringify(document.querySelector('.preview-state').textContent.includes('aproximace'));")
                wait("return JSON.stringify(document.querySelector('.phase-preview').dataset.artifactId);", original['identity']['artifact_sha256'])
                wait("return JSON.stringify(document.querySelector('.preview-surface img')?.naturalWidth>0);")
                if args.screenshot:
                    query("document.querySelector('.phase-workspace').scrollIntoView({block:'start'});return JSON.stringify(true);")
                    time.sleep(.2)
                    subprocess.run(['import', '-window', 'root', str(args.screenshot)], check=True)
                if case.app.dispatch('phase_preview', {'run_id': case.identifier, 'phase': args.phase, 'page': 1})['data']['identity'] != original['identity']:
                    raise AssertionError('Opening the view changed the original phase identity.')
                current = json.loads((case.work / 'review.json').read_text())
                if current['lines'][0]['text'] != 'ABC':
                    raise AssertionError('Controlled correction did not change the working transcript.')
                print(json.dumps({'status': 'passed', 'ai': 'controlled protocol fixture',
                    'phase': args.phase, 'original_visible_text': 'AXC', 'current_corrected_text': 'ABC',
                    'first_phase_identity_unchanged': True}), flush=True)
            except BaseException as error:
                failures.append(str(error)); print('NATIVE_READING_PREVIEW_FAILURE ' + str(error), flush=True)
            finally:
                webui.exit()
        worker = threading.Thread(target=inspect, daemon=True); worker.start()
        adapter.run(); worker.join(timeout=3)
    finally:
        case.doCleanups()
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
