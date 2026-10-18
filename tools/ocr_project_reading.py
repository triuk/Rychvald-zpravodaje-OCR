"""Candidate-only inputs and atomic first-review publication for visual reading."""
from pathlib import Path
from ocr_projects import ProjectError, atomic_json, source_hash
from ocr_quality import load, validate_review


def verified_pages(work, source_sha256):
    manifest = load(work / 'input-manifest.json')
    if manifest['source_sha256'] != source_sha256 or not manifest['pages']:
        raise ValueError('Prepared source identity differs')
    pages = []
    for index, page in enumerate(manifest['pages'], 1):
        path = work / 'raster' / f'page-{index}.png'
        if page['page'] != index or source_hash(path) != page['raster_sha256']:
            raise ValueError('Prepared source raster differs')
        pages.append({'page': index, 'path': str(path), 'sha256': page['raster_sha256'],
                      'raster_size': page['raster_size']})
    return pages


def reading_input(registry, project_id):
    with registry.project_lock(project_id) as record:
        work = registry.root / record['artifacts']['workspace']
        try:
            if source_hash(registry.root / record['artifacts']['source']) != record['project']['source_sha256']:
                raise ValueError('Registered source differs')
            pages = verified_pages(work, record['project']['source_sha256'])
            if not (work / 'local-candidates.json').exists():
                fresh = load(work / 'fresh-lines.json')
                atomic_json(work / 'local-candidates.json', [
                    {'id': f"page-{p['page']}", 'page': p['page'],
                     'lines': [line for line in fresh if line['page'] == p['page']]}
                    for p in pages])
            lines = [dict(id=line['id'], candidate_id=line['id'], page=line['page'],
                          text=line['text'], selection_region=line.get('ocr_bbox', [0, 0, 1, 1]),
                          source_crop=f"raster/page-{line['page']}.png", text_status='candidate',
                          decision_basis='Unconfirmed local OCR candidate')
                     for region in load(work / 'local-candidates.json') for line in region['lines']]
            draft = {'source_sha256': record['project']['source_sha256'], 'lines': lines, 'units': [],
                     'dropped_candidates': [], 'unresolved': [], 'publisher_errors': [], 'risk_register': []}
            atomic_json(work / 'reading-draft.json', draft)
            atomic_json(work / 'reading-input.json', {'schema_version': 1, 'pages': pages,
                        'source_sha256': draft['source_sha256'], 'candidate_sha256': source_hash(work / 'local-candidates.json'),
                        'expected_review_sha256': source_hash(work / 'review.json') if (work / 'review.json').exists() else None})
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ProjectError('reading_input_invalid', 'Verified prepared source inputs are required.') from error
        record['artifacts'].update(reading_draft=str((work / 'reading-draft.json').relative_to(registry.root)),
                                   reading_input=str((work / 'reading-input.json').relative_to(registry.root)))
        record['counts'].update(pages=len(pages), candidate_lines=len(lines))
    return registry.get(project_id)


def publish_reading(registry, project_id, proposal_path):
    """Validate the complete candidate accounting before one atomic review write.

    This native operation validates the data contract. The AI adapter additionally
    verifies coverage and proposal bytes against its original completed turns.
    """
    with registry.project_lock(project_id) as record:
        work = registry.root / record['artifacts']['workspace']
        review_path = work / 'review.json'
        try:
            packet = load(work / 'reading-input.json')
            proposal = load(proposal_path)
            current = source_hash(review_path) if review_path.exists() else None
            if current != proposal['expected_review_sha256'] or current != packet['expected_review_sha256']:
                raise ProjectError('reading_review_changed', 'Review changed while AI reading was in progress; nothing published.')
            pages = verified_pages(work, record['project']['source_sha256'])
            if pages != packet['pages'] or source_hash(work / 'local-candidates.json') != packet['candidate_sha256']:
                raise ValueError('Reading input changed')
            coverage, review = proposal['coverage'], proposal['review']
            if not coverage['source_turn_id'] or len(coverage['source_answer_sha256']) != 64:
                raise ValueError('Original source turn evidence required')
            if len(coverage['pages']) != len(pages):
                raise ValueError('Incomplete source-page reading')
            lines = {line['id']: line for line in review['lines']}
            observed = []
            for expected, actual in zip(pages, coverage['pages']):
                if actual['page'] != expected['page'] or actual['sha256'] != expected['sha256']:
                    raise ValueError('Source-page coverage differs')
                if not actual['line_ids'] and not actual.get('blank_reason'):
                    raise ValueError('Empty page needs a visual explanation')
                if any(key not in lines or lines[key]['page'] != expected['page'] for key in actual['line_ids']):
                    raise ValueError('Wrong-page source lines')
                observed.extend(actual['line_ids'])
            if len(observed) != len(set(observed)) or set(observed) != set(lines):
                raise ValueError('Source inventory differs from complete review')
            summary = validate_review(work, review)
        except ProjectError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ProjectError('reading_proposal_invalid', 'Complete source coverage and a valid whole-document review are required; nothing published.') from error
        if review_path.exists():
            history = work / 'review-history' / (current + '.json')
            history.parent.mkdir(exist_ok=True)
            if not history.exists():
                history.write_bytes(review_path.read_bytes())
        atomic_json(review_path, review)
        atomic_json(work / 'reading-publication.json', {'schema_version': 1,
                    'review_sha256': source_hash(review_path), 'proposal_sha256': source_hash(proposal_path),
                    'coverage': coverage})
        record['project'].update(phase='visually_read', operation_state='completed', validation='not_run',
                                 review_sha256=source_hash(review_path))
        record['counts'].update(summary)
        record['artifacts'].update(review=str(review_path.relative_to(registry.root)),
                                   reading_publication=str((work / 'reading-publication.json').relative_to(registry.root)))
    return registry.get(project_id)
