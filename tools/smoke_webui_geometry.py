#!/usr/bin/env python3
"""Native GUI geometry proof over disclosed existing source runs; never redoes reading."""
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
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disclosure', type=Path, required=True)
    parser.add_argument('--disclosure-sha256', required=True)
    parser.add_argument('--case', choices=['synthetic', 'difficult'], required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--ocr-python', required=True)
    parser.add_argument('--run-geometry', action='store_true')
    parser.add_argument('--inspect-preparation', action='store_true', help='Read-only native GUI; no model submission or visual milestone claim.')
    parser.add_argument('--continue-attempt', help='Explicitly reconcile this saved terminal attempt; never repeats a source-sample turn when frozen samples exist.')
    args = parser.parse_args()
    if sha(args.disclosure) != args.disclosure_sha256:
        parser.error('Concrete source/destination disclosure changed')
    disclosure = json.loads(args.disclosure.read_text())
    case = next(c for c in disclosure['cases'] if c['kind']==args.case)
    for image in case['original_images']:
        if sha(image['path']) != image['sha256']:
            parser.error('Disclosed source image changed')
    proof = args.proof.resolve(); proof.mkdir(parents=True, exist_ok=True)
    app = WebUIApplication(disclosure['registry'], browser='Chromium', browser_parameters='--ozone-platform=x11',
        process_command=[args.ocr_python, '-B', str(ROOT/'tools/ocr_projects.py')])
    from webui import webui
    failures = []

    def query(script):
        response = app.window.script(script, timeout=3)
        return None if response.error or not response.data or response.data.strip() in ('null', 'undefined') else json.loads(response.data)

    def wait(script, predicate=bool, timeout=120):
        deadline = time.monotonic()+timeout
        last = None
        while time.monotonic()<deadline:
            if app.window is not None and app.window.is_shown():
                last = query(script)
                if predicate(last):
                    return last
            time.sleep(.2)
        raise RuntimeError('Native geometry GUI timeout: '+repr(last))

    def status(operation):
        value = app.api.dispatch(operation, {'run_id': case['run_id']})
        if not value['ok']:
            raise RuntimeError(str(value['error']))
        return value['data']

    def inspect():
        try:
            selector = '.run[data-run-id='+json.dumps(case['run_id'])+']'
            wait('return JSON.stringify(Boolean(document.querySelector('+json.dumps(selector)+')));')
            query('document.querySelector('+json.dumps(selector)+').click();return JSON.stringify(true);')
            wait('return JSON.stringify(document.querySelector("#detail")?.dataset.runId==='+json.dumps(case['run_id'])+
                '&&Boolean(document.querySelector("#geometry-panel")));')
            previous = status('geometry_status')
            save(proof/'before-operation.json', {'reading': status('reading_status'), 'geometry': previous})
            if args.run_geometry:
                if previous['state'] != 'not_started' and previous.get('attempt_id') != args.continue_attempt:
                    raise RuntimeError('Existing geometry attempt needs explicit original-turn reconciliation; no duplicate submission')
                wait('return JSON.stringify(!readingRequestPending&&!geometryRequestPending&&!progressRequestPending&&displayedReading!==null);')
                if case.get('samples_path'):
                    for field, value in [('geometry-samples', case['samples_path']),
                        ('geometry-commitment', case['source_commitment_path']),
                        ('geometry-commitment-pointer', case['commitment_pointer'])]:
                        query('const e=document.querySelector('+json.dumps('#'+field)+');e.value='+json.dumps(value)+
                            ';e.dispatchEvent(new Event("input",{bubbles:true}));return JSON.stringify(true);')
                save(proof/'prepared-ai-disclosure.json', {'source_disclosure_sha256': args.disclosure_sha256,
                    'case': case, 'runtime': app.api.geometry.runtime, 'context_runtime': app.api.geometry.context_runtime,
                    'model_destination': disclosure['model_destination']})
                wait('const b=document.querySelector("#start-geometry");if(b&&!b.disabled){b.click();return JSON.stringify(true)}return JSON.stringify(false);')
                deadline = time.monotonic()+1200
                while time.monotonic()<deadline:
                    value = status('geometry_status')
                    save(proof/'native-geometry-current.json', value)
                    if value.get('attempt_id') != previous.get('attempt_id') and value['state'] not in ('starting','running','not_started'):
                        break
                    time.sleep(.8)
                else:
                    raise RuntimeError('Native geometry operation did not finish')
            value = status('geometry_status')
            save(proof/'native-geometry.json', value)
            if args.inspect_preparation:
                if not value.get('prepared_artifacts_valid'):
                    raise RuntimeError('Saved native geometry preparation failed validation')
            elif value['state'] != 'completed' or not value.get('geometry_complete'):
                raise RuntimeError('Native geometry not complete: '+str(value.get('error')))
            if not args.inspect_preparation:
                wait('return JSON.stringify(document.querySelector("#geometry-state")?.dataset.state);', lambda state: state=='completed')
                wait('return JSON.stringify(displayedGeometry==='+json.dumps(value['attempt_id'])+
                    '&&!geometryRequestPending&&!readingRequestPending&&!progressRequestPending);')
            else:
                wait('return JSON.stringify(Boolean(document.querySelector("#geometry-output details")));')
            query('document.querySelector("#geometry-panel").scrollIntoView({block:"start"});return JSON.stringify(true);')
            wait('const b=document.querySelector("#geometry-panel")?.getBoundingClientRect();return JSON.stringify(Boolean(b&&b.top>-8&&b.top<200));')
            save(proof/'native-metrics.json', app.api.dispatch('run_metrics', {'run_id': case['run_id']}))
            time.sleep(.3)
            screenshot = proof/'native-gui.png'
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','x11grab','-video_size','1920x1400',
                '-i',os.environ['DISPLAY'],'-frames:v','1','-update','1','-y',str(screenshot)],check=True)
            from PIL import Image,ImageStat
            with Image.open(screenshot) as image:
                mean = sum(ImageStat.Stat(image.convert('RGB')).mean)/(3*255)
            if mean<=.01:
                raise RuntimeError('Black screenshot cannot prove native GUI')
            save(proof/'summary.json', {'native_gui':True,'case':args.case,'run_id':case['run_id'],
                'attempt_id':value.get('attempt_id'),'geometry_complete':bool(value.get('geometry_complete')),'screenshot_mean':mean,
                'new_geometry_requested':args.run_geometry,'new_first_reading_requested':False})
            print(json.dumps({'native_gui':True,'case':args.case,'attempt_id':value['attempt_id'],'screenshot_mean':mean}),flush=True)
        except BaseException as error:
            failures.append(str(error)); save(proof/'failure.json', {'error':str(error)})
            print('NATIVE_FAILURE '+str(error),flush=True)
        finally:
            webui.exit()
    thread=threading.Thread(target=inspect,daemon=True);thread.start()
    app.run();thread.join(timeout=5)
    return int(bool(failures))


if __name__=='__main__':
    raise SystemExit(main())
