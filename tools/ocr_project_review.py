"""Selective project queries and validated review transactions (stdlib only)."""
import contextlib
import copy
import io
from pathlib import Path
from types import SimpleNamespace

from ocr_projects import (MAX_RESPONSE_BYTES, ProjectError, atomic_json, paginate_response,
                          response, response_size, source_hash)
from ocr_quality import load, patched_review, apply_line_patch, validate_review, save_review


def query_project(registry, project_id, view, *, page=None, ids=None, article=None,
                  offset=0, limit=10, text_bytes=256):
    try:
        return _query_project(registry, project_id, view, page=page, ids=ids, article=article,
                              offset=offset, limit=limit, text_bytes=text_bytes)
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError) as error:
        raise ProjectError('artifact_invalid', 'Query artifact has an invalid structure; inspect the stored file.') from error


def _query_project(registry, project_id, view, *, page=None, ids=None, article=None,
                   offset=0, limit=10, text_bytes=256):
    if offset < 0 or limit < 1 or not 0 <= text_bytes <= 512 or (page is not None and page < 1):
        raise ProjectError('invalid_selection', 'Use nonnegative offset, positive limit/page and text-bytes between 0 and 512.')
    record = registry.get(project_id)
    work = registry.root / record['artifacts']['workspace']
    if view not in ['transcript', 'candidates', 'findings', 'unresolved', 'publisher-errors', 'reconstructions', 'units']:
        raise ProjectError('invalid_selection', 'Unknown query view.')
    review = read_artifact(work / 'review.json') if (work / 'review.json').exists() else {}
    articles = {key: unit['article'] for unit in review.get('units', []) for key in unit['line_ids']}
    rows = []
    total = 0
    stale = stale_artifacts(work)
    for value, path, pointer, details in query_entries(work, view):
        total += 1
        number = value.get('page')
        if number is None and value.get('line'):
            number = next((line['page'] for line in review.get('lines', []) if line['id'] == value['line']), None)
        if page is not None and number != page:
            continue
        identifier = value.get('id', value.get('line'))
        if ids and identifier not in ids:
            continue
        if article is not None and value.get('article', articles.get(identifier)) != article:
            continue
        row = summarize(value, text_bytes)
        row.update(details)
        row['page'] = number
        row['artifact'] = {'path': str(path.relative_to(registry.root)), 'pointer': pointer}
        row['stale_for_current_review'] = str(path.relative_to(work)) in stale
        row['source'] = {'scan': record['artifacts']['source']}
        if number:
            row['source']['raster'] = str((work / 'raster' / f'page-{number}.png').relative_to(registry.root))
        if value.get('source_crop'):
            row['source']['crop'] = artifact_link(registry, work, value['source_crop'])
        if value.get('evidence'):
            row['source']['evidence'] = [artifact_link(registry, work, entry) for entry in value['evidence'][:5]]
        rows.append(row)
    record['counts'].update(total=total, matched=len(rows), returned=0)
    result = response('query', **record, view=view, rows=[], next_offset=None,
                      limits={'response_bytes': MAX_RESPONSE_BYTES, 'text_preview_bytes': text_bytes,
                              'requested_rows': limit})

    def prepare_row(row, result):
        if not result['rows'] and response_size({**result, 'rows': [row]}) > MAX_RESPONSE_BYTES - 64:
            keep = ['id', 'line', 'page', 'status', 'text_status', 'text', 'text_bytes',
                    'text_truncated', 'artifact', 'source', 'candidate_kind', 'variant', 'stale_for_current_review']
            omitted = [key for key in row if key not in keep]
            row = {key: row[key] for key in keep if key in row}
            row['omitted_fields'] = omitted
        return row

    return paginate_response(
        result, 'rows', rows, offset=offset, limit=limit, prepare_row=prepare_row,
        too_large='Selected record exceeds protocol budget; request a smaller text preview.')


def read_artifact(path):
    try:
        return load(path)
    except FileNotFoundError:
        raise ProjectError('artifact_missing', 'Query artifact is not available for this project.') from None
    except (ValueError, UnicodeError):
        raise ProjectError('artifact_invalid', 'Query artifact is not valid UTF-8 JSON.') from None


def artifact_link(registry, work, name):
    path = (work / name).resolve()
    if not path.is_relative_to(work.resolve()):
        raise ProjectError('artifact_invalid', 'Source evidence must stay inside the project workspace.')
    return str(path.relative_to(registry.root))


