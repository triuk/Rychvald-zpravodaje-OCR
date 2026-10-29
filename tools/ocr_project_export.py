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
        if path is not None:
            from ocr_installed_resources import selected_environment
            path = selected_environment(work, path)
        native = verify_environment(path, manifest['ocr']['language'])
        if native.identity != manifest['environment']:
            raise ValueError('Prepared environment differs from the selected environment')
        return native
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise ProjectError('environment_invalid', 'Verify the prepared native environment with doctor; export profile must match preparation.') from error


def workflow_command(work, native, command, *arguments, allowed=(0,)):
    from ocr_local_history import active_trace, child_environment
    vector = [sys.executable, str(WORKFLOW), '--environment', str(native.path),
              command, '--work', str(work), *map(str, arguments)]
    trace = active_trace()
    outputs = {'segment': ['pages.json', 'reviewed-lines.json', 'geometry.json', 'segmented-review.json'],
               'sheets': ['checks/geometry-sheets.json'], 'sample-sheets': ['checks/sample-source.json'],
               'export': ['output-manifest.json'], 'check': ['checks/technical.json'],
               'samples': ['checks/samples.json'], 'reports': ['checks/visual-review.json', 'checks/findings.json']}
    products = [work / p for p in outputs.get(command, [])]
    if command == 'export':
        for index, argument in enumerate(arguments[:-1]):
            if str(argument) in ('--pdf', '--txt'):
                products.append(Path(arguments[index + 1]))
    context = trace.span(operation=command, command=vector, scope='workflow_command',
                         tool={'name': 'ocr_workflow', 'version': sys.version.split()[0]},
                         outputs=products) if trace else contextlib.nullcontext({})
    with context as observation:
        result = subprocess.run(vector, capture_output=True, text=True, env=child_environment(native.env))
        observation.update(returncode=result.returncode, state='completed' if result.returncode in allowed else 'failed',
                           error={'code': 'workflow_failed', 'message': result.stderr} if result.returncode not in allowed else None)
    with (work / 'export-process.log').open('a', encoding='utf-8') as log:
        log.write(json.dumps(vector, ensure_ascii=False) + '\n' + result.stdout + result.stderr + '\n')
    if result.returncode not in allowed:
        raise ProjectError('export_failed', 'Export stage failed; inspect export-process.log.')
    return result.returncode


