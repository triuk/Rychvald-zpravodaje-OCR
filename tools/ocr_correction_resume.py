"""Read-only verification of a reserved correction and its immutable ancestors."""
from pathlib import Path

from ocr_projects import ProjectError, source_hash
from ocr_quality import load, load_bound, check_bindings, patched_review
from ocr_project_corrections import checked, cycle_record, ledger_path
from ocr_visual_evidence import verify_visual_turn
from ocr_correction_graph import output_child


def archived_bindings(work, archive, records):
    """A historical pathname resolves only to its independently recorded SHA."""
    inventory = load(archive / 'snapshot.json')['artifacts']
    selected = {}
    for key, item in records.items():
        path = Path(item['path']).resolve()
        if path.is_relative_to(work):
            name = str(path.relative_to(work))
            old = inventory.get(name)
            if old and old['stored'] and old['sha256'] == item['sha256']:
                path = archive / name
        selected[key] = {**item, 'path': str(path)}
    check_bindings(selected, historical=True)


def verify_archive(work, archive, record):
    if not archive.is_relative_to(work / 'iterations'):
        raise ValueError('Correction ancestor escaped its run')
    inventory = load(archive / 'snapshot.json')['artifacts']
    for name, item in inventory.items():
        path = (archive / name).resolve() if item['stored'] else (work / name).resolve()
        if not path.is_relative_to(archive if item['stored'] else work) or source_hash(path) != item['sha256']:
            raise ValueError('Correction ancestor changed: ' + name)
    manifest = load(archive / 'output-manifest.json')
    for key in ('project_id', 'run_id', 'source_sha256'):
        if manifest[key] != record['project'][key]:
            raise ValueError('Correction ancestor belongs to another source/run')
    for key in ('source', 'pdf', 'txt'):
        if source_hash(manifest[key]) != manifest[key + '_sha256']:
            raise ValueError('Original exported bytes changed: ' + key)
    archived_bindings(work, archive, manifest['inputs'])
    for packet_name, proof_name in (('geometry-preparation.json', 'geometry-checkpoint.json'),
            ('output-review-preparation.json', 'output-review-publication.json')):
        packet, proof = load(archive / packet_name), load(archive / proof_name)
        if proof['preparation_sha256'] != source_hash(archive / packet_name) or proof['identity'] != packet['identity']:
            raise ValueError('Original examination preparation changed')
        for key in ('project_id', 'run_id', 'source_sha256', 'review_sha256'):
            if packet['identity'][key] != manifest[key]:
                raise ValueError('Original examination source/iteration differs')
        archived_bindings(work, archive, packet['inputs'])
        archived_bindings(work, archive, proof['evidence'])
        answer = verify_visual_turn(proof['visual_turn'], work, packet['images'], archive=archive)
        proposal = proof['evidence']['proposal']
        if answer != load_bound(proposal):
            raise ValueError('Original examination differs from original assistant JSON')
    if source_hash(archive / 'samples.json') != source_hash(work / 'samples.json'):
        raise ValueError('Frozen export samples changed during correction')
    if source_hash(archive / 'geometry-source-samples.json') != source_hash(work / 'geometry-source-samples.json'):
        raise ValueError('Frozen source expectations changed during correction')


