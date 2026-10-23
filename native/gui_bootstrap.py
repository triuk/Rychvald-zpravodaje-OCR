"""Guard the complete installation before importing application or WebUI code."""
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent


def main():
    try:
        bootstrap = runpy.run_path(str(ROOT / 'bootstrap.py'))
        bootstrap['verify']()
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        os.environ['RYCHVALD_BUNDLE_ROOT'] = str(ROOT)
        os.environ['RYCHVALD_CONTEXT_DESCRIPTOR'] = str(ROOT / 'native/bundled-context.json')
        os.environ['RYCHVALD_CODEX_RUNTIME'] = str(ROOT / 'runtime/codex/codex')
        for key in ('RYCHVALD_CONTEXT_BIN', 'RYCHVALD_CONTEXT_RUNTIME'):
            os.environ.pop(key, None)
        sys.path.insert(0, str(ROOT))
        sys.argv = [str(ROOT / 'main.py'), *sys.argv[1:]]
        # The installed entry always owns the OCR process path. Development-only
        # overrides would bypass its selected native manifest and are rejected.
        if any(arg.split('=')[0] in ('--ocr-executable', '--ocr-python') for arg in sys.argv[1:]):
            raise ValueError('Installed GUI selects its bundled OCR executable')
        sys.argv += ['--ocr-executable', str(ROOT / 'bin/rychvald-ocr')]
        runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
    except (ValueError, KeyError, OSError, ImportError) as error:
        print(json.dumps({'operation': 'gui', 'status': 'failed', 'error':
                          {'code': 'installation_invalid', 'message': str(error)[:1024]}}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main() or 0)
