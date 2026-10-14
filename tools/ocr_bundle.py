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


def build(inputs, output):
    lock = json.loads(LOCK.read_text())
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
        manifest = json.loads((ROOT / 'native/environment.json').read_text())
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
        for source in sorted((ROOT / 'tools').glob('*.py')):
            shutil.copyfile(source, bundle / 'tools' / source.name)
        shutil.copyfile(ROOT / 'native/bundle_bootstrap.py', bundle / 'bootstrap.py')
        launcher = bundle / 'bin/rychvald-ocr'
        launcher.write_text('#!/bin/sh\nroot=${0%/*}/..\nunset LD_PRELOAD LD_LIBRARY_PATH PYTHONPATH PYTHONHOME PYTHONUSERBASE FONTCONFIG_PATH\nexec "$root/lib/ld-linux-x86-64.so.2" --inhibit-cache --library-path "$root/lib" "$root/bin/python3.14" -I -B "$root/bootstrap.py" "$@"\n')
        launcher.chmod(0o755)
        json_file(bundle / 'environment.json', manifest)
        json_file(bundle / 'provenance/input-lock.json', lock)
        json_file(bundle / 'provenance/application-files.json',
                  {str(path.relative_to(ROOT)): sha(path) for path in sorted((ROOT / 'tools').glob('*.py'))})
        for source, record in lock.get('licenses', {}).items():
            locked(inputs / record['sha256'], record['sha256'])
            target = bundle / 'licenses' / source.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(inputs / record['sha256'], target)
        for source in sorted((ROOT / 'native').glob('*LICENSE*')):
            shutil.copyfile(source, bundle / 'licenses' / source.name)
        # Canonical Apache license body has the exact pinned upstream Tesseract
        # and tessdata LICENSE hashes; retain attribution/source identities too.
        apache = lock.get('licenses', {}).get('/usr/share/licenses/qpdf/LICENSE.txt')
        if apache:
            for name in ('Tesseract-LICENSE', 'tessdata-LICENSE'):
                shutil.copyfile(inputs / apache['sha256'], bundle / 'licenses' / name)
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
    command = commands.add_parser('install')
    command.add_argument('--archive', required=True)
    command.add_argument('--sha256', required=True)
    command.add_argument('--destination', required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'build':
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
