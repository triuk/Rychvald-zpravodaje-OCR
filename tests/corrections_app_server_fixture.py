"""Synthetic external peer; AXC is a deliberate OCR error over the known ABC scan."""
from pathlib import Path
import sys

fixtures = Path(__file__).resolve().parent
mode = sys.argv[1]
if Path('reading-packet.json').exists():
    source = (fixtures / 'reading_app_server_fixture.py').read_text()
    source = source.replace("'ABC' if number == 1 else 'DEF'", "'AXC' if number == 1 else 'DEF'")
    if mode == 'publisher':
        record = [{'id': 'controlled-publisher-entry', 'line': 'line-1', 'printed': 'AXC',
            'explanation': 'Explicit controlled registry input, not a real publisher judgment', 'status': 'confirmed',
            'source_crop': 'raster/page-1.png', 'bbox': [0, 0, 90, 20]}]
        source = source.replace('            source_answer = ', '            review["publisher_errors"] = ' + repr(record) + '\n            source_answer = ')
    sys.argv.insert(1, 'full_run')
    exec(compile(source, str(fixtures / 'reading_app_server_fixture.py'), 'exec'))
else:
    import runpy
    if Path('diagnostic-data.txt').exists() or Path('image.png').exists():
        runpy.run_path(str(fixtures / 'autonomous_app_server_fixture.py'), run_name='__main__')
    else:
        sys.argv.insert(1, mode)
        runpy.run_path(str(fixtures / 'geometry_app_server_fixture.py'), run_name='__main__')
