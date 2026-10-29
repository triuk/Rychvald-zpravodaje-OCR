"""Real WebUI/Chromium preview interaction over a synthetic two-page scan.

Requires the selected native OCR environment, a browser and an X11 display.
Only local OCR runs; this check never submits an AI request.
"""
import argparse
import io
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
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    import fitz
    from PIL import Image, ImageDraw, ImageFont
    from webui import webui
    failures = []
    with tempfile.TemporaryDirectory(prefix='Nativní náhled ') as directory:
        root = Path(directory)
        source = root / 'Dvě stránky.pdf'
        image = Image.new('RGB', (900, 450), 'white')
        ImageDraw.Draw(image).text((60, 100), 'LOCAL OCR 12', fill='black', font=ImageFont.load_default(size=70))
        stream = io.BytesIO(); image.save(stream, format='PNG')
        with fitz.open() as document:
            for number in range(2):
                page = document.new_page(width=216, height=108)
                page.insert_image(page.rect, stream=stream.getvalue())
                if number == 1:
                    page.set_cropbox(fitz.Rect(5, 5, 210, 100)); page.set_rotation(90)
            document.save(source)
        app = WebUIApplication(root / 'evidence', browser='Chromium',
            browser_parameters='--headless --no-sandbox --disable-gpu' if args.headless else '--no-sandbox --ozone-platform=x11')
        imported = app.api.dispatch('import_sources', {'path': str(source)})['data']
        profile = app.api.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        run = app.api.dispatch('create_run', {'edition_id': imported['editions'][0]['edition_id'],
            'name': 'Náhled dvou stran', 'profile_path': profile['path'], 'profile_sha256': profile['sha256']})['data']
        run_id = run['project']['run_id']
        app.api.dispatch('start_preparation', {'run_id': run_id})
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            status = app.api.dispatch('preparation_status', {'run_id': run_id})['data']
            if status['state'] not in ('starting', 'running'):
                break
            time.sleep(.05)
        if status['state'] != 'completed':
            raise RuntimeError(str(status))
        before = app.api.dispatch('select_run', {'run_id': run_id})['data']

        def script(code):
            result = app.window.script(code, timeout=3)
            if result.error or not result.data or result.data in ('null', 'undefined'):
                return None
            return json.loads(result.data)

        def wait(code, expected=True):
            deadline = time.monotonic() + 30
            observed = None
            while time.monotonic() < deadline:
                if app.window is not None and app.window.is_shown():
                    observed = script(code)
                    if observed == expected:
                        return observed
                time.sleep(.1)
            raise AssertionError(f'Expected {expected!r}; observed {observed!r} for {code}')

        def inspect():
            try:
                selector = f'.run[data-run-id="{run_id}"]'
                wait(f'return JSON.stringify(Boolean(document.querySelector({json.dumps(selector)})));')
                script(f'document.querySelector({json.dumps(selector)}).click();return JSON.stringify(true);')
                wait("return JSON.stringify(document.querySelector('.preview-state')?.dataset.state);", 'available')
                wait("return JSON.stringify(document.querySelectorAll('.preview-overlay').length>0);")
                wait("return JSON.stringify(document.querySelector('.preview-surface img')?.naturalWidth>0);")
                script("const page=document.querySelector('[aria-label=\"Strana náhledu\"]');page.value=2;page.dispatchEvent(new Event('change'));const zoom=document.querySelector('[aria-label=\"Přiblížení náhledu\"]');zoom.value=150;zoom.dispatchEvent(new Event('change'));return JSON.stringify(true);")
                wait("return JSON.stringify(document.querySelector('.preview-state')?.dataset.state);", 'available')
                script("document.querySelector('#tab-reading').click();return JSON.stringify(true);")
                wait("return JSON.stringify(document.querySelector('.preview-state')?.dataset.state);", 'historical_missing')
                wait("return JSON.stringify([document.querySelector('[aria-label=\"Strana náhledu\"]').value,document.querySelector('[aria-label=\"Přiblížení náhledu\"]').value]);", ['2', '150'])
                script("document.querySelector('#tab-preparation').click();document.querySelector('.phase-splitter').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));return JSON.stringify(true);")
                wait("return JSON.stringify(document.querySelector('.phase-splitter').getAttribute('aria-valuenow'));", '35')
                script("[...document.querySelectorAll('.preview-controls button')].find(x=>x.textContent==='Zvětšit náhled').click();return JSON.stringify(true);")
                wait("return JSON.stringify(Boolean(document.querySelector('.preview-enlarged')));")
                script("document.querySelector('.preview-enlarged').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return JSON.stringify(true);")
                wait("return JSON.stringify(Boolean(document.querySelector('.preview-enlarged')));", False)
                # Return to the page containing a known visible helper text.
                script("const page=document.querySelector('[aria-label=\"Strana náhledu\"]');page.value=1;page.dispatchEvent(new Event('change'));return JSON.stringify(true);")
                wait("return JSON.stringify(document.querySelector('.preview-state')?.dataset.state);", 'available')
                wait("return JSON.stringify(document.querySelectorAll('.preview-overlay').length>0);")
                if args.screenshot:
                    app.window.script("document.querySelector('.phase-workspace').scrollIntoView({block:'start'});return true;", timeout=2)
                    time.sleep(.2)
                    subprocess.run(['import', '-window', 'root', str(args.screenshot)], check=True)
                if app.api.dispatch('select_run', {'run_id': run_id})['data'] != before:
                    raise AssertionError('Preview interaction modified the saved run or started work.')
                print(json.dumps({'status': 'passed', 'run_id': run_id,
                    'checks': ['actual local OCR', 'visible text overlays', 'crop/rotation page',
                        'page and zoom retained across phases', 'splitter', 'enlarge', 'no new work']}, ensure_ascii=False), flush=True)
            except BaseException as error:
                failures.append(str(error)); print('NATIVE_PREVIEW_FAILURE ' + str(error), flush=True)
            finally:
                webui.exit()
        worker = threading.Thread(target=inspect, daemon=True); worker.start()
        app.run(); worker.join(timeout=3)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