def query_entries(work, view):
    if view in ['transcript', 'units', 'unresolved', 'publisher-errors']:
        path = work / 'review.json'
        collection = {'transcript': 'lines', 'publisher-errors': 'publisher_errors'}.get(view, view)
        for index, value in enumerate(read_artifact(path).get(collection, [])):
            yield value, path, f'/{collection}/{index}', {}
    elif view == 'findings':
        path = work / 'checks/findings.json'
        for index, value in enumerate(read_artifact(path)['items']):
            yield value, path, f'/items/{index}', {}
    elif view == 'reconstructions':
        path = work / 'reconstructions.json'
        for index, value in enumerate(read_artifact(path)):
            yield value, path, f'/{index}', {}
    elif view == 'candidates':
        found = False
        for filename, kind in [('fresh-lines.json', 'full_page'), ('local-candidates.json', 'local'),
                               ('targeted-candidates.json', 'targeted')]:
            path = work / filename
            if not path.exists():
                continue
            found = True
            for index, value in enumerate(read_artifact(path)):
                if kind == 'local':
                    for line_index, line in enumerate(value['lines']):
                        yield line, path, f'/{index}/lines/{line_index}', {'candidate_kind': kind}
                else:
                    yield value, path, f'/{index}', {'candidate_kind': kind}
        path = work / 'ocr-commands.json'
        if path.exists():
            found = True
            for command in read_artifact(path):
                number, psm = command['page'], command['psm']
                text = work / 'ocr' / f'page-{number}-psm{psm}.txt'
                if text.is_file():
                    yield {'id': f'page-{number}-psm{psm}', 'page': number, 'text': text.read_text(encoding='utf-8')}, text, None, {'candidate_kind': 'pass', 'psm': psm}
        if not found:
            raise ProjectError('artifact_missing', 'OCR candidates are not available for this project.')


def summarize(value, text_bytes):
    keys = ['id', 'line', 'article', 'tag', 'text_status', 'status', 'variant', 'candidate_id',
            'region', 'selection_region', 'ocr_bbox', 'bbox', 'text', 'candidate', 'adopted',
            'reason', 'decision_basis', 'printed', 'explanation', 'context', 'value', 'basis',
            'expected', 'actual']
    result = {}
    for key in keys:
        if key not in value:
            continue
        entry = value[key]
        if isinstance(entry, str):
            encoded = entry.encode('utf-8')
            result[key] = encoded[:text_bytes if key not in ['id', 'line', 'article', 'status', 'text_status'] else 256].decode('utf-8', errors='ignore')
            if result[key] != entry:
                result.setdefault('truncated_fields', []).append(key)
        elif isinstance(entry, (int, float, bool)) or entry is None:
            result[key] = entry
        elif key in ['selection_region', 'ocr_bbox', 'bbox']:
            result[key] = entry[:4]
    text = value.get('text', value.get('candidate'))
    if isinstance(text, str):
        encoded = text.encode('utf-8')
        result.update(text=encoded[:text_bytes].decode('utf-8', errors='ignore'),
                      text_bytes=len(encoded), text_truncated=len(encoded) > text_bytes)
    if value.get('line_ids'):
        result['line_ids'] = value['line_ids'][:8]
        result['line_count'] = len(value['line_ids'])
    return result


def stale_artifacts(work):
    """Preserved evidence stays readable, but never masquerades as current."""
    marker = work / 'review-invalidation.json'
    if not marker.is_file() or not (work / 'review.json').is_file():
        return set()
    invalidation = read_artifact(marker)
    current = source_hash(work / 'review.json')
    if invalidation.get('status') != 'stale_for_current_review' or invalidation.get('review_sha256') != current:
        return set()
    stale = {entry['path'] for entry in invalidation['artifacts']
             if (work / entry['path']).is_file() and source_hash(work / entry['path']) == entry['sha256']}
    for manifest, artifacts in [('segment-manifest.json', SEGMENTATION_ARTIFACTS),
                                ('output-manifest.json', EXPORT_ARTIFACTS)]:
        path = work / manifest
        if path.is_file():
            inputs = read_artifact(path).get('inputs', {})
            if inputs.get('review', {}).get('sha256') == current:
                stale -= set(artifacts)
    return stale


