"""Bind visual conclusions to actual exported pixels and original model JSON.

Generation and automatic check code stay unchanged. This adapter publishes the
two human-readable reports only after the complete export snapshot passes CAS.
"""
import copy
from pathlib import Path
import uuid

from ocr_projects import ProjectError, atomic_json, source_hash
from ocr_quality import load, check_bindings, check_installed_bindings


def bound(path):
    return {'path': str(Path(path).resolve()), 'sha256': source_hash(path)}


def output_identity(record, work):
    manifest = load(work / 'output-manifest.json')
    keys = ('project_id', 'run_id', 'iteration_id', 'source_sha256', 'review_sha256')
    identity = {key: manifest[key] for key in keys}
    if any(identity[key] != record['project'][key] for key in keys):
        raise ValueError('Current output belongs to another run/review/iteration')
    identity.update(pdf_sha256=manifest['pdf_sha256'], txt_sha256=source_hash(manifest['txt']))
    for key in ('source', 'pdf', 'txt'):
        if source_hash(manifest[key]) != identity[key + '_sha256']:
            raise ValueError('Current output/source bytes changed')
    if source_hash(work / 'review.json') != identity['review_sha256']:
        raise ValueError('Current review differs from the exported transcript')
    check_installed_bindings(work, manifest['inputs'])
    return identity


def prepare_output_review(registry, project_id, *, environment=None):
    try:
        with registry.project_lock(project_id) as record:
            work = registry.root / record['artifacts']['workspace']
            identity = output_identity(record, work)
            from ocr_project_export import project_environment
            native = project_environment(work, environment)
            technical = load(work / 'checks/technical.json')
            samples = load(work / 'checks/geometry-samples.json')
            check_installed_bindings(work, technical['inputs'])
            check_installed_bindings(work, samples['inputs'])
            if (technical['source_sha256'] != identity['source_sha256'] or
                    technical['output_sha256'] != identity['pdf_sha256'] or
                    samples['inputs']['pdf']['sha256'] != identity['pdf_sha256']):
                raise ValueError('Automatic checks belong to another PDF')
            manifest = load(work / 'output-manifest.json')
            prepared = load(work / 'input-manifest.json')
            pages = [p['page'] for p in prepared['pages']]
            if not pages:
                raise ValueError('Actual final PDF render coverage is incomplete')
            # The legacy technical report does not hash its render files. Render
            # current source/PDF bytes again under the verified native runtime;
            # never bless an existing glob as evidence of this PDF's pixels.
            import fitz
            names = []
            with fitz.open(manifest['source']) as source, fitz.open(manifest['pdf']) as final:
                if len(source) != len(final) or len(final) != len(pages):
                    raise ValueError('Exported page coverage differs')
                for number in pages:
                    for kind, document in (('source', source), ('final', final)):
                        name = f'checks/{kind}-page-{number}.png'
                        document[number - 1].get_pixmap(dpi=150).save(work / name)
                        names.append(name)
                        prefix = work / f'checks/output-review-poppler-{kind}-{number}'
                        result = native.run(['pdftoppm', '-f', str(number), '-l', str(number),
                            '-singlefile', '-r', '150', '-png', manifest['source' if kind == 'source' else 'pdf'], str(prefix)])
                        if result.returncode:
                            raise ValueError('Native Poppler rendering failed')
                        names.append(str(prefix.with_suffix('.png').relative_to(work)))
            for page in prepared['pages']:
                name = f"raster/page-{page['page']}.png"
                if source_hash(work / name) != page['raster_sha256']:
                    raise ValueError('Original source raster changed')
                names.append(name)
            inputs = {name: bound(work / name) for name in
                ('output-manifest.json', 'review.json', 'checks/technical.json', 'checks/geometry-samples.json',
                 'checks/visual-review.json', 'checks/findings.json', 'samples.json')}
            preparation_id = uuid.uuid4().hex
            frozen = work / 'output-review-inputs' / preparation_id
            frozen.mkdir(parents=True)
            compare_and_swap = {}
            for name in ('checks/visual-review.json', 'checks/findings.json'):
                compare_and_swap[name] = inputs[name]
                target = frozen / Path(name).name
                target.write_bytes((work / name).read_bytes())
                inputs[name] = bound(target)
            for name in ('geometry-checkpoint.json', 'geometry-preparation.json', 'geometry-source-samples.json'):
                if (work / name).exists():
                    inputs[name] = bound(work / name)
            findings = load(work / 'checks/findings.json')
            protected = []
            historical_risks = []
            if (work / 'geometry-checkpoint.json').exists():
                from ocr_project_geometry import verify_geometry
                geometry = verify_geometry(registry, record)
                for image in geometry['images']:
                    names.append(image['path'])
                checkpoint = load(work / 'geometry-checkpoint.json')
                observations = load(checkpoint['evidence']['proposal']['path'])
                if geometry.get('correction_scope'):
                    from ocr_project_corrections import historical_geometry_observations
                    historical = historical_geometry_observations(work, geometry)
                    for (kind, identifier), original in historical.items():
                        row = original['observation']
                        if row['status'] == 'open':
                            protected.append({'id': f'geometry/observed/{kind}/{identifier}', 'status': 'open',
                                'reason': row['reason'], 'evidence': original['evidence_aliases']})
                for kind in ('lines', 'samples'):
                    for row in observations[kind]:
                        if row['status'] == 'open':
                            protected.append({'id': f"geometry/observed/{kind}/{row['id']}", 'status': 'open',
                                'reason': row['reason'], 'evidence': row['evidence']})
                # Narrative risks also describe the historical pre-export phase.
                # Preserve those exact statements without converting e.g. "PDF
                # validation has not run" into a permanent current defect.
                historical_risks = observations.get('remaining_risks', [])
            review = load(work / 'review.json')
            for row in review.get('unresolved', []):
                if row.get('status') != 'resolved':
                    protected.append({'id': 'source/unresolved/' + row['id'], 'status': 'open',
                        'reason': row['reason'], 'evidence': [row['source_crop']]})
            original_ids = {row['id'] for row in findings['items']}
            findings['items'].extend(row for row in protected if row['id'] not in original_ids)
            names = sorted(set(names))
            for name in names:
                if not (work / name).resolve().is_relative_to(work.resolve()):
                    raise ValueError('Diagnostic image escapes current workspace')
            images = [{'path': name, 'sha256': source_hash(work / name)} for name in names]
            packet = {'schema_version': 1, 'identity': identity, 'inputs': inputs, 'pages': pages,
                'compare_and_swap': compare_and_swap,
                'preparation_artifact': str((frozen / 'preparation.json').relative_to(work)),
                'images': images, 'technical': technical, 'samples': samples,
                'visual_review': load(work / 'checks/visual-review.json'),
                'findings': findings, 'protected_findings': protected,
                'historical_geometry_risks': historical_risks,
                'policy': 'Actual exported renders; completed turn alone is not visual verification. '
                          'Keep uncertain geometry and untested clipboard coverage open; acceptance is a separate user decision.'}
            atomic_json(frozen / 'preparation.json', packet)
            atomic_json(work / 'output-review-preparation.json', packet)
            record['artifacts']['output_review_preparation'] = str((work / 'output-review-preparation.json').relative_to(registry.root))
        return registry.get(project_id)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ProjectError('output_review_invalid', str(error)) from error


