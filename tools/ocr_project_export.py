"""Project export adapters retain construction F and existing validation contracts."""
from pathlib import Path
import json
import contextlib
import copy
import io
import subprocess
import sys
import uuid
from types import SimpleNamespace

from ocr_environment import verify_environment
from ocr_projects import ProjectError, atomic_json, source_hash
from ocr_quality import load, validate_review, validate_run, snapshot

WORKFLOW = Path(__file__).with_name('ocr_workflow.py')


def project_environment(work, path=None):
    try:
        manifest = load(work / 'input-manifest.json')
        native = verify_environment(path, manifest['ocr']['language'])
        if native.identity != manifest['environment']:
            raise ValueError('Prepared environment differs from the selected environment')
        return native
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise ProjectError('environment_invalid', 'Verify the prepared native environment with doctor; export profile must match preparation.') from error


def workflow_command(work, native, command, *arguments, allowed=(0,)):
    vector = [sys.executable, str(WORKFLOW), '--environment', str(native.path),
              command, '--work', str(work), *map(str, arguments)]
    result = subprocess.run(vector, capture_output=True, text=True, env=native.env)
    with (work / 'export-process.log').open('a', encoding='utf-8') as log:
        log.write(json.dumps(vector, ensure_ascii=False) + '\n' + result.stdout + result.stderr + '\n')
    if result.returncode not in allowed:
        raise ProjectError('export_failed', 'Export stage failed; inspect export-process.log.')
    return result.returncode


