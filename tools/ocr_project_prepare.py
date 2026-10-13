"""Preparation of registered source scans, with durable unit checkpoints."""
from pathlib import Path
from importlib.metadata import version
import concurrent.futures
import json
import sys

from ocr_environment import verify_environment
from ocr_projects import ProjectError, atomic_json, source_hash


def resume_project(registry, project_id, *, dpi=None, language=None, environment=None):
    record = registry.get(project_id)
    if record['project']['operation_state'] == 'running':
        raise ProjectError('project_busy', 'Another operation is active for this project.')
    work = registry.root / record['artifacts']['workspace']
    if not any((work / name).exists() for name in ('preparation-checkpoint.json', 'preparation-identity.json', 'input-manifest.json')):
        raise ProjectError('resume_unavailable', 'Preparation has not started; use prepare for the first pass.')
    saved = saved_preparation(work)
    identity = saved.get('identity', {})
    if not valid_identity(identity):
        raise ProjectError('checkpoint_invalid', 'Saved preparation identity is unavailable; import an explicit new run and preserve this workspace.')
    if (dpi is not None and dpi != identity['dpi']) or (language is not None and language != identity['language']):
        raise ProjectError('configuration_changed', 'Resume parameters differ from the original preparation; import an explicit new run.')
    return prepare_project(registry, project_id, dpi=identity['dpi'], language=identity['language'],
                           environment=environment or saved.get('environment_manifest'), resume=True)


def valid_identity(identity):
    return (isinstance(identity, dict) and type(identity.get('dpi')) is int and identity['dpi'] > 0
            and isinstance(identity.get('language'), str) and bool(identity['language'])
            and isinstance(identity.get('source_sha256'), str) and len(identity['source_sha256']) == 64
            and identity.get('psm') == [3, 11] and identity.get('hocr_char_boxes') == 1
            and isinstance(identity.get('environment'), dict)
            and isinstance(identity['environment'].get('build_id'), str)
            and isinstance(identity['environment'].get('manifest_sha256'), str)
            and len(identity['environment']['manifest_sha256']) == 64)


def saved_preparation(work):
    """Recover identity independently of the mutable progress marker."""
    anchor = read_checkpoint(work / 'preparation-identity.json')
    progress = read_checkpoint(work / 'preparation-checkpoint.json')
    if valid_identity(anchor.get('identity')):
        if valid_identity(progress.get('identity')) and progress['identity'] != anchor['identity']:
            raise ProjectError('checkpoint_conflict', 'Saved preparation identities disagree; preserve this workspace and import an explicit new run.')
        return anchor
    if valid_identity(progress.get('identity')):
        return {'schema_version': 1, 'identity': progress['identity']}
    manifest = read_checkpoint(work / 'input-manifest.json')
    ocr = manifest.get('ocr', {})
    if not isinstance(ocr, dict):
        return {}
    identity = {'source_sha256': manifest.get('source_sha256'), 'dpi': manifest.get('dpi'),
                'language': ocr.get('language'), 'psm': ocr.get('psm'),
                'hocr_char_boxes': ocr.get('hocr_char_boxes'), 'environment': manifest.get('environment')}
    return {'schema_version': 1, 'identity': identity} if valid_identity(identity) else {}


