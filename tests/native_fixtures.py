"""Explicit native resource selection for public CLI integration fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil


def environment_path(root):
    return Path(os.environ.get('OCR_ENVIRONMENT', root / 'native/environment.json')).resolve()


def environment_manifest(root):
    """Make a mutable fixture copy without rebasing selected relative resources."""
    path = environment_path(root)
    manifest = json.loads(path.read_text())
    resource_root = Path(manifest.get('root', '.'))
    if not resource_root.is_absolute():
        resource_root = (path.parent / resource_root).resolve()

    def absolute(value):
        value = Path(value)
        return str(value if value.is_absolute() else resource_root / value)

    manifest['root'] = str(resource_root)
    manifest['python']['path'] = absolute(manifest['python']['path'])
    for category in ('programs', 'models', 'fonts', 'configs', 'libraries'):
        for record in manifest.get(category, {}).values():
            record['path'] = absolute(record['path'])
    manifest['tessdata'] = absolute(manifest['tessdata'])
    manifest['library_dirs'] = [absolute(value) for value in manifest.get('library_dirs', [])]
    return manifest


def bundle_source(root, directory):
    """Stage an explicit test lock for the unchanged public bundle CLI."""
    selected = Path(os.environ.get('OCR_BUNDLE_LOCK', root / 'native/bundle-inputs.json')).resolve()
    files = [*sorted((root / 'tools').glob('*.py')),
             *sorted(path for path in (root / 'native').rglob('*') if path.is_file()),
             root / 'tests/bundle_workflow_fixture.py']
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in files}
    snapshot = root
    if 'OCR_BUNDLE_LOCK' in os.environ:
        snapshot = directory / 'bundle-source'
        for category in ('tools', 'native'):
            shutil.copytree(root / category, snapshot / category,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (snapshot / 'tests').mkdir()
        shutil.copyfile(root / 'tests/bundle_workflow_fixture.py', snapshot / 'tests/bundle_workflow_fixture.py')
        (snapshot / 'native/bundle-inputs.json').write_bytes(selected.read_bytes())
        for name, expected in hashes.items():
            if name != 'native/bundle-inputs.json' and hashlib.sha256((snapshot / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Test source snapshot changed original bytes: ' + name)
    return snapshot, {'source_root': str(root), 'snapshot_root': str(snapshot),
                      'selected_lock': str(selected),
                      'selected_lock_sha256': hashlib.sha256(selected.read_bytes()).hexdigest(),
                      'source_files': hashes}
