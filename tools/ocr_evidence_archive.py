"""Exact historical evidence reads. Availability grants no execution compatibility.

The catalog is an explicit inventory of (original absolute path, SHA256, kind).
It never supplies active installed resources or mutable write preconditions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('An exact lowercase SHA256 is required')
    return value


def _absolute(value):
    if not isinstance(value, (str, Path)):
        raise ValueError('An absolute evidence path is required')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or str(path) != str(value):
        raise ValueError('Evidence paths must be normalized absolute paths')
    return path


def _read(path):
    path = _absolute(path)
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('Symlinks are not evidence identities')
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError(f'Missing evidence: {path}') from error


def _catalog(value=None):
    value = value or os.environ.get('OCR_EVIDENCE_CATALOG')
    if not value:
        raise ValueError('No exact historical evidence catalog configured')
    if isinstance(value, dict):
        path, expected = _absolute(value['path']), _digest(value['sha256'])
    else:
        path = _absolute(value)
        expected = _digest(_read(Path(str(path) + '.sha256')).decode('ascii').strip())
    raw = _read(path)
    if _sha(raw) != expected:
        raise ValueError('Historical catalog SHA256 differs from its trusted pin')
    data = json.loads(raw)
    if data.get('schema') != 'ocr-evidence-archive-v1' or not isinstance(data.get('records'), list):
        raise ValueError('Unsupported historical evidence catalog')
    _validate_inventory(data)
    return path.parent, data


def _validate_inventory(data):
    seen = set()
    for record in data['records']:
        _absolute(record['original_path'])
        _digest(record['sha256'])
        if record['kind'] not in ('whole_file', 'protocol_line') or not record.get('proof'):
            raise ValueError('Explicit evidence kind and proof required')
        key = (record['original_path'], record['sha256'], record['kind'])
        if record['kind'] == 'protocol_line':
            if type(record.get('line')) is not int or record['line'] < 1 or type(record.get('byte_offset')) is not int or record['byte_offset'] < 0:
                raise ValueError('Protocol fragment location required')
            key += (record['line'], record['byte_offset'])
        if key in seen:
            raise ValueError('Duplicate historical evidence identity')
        seen.add(key)
    for binding in data.get('workspace_bindings', []):
        _absolute(binding['original_prefix'])
        _absolute(binding['canonical_prefix'])
        if not binding.get('proof'):
            raise ValueError('Explicit workspace relocation proof required')


def _object(root, record):
    object_sha = _digest(record['object_sha256'])
    if record['object'] != f'objects/{object_sha}':
        raise ValueError('Invalid historical CAS object path')
    path = root / record['object']
    raw = _read(path)
    if _sha(raw) != object_sha:
        raise ValueError('Historical CAS bytes changed')
    return path, raw


def _entry(original, expected, kind, catalog=None, **fragment):
    root, data = _catalog(catalog)
    matches = [record for record in data['records'] if
        record['original_path'] == str(original) and record['sha256'] == expected and
        record['kind'] == kind and all(record.get(k) == v for k, v in fragment.items())]
    if len(matches) != 1 or matches[0].get('status') != 'available':
        raise ValueError(f'Unavailable exact historical identity: {original} ({expected}, {kind})')
    record = matches[0]
    path, raw = _object(root, record)
    return path, raw, record


def resolve_bound(original_path, expected_sha256, *, catalog=None):
    """Return byte-verified whole-file evidence for one exact original identity."""
    original, expected = _absolute(original_path), _digest(expected_sha256)
    if original.exists():
        raw = _read(original)
        if _sha(raw) == expected:
            return original
    path, raw, _ = _entry(original, expected, 'whole_file', catalog)
    if _sha(raw) != expected:
        raise ValueError('Historical whole-file identity changed')
    return path


def load_bound(pointer, *, catalog=None):
    """Read JSON without rewriting the original pointer or payload."""
    return json.loads(resolve_bound(pointer['path'], pointer['sha256'], catalog=catalog).read_bytes())


def _fragment(raw, expected, line, byte_offset):
    if type(line) is not int or line < 1 or type(byte_offset) is not int or byte_offset < 0:
        raise ValueError('Exact protocol line and byte offset required')
    lines = raw.splitlines(keepends=True)
    if line > len(lines) or sum(map(len, lines[:line - 1])) != byte_offset:
        raise ValueError('Protocol fragment line/offset mismatch')
    fragment = lines[line - 1]
    if not fragment.endswith(b'\n') or _sha(fragment) != expected:
        raise ValueError('Protocol fragment SHA256/LF mismatch')
    return fragment


def resolve_fragment(original_path, expected_sha256, *, line, byte_offset, catalog=None):
    """Return an exact metric protocol line including LF, never whole-file bytes."""
    original, expected = _absolute(original_path), _digest(expected_sha256)
    if original.exists():
        try:
            return _fragment(_read(original), expected, line, byte_offset)
        except ValueError:
            pass
    _, raw, _ = _entry(original, expected, 'protocol_line', catalog,
        line=line, byte_offset=byte_offset)
    return _fragment(raw, expected, line, byte_offset)


def verify_relocated_path(original_path, current_path, expected_sha256, *, catalog=None):
    """Prove workspace lineage as well as bytes for an original image request."""
    original, current = _absolute(original_path), _absolute(current_path)
    expected = _digest(expected_sha256)
    if original == current:
        return
    # Equal bytes alone never grant an old requested image path a new identity.
    _entry(original, expected, 'whole_file', catalog)
    _, data = _catalog(catalog)
    for binding in data.get('workspace_bindings', []):
        old = _absolute(binding['original_prefix'])
        new = _absolute(binding['canonical_prefix'])
        if binding.get('proof') and original.is_relative_to(old) and new / original.relative_to(old) == current:
            return
    raise ValueError('Original requested image path lacks explicit workspace relocation proof')


def capture(inventory, output):
    """Capture only explicit inventoried bytes; never discover aliases by hash."""
    inventory_path = _absolute(inventory)
    source_raw = _read(inventory_path)
    source = json.loads(source_raw)
    _validate_inventory(source)
    output = _absolute(output)
    if output.exists():
        raise ValueError('Archive output must not already exist')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.evidence-capture-', dir=output.parent))
    try:
        (temporary / 'objects').mkdir()
        records = []
        for item in source['records']:
            original = _absolute(item['original_path'])
            expected = _digest(item['sha256'])
            record = dict(item, original_path=str(original))
            if item.get('status') == 'unavailable':
                if not item.get('proof'):
                    raise ValueError('Unavailable evidence requires explicit proof')
                records.append(record)
                continue
            if item['kind'] not in ('whole_file', 'protocol_line'):
                raise ValueError('Unsupported evidence kind')
            source_record = item['source']
            if 'repository' in source_record:
                repository = _absolute(source_record['repository'])
                commit, member = source_record['commit'], source_record['path']
                if not re.fullmatch('[0-9a-f]{40}', commit) or Path(member).is_absolute() or '..' in Path(member).parts:
                    raise ValueError('Exact Git commit and confined member required')
                result = subprocess.run(['git', '-C', str(repository), 'show', f'{commit}:{member}'],
                    capture_output=True, check=False)
                if result.returncode:
                    raise ValueError('Exact Git source unavailable')
                raw = result.stdout
            else:
                raw = _read(_absolute(source_record['path']))
            if item['kind'] == 'protocol_line':
                _fragment(raw, expected, item['line'], item['byte_offset'])
            elif _sha(raw) != expected:
                raise ValueError('Capture source differs from original trusted SHA256')
            if not item.get('proof'):
                raise ValueError('Explicit source proof is required')
            object_sha = _sha(raw)
            target = temporary / 'objects' / object_sha
            if not target.exists():
                target.write_bytes(raw)
                target.chmod(0o444)
            records.append(dict(record, status='available', object=f'objects/{object_sha}', object_sha256=object_sha))
        data = {'schema': 'ocr-evidence-archive-v1', 'inventory_sha256': _sha(source_raw),
            'records': records, 'workspace_bindings': source.get('workspace_bindings', [])}
        raw = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        (temporary / 'catalog.json').write_bytes(raw)
        (temporary / 'catalog.json.sha256').write_text(_sha(raw) + '\n')
        (temporary / 'inventory.json').write_bytes(source_raw)
        for name in ('catalog.json', 'catalog.json.sha256', 'inventory.json'):
            (temporary / name).chmod(0o444)
        temporary.rename(output)
        return {'catalog': str(output / 'catalog.json'), 'sha256': _sha(raw), 'records': len(records)}
    except BaseException:
        shutil.rmtree(temporary)
        raise


def verify_catalog(catalog):
    root, data = _catalog(catalog)
    if _sha(_read(root / 'inventory.json')) != data['inventory_sha256']:
        raise ValueError('Original capture inventory changed')
    available = 0
    for record in data['records']:
        if record.get('status') == 'unavailable':
            continue
        fragment = {k: record[k] for k in ('line', 'byte_offset')} if record['kind'] == 'protocol_line' else {}
        _, raw = _object(root, record)
        if record['kind'] == 'whole_file' and record['object_sha256'] != record['sha256']:
            raise ValueError('Whole-file identity differs from object identity')
        if record['kind'] == 'protocol_line':
            _fragment(raw, record['sha256'], **fragment)
        available += 1
    return {'verified': True, 'available': available, 'unavailable': len(data['records']) - available}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('capture')
    command.add_argument('--inventory', required=True)
    command.add_argument('--output', required=True)
    command = commands.add_parser('verify')
    command.add_argument('--catalog', required=True)
    command = commands.add_parser('resolve')
    command.add_argument('--catalog', required=True)
    command.add_argument('--path', required=True)
    command.add_argument('--sha256', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'capture':
            result = capture(args.inventory, args.output)
        elif args.command == 'verify':
            result = verify_catalog(args.catalog)
        else:
            result = {'path': str(resolve_bound(args.path, args.sha256, catalog=args.catalog))}
        print(json.dumps(result))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f'{error}\n')


if __name__ == '__main__':
    main()