def prepare_project(registry, project_id, *, dpi=300, language='ces', environment=None, resume=False):
    if dpi <= 0:
        raise ProjectError('invalid_parameters', 'DPI must be positive.')
    try:
        native = verify_environment(environment, language)
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise ProjectError('environment_invalid', 'Native environment verification failed; run doctor for diagnostics.') from error
    failure = None
    with registry.project_lock(project_id) as record:
        source = registry.root / record['artifacts']['source']
        work = registry.root / record['artifacts']['workspace']
        if source_hash(source) != record['project']['source_sha256']:
            raise ProjectError('source_corrupt', 'Registered source differs from its content hash.')
        preparation_phases = {'registered', 'prepared', 'preparation_failed', 'preparation_interrupted'}
        retained = {key: record['project'][key] for key in ('phase', 'validation', 'acceptance')}
        previous_state = read_checkpoint(work / 'preparation-checkpoint.json').get('previous_project_state')
        if (retained['phase'] in preparation_phases and isinstance(previous_state, dict)
                and all(isinstance(previous_state.get(key), str) for key in retained)
                and previous_state['phase'] not in preparation_phases):
            retained = previous_state
        try:
            counts = prepare_artifacts(source, work, dpi=dpi, language=language, native=native,
                                       resume=resume, retained_state=retained)
            if retained['phase'] in preparation_phases:
                record['project'].update(phase='prepared', validation='not_run')
            else:
                record['project'].update(retained)
            record['project']['operation_state'] = 'completed'
            record['counts'].update(counts)
            record['artifacts']['preparation_checkpoint'] = str((work / 'preparation-checkpoint.json').relative_to(registry.root))
            record['artifacts']['input_manifest'] = str((work / 'input-manifest.json').relative_to(registry.root))
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
            failure = ProjectError('prepare_failed', 'Preparation failed; consult preparation-error.log and resume explicitly.')
            record['project'].update(phase='preparation_failed', operation_state='failed', validation='not_run')
            marker = read_checkpoint(work / 'preparation-checkpoint.json')
            marker['status'] = 'failed'
            marker['previous_project_state'] = retained
            atomic_json(work / 'preparation-checkpoint.json', marker)
            (work / 'preparation-error.log').write_text(str(error), encoding='utf-8')
            record['artifacts']['preparation_error'] = str((work / 'preparation-error.log').relative_to(registry.root))
    if failure:
        raise failure
    return registry.get(project_id)


