"""Controlled peer for the full public action; never genuine model evidence."""
from pathlib import Path
import runpy
import sys

fixtures = Path(__file__).resolve().parent
peer_mode = next((value for value in sys.argv[1:] if value in
    ('waive_output', 'drop_output', 'template_output', 'tamper_output', 'tamper_geometry',
     'absolute_input_evidence', 'outside_evidence', 'repair_context_routing')), 'full_run')
if Path('reading-packet.json').exists():
    filename, mode = 'reading_app_server_fixture.py', 'full_run'
elif Path('diagnostic-data.txt').exists():
    # The context peer is the sole owner of its explicitly controlled stores.
    filename, mode = 'context_app_server_fixture.py', 'repair_redirect' if peer_mode == 'repair_context_routing' else 'autonomous_protocol'
elif Path('image.png').exists():
    filename, mode = 'codex_app_server_fixture.py', 'success'
else:
    filename, mode = 'geometry_app_server_fixture.py', 'full_run' if peer_mode == 'repair_context_routing' else peer_mode
sys.argv.insert(1, mode)
runpy.run_path(str(fixtures / filename), run_name='__main__')