@checked
def verify(registry, run_id, attempt, ledger_sha256):
    record = registry.get(run_id)
    work = (registry.root / record['artifacts']['workspace']).resolve()
    if source_hash(ledger_path(work)) != ledger_sha256:
        raise ValueError('Correction ledger changed after reconciliation')
    ledger = load(ledger_path(work))
    if ledger['run_id'] != run_id or not 1 <= len(ledger['cycles']) <= 3:
        raise ValueError('Invalid correction budget/run')
    previous = None
    for index, saved in enumerate(ledger['cycles'], 1):
        _, cycle, packet = cycle_record(work, saved['cycle_id'])
        if cycle['index'] != index or cycle['parent_cycle_id'] != previous:
            raise ValueError('Correction cycle chain changed')
        previous = cycle['cycle_id']
        if cycle['state'] == 'reserved':
            if cycle.get('patch_intent'):
                from ocr_correction_patch import verify_intent
                _, pending_archive = verify_intent(registry, record, work, cycle, packet)
                record['artifacts']['correction_patch_snapshot'] = str(pending_archive.relative_to(registry.root))
            else:
                check_bindings(packet['inputs'])
        elif cycle.get('patch_intent') and source_hash(work / cycle['patch_intent']) != cycle['patch_intent_sha256']:
            raise ValueError('Original patch transaction changed')
        if cycle.get('previous_snapshot'):
            archive = (work / cycle['previous_snapshot']).resolve()
            verify_archive(work, archive, record)
            if load(archive / 'output-manifest.json')['iteration_id'] != cycle['source_iteration_id']:
                raise ValueError('Correction source iteration changed')
            publication = load(work / cycle['publication'])
            check_bindings(publication['evidence'])
            answer = verify_visual_turn(publication['visual_turn'], work, packet['images'], archive=archive)
            if answer != load(work / cycle['proposal']) or answer['patch'] != load(work / cycle['patch']):
                raise ValueError('Published correction differs from its original turn')
            if source_hash(work / cycle['patch']) != cycle['patch_sha256']:
                raise ValueError('Published correction patch changed')
            repaired = patched_review(load(archive / 'review.json'), answer['patch'])
            if index == len(ledger['cycles']) and (repaired != load(work / 'review.json') or
                    source_hash(work / 'review.json') != cycle['review_sha256']):
                raise ValueError('Current review differs from the committed correction')
    cycle = ledger['cycles'][-1]
    from ocr_correction_outcome import verify_all
    outcome_pending = verify_all(work, record, ledger['cycles'])
    child = load(work / cycle['attempt'])
    if cycle['attempt_id'] != attempt or child['attempt_id'] != attempt or child['run_id'] != run_id:
        raise ValueError('Reserved correction child cannot be replaced')
    parent_binding = child.get('parent_binding')
    if parent_binding:
        parent_id = parent_binding['parent_attempt_id']
        if len(parent_id) != 32 or any(c not in '0123456789abcdef' for c in parent_id):
            raise ValueError('Invalid original correction parent identity')
        parent = load(work / 'application/autonomous-attempts' / parent_id / 'attempt.json')
        rows = [row for row in parent['stages'] if row['stage'] == 'corrections' and row.get('intent_id') == parent_binding['intent_id']]
        if (parent['run_id'] != run_id or parent['root'] != str(registry.root) or len(rows) != 1 or
                rows[0].get('attempt_id') not in (None, attempt) or parent_binding['stage'] != 'corrections'):
            raise ValueError('Original correction parent/stage/intent changed')
    if cycle.get('export_intent'):
        from ocr_correction_export import verify_intent
        path = work / cycle['export_intent']
        if source_hash(path) != cycle['export_intent_sha256']:
            raise ValueError('Original export intent changed')
        verify_intent(registry, record, work, cycle, load(path))
    rendered = False
    if cycle.get('export_rendered'):
        from ocr_correction_export import verify_rendered
        path = work / cycle['export_rendered']
        if source_hash(path) != cycle['export_rendered_sha256']:
            raise ValueError('Original staged export changed')
        verify_rendered(registry, record, work, cycle, load(work / cycle['export_intent']), load(path))
        rendered = True
    prepared = load(work / 'geometry-preparation.json')
    geometry_prepared = prepared.get('correction_scope', {}).get('cycle_id') == cycle['cycle_id']
    geometry_published = False
    if geometry_prepared:
        from ocr_project_geometry import verify_geometry
        verify_geometry(registry, record, examined=False)
        checkpoint = load(work / 'geometry-checkpoint.json')
        if checkpoint.get('preparation_sha256') == source_hash(work / 'geometry-preparation.json'):
            from ocr_project_corrections import historical_geometry_observations
            verify_geometry(registry, record)
            historical_geometry_observations(work, prepared)
            geometry_published = True
    manifest = load(work / 'output-manifest.json')
    raw_render_pending = 'iteration_id' not in manifest
    if raw_render_pending:
        if not cycle.get('export_intent') or not geometry_published or record['project']['iteration_id'] != cycle['source_iteration_id']:
            raise ValueError('Uncommitted render has no exact reserved correction intent')
        from ocr_correction_export import normalize_native_render
        normalize_native_render(registry, record, work, cycle, load(work / cycle['export_intent']), manifest)
    exported = not raw_render_pending and manifest['iteration_id'] != cycle['source_iteration_id']
    if exported:
        if not geometry_published or not rendered:
            raise ValueError('Current export has no exact rendered correction proof')
        export_intent = load(work / cycle['export_intent'])
        expected = {**load(work / cycle['export_rendered']),
            'pdf': export_intent['pdf'], 'txt': export_intent['txt']}
        if manifest != expected or any(source_hash(manifest[key]) != manifest[key + '_sha256'] for key in ('pdf', 'txt')):
            raise ValueError('Current export differs from the exact reserved/rendered bytes')
        if 'exported_iteration_id' not in cycle and 'exported_manifest_sha256' not in cycle:
            if record['project']['iteration_id'] != cycle['source_iteration_id']:
                raise ValueError('Uncommitted correction export has another registry iteration')
            exported = False  # Finish only this reserved local commit, using its already rendered bytes.
        else:
            if (manifest['iteration_id'] != cycle.get('exported_iteration_id') or
                    source_hash(work / 'output-manifest.json') != cycle.get('exported_manifest_sha256')):
                raise ValueError('Current export is not the exact committed correction iteration')
            if record['project']['iteration_id'] == cycle['source_iteration_id'] and record['project']['phase'] in ('exporting', 'export_interrupted'):
                exported = False  # The ledger committed before its exact project transaction.
            else:
                from ocr_project_output_review import output_identity
                output_identity(record, work)
                if record['artifacts'].get('previous_iteration') != str((work / cycle['previous_snapshot']).relative_to(registry.root)):
                    raise ValueError('Current export has another correction ancestor')
    intent, output = output_child(work, child, cycle['cycle_id'])
    if intent is not None:
        if (not exported or intent['cycle_index'] != cycle['index'] or
                intent['iteration_id'] != cycle['exported_iteration_id'] or
                intent['output_manifest_sha256'] != source_hash(work / 'output-manifest.json')):
            raise ValueError('Original output-review intent belongs to another correction iteration')
        from ocr_project_output_review import verify_preparation
        verify_preparation(record, work, intent['preparation_sha256'], publishing=False)
        if output and output['profile_sha256'] != child['profile_sha256']:
            raise ValueError('Original output child has a different frozen profile')
    record.setdefault('counts', {}).update(correction_geometry_prepared=int(geometry_prepared),
        correction_geometry_published=int(geometry_published), correction_export_committed=int(exported),
        correction_export_rendered=int(rendered), correction_patch_pending=int(cycle['state'] == 'reserved' and bool(cycle.get('patch_intent'))),
        correction_outcome_pending=int(outcome_pending))
    return record
