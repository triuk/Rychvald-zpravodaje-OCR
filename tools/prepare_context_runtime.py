#!/usr/bin/env python3
"""Prepare exactly locked local context-mode resources; never install anything."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('@clack/prompts', '@mixmark-io/domino', '@modelcontextprotocol/sdk',
            'picocolors', 'turndown', 'turndown-plugin-gfm', 'zod')


def digest(files):
    text = ''.join(f'{name}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n' for name, path in sorted(files.items()))
    return hashlib.sha256(text.encode()).hexdigest()


def source_files(source):
    files = {str(path.relative_to(source)): path for path in (source / 'hooks').rglob('*') if path.is_file()}
    for name in ('server.bundle.mjs', 'package.json', 'LICENSE'):
        files[name] = source / name
    seen = set()

    def package(name, owner):
        current = owner
        while True:
            candidate = current / 'node_modules' / name
            if (candidate / 'package.json').is_file():
                break
            if current == source or not current.is_relative_to(source):
                raise ValueError('Missing locked production dependency: ' + name)
            current = current.parent
        if candidate in seen:
            return
        seen.add(candidate)
        for path in candidate.rglob('*'):
            if path.is_symlink():
                raise ValueError('Unexpected resource symlink: ' + str(path))
            if path.is_file() and 'node_modules' not in path.relative_to(candidate).parts:
                files[str(path.relative_to(source))] = path
        metadata = json.loads((candidate / 'package.json').read_text())
        for dependency in metadata.get('dependencies', {}):
            package(dependency, candidate)

    for name in PACKAGES:
        package(name, source)
    return files


def prepare(source, destination):
    from reconstruct_context_runtime import inventory
    lock = json.loads((ROOT / 'native/context-runtime.json').read_text())
    files = source_files(source)
    expected = {entry['path']: entry['sha256'] for entry in inventory(lock)}
    if set(files) != set(expected) or any(hashlib.sha256(path.read_bytes()).hexdigest() != expected[name] for name, path in files.items()):
        raise ValueError('Context-mode source differs from its per-file provenance inventory.')
    if digest(files) != lock['source_tree_sha256']:
        raise ValueError('Installed context-mode source closure differs from the pinned version.')
    if destination.exists():
        raise ValueError('Output already exists; choose a new build directory.')
    destination.mkdir(parents=True)
    for name, path in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    shutil.copyfile(ROOT / 'native/context-no-install.mjs', destination / 'hooks/ensure-deps.mjs')
    actual = {str(path.relative_to(destination)): path for path in destination.rglob('*') if path.is_file()}
    if digest(actual) != lock['prepared_tree_sha256']:
        raise ValueError('Prepared context-mode closure failed verification.')
    return {'version': lock['version'], 'path': str(destination), 'tree_sha256': digest(actual), 'files': len(actual)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(Path(args.source).resolve(), Path(args.output).resolve()), indent=2))


if __name__ == '__main__':
    main()
