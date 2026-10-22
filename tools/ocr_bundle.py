#!/usr/bin/env python3
"""Build/install a frozen offline Linux OCR bundle; never bless drift during build."""
import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'native/bundle-inputs.json'


class BundleError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_file(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def locked(path, expected):
    if not Path(path).is_file() or sha(path) != expected:
        raise BundleError('input_mismatch', f'Locked input missing or changed: {path}')
    return Path(path)


def capture(inputs, wheel_cache, download=False):
    """Copy declared, hash-verified inputs to an immutable offline source cache."""
    lock = json.loads(LOCK.read_text())
    inputs, wheel_cache = Path(inputs), Path(wheel_cache)
    sources = [(Path(name), record['sha256']) for name, record in {**lock['files'], **lock.get('licenses', {})}.items()]
    sources.append((Path(lock['python_archive']['path']), lock['python_archive']['sha256']))
    for wheel in lock['wheels']:
        source = wheel_cache / wheel['filename']
        if not source.exists() and download:
            wheel_cache.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(wheel['url'], timeout=60) as response:
                payload = response.read()
            if hashlib.sha256(payload).hexdigest() != wheel['sha256']:
                raise BundleError('input_mismatch', 'Downloaded wheel differs from its frozen hash')
            source.write_bytes(payload)
        sources.append((source, wheel['sha256']))
    for source, expected in sources:
        locked(source, expected)
    inputs.mkdir(parents=True, exist_ok=True)
    for source, expected in sources:
        target = inputs / expected
        if target.exists():
            locked(target, expected)
        else:
            with tempfile.NamedTemporaryFile(dir=inputs, delete=False) as stream:
                temporary = Path(stream.name)
                with source.open('rb') as original:
                    shutil.copyfileobj(original, stream)
                stream.flush()
                os.fsync(stream.fileno())
            locked(temporary, expected)
            temporary.rename(target)
    return {'inputs': str(inputs.resolve()), 'objects': len(set(hash_value for _, hash_value in sources)),
            'lock_sha256': sha(LOCK)}


def capture_release(inputs, selection):
    """Capture only a reviewed closure; building subsequently needs this CAS alone."""
    selection = Path(selection)
    selected = json.loads(selection.read_text())
    native_lock = json.loads(locked(selected['native_lock']['path'], selected['native_lock']['sha256']).read_text())
    sources = []
    for record in [native_lock['python_archive'], *native_lock['files'].values(),
                   *native_lock['wheels'], *native_lock.get('licenses', {}).values()]:
        sources.append((Path(selected['native_inputs']) / record['sha256'], record['sha256']))
    resources = selected['resources']
    for record in resources.values():
        sources.append((Path(record['source']), record['sha256']))
    # Source capture deliberately enumerates the whole application boundary, so
    # newly integrated recovery tools are included without a stale hash allowlist.
    source_files = [ROOT / 'main.py']
    for folder in ('app', 'ui', 'profiles', 'tools', 'native'):
        source_files.extend(path for path in (ROOT / folder).rglob('*')
                            if path.is_file() and '__pycache__' not in path.parts
                            and path.suffix not in ('.pyc', '.pyo'))
    if any(path.is_symlink() for path in source_files):
        raise BundleError('input_mismatch', 'Application source contains symbolic links')
    application = {str(path.relative_to(ROOT)): {'sha256': sha(path),
                   'executable': bool(path.stat().st_mode & 0o111)} for path in sorted(source_files)}
    sources.extend((path, application[str(path.relative_to(ROOT))]['sha256']) for path in source_files)
    for source, expected in sources:
        locked(source, expected)
    from prepare_context_runtime import prepare
    with tempfile.TemporaryDirectory(prefix='rychvald-context-capture-') as temporary:
        package = Path(temporary) / 'context-mode'
        prepared = prepare(Path(selected['context_source']), package)
        context_files = {str(path.relative_to(package)): {'sha256': sha(path), 'executable': False}
                         for path in sorted(package.rglob('*')) if path.is_file()}
        sources.extend((package / name, record['sha256']) for name, record in context_files.items())
        inputs = Path(inputs)
        if (inputs / 'release.json').exists():
            raise BundleError('destination_exists', 'Release capture descriptor already exists')
        inputs.mkdir(parents=True, exist_ok=True)
        for source, expected in sources:
            target = inputs / expected
            if target.exists():
                locked(target, expected)
            else:
                with tempfile.NamedTemporaryFile(dir=inputs, delete=False) as stream:
                    candidate = Path(stream.name)
                    with source.open('rb') as original:
                        shutil.copyfileobj(original, stream)
                locked(candidate, expected)
                candidate.rename(target)
        revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                  capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=normal'],
                                   capture_output=True, text=True, check=True).stdout)
        descriptor = {'schema_version': 1, 'kind': 'offline-gui-release', 'native_lock': native_lock,
                      'native_lock_sha256': selected['native_lock']['sha256'],
                      'selection_sha256': sha(selection), 'selection': selected,
                      'source_revision': revision, 'source_dirty': dirty,
                      'source_files': application, 'context_files': context_files,
                      'prepared_context': prepared['tree_sha256'], 'resources': resources}
        json_file(inputs / 'release.json', descriptor)
    return {'inputs': str(inputs.resolve()), 'descriptor_sha256': sha(inputs / 'release.json'),
            'source_revision': revision, 'source_dirty': dirty, 'source_files': len(application)}


