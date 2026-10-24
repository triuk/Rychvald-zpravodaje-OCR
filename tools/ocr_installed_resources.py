"""Exact installed-origin evidence, never an executable or mutable CAS fallback."""
import hashlib
import json
import os
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def capture(registry, record, prefix):
    """Freeze one explicitly selected installation before its prefix is retired."""
    from ocr_projects import atomic_json
    from ocr_evidence_archive import capture as capture_archive
    prefix = Path(prefix).resolve()
    work = registry.root / record['artifacts']['workspace']
    inventory_path = prefix / 'inventory.json'
    inventory = json.loads(inventory_path.read_text())
    files = inventory['files']
    actual = {str(p.relative_to(prefix)) for p in prefix.rglob('*') if p.is_file()}
    if actual != set(files) | {'inventory.json'} or any(p.is_symlink() for p in prefix.rglob('*')):
        raise ValueError('Original installed inventory is incomplete or contains linked files')
    for name, pin in files.items():
        path = (prefix / name).resolve()
        if (not path.is_relative_to(prefix) or digest(path) != pin['sha256'] or
                bool(path.stat().st_mode & 0o111) != pin['executable']):
            raise ValueError('Original installed resource changed: ' + name)
    anchor_path = work / 'preparation-identity.json'
    if anchor_path.exists():
        anchor = json.loads(anchor_path.read_text())
        if (Path(anchor['environment_manifest']) != prefix / 'environment.json' or
                anchor['identity']['environment']['manifest_sha256'] != digest(prefix / 'environment.json')):
            raise ValueError('Selected original prefix is not the frozen preparation environment')
    elif prefix != Path(__file__).resolve().parents[1]:
        raise ValueError('An unprepared run can capture only its current installed prefix')
    identifier = hashlib.sha256((str(prefix) + '\n' + digest(inventory_path)).encode()).hexdigest()
    archive = registry.root / 'application/installed-resource-archives' / identifier
    archive.parent.mkdir(parents=True, exist_ok=True)
    expected = {str(prefix / name): pin['sha256'] for name, pin in files.items()}
    expected[str(inventory_path)] = digest(inventory_path)
    if not archive.exists():
        inputs = archive.with_name(identifier + '-inputs.json')
        packet = {'records': [{'original_path': name, 'sha256': sha, 'kind': 'whole_file',
            'source': {'path': name}, 'proof': {'installed_prefix': str(prefix),
                'inventory_sha256': digest(inventory_path), 'relative_path': str(Path(name).relative_to(prefix))}}
            for name, sha in sorted(expected.items())]}
        if inputs.exists() and json.loads(inputs.read_text()) != packet:
            raise ValueError('Original installed capture intent changed')
        atomic_json(inputs, packet)
        capture_archive(inputs, archive)
    catalog_path = archive / 'catalog.json'
    catalog = json.loads(catalog_path.read_text())
    if ({row['original_path']: row['sha256'] for row in catalog['records']} != expected or
            any(row['kind'] != 'whole_file' or row['status'] != 'available' for row in catalog['records'])):
        raise ValueError('Original installed archive differs from its exact inventory')
    origin_path = work / 'application/installed-resource-origin.json'
    run_path = registry.root / record['artifacts']['run_manifest']
    body = {'schema_version': 1, 'run_id': record['project']['run_id'],
        'source_sha256': record['project']['source_sha256'], 'original_prefix': str(prefix),
        'inventory_sha256': digest(inventory_path),
        'catalog': {'path': str(catalog_path.relative_to(registry.root)), 'sha256': digest(catalog_path)},
        'original_run_manifest_sha256': digest(run_path) if run_path.exists() else None}
    if origin_path.exists():
        pointer = record.get('installed_resources')
        if pointer is None or digest(origin_path) != pointer['sha256']:
            raise ValueError('Existing installed origin cannot be replaced')
        return pointer
    origin_path.parent.mkdir(exist_ok=True)
    atomic_json(origin_path, body)
    pointer = {'path': str(origin_path.relative_to(work)), 'sha256': digest(origin_path)}
    record['installed_resources'] = pointer
    return pointer


def check_bindings(work, records):
    """Allow only missing immutable installed evidence with exact frozen origins."""
    from ocr_quality import check_bindings as strict
    from ocr_evidence_archive import load_bound, resolve_bound
    work = Path(work).resolve()
    missing = {}
    for name, pin in records.items():
        path = Path(pin['path'])
        if path.exists():
            strict({name: pin})  # Existing changed files never reach an archive.
        else:
            missing[name] = pin
    if not missing:
        return
    record = json.loads((work / 'project.json').read_text())
    pointer = record.get('installed_resources')
    if not pointer or pointer['path'] != 'application/installed-resource-origin.json':
        strict(missing)
        return
    origin_path = work / pointer['path']
    if origin_path.is_symlink() or digest(origin_path) != pointer['sha256']:
        raise ValueError('Frozen installed-resource origin changed')
    origin = json.loads(origin_path.read_text())
    if (origin['schema_version'] != 1 or origin['run_id'] != record['project']['run_id'] or
            origin['source_sha256'] != record['project']['source_sha256']):
        raise ValueError('Installed-resource origin belongs to another run/source')
    registry_root = work.parents[1]
    run_path = registry_root / record['artifacts']['run_manifest']
    run = json.loads(run_path.read_text())
    if run.get('installed_resources') != pointer and digest(run_path) != origin['original_run_manifest_sha256']:
        raise ValueError('Installed origin has no exact frozen run binding')
    catalog_path = (registry_root / origin['catalog']['path']).resolve()
    if not catalog_path.is_relative_to(registry_root / 'application/installed-resource-archives'):
        raise ValueError('Installed resource catalog escaped its registry')
    catalog = {'path': str(catalog_path), 'sha256': origin['catalog']['sha256']}
    prefix = Path(origin['original_prefix'])
    inventory = load_bound({'path': str(prefix / 'inventory.json'), 'sha256': origin['inventory_sha256']}, catalog=catalog)
    for name, pin in missing.items():
        original = Path(pin['path'])
        if not original.is_absolute() or '..' in original.parts or not original.is_relative_to(prefix):
            raise ValueError('Missing current run input cannot use installed-resource history: ' + name)
        relative = str(original.relative_to(prefix))
        if inventory['files'].get(relative, {}).get('sha256') != pin['sha256']:
            raise ValueError('Unknown original installed resource identity: ' + name)
        resolve_bound(pin['path'], pin['sha256'], catalog=catalog)


def selected_environment(work, original):
    """Select current executable resources only for byte-identical env manifests."""
    original = Path(original)
    if original.exists():
        return original
    anchor = json.loads((Path(work) / 'preparation-identity.json').read_text())
    if anchor['environment_manifest'] != str(original):
        raise ValueError('Missing environment is not the exact frozen preparation selection')
    expected = anchor['identity']['environment']['manifest_sha256']
    check_bindings(work, {'environment': {'path': str(original), 'sha256': expected}})
    current = Path(os.environ.get('OCR_ENVIRONMENT', Path(__file__).resolve().parents[1] / 'environment.json')).resolve()
    installed = Path(__file__).resolve().parents[1]
    if (installed / 'inventory.json').is_file() and current != installed / 'environment.json':
        raise ValueError('Relocation must select the current installed environment, never an archive manifest')
    if not current.is_file() or digest(current) != expected:
        raise ValueError('Selected current environment is not byte-identical; no normalized compatibility is authorized')
    return current