def prepare_artifacts(source, work, *, dpi, language, native, resume=False, retained_state=None):
    """Use preserved raster and hOCR algorithms; record each completed unit."""
    import fitz
    from PIL import Image
    from lxml import etree
    import ocr_workflow as workflow
    workflow.ENVIRONMENT = native
    workflow.etree = etree
    source, work = Path(source), Path(work)
    identity = {'source_sha256': source_hash(source), 'dpi': dpi, 'language': language,
                'psm': [3, 11], 'hocr_char_boxes': 1, 'environment': native.identity}
    checkpoint_path = work / 'preparation-checkpoint.json'
    anchor_path = work / 'preparation-identity.json'
    if checkpoint_path.exists() or anchor_path.exists():
        saved = saved_preparation(work)
        if not valid_identity(saved.get('identity')):
            raise ProjectError('checkpoint_invalid', 'Saved preparation identity is unavailable; import an explicit new run and preserve this workspace.')
        if saved['identity'].get('environment') != identity['environment']:
            raise ProjectError('environment_changed' if resume else 'configuration_changed', 'Preparation environment differs from the original run; use its saved manifest or import an explicit new run.')
        if saved['identity'] != identity:
            raise ProjectError('configuration_changed', 'Preparation source or parameters changed; import an explicit new run.')
        previous = read_checkpoint(checkpoint_path)
        if previous.get('status') != 'completed' and not resume:
            raise ProjectError('resume_required', 'Preparation was interrupted; use explicit resume.')
    with fitz.open(source) as document:
        if document.needs_pass:
            raise ProjectError('invalid_source', 'PDF requires a password; password handling is not implemented.')
        if not len(document):
            raise ProjectError('invalid_source', 'Source PDF has no pages.')
        for name in ['raster', 'ocr', 'crops', 'checks', 'construction', 'output/pdf', 'output/text']:
            (work / name).mkdir(parents=True, exist_ok=True)
        if not valid_identity(read_checkpoint(anchor_path).get('identity')):
            atomic_json(anchor_path, {'schema_version': 1, 'identity': identity,
                                      'environment_manifest': str(native.path)})
        atomic_json(checkpoint_path, {'schema_version': 1, 'status': 'running', 'identity': identity,
                                     'previous_project_state': retained_state})
        pages = []
        rasters_reused = 0
        for number, page in enumerate(document, 1):
            raster = work / 'raster' / f'page-{number}.png'
            overview = work / 'raster' / f'overview-{number}.png'
            raster_checkpoint = work / 'raster' / f'page-{number}-checkpoint.json'
            raster_identity = {'source_sha256': identity['source_sha256'], 'page': number, 'dpi': dpi,
                               'renderer': fitz.VersionBind,
                               'renderer_sha256': native.manifest['packages']['PyMuPDF']['tree_sha256']}
            source_geometry = {'page': number, 'rect': list(page.rect), 'mediabox': list(page.mediabox),
                               'cropbox': list(page.cropbox), 'rotation': page.rotation,
                               'existing_text_characters': len(page.get_text().strip())}
            saved = read_checkpoint(raster_checkpoint)
            reusable = (saved.get('status') == 'completed' and saved.get('identity') == raster_identity and
                    isinstance(saved.get('page'), dict) and
                    all(key in saved['page'] for key in ['page', 'rect', 'mediabox', 'cropbox', 'rotation',
                                                        'raster_size', 'raster_sha256', 'existing_text_characters']) and
                    valid_outputs(work, saved.get('outputs', {}), [raster, overview]) and
                    all(saved['page'][key] == value for key, value in source_geometry.items()) and
                    saved['page']['raster_sha256'] == saved['outputs'].get(str(raster.relative_to(work))))
            if reusable:
                with Image.open(raster) as image:
                    reusable = saved['page']['raster_size'] == list(image.size)
            if reusable:
                pages.append(saved['page'])
                rasters_reused += 1
                continue
            atomic_json(raster_checkpoint, {'schema_version': 1, 'status': 'running',
                                           'identity': raster_identity, 'outputs': {}})
            page.get_pixmap(dpi=dpi).save(raster)
            with Image.open(raster) as image:
                size = list(image.size)
                image.thumbnail((1250, 1800))
                image.save(overview)
            geometry = {**source_geometry, 'raster_size': size, 'raster_sha256': source_hash(raster)}
            atomic_json(raster_checkpoint,
                        {'schema_version': 1, 'status': 'completed',
                         'identity': raster_identity,
                         'outputs': {str(path.relative_to(work)): source_hash(path) for path in [raster, overview]},
                         'page': geometry})
            pages.append(geometry)
        tesseract = workflow.run(['tesseract', '--version']).stdout.splitlines()[0]
        manifest = {'source': str(source.resolve()), 'source_sha256': identity['source_sha256'],
                    'pages': pages, 'dpi': dpi, 'transform': 'none', 'content_inputs': 'source raster only',
                    'environment': native.identity,
                    'versions': {'Python': sys.version, 'PyMuPDF': fitz.VersionBind, 'Tesseract': tesseract,
                                 **{name: version(name) for name in ['Pillow', 'numpy', 'lxml', 'reportlab', 'fonttools']}},
                    'ocr': {'language': language, 'psm': [3, 11], 'hocr_char_boxes': 1}}
        if read_checkpoint(work / 'input-manifest.json') != manifest:
            atomic_json(work / 'input-manifest.json', manifest)

        def recognize(job):
            number, psm = job
            prefix = work / 'ocr' / f'page-{number}-psm{psm}'
            command = ['tesseract', str(work / 'raster' / f'page-{number}.png'), str(prefix),
                       '-l', language, '--psm', str(psm), '-c', 'hocr_char_boxes=1', 'hocr', 'tsv', 'txt', 'makebox']
            reused = workflow.recognize_cached(command, prefix, work / 'raster' / f'page-{number}.png',
                                              ['.hocr', '.tsv', '.txt', '.box'], tesseract)
            return {'page': number, 'psm': psm, 'command': native.command(command), 'cache_hit': reused}

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            commands = list(pool.map(recognize, [(number, psm) for number in range(1, len(pages) + 1) for psm in [3, 11]]))
        atomic_json(work / 'ocr-commands.json', commands)
        lines = []
        for number in range(1, len(pages) + 1):
            lines.extend(workflow.parse_hocr(work / 'ocr' / f'page-{number}-psm3.hocr', number, f'p{number}-full'))
        atomic_json(work / 'fresh-lines.json', lines)
        counts = {'pages': len(pages), 'rasters_computed': len(pages) - rasters_reused, 'rasters_reused': rasters_reused,
                  'ocr_computed': sum(not row['cache_hit'] for row in commands),
                  'ocr_reused': sum(row['cache_hit'] for row in commands), 'lines': len(lines)}
        atomic_json(checkpoint_path, {'schema_version': 1, 'status': 'completed', 'identity': identity,
                                     'previous_project_state': retained_state,
                                     'counts': counts, 'artifacts': {'manifest': 'input-manifest.json',
                                     'commands': 'ocr-commands.json', 'lines': 'fresh-lines.json'}})
        return counts


def read_checkpoint(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def valid_outputs(work, outputs, expected):
    return isinstance(outputs, dict) and bool(outputs) and all(path.is_file() and source_hash(path) == outputs.get(str(path.relative_to(work)))
                                 for path in expected)
