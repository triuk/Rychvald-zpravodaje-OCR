"""Owned public application process with an optional filesystem-boundary crash.

The audit hook exits before the OS rename that would commit a correction's
first output-child link. It never changes a manager or writes native evidence.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


def crash_before_output_link(event, arguments):
    if event != 'os.rename':
        return
    source, destination = (Path(os.fsdecode(value)) for value in arguments[:2])
    if destination.name != 'attempt.json' or destination.parent.parent.name != 'correction-attempts':
        return
    if not source.is_file() or not destination.is_file():
        return
    old, new = json.loads(destination.read_text()), json.loads(source.read_text())
    links = [row for row in new.get('children', []) if row['stage'] == 'output_review']
    if old.get('children') or len(links) != 1:
        return
    work = destination.parents[3]
    child_path = work / 'application/output-review-attempts' / links[0]['attempt_id'] / 'attempt.json'
    child = json.loads(child_path.read_text())
    binding = child.get('parent_binding')
    if not binding or binding.get('correction_attempt_id') != new['attempt_id']:
        return
    marker.write_text(json.dumps({'boundary': 'before_os_rename_of_parent_child_link',
        'parent_attempt_id': binding['parent_attempt_id'], 'correction_attempt_id': new['attempt_id'],
        'output_attempt_id': child['attempt_id'], 'cycle_id': binding['cycle_id'],
        'original_parent_manifest_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'uncommitted_parent_manifest_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'child_manifest_sha256': hashlib.sha256(child_path.read_bytes()).hexdigest()}) + '\n')
    os._exit(91)


def crash_before_repair_publication(event, arguments):
    if event != 'os.rename':
        return
    source, destination = (Path(os.fsdecode(value)) for value in arguments[:2])
    prefix = 'checkpoint-' if fault_mode == 'geometry-publication' else 'publication-'
    if (not destination.name.startswith(prefix) or
            destination.parent.parent.name != 'correction-attempts' or not source.is_file()):
        return
    correction = destination.with_name('attempt.json')
    saved = json.loads(correction.read_text())
    publication = json.loads(source.read_text())
    work = destination.parents[3]
    cycle = json.loads((work / 'application/corrections/ledger.json').read_text())['cycles'][-1]
    marker.write_text(json.dumps({'boundary': 'before_original_' + fault_mode + '_rename',
        'parent_attempt_id': saved['parent_binding']['parent_attempt_id'],
        'correction_attempt_id': saved['attempt_id'], 'cycle_id': cycle['cycle_id'],
        'original_parent_manifest_sha256': hashlib.sha256(correction.read_bytes()).hexdigest(),
        'original_visual_turn': publication['visual_turn']}) + '\n')
    os._exit(91)


def crash_before_output_publication(event, arguments):
    if event != 'os.rename':
        return
    source, destination = (Path(os.fsdecode(value)) for value in arguments[:2])
    if (destination.name != 'publication-proposal.json' or
            destination.parent.parent.name != 'output-review-attempts' or not source.is_file()):
        return
    child = json.loads(destination.with_name('attempt.json').read_text())
    binding = child.get('parent_binding') or {}
    if not binding.get('correction_attempt_id'):
        return  # Only the exact correction descendant, not first-pass review.
    work = destination.parents[3]
    correction = work / 'application/correction-attempts' / binding['correction_attempt_id'] / 'attempt.json'
    manifest = json.loads((work / 'output-manifest.json').read_text())
    marker.write_text(json.dumps({'boundary': 'before_original_output_publication_rename',
        'parent_attempt_id': binding['parent_attempt_id'], 'correction_attempt_id': binding['correction_attempt_id'],
        'output_attempt_id': child['attempt_id'], 'cycle_id': binding['cycle_id'],
        'iteration_id': manifest['iteration_id'], 'rendered_pdf_sha256': manifest['pdf_sha256'],
        'rendered_txt_sha256': manifest['txt_sha256'],
        'original_parent_manifest_sha256': hashlib.sha256(correction.read_bytes()).hexdigest(),
        'original_visual_turn': json.loads(source.read_text())['visual_turn'],
        'owner': json.loads(owner_path.read_text())}) + '\n')
    os._exit(91)


def crash_native_before_render_binding(event, arguments):
    if event != 'os.rename':
        return
    source, destination = (Path(os.fsdecode(value)) for value in arguments[:2])
    if not source.is_file():
        return
    if fault_mode == 'export-project':
        if destination.name != 'project.json' or not destination.is_file():
            return
        work = destination.parent
        ledger_path = work / 'application/corrections/ledger.json'
        if not ledger_path.is_file():
            return
        old, new = json.loads(destination.read_text()), json.loads(source.read_text())
        cycle = json.loads(ledger_path.read_text())['cycles'][-1]
        if (not cycle.get('exported_iteration_id') or new['project']['phase'] != 'exported' or
                new['project']['iteration_id'] != cycle['exported_iteration_id'] or
                old['project']['iteration_id'] == new['project']['iteration_id']):
            return
        directory = ledger_path.parent / cycle['cycle_id']
        rendered = json.loads((directory / 'export-rendered.json').read_text())
        boundary = 'before_exported_project_rename'
    elif fault_mode == 'export-ledger':
        if destination.name != 'ledger.json' or destination.parent.name != 'corrections' or not destination.is_file():
            return
        old, new = json.loads(destination.read_text()), json.loads(source.read_text())
        if not new['cycles'] or not new['cycles'][-1].get('exported_iteration_id') or old['cycles'][-1].get('exported_iteration_id'):
            return
        work = destination.parents[2]
        directory = destination.parent / new['cycles'][-1]['cycle_id']
        rendered = json.loads((directory / 'export-rendered.json').read_text())
        boundary = 'before_exported_ledger_rename'
    else:
        if destination.name != 'export-rendered.json':
            return
        work = destination.parents[3]
        directory = destination.parent
        rendered = json.loads(source.read_text())
        boundary = 'before_native_render_manifest_rename'
    intent = json.loads((directory / 'export-intent.json').read_text())
    correction = work / 'application/correction-attempts' / intent['attempt_id'] / 'attempt.json'
    saved = json.loads(correction.read_text())
    owner = json.loads(owner_path.read_text())
    stat = Path('/proc/' + str(owner['pid']) + '/stat').read_text()
    if stat.rsplit(')', 1)[1].split()[19] != owner['start_ticks']:
        raise RuntimeError('Refuse to signal a different application owner')
    marker.write_text(json.dumps({'boundary': boundary,
        'parent_attempt_id': saved['parent_binding']['parent_attempt_id'], 'correction_attempt_id': intent['attempt_id'],
        'cycle_id': intent['cycle_id'], 'iteration_id': intent['iteration_id'],
        'original_parent_manifest_sha256': hashlib.sha256(correction.read_bytes()).hexdigest(),
        'public_manifest_sha256': hashlib.sha256((work / 'output-manifest.json').read_bytes()).hexdigest(),
        'rendered_pdf_sha256': rendered['pdf_sha256'], 'rendered_txt_sha256': rendered['txt_sha256'],
        'native_pid': os.getpid(), 'owner': owner}) + '\n')
    os.kill(owner['pid'], signal.SIGKILL)
    os._exit(92)


def crash_native_before_patch_ledger(event, arguments):
    if event != 'os.rename':
        return
    source, destination = (Path(os.fsdecode(value)) for value in arguments[:2])
    if not source.is_file():
        return
    if fault_mode == 'patch-chain':
        if destination.name != 'review-patch-chain.json':
            return
        work = destination.parent
        ledger = work / 'application/corrections/ledger.json'
        if not ledger.is_file():
            return
        cycle = json.loads(ledger.read_text())['cycles'][-1]
        if cycle['state'] != 'reserved' or not cycle.get('patch_intent'):
            return
        intent = json.loads((work / cycle['patch_intent']).read_text())
        if hashlib.sha256(source.read_bytes()).hexdigest() != intent['writes']['review-patch-chain.json']['sha256']:
            return
        cycle = {**cycle, 'previous_snapshot': intent['previous_snapshot'],
            'publication': str(Path(intent['inputs']['publication']['path']).relative_to(work)),
            'review_sha256': intent['record']['project']['review_sha256']}
    else:
        if destination.name != 'ledger.json' or destination.parent.name != 'corrections' or not destination.is_file():
            return
        old, new = json.loads(destination.read_text()), json.loads(source.read_text())
        cycle = new['cycles'][-1]
        if cycle['state'] != 'published' or old['cycles'][-1]['state'] != 'reserved':
            return
        work = destination.parents[2]
    correction = work / cycle['attempt']
    saved = json.loads(correction.read_text())
    publication = json.loads((work / cycle['publication']).read_text())
    owner = json.loads(owner_path.read_text())
    stat = Path('/proc/' + str(owner['pid']) + '/stat').read_text()
    if stat.rsplit(')', 1)[1].split()[19] != owner['start_ticks']:
        raise RuntimeError('Refuse to signal a different application owner')
    marker.write_text(json.dumps({'boundary': 'before_' + fault_mode + '_rename',
        'parent_attempt_id': saved['parent_binding']['parent_attempt_id'], 'correction_attempt_id': saved['attempt_id'],
        'cycle_id': cycle['cycle_id'], 'previous_snapshot': cycle['previous_snapshot'],
        'review_sha256': cycle['review_sha256'], 'original_visual_turn': publication['visual_turn'],
        'metadata_not_committed': fault_mode == 'patch-chain' and (not destination.exists() or
            hashlib.sha256(destination.read_bytes()).hexdigest() != hashlib.sha256(source.read_bytes()).hexdigest()),
        'original_parent_manifest_sha256': hashlib.sha256(correction.read_bytes()).hexdigest(),
        'native_pid': os.getpid(), 'owner': owner}) + '\n')
    os.kill(owner['pid'], signal.SIGKILL)
    os._exit(92)


def crash_native_before_outcome_ledger(event, arguments):
    if event != 'os.rename':
        return
    source, destination = (Path(os.fsdecode(value)) for value in arguments[:2])
    if destination.name != 'ledger.json' or destination.parent.name != 'corrections' or not source.is_file() or not destination.is_file():
        return
    old, new = json.loads(destination.read_text()), json.loads(source.read_text())
    cycle = new['cycles'][-1]
    if cycle['state'] != 'settled' or old['cycles'][-1]['state'] == 'settled':
        return
    work = destination.parents[2]
    correction = work / cycle['attempt']
    saved = json.loads(correction.read_text())
    manifest = json.loads((work / 'output-manifest.json').read_text())
    owner = json.loads(owner_path.read_text())
    stat = Path('/proc/' + str(owner['pid']) + '/stat').read_text()
    if stat.rsplit(')', 1)[1].split()[19] != owner['start_ticks']:
        raise RuntimeError('Refuse to signal a different application owner')
    marker.write_text(json.dumps({'boundary': 'before_original_outcome_ledger_rename',
        'parent_attempt_id': saved['parent_binding']['parent_attempt_id'], 'correction_attempt_id': saved['attempt_id'],
        'cycle_id': cycle['cycle_id'], 'iteration_id': manifest['iteration_id'],
        'rendered_pdf_sha256': manifest['pdf_sha256'], 'rendered_txt_sha256': manifest['txt_sha256'],
        'output_attempt_id': saved['children'][-1]['attempt_id'],
        'outcome_sha256': hashlib.sha256((work / cycle['outcome']).read_bytes()).hexdigest(),
        'validation_sha256': hashlib.sha256((work / 'checks/run-validation.json').read_bytes()).hexdigest(),
        'original_parent_manifest_sha256': hashlib.sha256(correction.read_bytes()).hexdigest(),
        'native_pid': os.getpid(), 'owner': owner}) + '\n')
    os.kill(owner['pid'], signal.SIGKILL)
    os._exit(92)


def crash_before_outcome_event(event, arguments):
    if event != 'os.rename':
        return
    source, destination = (Path(os.fsdecode(value)) for value in arguments[:2])
    if (destination.name != 'attempt.json' or destination.parent.parent.name != 'correction-attempts' or
            not source.is_file() or not destination.is_file()):
        return
    saved, new = json.loads(destination.read_text()), json.loads(source.read_text())
    if not new.get('events') or new['events'][-1]['type'] != 'correction_settled':
        return
    work = destination.parents[3]
    cycle = json.loads((work / 'application/corrections/ledger.json').read_text())['cycles'][-1]
    if cycle['state'] != 'settled':
        raise RuntimeError('Expected committed native settlement before the application event')
    manifest = json.loads((work / 'output-manifest.json').read_text())
    marker.write_text(json.dumps({'boundary': 'before_original_settlement_event_rename',
        'parent_attempt_id': saved['parent_binding']['parent_attempt_id'], 'correction_attempt_id': saved['attempt_id'],
        'cycle_id': cycle['cycle_id'], 'iteration_id': manifest['iteration_id'],
        'rendered_pdf_sha256': manifest['pdf_sha256'], 'rendered_txt_sha256': manifest['txt_sha256'],
        'output_attempt_id': saved['children'][-1]['attempt_id'],
        'outcome_sha256': hashlib.sha256((work / cycle['outcome']).read_bytes()).hexdigest(),
        'validation_sha256': hashlib.sha256((work / 'checks/run-validation.json').read_bytes()).hexdigest(),
        'original_parent_manifest_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'owner': json.loads(owner_path.read_text())}) + '\n')
    os._exit(91)


if sys.argv[1] == '--native':
    marker, owner_path = Path(sys.argv[2]), Path(sys.argv[3])
    fault_mode = sys.argv[4]
    arguments = sys.argv[5:]
    sys.addaudithook(crash_native_before_outcome_ledger if fault_mode == 'outcome-ledger' else
        crash_native_before_patch_ledger if fault_mode in ('patch-ledger', 'patch-chain') else crash_native_before_render_binding)
    sys.path.insert(0, str(ROOT / 'tools'))
    sys.argv = [str(ROOT / 'tools/ocr_projects.py'), *arguments]
    runpy.run_path(sys.argv[0], run_name='__main__')
    raise SystemExit()

marker = Path(sys.argv[4])
fault_mode = sys.argv[5] if len(sys.argv) > 5 else 'output-link'
owner_path = marker.with_suffix('.owner.json')
owner_path.write_text(json.dumps({'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]}))
native_command = [sys.executable, '-B', str(ROOT / 'tools/ocr_projects.py')]
if fault_mode == 'output-link':
    sys.addaudithook(crash_before_output_link)
elif fault_mode in ('repair-publication', 'geometry-publication'):
    sys.addaudithook(crash_before_repair_publication)
elif fault_mode == 'outcome-event':
    sys.addaudithook(crash_before_outcome_event)
elif fault_mode == 'output-publication':
    sys.addaudithook(crash_before_output_publication)
else:
    native_command = [sys.executable, '-B', str(Path(__file__)), '--native', str(marker), str(owner_path), fault_mode]
application = Application(Path(sys.argv[1]), codex_runtime=json.loads(Path(sys.argv[2]).read_text()),
    context_runtime=json.loads(Path(sys.argv[3]).read_text()), process_command=native_command)
try:
    for raw in sys.stdin:
        request = json.loads(raw)
        result = application.dispatch(request['operation'], request.get('payload'))
        print(json.dumps(result), flush=True)
finally:
    application.close()
