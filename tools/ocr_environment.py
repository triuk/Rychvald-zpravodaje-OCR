"""Verification and resource selection for the native OCR environment."""
from pathlib import Path
import json
import os
import subprocess
import platform
import hashlib
import importlib.metadata
import importlib.util
import sys

from ocr_quality import sha

DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / 'native/environment.json'


def verify_environment(path=None, language='ces'):
    path = Path(path or os.environ.get('OCR_ENVIRONMENT', DEFAULT_MANIFEST)).resolve()
    if not path.is_file():
        raise ValueError(f'Missing environment manifest: {path}')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    environment = NativeEnvironment(path, manifest)
    environment.verify(language)
    return environment


class NativeEnvironment:
    """Verified handles; resolving a program never consults PATH."""

    def __init__(self, path, manifest):
        self.path, self.manifest = path, manifest
        root = Path(manifest.get('root', '.'))
        self.root = root if root.is_absolute() else (path.parent / root).resolve()
        self.build_id = manifest['build_id']
        self.identity = {'build_id': self.build_id, 'manifest_sha256': sha(path)}
        self.env = os.environ.copy()
        self.env['TESSDATA_PREFIX'] = str(self.resolve(manifest['tessdata']))
        self.env.pop('LD_PRELOAD', None)
        self.env.pop('LD_LIBRARY_PATH', None)
        if manifest.get('library_dirs'):
            self.env['LD_LIBRARY_PATH'] = ':'.join(str(self.resolve(p)) for p in manifest['library_dirs'])

    def resolve(self, path):
        path = Path(path)
        return path if path.is_absolute() else self.root / path

    def command(self, command):
        return [str(self.resolve(self.manifest['programs'][command[0]]['path'])), *map(str, command[1:])]

    def run(self, command):
        return subprocess.run(self.command(command), capture_output=True, text=True, env=self.env)

    def check_file(self, name, record):
        path = self.resolve(record['path'])
        if not path.is_file():
            raise ValueError(f'Missing resource: {name} ({path})')
        if sha(path) != record['sha256']:
            raise ValueError(f'Changed content: {name} ({path})')

    def verify(self, language):
        m = self.manifest
        if m['schema_version'] != 1:
            raise ValueError('Unsupported environment schema')
        if platform.system() != m['platform']['system'] or platform.machine() != m['platform']['machine']:
            raise ValueError('Unsupported platform: expected Linux x86_64')
        runtime = m['python']
        if platform.python_version() != runtime['version']:
            raise ValueError(f'Wrong version: Python (expected {runtime["version"]})')
        self.check_file('Python', runtime)
        if sha(Path(sys._base_executable)) != runtime['sha256']:
            raise ValueError('Wrong runtime: active Python executable differs from manifest')
        for name, record in m['programs'].items():
            executable = self.resolve(record['path'])
            if not executable.is_file():
                raise ValueError(f'Missing resource: {name} ({executable})')
            # Check bytes before running even a version probe.
            self.check_file(name, record)
            result = self.run([name, '--version' if name in ('tesseract', 'qpdf') else '-v'])
            lines = (result.stdout + result.stderr).splitlines()
            if result.returncode or not lines or lines[0] != record['version']:
                raise ValueError(f'Wrong version: {name} (expected {record["version"]})')
        for category in ('models', 'fonts', 'configs', 'libraries'):
            for name, record in m.get(category, {}).items():
                self.check_file(f'{category}/{name}', record)
        for name in language.split('+'):
            if name not in m['models']:
                raise ValueError(f'Missing resource: model/{name}')
            expected = self.resolve(m['tessdata']) / (name + '.traineddata')
            if expected.resolve() != self.resolve(m['models'][name]['path']).resolve():
                raise ValueError(f'Model outside configured tessdata: {name}')
        for name in ('hocr', 'tsv', 'txt', 'makebox'):
            if name not in m['configs']:
                raise ValueError(f'Missing resource: config/{name}')
            expected = self.resolve(m['tessdata']) / 'configs' / name
            if expected.resolve() != self.resolve(m['configs'][name]['path']).resolve():
                raise ValueError(f'Config outside configured tessdata: {name}')
        for name, record in m['packages'].items():
            try:
                distribution = importlib.metadata.distribution(name)
            except importlib.metadata.PackageNotFoundError as error:
                raise ValueError(f'Missing resource: Python package/{name}') from error
            if distribution.version != record['version']:
                raise ValueError(f'Wrong version: Python package/{name} (expected {record["version"]})')
            digest = hashlib.sha256()
            files = sorted(f for f in distribution.files or [] if '..' not in f.parts and '__pycache__' not in f.parts
                           and not any(str(p).endswith('.dist-info') for p in f.parts))
            if not files:
                raise ValueError(f'Missing contents: Python package/{name}')
            for file in files:
                actual = distribution.locate_file(file)
                if not actual.is_file():
                    raise ValueError(f'Missing resource: Python package/{name}/{file}')
                digest.update(str(file).encode() + b'\0' + bytes.fromhex(sha(actual)))
            if digest.hexdigest() != record['tree_sha256']:
                raise ValueError(f'Changed content: Python package/{name}')
            module = {'PyMuPDF': 'fitz', 'Pillow': 'PIL', 'fonttools': 'fontTools',
                      'charset-normalizer': 'charset_normalizer'}.get(name, name)
            spec = importlib.util.find_spec(module)
            allowed = {distribution.locate_file(file).resolve() for file in files}
            if spec is None or spec.origin is None or Path(spec.origin).resolve() not in allowed:
                raise ValueError(f'Wrong import location: {name}')

    def report(self):
        return {'ok': True, **self.identity, 'manifest': str(self.path), 'python': sys.version,
                'executable': sys.executable,
                'checks': {name: {'ok': True, 'path': str(self.resolve(record['path'])), 'version': record.get('version'),
                                  'sha256': record['sha256']}
                           for category in ('programs', 'models', 'fonts') for name, record in self.manifest[category].items()}}
