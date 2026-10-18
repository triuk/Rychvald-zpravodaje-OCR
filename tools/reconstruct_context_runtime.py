#!/usr/bin/env python3
"""Reconstruct the pinned build input offline from Git objects and npm archives.

This build-time tool never uses mutable installed file bytes, downloads data,
changes a plugin, installs dependencies or runs package lifecycle scripts.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def inventory(lock):
    raw = (ROOT / lock['source_inventory']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != lock['source_inventory_sha256']:
        raise ValueError('The pinned per-file source inventory changed.')
    records = json.loads(raw)
    names = [entry['path'] for entry in records]
    if len(records) != lock['file_count'] or len(names) != len(set(names)):
        raise ValueError('Source inventory count/identity mismatch.')
    if any(Path(name).is_absolute() or '..' in Path(name).parts for name in names):
        raise ValueError('Unsafe inventory path.')
    return records


def reconstruct(upstream, npm_cache, destination):
    from prepare_context_runtime import digest
    lock = json.loads((ROOT / 'native/context-runtime.json').read_text())
    records = inventory(lock)
    if destination.exists():
        raise ValueError('Choose an unused build destination.')
    archives, files = {}, {}
    for entry in records:
        origin = entry['provenance']
        if origin['kind'] == 'upstream_git_blob':
            if origin['commit'] != lock['upstream_commit']:
                raise ValueError('Foreign upstream commit in source inventory.')
            blob = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', origin['commit'] + ':' + entry['path']]).decode().strip()
            if blob != origin['blob']:
                raise ValueError('Upstream Git blob identity differs.')
            data = subprocess.check_output(['git', '-C', str(upstream), 'show', origin['commit'] + ':' + entry['path']])
        elif origin['kind'] == 'npm_integrity_archive':
            integrity = origin['integrity']
            if integrity not in archives:
                algorithm, encoded = integrity.split('-', 1)
                if algorithm not in ('sha512', 'sha256'):
                    raise ValueError('Unsupported archive integrity algorithm.')
                expected = base64.b64decode(encoded, validate=True).hex()
                archive = npm_cache / 'content-v2' / algorithm / expected[:2] / expected[2:4] / expected[4:]
                raw = archive.read_bytes()
                if hashlib.new(algorithm, raw).hexdigest() != expected:
                    raise ValueError('Package archive integrity mismatch.')
                members = {}
                with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as stream:
                    for member in stream:
                        if not member.isfile():
                            continue
                        name = member.name.partition('/')[2]
                        if not name or Path(name).is_absolute() or '..' in Path(name).parts or name in members:
                            raise ValueError('Unsafe or duplicate package member.')
                        members[name] = stream.extractfile(member).read()
                archives[integrity] = members
            data = archives[integrity][origin['member']]
        else:
            raise ValueError('Unknown source provenance.')
        if len(data) != entry['size_bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Reconstructed source file differs: ' + entry['path'])
        files[entry['path']] = data
    # Resolve and verify every immutable input before publishing any build tree.
    destination.mkdir(parents=True)
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    actual = {str(p.relative_to(destination)): p for p in destination.rglob('*') if p.is_file()}
    if digest(actual) != lock['source_tree_sha256']:
        raise ValueError('Reconstructed closure aggregate differs.')
    return {'path': str(destination), 'files': len(actual), 'source_tree_sha256': digest(actual)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, help='Local Git object repository containing the exact locked upstream commit.')
    parser.add_argument('--npm-cache', type=Path, help='Read-only npm _cacache directory containing integrity-addressed tarballs.')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--import-inventory', type=Path, help='Bootstrap the generated per-file inventory from exactly its locked SHA-256.')
    args = parser.parse_args()
    if args.import_inventory:
        lock = json.loads((ROOT / 'native/context-runtime.json').read_text())
        raw = args.import_inventory.read_bytes()
        if hashlib.sha256(raw).hexdigest() != lock['source_inventory_sha256']:
            raise ValueError('Provided generated source inventory does not match the reviewed pin.')
        target = ROOT / lock['source_inventory']
        if target.exists() and target.read_bytes() != raw:
            raise ValueError('An existing source inventory differs; no overwrite.')
        target.write_bytes(raw)
        print(json.dumps({'inventory': str(target), 'sha256': lock['source_inventory_sha256']}))
        return
    if not all([args.upstream, args.npm_cache, args.output]):
        parser.error('--upstream, --npm-cache and --output are required for reconstruction')
    print(json.dumps(reconstruct(args.upstream.resolve(), args.npm_cache.resolve(), args.output.resolve())))


if __name__ == '__main__':
    main()
