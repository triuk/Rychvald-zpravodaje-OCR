"""Public application boundary used by both WebUI and integration scenarios.

Existing version 1 projects represent individual OCR runs. Editions are a read
view grouped by the complete source hash; opening the GUI never migrates data.
The OCR implementation stays behind its existing subprocess JSON protocol.
"""

from collections import deque
import json
from pathlib import Path
import subprocess
import sys
import threading


class ApplicationError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class OcrProcess:
    """Version 1 process client; command is an argument list, never shell text."""

    def __init__(self, command=None):
        self.command = list(command) if command else [
            sys.executable, str(Path(__file__).resolve().parents[1] / 'tools/ocr_projects.py')]

    def request(self, root, *arguments):
        try:
            result = subprocess.run(
                [*self.command, '--root', str(root), '--json', *map(str, arguments)],
                capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise ApplicationError('ocr_timeout', 'OCR process did not answer in time.') from None
        except OSError as error:
            raise ApplicationError('ocr_unavailable', str(error)) from None
        try:
            value = json.loads(result.stdout)
            if not isinstance(value, dict) or value.get('protocol_version') != 1:
                raise ValueError()
            if value.get('error'):
                raise ApplicationError(value['error']['code'], value['error']['message'])
            if result.returncode or value.get('status') != 'completed':
                raise ValueError()
            return value
        except (ValueError, KeyError, TypeError):
            raise ApplicationError('ocr_protocol_invalid', 'OCR process returned an invalid version 1 response.') from None


class Application:
    """Synchronous queries; long running work belongs in separate workers.

    dispatch() is the GUI's only request seam. Each response carries a stable
    error code and an event cursor. events(after) returns changes since a cursor.
    """

    def __init__(self, root, *, process_command=None):
        self.root = Path(root).expanduser().resolve()
        self.process = OcrProcess(process_command)
        self._lock = threading.RLock()
        self._events = deque(maxlen=1000)
        self._sequence = 0

    def dispatch(self, operation, payload=None):
        with self._lock:
            try:
                if not isinstance(payload, (dict, type(None))):
                    raise ApplicationError('invalid_request', 'Request payload must be an object.')
                payload = payload or {}
                if operation == 'projects':
                    data = self.projects()
                elif operation == 'open_registry':
                    data = self.open_registry(payload.get('root'))
                elif operation == 'select_run':
                    data = self.select_run(payload.get('run_id'))
                elif operation == 'events':
                    after = payload.get('after', 0)
                    if not isinstance(after, int) or isinstance(after, bool) or after < 0:
                        raise ApplicationError('invalid_request', 'Event cursor must be a nonnegative integer.')
                    data = {'events': [dict(event) for event in self._events if event['sequence'] > after],
                            'reset': bool(self._events and after < self._events[0]['sequence'] - 1)}
                else:
                    raise ApplicationError('unknown_operation', 'Unknown application operation.')
                return {'ok': True, 'data': data, 'error': None, 'event_cursor': self._sequence}
            except ApplicationError as error:
                return {'ok': False, 'data': None,
                        'error': {'code': error.code, 'message': str(error)},
                        'event_cursor': self._sequence}

    def publish(self, event_type, **data):
        self._sequence += 1
        self._events.append({'sequence': self._sequence, 'type': event_type, **data})

    def open_registry(self, root):
        if not isinstance(root, str) or not root.strip():
            raise ApplicationError('invalid_request', 'Choose the OCR registry directory.')
        candidate = Path(root).expanduser().resolve()
        if not candidate.is_dir():
            raise ApplicationError('registry_missing', 'OCR registry directory does not exist.')
        previous = self.root
        self.root = candidate
        try:
            return self.projects()
        except ApplicationError:
            self.root = previous
            raise

    def projects(self):
        editions = {}
        offset = 0
        while offset is not None:
            result = self.process.request(self.root, 'list', '--offset', offset, '--limit', 100)
            for run in result['projects']:
                digest = run['source_sha256']
                edition = editions.setdefault(digest, {
                    'edition_id': digest, 'source_sha256': digest,
                    'name': run['original_name'], 'names': [], 'runs': []})
                if run['original_name'] not in edition['names']:
                    edition['names'].append(run['original_name'])
                edition['runs'].append(run)
            next_offset = result['next_offset']
            if next_offset is not None and (not isinstance(next_offset, int) or next_offset <= offset):
                raise ApplicationError('ocr_protocol_invalid', 'OCR list did not advance its page cursor.')
            offset = next_offset
        self.publish('projects_changed', edition_count=len(editions))
        return {'root': str(self.root), 'editions': list(editions.values())}

    def select_run(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ApplicationError('invalid_request', 'Choose an OCR run.')
        result = self.process.request(self.root, 'status', run_id)
        artifacts = {}
        for name, relative_path in result['artifacts'].items():
            path = (self.root / relative_path).resolve()
            # Legacy metadata is user data. Do not expose outside-root links.
            safe = path.is_relative_to(self.root)
            artifacts[name] = {'path': relative_path, 'available': safe and path.exists(),
                               'kind': 'directory' if safe and path.is_dir() else 'file'}
        data = {'edition_id': result['project']['source_sha256'],
                'project': result['project'], 'counts': result['counts'], 'artifacts': artifacts}
        self.publish('run_selected', run_id=run_id, edition_id=data['edition_id'])
        return data