def export_project(registry, project_id, *, environment=None, reviewer_root=None, geometry_checkpoint=None, previous_snapshot=None, _render_only=False):
    current = registry.get(project_id)
    work = registry.root / current['artifacts']['workspace']
    native = project_environment(work, environment)
    failure = None
    with registry.project_lock(project_id) as record:
        examined = None
        if geometry_checkpoint is not None:
            from ocr_project_geometry import verify_geometry
            examined = verify_geometry(registry, record)
            if examined.get('correction_scope'):
                from ocr_project_corrections import historical_geometry_observations
                if load(work / 'geometry-checkpoint.json').get('correction_scope') != examined['correction_scope']:
                    raise ProjectError('geometry_invalid', 'Correction examination scope changed before export.')
                historical_geometry_observations(work, examined)
            try:
                if source_hash(geometry_checkpoint) != source_hash(work / 'geometry-checkpoint.json'):
                    raise ValueError('Selected checkpoint differs from the examined geometry')
            except (OSError, ValueError) as error:
                raise ProjectError('geometry_invalid', str(error)) from error
            examined = {'checkpoint_sha256': source_hash(work / 'geometry-checkpoint.json'),
                        'preparation_sha256': source_hash(work / 'geometry-preparation.json'),
                        'source_samples_sha256': source_hash(work / 'geometry-source-samples.json')}
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
            export_iteration(registry, record, work, source, native, reviewer_root, previous_record, examined, previous_snapshot,
                render_only=_render_only)
        except (ProjectError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            failure = error if isinstance(error, ProjectError) else ProjectError('export_failed', 'Export failed; inspect export-error.json.')
            atomic_json(work / 'export-error.json', {'code': failure.code, 'diagnostic': str(error)})
            record['project'].update(phase='export_failed', operation_state='failed', validation='not_run')
            record['artifacts']['export_error'] = str((work / 'export-error.json').relative_to(registry.root))
    if failure:
        raise failure
    return registry.get(project_id)


def export_iteration(registry, record, work, source, native, reviewer_root, previous_record, examined=None, previous_snapshot=None, *, render_only=False):
    project_id = record['project']['project_id']
    scope = load(work / 'geometry-preparation.json').get('correction_scope') if examined else None
    if scope:
        from ocr_correction_export import reserve_locked
        intent = reserve_locked(registry, record, work, scope['cycle_id'])
        iteration = intent['iteration_id']
    else:
        iteration = uuid.uuid4().hex
    pdf = registry.root / 'outputs' / f'{project_id}-{iteration}-ocr.pdf'
    txt = pdf.with_suffix('.txt')
    if not scope and (pdf.exists() or txt.exists()):
        raise ProjectError('output_collision', 'New iteration output already exists; preserve it and retry with a fresh iteration.')
    previous = snapshot(work) if previous_snapshot is None and (work / 'output-manifest.json').exists() else previous_snapshot
    if previous_snapshot is not None:
        previous = Path(previous_snapshot).resolve()
        if (not previous.is_relative_to((work / 'iterations').resolve()) or
                (not scope and (previous / 'output-manifest.json').read_bytes() != (work / 'output-manifest.json').read_bytes())):
            raise ProjectError('snapshot_invalid', 'Select the unchanged snapshot of the previous export.')
        if scope and previous != (work / scope['previous_snapshot']).resolve():
            raise ProjectError('snapshot_invalid', 'Select the exact reserved correction ancestor.')
        for name, item in load(previous / 'snapshot.json')['artifacts'].items():
            if item['stored'] and source_hash(previous / name) != item['sha256']:
                raise ProjectError('snapshot_invalid', 'Previous iteration snapshot changed.')
    if previous and previous_snapshot is None:
        atomic_json(previous / 'project.json', previous_record)
        archived = load(previous / 'snapshot.json')
        archived['artifacts']['project.json'] = {'sha256': source_hash(previous / 'project.json'), 'stored': True}
        atomic_json(previous / 'snapshot.json', archived)
    if examined is None:
        workflow_command(work, native, 'segment', '--review', work / 'review.json')
        workflow_command(work, native, 'sheets', '--lines', work / 'reviewed-lines.json')
        workflow_command(work, native, 'sample-sheets', '--samples', work / 'samples.json')
    export_args = ['--source', source, '--pages', work / 'pages.json', '--pdf', pdf, '--txt', txt]
    if previous:
        export_args.extend(['--previous-snapshot', previous])
    if scope:
        from ocr_correction_export import render_locked, commit_artifacts
        manifest = render_locked(registry, record, work, intent, native, examined, previous)
        if render_only:
            record['project'].update(phase='correction_export_rendered', operation_state='completed', validation='not_run')
            return
        manifest = commit_artifacts(work, intent, manifest)
    else:
        workflow_command(work, native, 'export', *export_args)
        manifest = load(work / 'output-manifest.json')
    manifest.update(project_id=project_id, run_id=record['project']['run_id'], iteration_id=iteration,
                    review_sha256=source_hash(work / 'review.json'))
    if examined is not None:
        manifest['examined_geometry'] = examined
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
    if scope:
        from ocr_project_corrections import cycle_record, ledger_path
        ledger, cycle, _ = cycle_record(work, scope['cycle_id'])
        if cycle['review_sha256'] != manifest['review_sha256'] or scope['previous_snapshot'] != cycle['previous_snapshot']:
            raise ProjectError('correction_invalid', 'Export differs from the reserved correction input.')
        cycle.update(phase='exported', exported_iteration_id=iteration,
            exported_manifest_sha256=source_hash(work / 'output-manifest.json'))
        atomic_json(ledger_path(work), ledger)


def validate_project(registry, project_id, *, environment=None):
    current = registry.get(project_id)
    work = registry.root / current['artifacts']['workspace']
    project_environment(work, environment)
    with registry.project_lock(project_id) as record:
        with contextlib.redirect_stdout(io.StringIO()):
            code = validate_run(SimpleNamespace(work=work))
        report = load(work / 'checks/run-validation.json')
        visual_provenance = True
        if load(work / 'output-manifest.json').get('examined_geometry'):
            try:
                from ocr_project_output_review import verify_output_review
                verify_output_review(registry, project_id)
            except ProjectError:
                visual_provenance = False
        try:
            manifest = load(work / 'output-manifest.json')
            bound = (all(manifest.get(key) == record['project'].get(key) for key in ['project_id', 'run_id', 'iteration_id']) and
                     all(Path(manifest[key]).resolve() == (registry.root / record['artifacts'][artifact]).resolve()
                         for key, artifact in [('source', 'source'), ('pdf', 'output_pdf'), ('txt', 'output_txt')]) and
                     manifest.get('review_sha256') == record['project'].get('review_sha256') == source_hash(work / 'review.json'))
        except (ValueError, OSError, KeyError, TypeError):
            bound = False
        report['project_binding_valid'] = bound
        if not bound or not visual_provenance:
            code = 1
            report['status'] = 'failed'
            reason = 'project_output_binding' if not bound else 'output_review_provenance'
            report['errors'].append(reason)
            summary = (work / 'checks/run-summary.md').read_text(encoding='utf-8').splitlines()
            summary[0] = 'OCR validation: failed'
            summary = [f'Errors: {len(report["errors"])}; open items: {len(report["open_items"])}'
                       if line.startswith('Errors: ') else line for line in summary]
            summary.append('- ' + reason)
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
