"""Public application owner killed at a real unsubmitted preparation boundary."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application

marker = Path(sys.argv[4])
boundary = sys.argv[5]


def crash(event, args):
    if marker.exists():
        return
    if boundary == 'directory' and event == 'os.mkdir':
        path = Path(os.fsdecode(args[0]))
        if path.name != 'workspace' or not path.parent.name.startswith('continuation-'):
            return
        physical = path.parent
    elif boundary == 'intent' and event == 'os.rename':
        source, target = [Path(os.fsdecode(p)) for p in args[:2]]
        if target.name != 'attempt.json' or not source.is_file():
            return
        value = json.loads(source.read_text())
        reserved = [c for c in value.get('continuations', []) if c.get('successor')]
        if not reserved:
            return
        physical = Path(reserved[-1]['successor']['request']['path']).parent
        if not (physical / 'submission-intent.json').exists():
            return
    else:
        return
    marker.write_text(json.dumps({'boundary': boundary, 'directory': str(physical),
        'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19],
        'pid_namespace': os.readlink('/proc/self/ns/pid'), 'mount_namespace': os.readlink('/proc/self/ns/mnt')}))
    os._exit(91)


sys.addaudithook(crash)
application = Application(Path(sys.argv[1]), codex_runtime=json.loads(Path(sys.argv[2]).read_text()),
    context_runtime=json.loads(Path(sys.argv[3]).read_text()))
try:
    for raw in sys.stdin:
        request = json.loads(raw)
        print(json.dumps(application.dispatch(request['operation'], request.get('payload'))), flush=True)
finally:
    application.close()