SEGMENTATION_ARTIFACTS = (
    'segment-manifest.json', 'segmented-review.json', 'pages.json', 'reviewed-lines.json',
    'geometry.json', 'segmentation-events.json', 'unresolved.json', 'publisher-errors.json',
    'reconstructions.json', 'risk-register.json', 'checks/unsupported-cells.json',
    'checks/geometry-anomalies.json',
)
EXPORT_ARTIFACTS = (
    'output-manifest.json', 'exported-pages.json',
    'exported-review.json', 'export-inputs.json', 'construction/construction-events.json',
    'checks/technical.json', 'checks/geometry-samples.json', 'checks/visual-review.json',
    'checks/findings.json', 'checks/manual-copy/status.json', 'checks/report-todo.json',
    'checks/run-validation.json', 'checks/run-summary.md',
)
DERIVED_ARTIFACTS = SEGMENTATION_ARTIFACTS + EXPORT_ARTIFACTS + ('geometry-preparation.json', 'geometry-checkpoint.json')


def patch_project(registry, project_id, patch, *, line_id=None, expected_review_sha256=None):
    with registry.project_lock(project_id) as record:
        work = registry.root / record['artifacts']['workspace']
        path = work / 'review.json'
        if expected_review_sha256 is not None and source_hash(path) != expected_review_sha256:
            raise ProjectError('review_changed', 'Review changed before the validated patch; nothing changed.')
        original = read_artifact(path)
        try:
            edits = load(patch)
            if line_id is None:
                changed = patched_review(original, edits)
            else:
                changed = copy.deepcopy(original)
                apply_line_patch(changed, line_id, edits)
            if changed['source_sha256'] != record['project']['source_sha256']:
                raise ValueError('Review belongs to another registered source')
            summary = validate_review(work, changed)
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
            raise ProjectError('patch_invalid', 'Patch was rejected by the complete review validator; no files changed.') from error
        previous_hash = source_hash(path)
        chain_path = work / 'review-patch-chain.json'
        chain = load(chain_path) if chain_path.exists() else []
        if changed == original:
            result = copy.deepcopy(record)
            result['counts'].update(changed_lines=0, invalidated_artifacts=0)
            return result
        old_lines = {line['id']: line for line in original['lines']}
        new_lines = {line['id']: line for line in changed['lines']}
        changed_lines = {key for key in old_lines.keys() | new_lines.keys()
                         if old_lines.get(key) != new_lines.get(key)}
        affected = set(changed_lines)
        for register in ['unresolved', 'publisher_errors', 'risk_register']:
            if original.get(register, []) != changed.get(register, []):
                affected.update(row['line'] for row in original.get(register, []) + changed.get(register, []))
        reordered = original['units'] != changed['units']
        if reordered:
            old_units = {unit['id']: (index, unit) for index, unit in enumerate(original['units'])}
            new_units = {unit['id']: (index, unit) for index, unit in enumerate(changed['units'])}
            for key in old_units.keys() | new_units.keys():
                if old_units.get(key) != new_units.get(key):
                    for units in [old_units, new_units]:
                        if key in units:
                            affected.update(units[key][1]['line_ids'])
        affected = sorted(affected)
        pages = sorted({line['page'] for key in affected for line in [old_lines.get(key), new_lines.get(key)] if line})
        artifacts = [{'path': name, 'sha256': source_hash(work / name)}
                     for name in DERIVED_ARTIFACTS if (work / name).is_file()]
        with contextlib.redirect_stdout(io.StringIO()):
            save_review(SimpleNamespace(work=work, review=path), original, changed)
        current_hash = source_hash(path)
        saved_patch = work / 'review-history' / (current_hash + '-patch.json')
        atomic_json(saved_patch, edits)
        chain.append({'previous': previous_hash, 'current': current_hash,
                      'patch': str(saved_patch.relative_to(work)), 'patch_sha256': source_hash(saved_patch), 'line_id': line_id})
        atomic_json(chain_path, chain)
        invalidation = {'schema_version': 1, 'status': 'stale_for_current_review',
                        'previous_review_sha256': previous_hash, 'review_sha256': current_hash,
                        'affected_lines': affected, 'affected_pages': pages, 'unit_order_changed': reordered,
                        'artifacts': artifacts}
        atomic_json(work / 'review-invalidation.json', invalidation)
        record['project'].update(phase='review_updated', operation_state='completed', validation='not_run',
                                 review_sha256=current_hash)
        record['counts'].update(summary, changed_lines=len(changed_lines), affected_lines=len(affected),
                                affected_pages=len(pages), invalidated_artifacts=len(artifacts))
        record['artifacts'].update(review=str(path.relative_to(registry.root)),
                                   previous_review=str((work / 'review-history' / (previous_hash + '.json')).relative_to(registry.root)),
                                   review_invalidation=str((work / 'review-invalidation.json').relative_to(registry.root)))
    return registry.get(project_id)