def build_release(inputs, output):
    inputs = Path(inputs)
    release = json.loads((inputs / 'release.json').read_text())
    lock = release['native_lock']
    for record in [lock['python_archive'], *lock['files'].values(), *lock['wheels'],
                   *lock.get('licenses', {}).values(), *release['source_files'].values(),
                   *release['context_files'].values(), *release['resources'].values()]:
        locked(inputs / record['sha256'], record['sha256'])
    with tempfile.TemporaryDirectory(prefix='rychvald-release-source-') as temporary:
        root = Path(temporary)
        for name, record in release['source_files'].items():
            relative = safe_relative(name)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(inputs / record['sha256'], target)
            target.chmod(0o755 if record['executable'] else 0o644)
        return build(inputs, output, source_root=root, native_lock=lock, release=release)


def safe_relative(name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise BundleError('unsafe_archive', 'Unsafe release member: ' + name)
    return path


def populate_release(bundle, inputs, root, release):
    for name, record in release['source_files'].items():
        target = bundle / safe_relative(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs / record['sha256'], target)
        target.chmod(0o755 if record['executable'] else 0o644)
    for name, record in release['resources'].items():
        target = bundle / safe_relative(name)
        if target.exists() and sha(target) != record['sha256']:
            raise BundleError('basename_collision', 'Conflicting release resource: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs / record['sha256'], target)
        target.chmod(0o755 if record['executable'] else 0o644)
    for name, record in release['context_files'].items():
        target = bundle / 'runtime/context-mode' / safe_relative(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs / record['sha256'], target)
        target.chmod(0o644)

    def wrapper(name, program, python=False):
        target = bundle / 'runtime/bin' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#!/bin/sh\nroot=${0%/*}/../..\n'
                          'unset LD_PRELOAD LD_LIBRARY_PATH' +
                          (' PYTHONPATH PYTHONHOME PYTHONUSERBASE' if python else '') + '\n'
                          'exec "$root/lib/ld-linux-x86-64.so.2" --inhibit-cache --library-path "$root/lib" '
                          '"$root/' + program + '"' + (' -I -B' if python else '') + ' "$@"\n')
        target.chmod(0o755)

    for name, program in [('node', 'runtime/native/node'), ('bash', 'runtime/native/bash'),
                          ('sh', 'runtime/native/bash'), ('env', 'runtime/native/env'),
                          ('python3', 'bin/python3.14')]:
        wrapper(name, program, name == 'python3')
    loader = ['lib/ld-linux-x86-64.so.2', '--inhibit-cache', '--library-path', 'lib']
    context_lock = json.loads((root / 'native/context-runtime.json').read_text())
    runtime_files = {name: record['sha256'] for name, record in release['resources'].items()
                     if name.startswith(('lib/', 'runtime/native/')) and '/site-packages/' not in name}
    runtime_files['bin/python3.14'] = sha(bundle / 'bin/python3.14')
    for path in (bundle / 'runtime/bin').iterdir():
        runtime_files[str(path.relative_to(bundle))] = sha(path)
    descriptor = {'kind': 'native', 'version': context_lock['version'],
                  'node': 'runtime/bin/node', 'node_command': [*loader, 'runtime/native/node'],
                  'env_command': [*loader, 'runtime/native/env'],
                  'package': 'runtime/context-mode', 'tree_sha256': release['prepared_context'],
                  'files': [{'path': name, 'sha256': value} for name, value in sorted(runtime_files.items())],
                  'interpreters': [{'name': name, 'path': 'runtime/bin/' + name} for name in ('python3', 'bash', 'sh')]}
    json_file(bundle / 'native/bundled-context.json', descriptor)
    shutil.copyfile(root / 'native/gui_bootstrap.py', bundle / 'gui_bootstrap.py')
    launcher = bundle / 'bin/rychvald-ocr-gui'
    launcher.write_text('#!/bin/sh\nroot=${0%/*}/..\n'
                        'unset LD_PRELOAD LD_LIBRARY_PATH PYTHONPATH PYTHONHOME PYTHONUSERBASE FONTCONFIG_PATH\n'
                        'exec "$root/lib/ld-linux-x86-64.so.2" --inhibit-cache --library-path "$root/lib" '
                        '"$root/bin/python3.14" -I -B "$root/gui_bootstrap.py" "$@"\n')
    launcher.chmod(0o755)
    json_file(bundle / 'provenance/release.json', release)
    json_file(bundle / 'provenance/source-files.json', release['source_files'])
    (bundle / 'licenses/RELEASE-NOTICE.txt').write_text(
        'Codex 0.162.0-alpha.17.2 and companion: LicenseRef-OpenAI-Proprietary; see Codex-LICENSE.\n'
        'Node 24.21.0 is the selected CUA build; see node-LICENSE and node-manifest.json.\n'
        'context-mode 1.0.169: Elastic License 2.0; runtime/context-mode/LICENSE and dependency licenses.\n'
        'WebUI2 2.5.8 wrapper and native WebUI: MIT; copyright Hassan Draga, '
        'https://github.com/webui-dev/webui and https://github.com/webui-dev/python-webui; '
        'see lib/python3.14/site-packages/webui2-2.5.8.dist-info/licenses/LICENSE.\n'
        'Selected native WebUI is an installed artifact, absent from wrapper RECORD; archive origin unestablished.\n'
        'Bash/readline/coreutils GPL-3.0-or-later; coreutils also GFDL-1.3-or-later. '
        'glibc LGPL-2.1-or-later/GPL-2.0-or-later; GCC libraries GPL-3.0-or-later '
        'with GCC Runtime Library Exception; ncurses license: licenses/release/.\n'
        'Package signature verification was not performed. Exact per-file provenance is in provenance/release.json.\n')


def build(inputs, output, *, source_root=None, native_lock=None, release=None):
    root = Path(source_root) if source_root else ROOT
    lock = native_lock if native_lock is not None else json.loads(LOCK.read_text())
    inputs, output = Path(inputs), Path(output)
    locked(inputs / lock['python_archive']['sha256'], lock['python_archive']['sha256'])
    for record in [*lock['files'].values(), *lock['wheels'], *lock.get('licenses', {}).values()]:
        locked(inputs / record['sha256'], record['sha256'])
    if output.exists() or output.with_suffix(output.suffix + '.sha256').exists():
        raise BundleError('destination_exists', 'Package output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ocr-build-', dir=output.parent) as temporary:
        bundle = Path(temporary) / 'rychvald-ocr'
        for directory in ('bin', 'lib/python3.14', 'native', 'tools', 'fonts', 'tessdata/configs', 'licenses', 'provenance'):
            (bundle / directory).mkdir(parents=True, exist_ok=True)
        manifest = json.loads((root / 'native/environment.json').read_text())
        manifest.update(root='.', build_id=lock['build_id'], profile='installed-linux-bundle',
                        library_dirs=['lib'], libraries={})
        manifest['python'].update(path='bin/python3.14', source=lock['python_archive']['source'])

        def copy_input(source, relative, executable=False):
            record = lock['files'][str(Path('/') / source)]
            target = bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(inputs / record['sha256'], target)
            target.chmod(0o755 if executable else 0o644)
            return record

        copy_input('/usr/bin/python3.14', 'bin/python3.14', True)
        with tarfile.open(inputs / lock['python_archive']['sha256']) as archive:
            for member in archive:
                prefix = 'usr/lib/python3.14/'
                if member.isfile() and member.name.startswith(prefix) and 'site-packages' not in Path(member.name).parts:
                    relative = Path(member.name[len(prefix):])
                    if relative.is_absolute() or '..' in relative.parts:
                        raise BundleError('unsafe_archive', 'Unsafe stdlib member')
                    target = bundle / 'lib/python3.14' / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
                    target.chmod(0o644)
                elif member.isfile() and member.name in ('.PKGINFO', '.BUILDINFO', 'usr/share/licenses/python/LICENSE'):
                    target = bundle / ('licenses/CPython-LICENSE' if member.name.endswith('/LICENSE') else 'provenance/python' + member.name)
                    target.write_bytes(archive.extractfile(member).read())
        for source, record in lock['files'].items():
            if source.startswith(('/usr/lib/', '/lib')):
                candidate = inputs / record['sha256']
                with candidate.open('rb') as stream:
                    elf = stream.read(4) == b'\x7fELF'
                if not elf:
                    continue
                relative = 'lib/' + Path(source).name
                target = bundle / relative
                if target.exists() and sha(target) != record['sha256']:
                    raise BundleError('basename_collision', f'Conflicting ELF basename: {source}')
                copy_input(source, relative, True)
                manifest['libraries'][Path(source).name] = {'path': relative, 'sha256': record['sha256'],
                                                           'source': f"locked-installed-file:{record['owner']}={record['version']}"}
        for category in ('models', 'fonts', 'configs'):
            for record in manifest[category].values():
                source = record['path']
                relative = ('tessdata/configs/' if category == 'configs' else 'tessdata/' if category == 'models' else 'fonts/') + Path(source).name
                copy_input(source, relative)
                record['path'] = relative
        manifest['tessdata'] = 'tessdata'
        for name, record in manifest['programs'].items():
            source = record['path']
            copy_input(source, 'native/' + name, True)
            manifest['libraries']['native/' + name] = {'path': 'native/' + name, 'sha256': record['sha256'], 'source': record['source']}
            wrapper = bundle / 'bin' / name
            wrapper.write_text('#!/bin/sh\nroot=${0%/*}/..\nunset LD_PRELOAD\nexec "$root/lib/ld-linux-x86-64.so.2" --inhibit-cache --library-path "$root/lib" "$root/native/' + name + '" "$@"\n')
            wrapper.chmod(0o755)
            record.update(path='bin/' + name, sha256=sha(wrapper))
        site = bundle / 'lib/python3.14/site-packages'
        site.mkdir()
        for wheel in lock['wheels']:
            with zipfile.ZipFile(inputs / wheel['sha256']) as archive:
                for name in archive.namelist():
                    parts = Path(name).parts
                    if name.endswith('/'):
                        continue
                    if '..' in parts or Path(name).is_absolute():
                        raise BundleError('unsafe_archive', 'Unsafe wheel member')
                    if any(part.endswith('.data') for part in parts):
                        if len(parts) >= 3 and parts[1] in ('purelib', 'platlib'):
                            name = '/'.join(parts[2:])
                        else:
                            continue  # CLI scripts/man pages unused by the OCR process.
                    payload = archive.read('/'.join(parts))
                    if name.endswith('.dist-info/RECORD'):
                        rows = [row for row in csv.reader(io.StringIO(payload.decode())) if not any(part.endswith('.data') for part in Path(row[0]).parts)]
                        stream = io.StringIO()
                        csv.writer(stream).writerows(rows)
                        payload = stream.getvalue().encode()
                    target = site / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                    target.chmod(0o644)
        for source in sorted((root / 'tools').glob('*.py')):
            shutil.copyfile(source, bundle / 'tools' / source.name)
        shutil.copyfile(root / 'native/bundle_bootstrap.py', bundle / 'bootstrap.py')
        launcher = bundle / 'bin/rychvald-ocr'
        launcher.write_text('#!/bin/sh\nroot=${0%/*}/..\nunset LD_PRELOAD LD_LIBRARY_PATH PYTHONPATH PYTHONHOME PYTHONUSERBASE FONTCONFIG_PATH\nexec "$root/lib/ld-linux-x86-64.so.2" --inhibit-cache --library-path "$root/lib" "$root/bin/python3.14" -I -B "$root/bootstrap.py" "$@"\n')
        launcher.chmod(0o755)
        json_file(bundle / 'environment.json', manifest)
        json_file(bundle / 'provenance/input-lock.json', lock)
        json_file(bundle / 'provenance/application-files.json',
                  {str(path.relative_to(root)): sha(path) for path in sorted((root / 'tools').glob('*.py'))})
        for source, record in lock.get('licenses', {}).items():
            locked(inputs / record['sha256'], record['sha256'])
            target = bundle / 'licenses' / source.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(inputs / record['sha256'], target)
        for source in sorted((root / 'native').glob('*LICENSE*')):
            shutil.copyfile(source, bundle / 'licenses' / source.name)
        # Canonical Apache license body has the exact pinned upstream Tesseract
        # and tessdata LICENSE hashes; retain attribution/source identities too.
        apache = lock.get('licenses', {}).get('/usr/share/licenses/qpdf/LICENSE.txt')
        if apache:
            for name in ('Tesseract-LICENSE', 'tessdata-LICENSE'):
                shutil.copyfile(inputs / apache['sha256'], bundle / 'licenses' / name)
        if release is not None:
            populate_release(bundle, inputs, root, release)
        inventory = {str(path.relative_to(bundle)): {'sha256': sha(path), 'executable': bool(path.stat().st_mode & 0o111)}
                     for path in sorted(bundle.rglob('*')) if path.is_file()}
        json_file(bundle / 'inventory.json', {'schema_version': 1, 'build_id': lock['build_id'], 'files': inventory})
        candidate = Path(temporary) / 'archive.tar.gz'
        with candidate.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w') as archive:
            for path in [bundle, *sorted(bundle.rglob('*'))]:
                info = archive.gettarinfo(path, arcname='rychvald-ocr' + ('/' + str(path.relative_to(bundle)) if path != bundle else ''))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                info.mode = 0o755 if path.is_dir() or bool(path.stat().st_mode & 0o111) else 0o644
                if path.is_file():
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
                else:
                    archive.addfile(info)
        digest = sha(candidate)
        candidate.rename(output)
        output.with_suffix(output.suffix + '.sha256').write_text(digest + '  ' + output.name + '\n')
    return {'archive': str(output.resolve()), 'sha256': digest, 'files': len(inventory), 'build_id': lock['build_id']}


def install(archive, expected, destination):
    archive, destination = Path(archive), Path(destination)
    if not archive.is_file() or sha(archive) != expected:
        raise BundleError('archive_mismatch', 'Archive SHA256 differs from the supplied expected hash')
    if destination.exists():
        raise BundleError('destination_exists', 'Installation destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ocr-install-', dir=destination.parent) as temporary:
        staging = Path(temporary)
        with tarfile.open(archive) as stream:
            for member in stream:
                name = Path(member.name)
                if (name.is_absolute() or '..' in name.parts or not name.parts or
                        name.parts[0] != 'rychvald-ocr' or not (member.isfile() or member.isdir())):
                    raise BundleError('unsafe_archive', f'Unsafe archive member: {member.name}')
                stream.extract(member, staging, filter='data')
        bundle = staging / 'rychvald-ocr'
        result = subprocess.run([str(bundle / 'bin/rychvald-ocr'), 'verify'], capture_output=True, text=True)
        if result.returncode:
            raise BundleError('installation_invalid', (result.stdout + result.stderr)[-1024:])
        # Refuse a race with another installer rather than replacing a user prefix.
        if destination.exists():
            raise BundleError('destination_exists', 'Installation destination appeared during verification')
        bundle.rename(destination)
    return {'installation': str(destination.resolve()), 'archive_sha256': expected}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    command = commands.add_parser('build')
    command.add_argument('--inputs', required=True)
    command.add_argument('--output', required=True)
    command = commands.add_parser('capture')
    command.add_argument('--inputs', required=True)
    command.add_argument('--wheel-cache', required=True)
    command.add_argument('--download', action='store_true')
    command = commands.add_parser('capture-release')
    command.add_argument('--selection', required=True)
    command.add_argument('--inputs', required=True)
    command = commands.add_parser('build-release')
    command.add_argument('--inputs', required=True)
    command.add_argument('--output', required=True)
    command = commands.add_parser('install')
    command.add_argument('--archive', required=True)
    command.add_argument('--sha256', required=True)
    command.add_argument('--destination', required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'capture-release':
            result = capture_release(args.inputs, args.selection)
        elif args.operation == 'build-release':
            result = build_release(args.inputs, args.output)
        elif args.operation == 'build':
            result = build(args.inputs, args.output)
        elif args.operation == 'capture':
            result = capture(args.inputs, args.wheel_cache, args.download)
        else:
            result = install(args.archive, args.sha256, args.destination)
        print(json.dumps({'operation': args.operation, 'status': 'completed', **result}))
        return 0
    except (BundleError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'operation': args.operation, 'status': 'failed', 'error':
                          {'code': getattr(error, 'code', 'package_failed'), 'message': str(error)[:1024]}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
