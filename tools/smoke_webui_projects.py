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
    parser.add_argument('--profiles', action='store_true', help='Also exercise GUI import, profile inspection and two named runs.')
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
                if args.profiles:
                    exercise_profiles()
                if args.screenshot:
                    time.sleep(.2)
                    subprocess.run(['import', '-window', 'root', str(args.screenshot)], check=True)
                    print('NATIVE_SCREENSHOT ' + str(args.screenshot), flush=True)
            except BaseException as error:
                failures.append(str(error))
                print('NATIVE_FAILURE ' + str(error), flush=True)
            finally:
                webui.exit()

        def exercise_profiles():
            incoming = root / 'new sources with spaces'
            incoming.mkdir()
            content = b'%PDF-1.4\nnew source for named runs\n%%EOF\n'
            (incoming / 'novy-zpravodaj.pdf').write_bytes(content)
            (incoming / 'kopie.pdf').write_bytes(content)

            def submit(form, values):
                script = ''.join(f'document.querySelector({json.dumps(selector)}).value={json.dumps(value)};'
                                 for selector, value in values.items())
                result = app.window.script(script + f'document.querySelector({json.dumps(form)}).requestSubmit(); return true;', timeout=2)
                if result.error:
                    raise AssertionError('Could not submit native GUI form: ' + form)

            submit('#source-form', {'#source-path': str(incoming)})
            imported = wait_for(
                "return JSON.stringify({editions:document.querySelectorAll('.edition').length,runs:document.querySelectorAll('.run').length});",
                {'editions': 3, 'runs': 4})
            print('NATIVE_IMPORTED ' + json.dumps(imported), flush=True)
            profile_path = root / 'external profile.json'
            profile = {'schema_version': 1, 'name': 'Profil A',
                       'parameters': {'dpi': 300, 'language': 'ces', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'},
                       'prompts': {'read': 'Přečti celý zdrojový sken.', 'repair': 'Oprav doložené nálezy.',
                                   'final_check': 'Porovnej výsledek se skenem.'}}
            profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding='utf-8')

            def inspect(expected_name, dpi):
                submit('#profile-form', {'#profile-path': str(profile_path)})
                wait_for("return JSON.stringify({name:document.querySelector('#profile-title').textContent,parameters:document.querySelector('#profile-parameters').textContent});",
                         {'name': expected_name, 'parameters': f'{dpi} DPI · ces · gpt-6.1-sol · high'})
                raw = query("return JSON.stringify(JSON.parse(document.querySelector('#profile-text').textContent));")
                if raw != profile:
                    raise AssertionError('Inspected GUI profile differs from the external file.')
                print('NATIVE_PROFILE ' + json.dumps({'name': expected_name, 'dpi': dpi}), flush=True)

            inspect('Profil A', 300)
            app.window.script("const choice=document.querySelector('#edition-choice');choice.selectedIndex=choice.options.length-1;return true;", timeout=2)
            submit('#run-form', {'#run-name': 'Vizuální čtení A'})
            wait_for("return JSON.stringify({name:document.querySelector('.detail-title').textContent,profile:document.querySelector('#run-profile p')?.textContent,history:document.querySelectorAll('#run-history li').length});",
                     {'name': 'Vizuální čtení A', 'profile': '300 DPI · ces · gpt-6.1-sol · high', 'history': 1})
            first_id = query("return JSON.stringify(document.querySelector('.run[aria-pressed=true]').dataset.runId);")
            profile['name'] = 'Profil B'
            profile['parameters']['dpi'] = 400
            profile['prompts']['read'] = 'Přečti celý sken s důrazem na tabulky.'
            profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding='utf-8')
            inspect('Profil B', 400)
            submit('#run-form', {'#run-name': 'Vizuální čtení B'})
            wait_for("return JSON.stringify({name:document.querySelector('.detail-title').textContent,profile:document.querySelector('#run-profile p')?.textContent,history:document.querySelectorAll('#run-history li').length});",
                     {'name': 'Vizuální čtení B', 'profile': '400 DPI · ces · gpt-6.1-sol · high', 'history': 1})
            app.window.script(f'document.querySelector(\'[data-run-id="{first_id}"]\').click(); return true;', timeout=2)
            preserved = wait_for(
                "return JSON.stringify({name:document.querySelector('.detail-title').textContent,profile:document.querySelector('#run-profile p')?.textContent,prompt:JSON.parse(document.querySelector('#run-profile pre').textContent).prompts.read,history:document.querySelectorAll('#run-history li').length});",
                {'name': 'Vizuální čtení A', 'profile': '300 DPI · ces · gpt-6.1-sol · high',
                 'prompt': 'Přečti celý zdrojový sken.', 'history': 1})
            print('NATIVE_NAMED_RUNS ' + json.dumps({'named_runs': 2, 'first_preserved': preserved}, ensure_ascii=False), flush=True)
            app.window.script("document.querySelector('#run-profile details').open=true;document.querySelector('#run-profile').scrollIntoView({block:'start'});return true;", timeout=2)
            wait_for("return JSON.stringify(document.querySelector('#run-profile').getBoundingClientRect().top < window.innerHeight);", True)

        thread = threading.Thread(target=inspect_browser, daemon=True)
        thread.start()
        app.run()
        thread.join(timeout=3)
        return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
