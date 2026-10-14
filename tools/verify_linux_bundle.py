#!/usr/bin/env python3
"""Mandatory installed-package proof. Missing cache/bwrap/native support is failure."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def command(vector, **kwargs):
    result = subprocess.run(list(map(str, vector)), capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-6000:])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--artifacts', required=True)
    args = parser.parse_args()
    artifacts = Path(args.artifacts).resolve() / ('package-proof-' + uuid.uuid4().hex)
    artifacts.mkdir(parents=True)
    try:
        archive = artifacts / 'rychvald-ocr.tar.gz'
        built = json.loads(command([sys.executable, ROOT / 'tools/ocr_bundle.py', 'build',
                                    '--inputs', args.inputs, '--output', archive]).stdout)
        rebuilt = json.loads(command([sys.executable, ROOT / 'tools/ocr_bundle.py', 'build',
                                      '--inputs', args.inputs, '--output', artifacts / 'repeat.tar.gz']).stdout)
        if rebuilt['sha256'] != built['sha256']:
            raise RuntimeError('Identical locked inputs did not reproduce the same archive bytes')
        (artifacts / 'repeat.tar.gz').unlink()
        installed = artifacts / 'installed prefix ž'
        command([sys.executable, ROOT / 'tools/ocr_bundle.py', 'install', '--archive', archive,
                 '--sha256', built['sha256'], '--destination', installed])
        # Relocation is verified on the installation, before it enters isolation.
        relocated = artifacts / 'relocated prefix č'
        installed.rename(relocated)
        command([relocated / 'bin/rychvald-ocr', 'verify'])
        shutil.copyfile(ROOT / 'tests/bundle_workflow_fixture.py', artifacts / 'fixture.py')
        lock = json.loads((ROOT / 'native/bundle-inputs.json').read_text())
        shell = Path(args.inputs) / lock['files']['/usr/bin/bash']['sha256']
        shell_target = artifacts / 'declared-sh'
        shutil.copyfile(shell, shell_target)
        shell_target.chmod(0o755)
        work = artifacts / 'work'
        work.mkdir()
        vector = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
                  '--bind', relocated, '/app', '--bind', work, '/work',
                  '--ro-bind', artifacts / 'fixture.py', '/checks/fixture.py',
                  '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                  '--dir', '/bin', '--ro-bind', shell_target, '/bin/sh', '--symlink', '/app/lib', '/lib64',
                  '--setenv', 'LD_LIBRARY_PATH', '/app/lib', '--setenv', 'PATH', '/poisoned-path',
                  '--setenv', 'TESSDATA_PREFIX', '/wrong-models', '--setenv', 'PYTHONPATH', '/wrong-python',
                  '--setenv', 'PYTHONHOME', '/wrong-home', '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
                  '/app/lib/ld-linux-x86-64.so.2', '--inhibit-cache', '--library-path', '/app/lib',
                  '/app/bin/python3.14', '-I', '-B', '/checks/fixture.py']
        result = subprocess.run(list(map(str, vector)), capture_output=True, text=True)
        (artifacts / 'clean.stdout').write_text(result.stdout)
        (artifacts / 'clean.stderr').write_text(result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr)[-6000:])
        evidence = json.loads((work / 'package-evidence.json').read_text())
        evidence.update(status='completed', archive=str(archive), archive_sha256=built['sha256'],
                        installation=str(relocated), artifact_directory=str(artifacts), reproducible_archive=True)
        (artifacts / 'verification.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(json.dumps(evidence, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({'status': 'failed', 'artifacts': str(artifacts), 'error': str(error)[-6000:]}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
