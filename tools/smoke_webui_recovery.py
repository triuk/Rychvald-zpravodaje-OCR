#!/usr/bin/env python3
"""Native GUI close/relaunch proof with real local OCR and controlled AI only.

Run close and resume as separate OS processes against the same durable proof
directory. This never opens an account or sends a prompt to an actual model.
"""
import argparse
import hashlib
import io
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
from app.service import Application


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['close', 'resume'], required=True)
    parser.add_argument('--proof', required=True, type=Path)
    parser.add_argument('--webui-library', required=True, type=Path)
    parser.add_argument('--webui-library-sha256', required=True)
    args = parser.parse_args()
    if not args.webui_library.is_file() or hashlib.sha256(args.webui_library.read_bytes()).hexdigest() != args.webui_library_sha256:
        parser.error('Exact existing local WebUI library required before import; no download.')
    proof = args.proof.resolve(); proof.mkdir(parents=True, exist_ok=True)
    source = proof / 'fictional-source.pdf'
    if args.phase == 'close':
        if (proof / 'case.json').exists():
            parser.error('Existing proof case cannot be silently replayed.')
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        with fitz.open() as document:
            for text in ('ABC', 'DEF'):
                image = Image.new('RGB', (100, 100), 'white')
                ImageDraw.Draw(image).text((2, 0), text, fill='black',
                    font=ImageFont.truetype('/usr/share/fonts/noto/NotoSerif-Regular.ttf', 16))
                stream = io.BytesIO(); image.save(stream, format='PNG')
                page = document.new_page(width=24, height=24)
                page.insert_image(page.rect, stream=stream.getvalue())
            document.save(source)
    files = [ROOT / 'tests' / name for name in ('autonomous_app_server_fixture.py',
        'reading_app_server_fixture.py', 'geometry_app_server_fixture.py',
        'codex_app_server_fixture.py', 'context_app_server_fixture.py')]
    runtime = {'kind': 'controlled_process_fixture', 'version': 'recovery-gui-peer-19',
        'command': [sys.executable, '-B', str(files[0])],
        'files': [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]}
    context = {'kind': 'controlled_process_fixture', 'package': str(proof), 'node': sys.executable,
        'files': [], 'interpreters': [], 'probe_command': [sys.executable, '-B', '-c',
            'print(\'{"node":"fixture","sqlite_fts5":true}\')']}
    gui = WebUIApplication(proof / 'registry', browser='Chromium',
        browser_parameters='--ozone-platform=x11 --no-first-run --no-default-browser-check',
        browser_profile=proof / ('browser-' + args.phase))
    gui.api = Application(proof / 'registry', codex_runtime=runtime, context_runtime=context)
    from webui import webui, load_library
    if Path(load_library._get_library_path()).resolve() != args.webui_library.resolve():
        parser.error('Imported WebUI binary differs from the verified local path.')
    errors = []

    def query(script):
        response = gui.window.script(script, timeout=4)
        if response.error or not response.data or response.data.strip() in ('null', 'undefined'):
            return None
        return json.loads(response.data)

    def wait(script, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if gui.window is not None and gui.window.is_shown():
                value = query(script)
                if value:
                    return value
            time.sleep(.1)
        raise RuntimeError('GUI timeout: ' + script)

    def capture(name):
        query('document.querySelector("#export-panel").scrollIntoView({block:"start"});return JSON.stringify(true);')
        time.sleep(.2)
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab',
            '-video_size', '1920x1400', '-i', os.environ['DISPLAY'], '-frames:v', '1',
            '-update', '1', '-y', str(proof / name)], check=True)

    def operate():
        try:
            wait('return JSON.stringify(connected);')
            if args.phase == 'close':
                query('document.querySelector("#profile-path").value=' + json.dumps(str(ROOT / 'profiles/faithful-reading.json')) +
                    ';document.querySelector("#profile-form").requestSubmit();return JSON.stringify(true);')
                wait('return JSON.stringify(Boolean(selectedProfile)&&!document.querySelector("#start-autonomous").disabled);')
                query('document.querySelector("#source-path").value=' + json.dumps(str(source)) +
                    ';document.querySelector("#run-name").value="Obnova po zavření GUI";'
                    'document.querySelector("#autonomous-environment").value=' + json.dumps(os.environ['OCR_ENVIRONMENT']) +
                    ';document.querySelector("#start-autonomous").click();return JSON.stringify(true);')
                run_id = wait('return JSON.stringify(selectedRun);')
                save(proof / 'case.json', {'run_id': run_id, 'source': str(source), 'actual_inference': False,
                    'gui_pid': os.getpid(), 'display': os.environ['DISPLAY'], 'runtime': runtime})
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    local = gui.api.dispatch('preparation_status', {'run_id': run_id})['data']
                    if local.get('process_group') and local.get('active_steps'):
                        break
                    time.sleep(.02)
                if not local.get('process_group'):
                    raise RuntimeError('Real owned native process was not observed.')
                save(proof / 'before-close.json', {'local': local,
                    'autonomous': gui.api.dispatch('autonomous_status', {'run_id': run_id})['data']})
                wait('return JSON.stringify(Boolean(document.querySelector("#interrupt-autonomous")&&!document.querySelector("#interrupt-autonomous").disabled));')
                capture('native-before-close.png')
            else:
                case = json.loads((proof / 'case.json').read_text()); run_id = case['run_id']
                selector = '.run[data-run-id=' + json.dumps(run_id) + ']'
                wait('return JSON.stringify(Boolean(document.querySelector(' + json.dumps(selector) + ')));')
                query('document.querySelector(' + json.dumps(selector) + ').click();return JSON.stringify(true);')
                wait('return JSON.stringify(document.querySelector("#autonomous-state")?.dataset.state==="interrupted");')
                capture('native-after-restart.png')
                query('document.querySelector("#reconcile-autonomous").click();return JSON.stringify(true);')
                wait('const b=document.querySelector("#resume-autonomous");return JSON.stringify(Boolean(b&&!b.disabled&&recoveryProofs.get(selectedRun)));')
                save(proof / 'gui-reconciliation.json', query('return JSON.stringify(recoveryProofs.get(selectedRun));'))
                capture('native-offers-resume.png')
                query('document.querySelector("#resume-autonomous").click();return JSON.stringify(true);')
                wait('return JSON.stringify(document.querySelector("#autonomous-state")?.dataset.state==="completed");', timeout=150)
                save(proof / 'gui-resumed.json', gui.api.dispatch('autonomous_status', {'run_id': run_id})['data'])
                capture('native-resumed-complete.png')
            save(proof / ('native-dom-' + args.phase + '.json'), query('return JSON.stringify({run_id:selectedRun,'
                'state:document.querySelector("#autonomous-state")?.textContent,'
                'recovery:document.querySelector("#recovery-state")?.textContent,'
                'controls:[...document.querySelectorAll(".recovery-controls button")].map(b=>({text:b.textContent,disabled:b.disabled}))});'))
        except BaseException as error:
            errors.append(str(error)); save(proof / ('failure-' + args.phase + '.json'), {'error': str(error)})
        finally:
            if gui.window:
                gui.window.close()  # Native window close; Application.run finally owns cancellation.

    worker = threading.Thread(target=operate, daemon=True); worker.start()
    gui.run(); worker.join(timeout=5)
    if worker.is_alive():
        errors.append('GUI proof worker did not finish.')
    if (proof / 'case.json').exists():
        run_id = json.loads((proof / 'case.json').read_text())['run_id']
        state = gui.api.dispatch('autonomous_status', {'run_id': run_id})
        save(proof / ('after-window-' + args.phase + '.json'), state)
        if args.phase == 'close' and state.get('data', {}).get('state') != 'interrupted':
            errors.append('Window close did not persist interrupted state.')
    webui.exit()
    save(proof / ('summary-' + args.phase + '.json'), {'phase': args.phase, 'errors': errors,
        'actual_inference': False, 'gui_pid': os.getpid(), 'display': os.environ['DISPLAY']})
    print(json.dumps({'phase': args.phase, 'errors': errors}), flush=True)
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
