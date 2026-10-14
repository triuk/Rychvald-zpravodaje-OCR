"""Installed runtime entry point; executable/import paths are confined to the bundle."""
from pathlib import Path
import hashlib
import json
import os
import runpy
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
os.environ['OCR_ENVIRONMENT'] = str(ROOT / 'environment.json')


def verify():
    inventory = json.loads((ROOT / 'inventory.json').read_text())
    expected = inventory['files']
    paths = list(ROOT.rglob('*'))
    if any(path.is_symlink() for path in paths):
        raise ValueError('Installation has unexpected symbolic links')
    actual = {str(path.relative_to(ROOT)) for path in paths if path.is_file()}
    if actual != set(expected) | {'inventory.json'}:
        raise ValueError('Installation has missing or unexpected files')
    for name, record in expected.items():
        path = ROOT / name
        if path.is_symlink() or not path.is_relative_to(ROOT):
            raise ValueError(f'Unexpected linked installation file: {name}')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != record['sha256'] or bool(path.stat().st_mode & 0o111) != record['executable']:
            raise ValueError(f'Changed installation file: {name}')
    from ocr_environment import verify_environment
    environment = verify_environment(ROOT / 'environment.json')
    # Real imports expose extension-library dependencies that doctor alone misses.
    import fitz
    import PIL.Image
    import numpy
    import lxml.etree
    import reportlab
    import fontTools
    import charset_normalizer
    for module in (fitz, PIL.Image, numpy, lxml.etree, reportlab, fontTools, charset_normalizer):
        if not Path(module.__file__).resolve().is_relative_to(ROOT):
            raise ValueError('Runtime imported a package outside installation')
    return {'build_id': inventory['build_id'], 'files': len(expected),
            'environment': environment.identity, 'python': sys.executable}


def main():
    operation = sys.argv[1] if len(sys.argv) > 1 else '--help'
    if operation == 'verify':
        try:
            print(json.dumps({'operation': 'verify', 'status': 'completed', **verify()}))
            return 0
        except (ValueError, KeyError, OSError, ImportError) as error:
            print(json.dumps({'operation': 'verify', 'status': 'failed',
                              'error': {'code': 'installation_invalid', 'message': str(error)[:1024]}}))
            return 1
    if operation == 'install':
        import ocr_bundle
        return ocr_bundle.main(sys.argv[1:])
    # Keep fontconfig independent of host config and relocation-safe. Nothing is
    # written into the read-only installation or project before native preflight.
    with tempfile.TemporaryDirectory(prefix='rychvald-fonts-') as cache:
        import xml.sax.saxutils
        config = Path(cache) / 'fonts.conf'
        fontdir = xml.sax.saxutils.escape(str(ROOT / 'fonts'))
        cachedir = xml.sax.saxutils.escape(cache)
        config.write_text(f'<?xml version="1.0"?><fontconfig><dir>{fontdir}</dir><cachedir>{cachedir}</cachedir></fontconfig>')
        os.environ['FONTCONFIG_FILE'] = str(config)
        if operation == 'workflow':
            sys.argv = [str(ROOT / 'tools/ocr_workflow.py'), *sys.argv[2:]]
            runpy.run_path(sys.argv[0], run_name='__main__')
        else:
            import ocr_projects
            return ocr_projects.main(sys.argv[1:])


if __name__ == '__main__':
    sys.exit(main() or 0)
