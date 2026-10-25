"""Controlled provider supporting native resume of a thread with no submitted turn."""
import os
from pathlib import Path
import sys

fixtures = Path(__file__).resolve().parent
stage, marker = os.environ['PRESUBMIT_STAGE'], os.environ['PRESUBMIT_MARKER']
os.environ['RELEASE_REPAIR_REJECT' if stage == 'repair' else 'RELEASE_OUTPUT_REJECT'] = marker
sys.argv.insert(1, 'repair')
source = (fixtures / 'corrections_app_server_fixture.py').read_text()
geometry = (fixtures / 'geometry_app_server_fixture.py').read_text()
geometry = geometry.replace("method == 'thread/start'", "method in ('thread/start', 'thread/resume')")
geometry = geometry.replace("    elif method == 'turn/start':", """    elif method == 'thread/read':
        result = {'thread': {'id': params['threadId'], 'turns': [{'id': 'controlled-unfinished', 'status': 'inProgress'}]}}
    elif method == 'turn/start':""")
geometry = geometry.replace("        correction = 'CORRECTION_PACKET\\n' in prompt", """        correction = 'CORRECTION_PACKET\\n' in prompt
        delivery_path = Path(os.environ['PRESUBMIT_MARKER'] + '.delivery')
        target = correction if os.environ['PRESUBMIT_STAGE'] == 'repair' else output
        if target and delivery_path.exists():
            if delivery_path.read_text() == 'accepted':
                emit({'id': request['id'], 'result': {'turn': {'id': 'controlled-unfinished'}}})
            raise SystemExit(0)""")
source = source.replace("runpy.run_path(str(fixtures / 'geometry_app_server_fixture.py'), run_name='__main__')",
    "exec(compile(" + repr(geometry) + ", str(fixtures / 'geometry_app_server_fixture.py'), 'exec'))")
exec(compile(source, str(fixtures / 'corrections_app_server_fixture.py'), 'exec'))
