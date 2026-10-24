"""Controlled transport faults for correction output descendants; never actual AI."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

fixtures = Path(__file__).resolve().parent


def owned_application():
    sys.path.insert(0, str(fixtures.parent))
    from app.service import Application
    marker = Path(sys.argv[5])
    fault = sys.argv[6] if len(sys.argv) > 6 else 'link'

    def crash_before_link(event, arguments):
        if event != 'os.rename':
            return
        source, destination = (Path(os.fsdecode(value)) for value in arguments[:2])
        if fault == 'terminal':
            if (destination.name != 'publication-proposal.json' or destination.parent.parent.name != 'output-review-attempts'):
                return
            output_path = destination.parent / 'attempt.json'
            output = json.loads(output_path.read_text())
            binding = output.get('parent_binding') or {}
            if binding.get('stage') != 'correction_output_review':
                return
            work = destination.parents[3]
            correction_path = work / 'application/correction-attempts' / binding['correction_attempt_id'] / 'attempt.json'
            marker.write_text(json.dumps({'boundary': 'completed_output_before_publication',
                'correction_attempt_id': binding['correction_attempt_id'], 'output_attempt_id': output['attempt_id'],
                'cycle_id': binding['cycle_id'], 'parent_binding': binding,
                'original_correction_sha256': hashlib.sha256(correction_path.read_bytes()).hexdigest()}))
            os._exit(91)
        if (destination.name != 'attempt.json' or destination.parent.parent.name != 'correction-attempts' or
                not source.is_file() or not destination.is_file()):
            return
        old, new = json.loads(destination.read_text()), json.loads(source.read_text())
        links = [row for row in new.get('children', []) if row['stage'] == 'output_review']
        if old.get('children') or len(links) != 1:
            return
        work = destination.parents[3]
        output_path = work / 'application/output-review-attempts' / links[0]['attempt_id'] / 'attempt.json'
        output = json.loads(output_path.read_text())
        marker.write_text(json.dumps({'boundary': 'output_manifest_before_parent_link',
            'correction_attempt_id': new['attempt_id'], 'output_attempt_id': output['attempt_id'],
            'cycle_id': links[0]['cycle_id'], 'parent_binding': output['parent_binding'],
            'original_correction_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}))
        os._exit(91)

    sys.addaudithook(crash_before_link)
    application = Application(Path(sys.argv[2]), codex_runtime=json.loads(Path(sys.argv[3]).read_text()),
        context_runtime=json.loads(Path(sys.argv[4]).read_text()),
        process_command=[sys.executable, '-B', str(fixtures.parent / 'tools/ocr_projects.py')])
    try:
        for raw in sys.stdin:
            request = json.loads(raw)
            print(json.dumps(application.dispatch(request['operation'], request.get('payload'))), flush=True)
    finally:
        application.close()


if sys.argv[1] == '--owner':
    raise SystemExit(owned_application())

mode = sys.argv.pop(1)
original_stdin = sys.stdin
original_stdout = sys.stdout
output_request_id = None


def correction_binding():
    manifest = Path.cwd().parents[1] / 'attempt.json'
    return (json.loads(manifest.read_text()).get('parent_binding') or {}) if manifest.exists() else {}


class ControlledInput:
    def __iter__(self):
        global output_request_id
        for raw in original_stdin:
            request = json.loads(raw)
            if request.get('method') == 'thread/read' and mode == 'accepted':
                print(json.dumps({'id': request['id'], 'result': {'thread': {
                    'id': request['params']['threadId'], 'turns': [{'id': 'owned-output-turn', 'status': 'completed'}]}}}), flush=True)
                continue
            binding = correction_binding()
            owned_output = request.get('method') == 'turn/start' and binding.get('stage') == 'correction_output_review'
            if owned_output:
                output_request_id = request['id']
            if owned_output and mode in ('unknown', 'accepted', 'foreign_started', 'quota', 'authentication', 'network'):
                def emit(message):
                    print(json.dumps(message), flush=True)
                if mode in ('quota', 'authentication', 'network'):
                    variant = {'quota': 'usageLimitExceeded', 'authentication': 'unauthorized',
                        'network': 'httpConnectionFailed'}[mode]
                    emit({'id': request['id'], 'error': {'code': -32000,
                        'message': 'Controlled correction output rejection',
                        'data': {'codexErrorInfo': variant}}})
                else:
                    if mode == 'accepted':
                        emit({'id': request['id'], 'result': {'turn': {'id': 'owned-output-turn'}}})
                    if mode == 'foreign_started':
                        emit({'method': 'turn/started', 'params': {'threadId': request['params']['threadId'],
                            'turn': {'id': 'foreign-turn', 'status': 'inProgress'}}})
                    # Delayed notification for another thread/turn must not settle
                    # this request, even on the same provider connection.
                    emit({'method': 'turn/completed', 'params': {'threadId': request['params']['threadId'] if mode in ('accepted', 'foreign_started') else 'foreign-thread',
                        'turn': {'id': 'foreign-turn', 'status': 'completed'}}})
                raise SystemExit(0)
            yield raw


class ControlledOutput:
    def __init__(self):
        self.pending = ''

    def write(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            message = json.loads(line)
            lines = [line]
            if (mode == 'completed_late_started' and correction_binding().get('stage') == 'correction_output_review' and
                    message.get('method') == 'turn/completed' and message['params']['turn']['status'] == 'completed'):
                # A duplicate terminal and duplicate correlated ACK remain terminal;
                # an out-of-order started notification cannot reopen the same turn.
                lines.extend([line, json.dumps({'id': output_request_id, 'result': {'turn': {'id': message['params']['turn']['id']}}}),
                    json.dumps({'method': 'turn/started', 'params': message['params']})])
            original_stdout.write('\n'.join(lines) + '\n')
        return len(text)

    def flush(self):
        original_stdout.flush()


sys.stdin = ControlledInput()
if mode == 'completed_late_started':
    sys.stdout = ControlledOutput()
sys.argv.insert(1, 'repair')
runpy.run_path(str(fixtures / 'corrections_app_server_fixture.py'), run_name='__main__')
