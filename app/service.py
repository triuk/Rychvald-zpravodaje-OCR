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

from tools.ocr_profiles import ProfileError, load_profile, run_name as validate_run_name
from .jobs import JobError, PreparationJobs, read_history
from .codex import CodexJobs


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

    def __init__(self, root, *, process_command=None, codex_runtime=None):
        self.root = Path(root).expanduser().resolve()
        self.process = OcrProcess(process_command)
        self._lock = threading.RLock()
        self._events = deque(maxlen=1000)
        self._sequence = 0
        self.preparation = PreparationJobs(self.process.command, self.publish)
        self.codex = CodexJobs(self.publish, codex_runtime)

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
                elif operation == 'import_sources':
                    data = self.import_sources(payload.get('path'))
                elif operation == 'inspect_profile':
                    data = self.inspect_profile(payload.get('path'))
                elif operation == 'create_run':
                    data = self.create_run(payload)
                elif operation == 'start_preparation':
                    data = self.start_preparation(payload)
                elif operation == 'preparation_status':
                    data = self.preparation_status(payload.get('run_id'))
                elif operation == 'start_model_diagnostic':
                    data = self.start_model_diagnostic(payload)
                elif operation == 'model_diagnostic_status':
                    data = self.model_diagnostic_status(payload.get('run_id'))
                elif operation in ('check_codex_account', 'start_codex_login'):
                    data = self.start_model_diagnostic(payload, operation='check_account' if operation == 'check_codex_account' else 'login')
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
            except (ProfileError, JobError) as error:
                return {'ok': False, 'data': None,
                        'error': {'code': error.code, 'message': str(error)},
                        'event_cursor': self._sequence}

    def publish(self, event_type, **data):
        with self._lock:
            self._sequence += 1
            self._events.append({'sequence': self._sequence, 'type': event_type, **data})

    def open_registry(self, root):
        if self.preparation.busy() or self.codex.busy():
            raise ApplicationError('operation_active', 'A preparation or Codex operation is active; wait before opening another registry.')
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

    def import_sources(self, path):
        if not isinstance(path, str) or not path.strip():
            raise ApplicationError('invalid_request', 'Choose a source PDF or directory.')
        source = Path(path).expanduser().resolve()
        try:
            if not source.exists():
                raise ApplicationError('source_missing', 'Source PDF or directory does not exist.')
            files = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == '.pdf') if source.is_dir() else [source]
            if not files:
                raise ApplicationError('source_empty', 'Directory contains no PDF files.')
            # Validate every selected input before the process can publish any
            # project. A bad last PDF must not cause a partial folder import.
            for pdf in files:
                if not pdf.is_file() or pdf.suffix.lower() != '.pdf':
                    raise ApplicationError('invalid_source', 'Source must be a PDF file.')
                with pdf.open('rb') as stream:
                    if b'%PDF-' not in stream.read(1024):
                        raise ApplicationError('invalid_source', f'Source has no PDF header: {pdf.name}')
        except OSError as error:
            raise ApplicationError('source_unreadable', str(error)) from None
        result = self.process.request(self.root, 'import', source)
        counts = {'sources': len(files), **result['counts']}
        data = self.projects()
        self.publish('sources_imported', **counts)
        return {**data, 'counts': counts}

    def inspect_profile(self, path):
        return load_profile(path)

    def create_run(self, payload):
        name = validate_run_name(payload.get('name'))
        expected = payload.get('profile_sha256')
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise ApplicationError('invalid_request', 'Inspect the profile before creating a run.')
        profile = load_profile(payload.get('profile_path'), expected_sha256=expected)
        edition_id = payload.get('edition_id')
        editions = self.projects()['editions']
        edition = next((item for item in editions if item['edition_id'] == edition_id), None)
        if edition is None:
            raise ApplicationError('edition_not_found', 'Choose an existing edition before creating a run.')
        representative = self.process.request(self.root, 'status', edition['runs'][0]['run_id'])
        source = self.root / representative['artifacts']['source']
        result = self.process.request(self.root, 'import', source, '--new-run',
                                      '--run-name=' + name, '--profile=' + profile['path'],
                                      '--profile-sha256=' + profile['sha256'], '--source-sha256=' + edition_id)
        run_id = result['project']['run_id']
        self.publish('run_created', run_id=run_id, edition_id=edition_id)
        return self.select_run(run_id)

    def start_preparation(self, payload):
        if self.preparation.busy() or self.codex.busy():
            raise ApplicationError('operation_active', 'A preparation or Codex operation is already active.')
        run = self.select_run(payload.get('run_id'))
        if 'run' not in run:
            raise ApplicationError('run_profile_required', 'Create a named run with a profile before starting preparation.')
        if run['project']['operation_state'] == 'running':
            raise ApplicationError('project_busy', 'Another process is active for this run.')
        parameters = run['run']['profile']['parameters']
        if any(key in payload and payload[key] != parameters[key] for key in ('dpi', 'language')):
            raise ApplicationError('configuration_changed', 'Create an explicit new named run to change profile parameters.')
        environment = payload.get('environment')
        if environment is not None:
            if not isinstance(environment, str) or not environment.strip():
                raise ApplicationError('invalid_request', 'Environment manifest must be a file path.')
            environment = str(Path(environment).expanduser().resolve())
        return self.preparation.start(self.root, run, environment)

    def preparation_status(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ApplicationError('invalid_request', 'Choose an OCR run.')
        result = self.process.request(self.root, 'status', run_id)
        work = self.root / result['artifacts']['workspace']
        return self.preparation.status(self.root, run_id, work)

    def close(self):
        self.preparation.close()
        self.codex.close()

    def start_model_diagnostic(self, payload, operation='vision_diagnostic'):
        if self.preparation.busy() or self.codex.busy():
            raise ApplicationError('operation_active', 'Another preparation or Codex operation is active.')
        run = self.select_run(payload.get('run_id'))
        if 'run' not in run:
            raise ApplicationError('run_profile_required', 'Create a named run with a profile before image diagnostics.')
        if run['project']['operation_state'] == 'running':
            raise ApplicationError('project_busy', 'Another process is active for this run.')
        try:
            return self.codex.start(self.root, run, payload.get('image_path'), operation)
        except OSError as error:
            raise ApplicationError('diagnostic_artifact_failed', f'Cannot preserve diagnostic input: {error}') from None

    def model_diagnostic_status(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ApplicationError('invalid_request', 'Choose an OCR run.')
        result = self.process.request(self.root, 'status', run_id)
        return self.codex.status(self.root, run_id, self.root / result['artifacts']['workspace'])

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
        if 'run_manifest' in artifacts:
            try:
                if not all(artifacts[name]['available'] for name in ('run_manifest', 'profile_snapshot', 'history')):
                    raise ValueError('Named run artifacts are missing or outside the registry.')
                manifest = json.loads((self.root / artifacts['run_manifest']['path']).read_text(encoding='utf-8'))
                profile = load_profile(self.root / artifacts['profile_snapshot']['path'],
                                       expected_sha256=manifest['profile_sha256'])
                if manifest['run_id'] != run_id or manifest['edition_id'] != data['edition_id']:
                    raise ValueError('Run manifest identity differs from the registered run.')
                history = read_history(self.root / artifacts['history']['path'])
                data.update(run={**manifest, 'profile': profile['profile']}, history=history)
            except (OSError, ValueError, KeyError, TypeError, ProfileError) as error:
                raise ApplicationError('run_metadata_invalid', f'Cannot load named run metadata: {error}') from None
        self.publish('run_selected', run_id=run_id, edition_id=data['edition_id'])
        return data
