"""Optional real native smoke: WebUI2, a browser, and a display are required.

Runs the production adapter, clicks a rendered run through the native browser
script channel, and checks independently expected legacy states. All source and
registry files are temporary. No WebUI, browser, or OCR process is replaced.
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
sys.path.insert(0, str(ROOT))
from app.application import WebUIApplication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', default='Chromium', choices=['Chromium', 'Chrome', 'Firefox'])
    parser.add_argument('--screenshot', type=Path, help='Optional screenshot via ImageMagick import (X11).')
    args = parser.parse_args()
    from webui import webui

    with tempfile.TemporaryDirectory(prefix='WebUI native evidence ') as directory:
        root = Path(directory)
        registry = root / 'registry with spaces'
        source = root / 'zpravodaj.pdf'
        source.write_bytes(b'%PDF-1.4\nfirst source\n%%EOF\n')

        def cli(*arguments):
            result = subprocess.run(
                [sys.executable, '-S', str(ROOT / 'tools/ocr_projects.py'),
                 '--root', str(registry), '--json', *map(str, arguments)],
                capture_output=True, check=True)
            return json.loads(result.stdout)

        cli('import', source)
        cli('import', source, '--new-run')
        source.write_bytes(b'%PDF-1.4\ndifferent source\n%%EOF\n')
        cli('import', source)
        app = WebUIApplication(registry, browser=args.browser)
        failures = []

        def query(script):
            result = app.window.script(script, timeout=2)
            return None if result.error else json.loads(result.data)

        def wait_for(script, expected, timeout=30):
            deadline = time.monotonic() + timeout
            observed = None
            while time.monotonic() < deadline:
                if app.window is not None and app.window.is_shown():
                    observed = query(script)
                    if observed == expected:
                        return observed
                time.sleep(.1)
            raise AssertionError(f'Expected {expected!r}; observed {observed!r}')

        def inspect_browser():
            try:
                listing = wait_for(
                    "return JSON.stringify({editions:document.querySelectorAll('.edition').length,"
                    "runs:document.querySelectorAll('.run').length});",
                    {'editions': 2, 'runs': 3})
                print('NATIVE_LIST ' + json.dumps(listing), flush=True)
                clicked = app.window.script("document.querySelector('.run').click(); return true;", timeout=2)
                if clicked.error:
                    raise AssertionError('Native browser could not click the rendered run.')
                selected = wait_for(
                    "return JSON.stringify({statuses:[...document.querySelectorAll('.status-code')]"
                    ".map(x=>x.textContent),artifacts:document.querySelectorAll('.artifacts tbody tr').length});",
                    {'statuses': ['registered', 'idle', 'not_run', 'not_recorded'], 'artifacts': 5})
                print('NATIVE_SELECTED ' + json.dumps(selected), flush=True)
                if args.screenshot:
                    subprocess.run(['import', '-window', 'root', str(args.screenshot)], check=True)
                    print('NATIVE_SCREENSHOT ' + str(args.screenshot), flush=True)
            except BaseException as error:
                failures.append(str(error))
                print('NATIVE_FAILURE ' + str(error), flush=True)
            finally:
                webui.exit()

        thread = threading.Thread(target=inspect_browser, daemon=True)
        thread.start()
        app.run()
        thread.join(timeout=3)
        return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