def verify_preparation(record, work, digest, preparation=None, *, publishing=True):
    path = Path(preparation) if preparation else work / 'output-review-preparation.json'
    if not path.resolve().is_relative_to(work.resolve()):
        raise ValueError('Output review preparation escapes the run workspace')
    if source_hash(path) != digest:
        raise ValueError('Output review preparation changed before publication')
    packet = load(path)
    if packet['identity'] != output_identity(record, work):
        raise ValueError('Output review belongs to another export')
    check_installed_bindings(work, packet['inputs'])
    if publishing:
        check_bindings(packet['compare_and_swap'])
    for image in packet['images']:
        path = (work / image['path']).resolve()
        if not path.is_relative_to(work.resolve()) or source_hash(path) != image['sha256']:
            raise ValueError('Examined output pixels changed')
    return packet


def verify_output_preparation(registry, project_id, digest, *, output_manifest_sha256=None):
    try:
        with registry.project_lock(project_id) as record:
            work = registry.root / record['artifacts']['workspace']
            if output_manifest_sha256 is not None and source_hash(work / 'output-manifest.json') != output_manifest_sha256:
                raise ValueError('Explicitly selected current export changed')
            packet = verify_preparation(record, work, digest)
            from ocr_project_export import project_environment
            project_environment(work)
            if 'geometry-checkpoint.json' in packet['inputs']:
                from ocr_project_geometry import verify_geometry
                verify_geometry(registry, record)
        return registry.get(project_id)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ProjectError('output_review_invalid', str(error)) from error