def export_project(registry, project_id, *, environment=None, reviewer_root=None):
    current = registry.get(project_id)
    work = registry.root / current['artifacts']['workspace']
    native = project_environment(work, environment)
    failure = None
    with registry.project_lock(project_id) as record:
        source = registry.root / record['artifacts']['source']
        if source_hash(source) != record['project']['source_sha256']:
            raise ProjectError('source_corrupt', 'Registered source differs from its content hash.')
        try:
            review = load(work / 'review.json')
            if review['source_sha256'] != record['project']['source_sha256']:
                raise ValueError('Review belongs to another registered source')
            validate_review(work, review)
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise ProjectError('review_invalid', 'Export requires a complete validated source-derived review.') from error
        previous_record = copy.deepcopy(record)
        record['project'].update(phase='exporting', operation_state='running', validation='not_run')
        atomic_json(registry.root / record['artifacts']['project'], record)
        try:
            export_iteration(registry, record, work, source, native, reviewer_root, previous_record)
        except (ProjectError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            failure = error if isinstance(error, ProjectError) else ProjectError('export_failed', 'Export failed; inspect export-error.json.')
            atomic_json(work / 'export-error.json', {'code': failure.code, 'diagnostic': str(error)})
            record['project'].update(phase='export_failed', operation_state='failed', validation='not_run')
            record['artifacts']['export_error'] = str((work / 'export-error.json').relative_to(registry.root))
    if failure:
        raise failure
    return registry.get(project_id)


def export_iteration(registry, record, work, source, native, reviewer_root, previous_record):
    project_id = record['project']['project_id']
    iteration = uuid.uuid4().hex
    pdf = registry.root / 'outputs' / f'{project_id}-{iteration}-ocr.pdf'
    txt = pdf.with_suffix('.txt')
    if pdf.exists() or txt.exists():
        raise ProjectError('output_collision', 'New iteration output already exists; preserve it and retry with a fresh iteration.')
    previous = snapshot(work) if (work / 'output-manifest.json').exists() else None
    if previous:
        atomic_json(previous / 'project.json', previous_record)
        archived = load(previous / 'snapshot.json')
        archived['artifacts']['project.json'] = {'sha256': source_hash(previous / 'project.json'), 'stored': True}
        atomic_json(previous / 'snapshot.json', archived)
    workflow_command(work, native, 'segment', '--review', work / 'review.json')
    workflow_command(work, native, 'sheets', '--lines', work / 'reviewed-lines.json')
    workflow_command(work, native, 'sample-sheets', '--samples', work / 'samples.json')
    export_args = ['--source', source, '--pages', work / 'pages.json', '--pdf', pdf, '--txt', txt]
    if previous:
        export_args.extend(['--previous-snapshot', previous])
    workflow_command(work, native, 'export', *export_args)
    manifest = load(work / 'output-manifest.json')
    manifest.update(project_id=project_id, run_id=record['project']['run_id'], iteration_id=iteration,
                    review_sha256=source_hash(work / 'review.json'))
    atomic_json(work / 'output-manifest.json', manifest)
    check_args = ['--source', source, '--pages', work / 'exported-pages.json', '--pdf', pdf, '--txt', txt]
    if reviewer_root is not None:
        check_args.extend(['--reviewer-root', reviewer_root])
    technical_code = workflow_command(work, native, 'check', *check_args, allowed=(0, 1))
    samples_code = workflow_command(work, native, 'samples', '--pdf', pdf, '--samples', work / 'samples.json', allowed=(0, 1))
    workflow_command(work, native, 'reports', *(['--reset'] if previous else []))
    record['project'].update(phase='exported', operation_state='completed', validation='not_run', iteration_id=iteration,
                             review_sha256=manifest['review_sha256'], acceptance='not_recorded')
    record.pop('coverage', None)
    for key in ['errors', 'open_items']:
        record['counts'].pop(key, None)
    record['artifacts'].update(output_pdf=str(pdf.relative_to(registry.root)), output_txt=str(txt.relative_to(registry.root)),
                               output_manifest=str((work / 'output-manifest.json').relative_to(registry.root)),
                               export_log=str((work / 'export-process.log').relative_to(registry.root)))
    record['counts'].update(technical_check_exit=technical_code, sample_check_exit=samples_code,
                            export_iterations=len(list((work / 'iterations').glob('*/snapshot.json'))) + 1)
    if previous:
        record['artifacts']['previous_iteration'] = str(previous.relative_to(registry.root))


def validate_project(registry, project_id, *, environment=None):
    current = registry.get(project_id)
    work = registry.root / current['artifacts']['workspace']
    project_environment(work, environment)
    with registry.project_lock(project_id) as record:
        with contextlib.redirect_stdout(io.StringIO()):
            code = validate_run(SimpleNamespace(work=work))
        report = load(work / 'checks/run-validation.json')
        try:
            manifest = load(work / 'output-manifest.json')
            bound = (all(manifest.get(key) == record['project'].get(key) for key in ['project_id', 'run_id', 'iteration_id']) and
                     all(Path(manifest[key]).resolve() == (registry.root / record['artifacts'][artifact]).resolve()
                         for key, artifact in [('source', 'source'), ('pdf', 'output_pdf'), ('txt', 'output_txt')]) and
                     manifest.get('review_sha256') == record['project'].get('review_sha256') == source_hash(work / 'review.json'))
        except (ValueError, OSError, KeyError, TypeError):
            bound = False
        report['project_binding_valid'] = bound
        if not bound:
            code = 1
            report['status'] = 'failed'
            report['errors'].append('project_output_binding')
            summary = (work / 'checks/run-summary.md').read_text(encoding='utf-8').splitlines()
            summary[0] = 'OCR validation: failed'
            summary = [f'Errors: {len(report["errors"])}; open items: {len(report["open_items"])}'
                       if line.startswith('Errors: ') else line for line in summary]
            summary.append('- project_output_binding')
            (work / 'checks/run-summary.md').write_text('\n'.join(summary), encoding='utf-8')
        atomic_json(work / 'checks/run-validation.json', report)
        record['project'].update(phase='validation_failed' if code == 1 else 'validated',
                                 operation_state='completed', validation=report['status'])
        record['counts'].update(errors=len(report['errors']), open_items=len(report['open_items']))
        record['coverage'] = {'ui_clipboard': {'status': report['ui_clipboard']['status'],
                                              'tested_cases': len(report['ui_clipboard']['tested_cases'])},
                              'reviewer': {'status': report['reviewer_integration']['status'],
                                           'tested_pages': len(report['reviewer_integration']['tested_pages'])},
                              'extractor_framing': {'differences': len(report['extractor_framing'])}}
        record['artifacts'].update(validation_report=str((work / 'checks/run-validation.json').relative_to(registry.root)),
                                   validation_summary=str((work / 'checks/run-summary.md').relative_to(registry.root)))
    return registry.get(project_id), code
