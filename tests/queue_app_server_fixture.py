"""Controlled quota recovery backend; never actual provider evidence."""
from pathlib import Path
import runpy
import sys

state = sys.argv[1]
if Path('image.png').exists():
    sys.argv = [sys.argv[0], 'queue_quota', state, *sys.argv[2:]]
    runpy.run_path(str(Path(__file__).with_name('codex_app_server_fixture.py')), run_name='__main__')
else:
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    runpy.run_path(str(Path(__file__).with_name('autonomous_app_server_fixture.py')), run_name='__main__')