def validate_reports(work, packet, answer):
    from ocr_project_geometry import image_identity
    if sorted(image_identity(work, i) for i in answer['images_examined']) != sorted(
            image_identity(work, i) for i in packet['images']):
        raise ValueError('Model did not account for every attached output/source image')
    visual, findings = answer['visual_review'], answer['findings']
    for report in (visual, findings):
        if any(report.get(k) != packet['identity'][k] for k in ('source_sha256', 'pdf_sha256')):
            raise ValueError('Report belongs to another source/PDF')
    if (visual.get('review_sha256') != packet['identity']['review_sha256'] or
            not isinstance(visual.get('reviewer'), str) or not visual['reviewer'].strip() or
            sorted(visual.get('pages_reviewed', [])) != sorted(packet['pages']) or
            visual.get('geometry_status') not in ('visually_verified', 'approximation_requires_character_review') or
            not isinstance(visual.get('conclusion'), str) or not visual['conclusion'].strip()):
        raise ValueError('Visual report is an incomplete template')
    allowed = {(work / image['path']).resolve(): image['sha256'] for image in packet['images']}
    allowed.update({Path(item['path']).resolve(): item['sha256'] for item in packet['inputs'].values()})

    def evidence(row):
        if not isinstance(row.get('evidence'), list) or not row['evidence']:
            raise ValueError('Report evidence must identify examined, bound local artifacts')
        for name in row['evidence']:
            if type(name) is not str:
                raise ValueError('Evidence path must be text')
            path = (work / name).resolve()
            if (not path.is_relative_to(work.resolve()) or path not in allowed or
                    source_hash(path) != allowed[path]):
                raise ValueError('Report evidence must identify unchanged workspace-confined images or bound input paths')

    evidence(visual)
    old_ids = {row['id'] for row in packet['findings']['items']}
    rows = findings['items']
    if len({row['id'] for row in rows}) != len(rows) or not old_ids <= {row['id'] for row in rows}:
        raise ValueError('Finding coverage changed or contains duplicates')
    for row in rows:
        if row.get('status') not in ('open', 'resolved') or not isinstance(row.get('reason'), str) or not row['reason'].strip():
            raise ValueError('Each finding needs an honest disposition and specific reason')
        evidence(row)
    protected = {row['id']: row for row in packet.get('protected_findings', [])}
    baseline = packet['inputs'].get('geometry-preparation.json')
    if baseline and load(baseline['path']).get('geometry_status') != 'visually_verified':
        if visual['geometry_status'] != 'approximation_requires_character_review':
            raise ValueError('A whole-output review cannot upgrade the bound approximate character/cell geometry')
    if any(row['id'] in protected and row['status'] != 'open' for row in rows):
        raise ValueError('Unchanged source/geometry limitations require a validated correction, not a general page impression')
    if protected and visual['geometry_status'] == 'visually_verified':
        raise ValueError('An examined export with unchanged limitations remains approximate')
    if visual['geometry_status'] != 'visually_verified' and not any(
            row['id'] == 'geometry/approximation' and row['status'] == 'open' for row in rows):
        raise ValueError('Approximate geometry must remain an open finding')
    return copy.deepcopy(visual), copy.deepcopy(findings)


def publish_output_review(registry, project_id, proposal):
    try:
        value = load(proposal)
        with registry.project_lock(project_id) as record:
            work = registry.root / record['artifacts']['workspace']
            packet = verify_preparation(record, work, value['preparation_sha256'], value.get('preparation'))
            if 'geometry-checkpoint.json' in packet['inputs']:
                from ocr_project_geometry import verify_geometry
                verify_geometry(registry, record)
            check_installed_bindings(work, value['evidence'])
            from ocr_visual_evidence import verify_visual_turn
            answer = verify_visual_turn(value['visual_turn'], work, packet['images'], activity='final_check')
            if answer != load(value['evidence']['proposal']['path']) or answer['preparation_sha256'] != value['preparation_sha256']:
                raise ValueError('Reports differ from original completed assistant JSON')
            visual, findings = validate_reports(work, packet, answer)
            names = ('checks/visual-review.json', 'checks/findings.json', 'output-review-publication.json')
            before = {name: (work / name).read_bytes() if (work / name).exists() else None for name in names}
            publication = {**value, 'identity': packet['identity'],
                'original_proposal': bound(value['evidence']['proposal']['path']),
                'reports': {'visual_review': visual, 'findings': findings}}
            try:
                atomic_json(work / names[0], visual)
                atomic_json(work / names[1], findings)
                atomic_json(work / names[2], publication)
            except BaseException:
                for name, data in before.items():
                    if data is None:
                        (work / name).unlink(missing_ok=True)
                    else:
                        (work / name).write_bytes(data)
                raise
            record['project'].update(phase='output_examined', operation_state='completed', validation='not_run')
            record['artifacts'].update(visual_review=str((work / names[0]).relative_to(registry.root)),
                findings=str((work / names[1]).relative_to(registry.root)),
                output_review_publication=str((work / names[2]).relative_to(registry.root)))
        return registry.get(project_id)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        raise ProjectError('output_review_invalid', str(error)) from error


def verify_output_review(registry, project_id):
    try:
        record = registry.get(project_id)
        work = registry.root / record['artifacts']['workspace']
        value = load(work / 'output-review-publication.json')
        packet = verify_preparation(record, work, value['preparation_sha256'], value['preparation'], publishing=False)
        if 'geometry-checkpoint.json' in packet['inputs']:
            from ocr_project_geometry import verify_geometry
            verify_geometry(registry, record)
        check_installed_bindings(work, value['evidence'])
        from ocr_visual_evidence import verify_visual_turn
        answer = verify_visual_turn(value['visual_turn'], work, packet['images'], activity='final_check')
        if answer != load(value['evidence']['proposal']['path']) or answer['preparation_sha256'] != value['preparation_sha256']:
            raise ValueError('Published reports differ from the original assistant JSON')
        visual, findings = validate_reports(work, packet, answer)
        if (load(work / 'checks/visual-review.json') != visual or load(work / 'checks/findings.json') != findings or
                value['reports'] != {'visual_review': visual, 'findings': findings}):
            raise ValueError('Published report bytes/contents changed')
        return record
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        raise ProjectError('output_review_invalid', str(error)) from error
