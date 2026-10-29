"""Public application boundary used by both WebUI and integration scenarios.

Existing version 1 projects represent individual OCR runs. Editions are a read
view grouped by the complete source hash; opening the GUI never migrates data.
The OCR implementation stays behind its existing subprocess JSON protocol.
"""

from collections import deque
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from tools.ocr_profiles import ProfileError, load_profile, run_name as validate_run_name
from .jobs import JobError, PreparationJobs, read_history, atomic_json
from .codex import CodexJobs, process_identity
from .context import ContextJobs
from .reading import ReadingJobs
from .geometry import GeometryJobs
from .output_review import OutputReviewJobs
from .autonomous import AutonomousJobs
from .corrections import CorrectionJobs
from .run_queue import RunQueue
from .preferences import Preferences
from .model_capabilities import ModelCapabilities


class ApplicationError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class OcrProcess:
    """Version 1 process client; command is an argument list, never shell text."""

    def __init__(self, command=None):
        self.command = list(command) if command else [
            sys.executable, str(Path(__file__).resolve().parents[1] / 'tools/ocr_projects.py')]
        self._owner = threading.local()

    def bind_owner(self, job):
        self._owner.job = job

    def release_owner(self):
        self._owner.job = None

    def request(self, root, *arguments, allowed_returncodes=(0,), timeout=30, cancelled=None, owned=None):
        job = getattr(self._owner, 'job', None)
        if job is not None and cancelled is None:
            cancelled = lambda: job['cancel']

            def owned(process):
                job['manifest'].setdefault('native_processes', []).append({'pid': process.pid,
                    'process_group': process.pid, 'process_start_ticks': process_identity(process.pid),
                    'operation': str(arguments[0])})
                atomic_json(job['directory'] / 'attempt.json', job['manifest'])
        if cancelled is not None and cancelled():
            raise ApplicationError('operation_cancelled', 'Application stopped before native work was admitted.')
        try:
            command = [*self.command, '--root', str(root), '--json', *map(str, arguments)]
            if cancelled is None:
                result = subprocess.run(command, capture_output=True, timeout=timeout)
            else:
                import signal
                import time
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                try:
                    if owned:
                        owned(process)
                    deadline = time.monotonic() + timeout
                    while True:
                        if cancelled() or time.monotonic() >= deadline:
                            try:
                                os.killpg(process.pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                            try:
                                process.communicate(timeout=2)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                                process.communicate()
                            raise ApplicationError('operation_cancelled' if cancelled() else 'ocr_timeout', 'Owned native operation stopped.')
                        try:
                            stdout, stderr = process.communicate(timeout=.05)
                            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                            break
                        except subprocess.TimeoutExpired:
                            pass
                finally:
                    # The group belongs to this exact Popen session, including
                    # helpers left after the leader returned.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
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
            if result.returncode not in allowed_returncodes or value.get('status') != 'completed':
                raise ValueError()
            return value
        except (ValueError, KeyError, TypeError):
            raise ApplicationError('ocr_protocol_invalid', 'OCR process returned an invalid version 1 response.') from None


class Application:
    """Synchronous queries; long running work belongs in separate workers.

    dispatch() is the GUI's only request seam. Each response carries a stable
    error code and an event cursor. events(after) returns changes since a cursor.
    """

    def __init__(self, root, *, process_command=None, codex_runtime=None, context_runtime=None, path_picker=None):
        self.root = Path(root).expanduser().resolve()
        self.path_picker = path_picker
        self.process = OcrProcess(process_command)
        self._lock = threading.RLock()
        self._events = deque(maxlen=1000)
        self._sequence = 0
        self._closing = False
        self.preparation = PreparationJobs(self.process.command, self.publish)
        self.codex = CodexJobs(self.publish, codex_runtime)
        self.model_catalog = ModelCapabilities(self.codex.runtime, self.publish)
        self.context = ContextJobs(self.publish, codex_runtime, context_runtime)
        self.reading = ReadingJobs(self.publish, codex_runtime, context_runtime, self.process)
        self.geometry = GeometryJobs(self.publish, codex_runtime, context_runtime, self.process)
        self.output_review = OutputReviewJobs(self.publish, codex_runtime, context_runtime, self.process)
        self.autonomous = AutonomousJobs(self)
        self.corrections = CorrectionJobs(self, codex_runtime, context_runtime)
        self.queue = RunQueue(self)
        self._manual_lease = None
        self._manual_thread = None

    def dispatch(self, operation, payload=None):
        if operation == 'phase_preview':
            # Capture selection under the application lock; rendering and large
            # artifact reads must not block controls or background progress.
            try:
                from .phase_preview import preview, PreviewError
                if not isinstance(payload, dict):
                    raise ApplicationError('invalid_request', 'Preview payload must be an object.')
                with self._lock:
                    root = self.root
                    run = self.select_run(payload.get('run_id'), notify=False)
                data = preview(root, run, payload)
                return {'ok': True, 'data': data, 'error': None, 'event_cursor': self._sequence}
            except (ApplicationError, PreviewError) as error:
                return {'ok': False, 'data': None, 'error': {'code': error.code, 'message': str(error)},
                    'event_cursor': self._sequence}
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                return {'ok': False, 'data': None, 'error': {'code': 'preview_invalid', 'message': str(error)},
                    'event_cursor': self._sequence}
        if operation == 'choose_path':
            # A modal desktop dialog must not hold the application lock: status
            # polling and background OCR continue while the operator chooses.
            from .path_picker import PathSelectionError, select_path
            try:
                data = select_path(payload, self.path_picker)
                return {'ok': True, 'data': data, 'error': None, 'event_cursor': self._sequence}
            except (PathSelectionError, OSError, ValueError, TypeError) as error:
                return {'ok': False, 'data': None, 'event_cursor': self._sequence,
                        'error': {'code': getattr(error, 'code', 'path_invalid'), 'message': str(error)}}
        with self._lock:
            manual_lease = None
            try:
                if not isinstance(payload, (dict, type(None))):
                    raise ApplicationError('invalid_request', 'Request payload must be an object.')
                payload = payload or {}
                self._settle_finished_manual()
                if self._closing and (operation.startswith('start_') or operation in ('resume_autonomous', 'resume_queue', 'enqueue_run')):
                    raise ApplicationError('application_closing', 'Application is closing; no new work can start.')
                if operation in ('start_preparation', 'start_model_diagnostic', 'start_context_diagnostic',
                        'prepare_context_diagnostic', 'start_reading', 'start_geometry', 'patch_geometry',
                        'recover_geometry', 'start_output_review', 'start_corrections', 'check_codex_account', 'start_codex_login'):
                    manual_lease = self.autonomous._lease(inspection=operation in ('check_codex_account', 'start_codex_login'))
                    self._manual_lease = manual_lease
                    (self.root / 'application').mkdir(exist_ok=True)
                    atomic_json(self.root / 'application/manual-execution.json', {'schema_version': 1,
                        'manual_id': uuid.uuid4().hex, 'root': str(self.root),
                        'state': 'running', 'operation': operation, 'run_id': payload.get('run_id'),
                        'owner_pid': os.getpid(), 'owner_start_ticks': process_identity(os.getpid())})
                    intent = json.loads((self.root / 'application/manual-execution.json').read_text())
                    for manager in self.autonomous._managers():
                        manager.launch_manual = {'manual_id': intent['manual_id']}
                if operation in ('start_preparation', 'start_model_diagnostic', 'start_context_diagnostic',
                        'start_reading', 'start_geometry', 'start_output_review', 'start_first_export', 'start_corrections') and payload.get('run_id'):
                    saved_run = self.select_run(payload['run_id'])
                    work = self.root / saved_run['artifacts']['workspace']['path']
                    parent = self.autonomous.status(self.root, payload['run_id'], work)
                    if parent['state'] in ('paused', 'interrupted', 'failed', 'interrupting'):
                        raise ApplicationError('reconciliation_required', 'Continue this saved autonomous attempt through checkpoint and original-turn reconciliation.')
                if (self.autonomous.busy() or self.output_review.busy() or self.corrections.busy()) and operation in (
                        'open_registry', 'import_sources', 'create_run', 'start_preparation', 'start_model_diagnostic',
                        'start_context_diagnostic', 'prepare_context_diagnostic', 'start_reading', 'start_geometry',
                        'patch_geometry', 'recover_geometry', 'start_autonomous', 'start_first_export', 'start_output_review',
                        'check_codex_account', 'start_codex_login', 'start_corrections'):
                    raise ApplicationError('operation_active', 'An autonomous/export operation is active; wait for its saved result.')
                if operation == 'enqueue_run':
                    data = self.queue.enqueue(payload)
                elif operation == 'queue_status':
                    data = self.queue.status()
                elif operation == 'reorder_queue':
                    data = self.queue.reorder(payload)
                elif operation == 'resume_queue':
                    data = self.queue.resume(payload)
                elif operation in ('pause_queue', 'interrupt_queue'):
                    data = self.queue.control('pause' if operation == 'pause_queue' else 'interrupt')
                elif operation == 'projects':
                    data = self.projects()
                elif operation == 'open_registry':
                    data = self.open_registry(payload.get('root'))
                elif operation == 'select_run':
                    data = self.select_run(payload.get('run_id'))
                elif operation == 'compare_runs':
                    from .comparison import compare
                    data = compare(self, payload)
                elif operation == 'import_sources':
                    data = self.import_sources(payload.get('path'))
                elif operation == 'start_model_capabilities':
                    data = self.model_catalog.start(self.root)
                elif operation == 'model_capabilities':
                    data = self.model_catalog.status(self.root)
                elif operation in ('global_preferences', 'set_global_preferences', 'project_preferences',
                        'set_project_preferences', 'adopt_global_preferences'):
                    data = self.preferences(operation, payload)
                elif operation == 'inspect_profile':
                    data = self.inspect_profile(payload.get('path'))
                elif operation == 'create_run':
                    data = self.create_run(payload)
                elif operation == 'start_preparation':
                    data = self.start_preparation(payload)
                elif operation in ('start_autonomous', 'start_first_export'):
                    data = self.start_autonomous(payload, from_geometry=operation == 'start_first_export')
                elif operation in ('pause_autonomous', 'interrupt_autonomous', 'reconcile_autonomous', 'resume_autonomous'):
                    run = self.select_run(payload.get('run_id'))
                    if operation == 'reconcile_autonomous':
                        data = self.autonomous.reconcile(run, payload.get('attempt_id'))
                    elif operation == 'resume_autonomous':
                        data = self.autonomous.resume(run, payload)
                    else:
                        data = self.autonomous.control(run, payload.get('attempt_id'),
                            'pause' if operation == 'pause_autonomous' else 'interrupt')
                elif operation == 'autonomous_status':
                    run = self.select_run(payload.get('run_id'))
                    data = self.autonomous.status(self.root, run['project']['run_id'],
                        self.root / run['artifacts']['workspace']['path'])
                elif operation == 'start_output_review':
                    data = self.start_output_review(payload)
                elif operation == 'output_review_status':
                    run = self.select_run(payload.get('run_id'))
                    data = self.output_review.status(self.root, run['project']['run_id'],
                        self.root / run['artifacts']['workspace']['path'])
                elif operation == 'output_results':
                    data = self.output_results(payload)
                elif operation == 'start_corrections':
                    data = self.start_corrections(payload)
                elif operation == 'correction_status':
                    run = self.select_run(payload.get('run_id'))
                    data = self.corrections.status(self.root, run['project']['run_id'],
                        self.root / run['artifacts']['workspace']['path'])
                elif operation == 'correction_history':
                    data = self.correction_history(payload)
                elif operation == 'open_correction_artifact':
                    data = self.open_correction_artifact(payload)
                elif operation == 'open_output_artifact':
                    data = self.open_output_artifact(payload)
                elif operation == 'preparation_status':
                    data = self.preparation_status(payload.get('run_id'))
                elif operation == 'start_model_diagnostic':
                    data = self.start_model_diagnostic(payload)
                elif operation == 'model_diagnostic_status':
                    data = self.model_diagnostic_status(payload.get('run_id'))
                elif operation == 'start_context_diagnostic':
                    data = self.start_context_diagnostic(payload)
                elif operation == 'prepare_context_diagnostic':
                    if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
                        raise ApplicationError('operation_active', 'Another preparation or AI operation is active.')
                    run = self.select_run(payload.get('run_id'))
                    if 'run' not in run:
                        raise ApplicationError('run_profile_required', 'Choose a named run before preparing a diagnostic.')
                    data = self.context.prepare(self.root, run)
                elif operation == 'context_status':
                    data = self.context_status(payload.get('run_id'))
                elif operation == 'start_reading':
                    data = self.start_reading(payload)
                elif operation == 'reading_status':
                    run = self.select_run(payload.get('run_id'))
                    data = self.reading.status(self.root, run['project']['run_id'],
                        self.root / run['artifacts']['workspace']['path'])
                elif operation == 'start_geometry':
                    data = self.start_geometry(payload)
                elif operation == 'geometry_status':
                    run = self.select_run(payload.get('run_id'))
                    data = self.geometry.status(self.root, run['project']['run_id'],
                        self.root / run['artifacts']['workspace']['path'])
                elif operation == 'patch_geometry':
                    data = self.patch_geometry(payload)
                elif operation == 'recover_geometry':
                    if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
                        raise ApplicationError('operation_active', 'Wait for the active operation before saved-proposal recovery.')
                    run = self.select_run(payload.get('run_id'))
                    data = self.geometry.recover(self.root, run, payload.get('attempt_id'))
                elif operation == 'open_geometry_artifact':
                    data = self.open_geometry_artifact(payload)
                elif operation in ('run_metrics', 'step_detail'):
                    from app.metrics import collect, summary, step_detail
                    offset, limit = payload.get('offset', 0), payload.get('limit', 100)
                    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
                        raise ApplicationError('invalid_request', 'Metric pages require offset >=0 and limit 1..200.')
                    run = self.select_run(payload.get('run_id'), notify=False)
                    if not run.get('run'):
                        raise ApplicationError('named_run_required', 'Metrics require a named run; legacy data stays available in its read view.')
                    try:
                        data = collect(self.root, run)
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        raise ApplicationError('metrics_artifact_invalid', f'Cannot read metrics artifacts: {error}') from None
                    if operation == 'step_detail':
                        step = next((s for s in data['steps'] if s['step_id'] == payload.get('step_id')), None)
                        if step is None:
                            raise ApplicationError('step_not_found', 'Choose a recorded step of this run.')
                        data = step_detail(data, step, offset, limit)
                    else:
                        data = summary(data, offset, limit)
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
                # A public terminal result must not leave this application's
                # already-idle manual lease waiting for its polling thread.
                self._settle_finished_manual()
                return {'ok': True, 'data': data, 'error': None, 'event_cursor': self._sequence}
            except ApplicationError as error:
                return {'ok': False, 'data': None,
                        'error': {'code': error.code, 'message': str(error)},
                        'event_cursor': self._sequence}
            except (ProfileError, JobError) as error:
                return {'ok': False, 'data': None,
                        'error': {'code': error.code, 'message': str(error)},
                        'event_cursor': self._sequence}
            except (OSError, ValueError, KeyError, TypeError) as error:
                if operation in ('enqueue_run', 'queue_status', 'reorder_queue', 'pause_queue', 'interrupt_queue', 'resume_queue'):
                    return {'ok': False, 'data': None, 'error': {'code': 'queue_invalid', 'message': str(error)}, 'event_cursor': self._sequence}
                if operation in ('pause_autonomous', 'interrupt_autonomous', 'reconcile_autonomous', 'resume_autonomous', 'autonomous_status'):
                    return {'ok': False, 'data': None, 'error': {'code': 'checkpoint_invalid', 'message': str(error)}, 'event_cursor': self._sequence}
                raise
            finally:
                if manual_lease is not None:
                    for manager in self.autonomous._managers():
                        manager.launch_manual = None
                    if any(manager.busy() for manager in self.autonomous._managers()):
                        self._manual_thread = threading.Thread(target=self._release_manual, args=(manual_lease, self.root),
                            daemon=True, name='OCR-manual-ownership')
                        self._manual_thread.start()
                    else:
                        self._release_manual(manual_lease, self.root)

    def _settle_finished_manual(self):
        if self._manual_lease is not None and not any(manager.busy() for manager in self.autonomous._managers()):
            self._release_manual(self._manual_lease, self.root)

    def _release_manual(self, lease, root):
        managers = self.autonomous._managers()
        while self._manual_lease is lease and any(manager.busy() for manager in managers):
            time.sleep(.02)
        with self._lock:
            # A synchronous terminal read may already have settled this lease
            # and admitted a new job before the old watcher obtains the lock.
            if self._manual_lease is not lease:
                return
            path = root / 'application/manual-execution.json'
            value = json.loads(path.read_text())
            from .manual_execution import settle
            try:
                value = settle(self, root, value)
            except Exception as error:
                value.update(state='reconciliation_required', delivery_state='unknown', failure={
                    'code': getattr(error, 'code', 'manual_evidence_invalid'), 'message': str(error)})
            atomic_json(path, value)
            self._manual_lease = None
            lease.close()

    def publish(self, event_type, **data):
        with self._lock:
            self._sequence += 1
            self._events.append({'sequence': self._sequence, 'type': event_type, **data})

    def open_registry(self, root):
        if self.queue.owns_schedule():
            raise ApplicationError('operation_active', 'Pause the owned queue before switching its registry, including while it waits for another execution owner.')
        if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
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
        previous_editions = {item['edition_id'] for item in self.projects()['editions']}
        result = self.process.request(self.root, 'import', source)
        counts = {'sources': len(files), **result['counts']}
        data = self.projects()
        Preferences(self.root).capture_imported(data['editions'], previous_editions)
        self.publish('sources_imported', **counts)
        return {**data, 'counts': counts}

    def preferences(self, operation, payload):
        store = Preferences(self.root)
        if operation in ('global_preferences', 'set_global_preferences'):
            value = store.set_global({key: payload.get(key) for key in ('model', 'reasoning_effort')}) if operation == 'set_global_preferences' else store.global_value()
            return {'scope': 'global', 'preferences': value, 'availability': self.model_catalog.availability(self.root, value)}
        edition_id = payload.get('edition_id')
        if not any(item['edition_id'] == edition_id for item in self.projects()['editions']):
            raise ApplicationError('edition_not_found', 'Vyberte existující projekt vydání.')
        if operation == 'set_project_preferences':
            value = store.set_project(edition_id, {key: payload.get(key) for key in ('model', 'reasoning_effort')})
        elif operation == 'adopt_global_preferences':
            value = store.set_project(edition_id, store.global_value())
        else:
            value = store.project_value(edition_id)
        return {'scope': 'project', 'edition_id': edition_id, 'preferences': value,
                'availability': self.model_catalog.availability(self.root, value)}

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
        availability = self.model_catalog.availability(self.root, Preferences(self.root).project_value(edition_id))
        if availability['state'] == 'unavailable':
            raise ApplicationError('model_capability_unavailable', availability['message'])
        profile = Preferences(self.root).resolve_profile(profile, edition_id)
        representative = self.process.request(self.root, 'status', edition['runs'][0]['run_id'])
        source = self.root / representative['artifacts']['source']
        result = self.process.request(self.root, 'import', source, '--new-run',
                                      '--run-name=' + name, '--profile=' + profile['path'],
                                      '--profile-sha256=' + profile['sha256'], '--source-sha256=' + edition_id)
        run_id = result['project']['run_id']
        self.publish('run_created', run_id=run_id, edition_id=edition_id)
        return self.select_run(run_id)

    def start_preparation(self, payload):
        if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
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
        donor_id = payload.get('reuse_from_run_id')
        if donor_id is not None:
            donor = self.select_run(donor_id)
            if not donor.get('run') or donor_id == run['project']['run_id'] or donor['edition_id'] != run['edition_id']:
                raise ApplicationError('invalid_donor', 'Choose another named run of this same complete source hash.')
            work = self.root / run['artifacts']['workspace']['path']
            for directory in (work / 'raster', work / 'ocr'):
                if any(path.is_symlink() or path.is_file() and path.stat().st_nlink > 1
                       for path in (directory, *directory.rglob('*'))):
                    raise ApplicationError('invalid_import_destination', 'Destination preparation must own independent regular files.')
        return self.preparation.start(self.root, run, environment, donor_id,
            resume=payload.get('resume_preparation') is True)

    def preparation_status(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ApplicationError('invalid_request', 'Choose an OCR run.')
        result = self.process.request(self.root, 'status', run_id)
        work = self.root / result['artifacts']['workspace']
        return self.preparation.status(self.root, run_id, work)

    def close(self):
        with self._lock:
            self._closing = True
            self.queue.close()
        self.model_catalog.close()
        self.autonomous.close()
        self.corrections.close()
        self.preparation.close()
        self.codex.close()
        self.context.close()
        self.reading.close()
        self.geometry.close()
        self.output_review.close()
        self.autonomous.join()
        if self._manual_thread is not None:
            self._manual_thread.join(timeout=5)

    def start_corrections(self, payload):
        if any(manager.busy() for manager in (self.preparation, self.codex, self.context, self.reading, self.geometry,
                self.output_review, self.corrections)):
            raise ApplicationError('operation_active', 'Wait for the current native or AI operation before corrections.')
        run = self.select_run(payload.get('run_id'))
        if not run.get('run'):
            raise ApplicationError('run_profile_required', 'Corrections require a named run and frozen profile.')
        if not isinstance(payload.get('expected_iteration_id'), str) or not isinstance(payload.get('expected_validation_sha256'), str):
            raise ApplicationError('invalid_request', 'Choose the current complete export iteration and native validation hash.')
        try:
            work = self.root / run['artifacts']['workspace']['path']
            checkpoint = json.loads((work / 'geometry-checkpoint.json').read_text())
            if checkpoint['runtime'] != self.corrections.runtime or checkpoint['context_runtime'] != self.corrections.context_runtime:
                raise ValueError('Correction runtime differs from the completed run-local preflight.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ApplicationError('correction_preflight_changed', str(error)) from error
        return self.corrections.start_corrections(self.root, run, payload)

    def correction_history(self, payload):
        from .jobs import sha
        run = self.select_run(payload.get('run_id'))
        work = self.root / run['artifacts']['workspace']['path']
        status = self.corrections.status(self.root, run['project']['run_id'], work)
        artifacts = {}
        for cycle in status['cycles']:
            for key in ('plan', 'proposal', 'publication', 'outcome', 'attempt', 'patch'):
                name = cycle.get(key)
                if name and (work / name).is_file():
                    path = (work / name).resolve()
                    if not path.is_relative_to(work.resolve()):
                        raise ApplicationError('artifact_unavailable', 'Correction evidence escapes this run.')
                    artifacts[str(path.relative_to(self.root))] = sha(path)
            if cycle.get('previous_snapshot'):
                directory = (work / cycle['previous_snapshot']).resolve()
                if not directory.is_relative_to((work / 'iterations').resolve()):
                    raise ApplicationError('artifact_unavailable', 'Previous iteration escapes this run.')
                manifest = json.loads((directory / 'snapshot.json').read_text())
                artifacts[str((directory / 'snapshot.json').relative_to(self.root))] = sha(directory / 'snapshot.json')
                for name, record in manifest['artifacts'].items():
                    if record['stored']:
                        path = (directory / name).resolve()
                        if not path.is_relative_to(directory) or sha(path) != record['sha256']:
                            raise ApplicationError('artifact_unavailable', 'Archived correction evidence changed.')
                        artifacts[str(path.relative_to(self.root))] = record['sha256']
        offset, limit = payload.get('offset', 0), payload.get('limit', 100)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ApplicationError('invalid_request', 'History pages require offset >=0 and limit 1..200.')
        rows = [{'path': name, 'sha256': digest} for name, digest in artifacts.items()]
        return {**status, 'artifacts': rows[offset:offset+limit], 'total_artifacts': len(rows),
            'next_offset': offset+limit if offset+limit < len(rows) else None}

    def open_correction_artifact(self, payload):
        offset, item = 0, None
        while offset is not None and item is None:
            result = self.correction_history({**payload, 'offset': offset, 'limit': 200})
            item = next((a for a in result['artifacts'] if a['path'] == payload.get('path') and a['sha256'] == payload.get('sha256')), None)
            offset = result['next_offset']
        if item is None:
            raise ApplicationError('artifact_unavailable', 'Choose an original archived artifact and its exact hash.')
        subprocess.Popen(['xdg-open', str(self.root / item['path'])], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        return {'requested': True, 'path': item['path'], 'meaning': 'External open request; acceptance remains separate.'}

    def start_autonomous(self, payload, *, from_geometry=False):
        lease = self.autonomous._lease()
        try:
            return self._start_autonomous(payload, from_geometry=from_geometry, lease=lease)
        except BaseException:
            lease.close()
            raise

    def _start_autonomous(self, payload, *, from_geometry=False, lease=None):
        if any(manager.busy() for manager in (self.preparation, self.codex, self.context, self.reading, self.geometry, self.output_review)):
            raise ApplicationError('operation_active', 'Another preparation or AI operation is active.')
        if from_geometry:
            run = self.select_run(payload.get('run_id'))
            if not run.get('run'):
                raise ApplicationError('run_profile_required', 'Autonomous export requires a named run and immutable profile.')
            self.process.request(self.root, 'verify-geometry', run['project']['run_id'])
            if payload.get('existing_export_sha256'):
                if not isinstance(payload.get('prepared_review_sha256'), str) or len(payload['prepared_review_sha256']) != 64:
                    raise ApplicationError('invalid_request', 'Resume requires the exact disclosed current export and prepared review hashes.')
                self.process.request(self.root, 'verify-output-preparation', run['project']['run_id'],
                    '--sha256', payload['prepared_review_sha256'], '--output-manifest-sha256', payload['existing_export_sha256'])
        else:
            path = payload.get('source_path')
            if not isinstance(path, str) or not Path(path).expanduser().is_file():
                raise ApplicationError('single_source_required', 'Choose one existing PDF for an autonomous named run.')
            # Profile and name are checked before import can publish any run.
            validate_run_name(payload.get('name'))
            if not isinstance(payload.get('profile_sha256'), str) or len(payload['profile_sha256']) != 64:
                raise ApplicationError('invalid_request', 'Inspect and select an exact profile before starting an autonomous run.')
            if not isinstance(payload.get('profile_path'), str) or not payload['profile_path'].strip():
                raise ApplicationError('invalid_request', 'Choose the inspected profile file.')
            load_profile(payload.get('profile_path'), expected_sha256=payload['profile_sha256'])
            imported = self.import_sources(path)
            if len(imported['editions']) != 1:
                raise ApplicationError('single_source_required', 'Choose one PDF for an autonomous named run.')
            run = self.create_run({**payload, 'edition_id': imported['editions'][0]['edition_id']})
        return self.autonomous.start(run, payload, from_geometry=from_geometry, lease=lease)

    def start_output_review(self, payload):
        if any(manager.busy() for manager in (self.preparation, self.codex, self.context, self.reading, self.geometry, self.output_review)):
            raise ApplicationError('operation_active', 'Wait for the current operation before output examination.')
        run = self.select_run(payload.get('run_id'))
        if not run.get('run'):
            raise ApplicationError('run_profile_required', 'Output examination requires a named run.')
        return self.output_review.start(self.root, run, operation='output_review', metadata={
            'environment': payload.get('environment'), 'prepared_review_sha256': payload.get('prepared_review_sha256')})

    def output_results(self, payload, *, run=None):
        from .jobs import sha
        run = run or self.select_run(payload.get('run_id'))
        work = self.root / run['artifacts']['workspace']['path']
        manifest_path = work / 'output-manifest.json'
        if not manifest_path.exists():
            return {'run_id': run['project']['run_id'], 'project': run['project'], 'available': False}
        try:
            manifest = json.loads(manifest_path.read_text())
            allowed = {}
            for name in ('source', 'pdf', 'txt'):
                path = Path(manifest[name]).resolve()
                digest = manifest[name + '_sha256']
                if not path.is_relative_to(self.root) or sha(path) != digest:
                    raise ValueError('Current exported artifact identity changed')
                allowed[str(path.relative_to(self.root))] = sha(path)
            reports = {}
            for key, name in (('visual_review', 'visual-review.json'), ('findings', 'findings.json'),
                              ('validation', 'run-validation.json')):
                path = work / 'checks' / name
                if path.exists():
                    reports[key] = json.loads(path.read_text())
                    allowed[str(path.relative_to(self.root))] = sha(path)
            prepared_resume = None
            if (work / 'output-review-preparation.json').exists():
                packet = json.loads((work / 'output-review-preparation.json').read_text())
                if (packet['inputs']['output-manifest.json']['sha256'] == sha(manifest_path) and
                        all(sha(Path(item['path'])) == item['sha256'] for item in packet['compare_and_swap'].values())):
                    prepared_resume = {'existing_export_sha256': sha(manifest_path),
                        'prepared_review_sha256': sha(work / 'output-review-preparation.json')}
            provenance = {'status': 'not_published'}
            if (work / 'output-review-publication.json').exists():
                try:
                    self.process.request(self.root, 'verify-output-review', run['project']['run_id'])
                    provenance = {'status': 'original_turn_verified'}
                except ApplicationError as error:
                    provenance = {'status': 'invalidated', 'code': error.code, 'message': str(error)}
            return {'run_id': run['project']['run_id'], 'project': run['project'], 'available': True,
                'iteration_id': manifest['iteration_id'],
                'validation_sha256': sha(work / 'checks/run-validation.json') if (work / 'checks/run-validation.json').exists() else None,
                'workspace': str(work),
                'reports': reports, 'report_provenance': provenance, 'prepared_resume': prepared_resume,
                'artifacts': [{'path': name, 'sha256': digest} for name, digest in allowed.items()]}
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ApplicationError('output_identity_invalid', str(error)) from error

    def open_output_artifact(self, payload):
        from .jobs import sha
        result = self.output_results(payload)
        item = next((row for row in result.get('artifacts', []) if row['path'] == payload.get('path')), None)
        if item is None or payload.get('sha256') != item['sha256']:
            raise ApplicationError('artifact_unavailable', 'Choose a current recorded output/report and its exact hash.')
        path = (self.root / item['path']).resolve()
        if not path.is_relative_to(self.root) or not path.is_file() or sha(path) != item['sha256']:
            raise ApplicationError('artifact_unavailable', 'Recorded output changed or is unavailable.')
        subprocess.Popen(['xdg-open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {'requested': True, 'path': item['path'], 'meaning': 'External open request; no visual verification or acceptance.'}

    def start_geometry(self, payload):
        if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
            raise ApplicationError('operation_active', 'Another preparation or AI operation is active.')
        run = self.select_run(payload.get('run_id'))
        work = self.root / run['artifacts']['workspace']['path']
        previous = self.geometry.status(self.root, run['project']['run_id'], work)
        if previous['state'] != 'not_started' and payload.get('previous_attempt_id') != previous.get('attempt_id'):
            raise ApplicationError('geometry_reconciliation_required', 'Inspect the original geometry attempt and explicitly identify it before continuation.')
        reading = self.reading.status(self.root, run['project']['run_id'], work)
        if not reading.get('reading_complete'):
            raise ApplicationError('geometry_reading_required', 'Geometry requires a verified source reading of this run.')
        context = self.context_status(run['project']['run_id'])
        model = self.model_diagnostic_status(run['project']['run_id'])
        if (not context.get('autonomous_ocr_ready') or context.get('runtime') != self.geometry.runtime or
            context.get('context_runtime') != self.geometry.context_runtime or
            context.get('profile_sha256') != run['run']['profile_sha256'] or
            model.get('runtime') != self.geometry.runtime or model.get('profile_sha256') != run['run']['profile_sha256']):
            raise ApplicationError('geometry_preflight_required', 'Geometry requires the same exact completed run-local model/context preflight.')
        prepared = self.preparation.status(self.root, run['project']['run_id'], work)
        if not prepared.get('checkpoint_valid'):
            raise ApplicationError('geometry_preparation_required', 'Verified native source preparation is required.')
        from .jobs import sha
        original = work / ('review.json' if reading.get('current_review_bound', True) else
            'review-history/' + reading['review_sha256'] + '.json')
        snapshot = work / 'reading-first-publication-review.json'
        if snapshot.exists() and sha(snapshot) != reading['review_sha256']:
            raise ApplicationError('reading_publication_changed', 'Historical first-reading snapshot changed.')
        if not snapshot.exists():
            snapshot.write_bytes(original.read_bytes())
        reading_proof = {'attempt_id': reading['attempt_id'], 'review_sha256': reading['review_sha256'],
            'current_review_sha256': sha(work / 'review.json'), 'evidence': {
                name: {'path': str(self.root / reading['artifacts'][name]), 'sha256': sha(self.root / reading['artifacts'][name])}
                for name in ('protocol', 'proposal', 'attempt')}}
        reading_proof['evidence']['first_publication_review'] = {'path': str(snapshot), 'sha256': sha(snapshot)}
        metadata = {'run': run, 'source': reading['source'], 'reading': reading_proof,
            'environment': prepared.get('environment'), 'previous_attempt_id': payload.get('previous_attempt_id')}
        frozen = work/'geometry-source-samples.json'
        if frozen.exists():
            self.process.request(self.root, 'verify-geometry-samples', run['project']['run_id'])
            metadata.update(samples=json.loads(frozen.read_text()), samples_bytes=list(frozen.read_bytes()),
                saved_origin=json.loads((work/'geometry-sample-origin.json').read_text()))
        if payload.get('samples_path') is not None:
            try:
                samples_path = Path(payload['samples_path']).expanduser().resolve()
                commitment_path = Path(payload['source_commitment_path']).expanduser().resolve()
                samples = json.loads(samples_path.read_text())
                if frozen.exists() and samples_path.read_bytes() != frozen.read_bytes():
                    raise ValueError('Explicit sample seed conflicts with original committed bytes')
                committed = json.loads(commitment_path.read_text())
                pointer = payload.get('commitment_pointer', '/samples_commitment')
                expected = committed
                for part in pointer.lstrip('/').split('/'):
                    expected = expected[part]
                source_hashes = [committed.get('source_sha256')] + [c.get('source_sha256') for c in committed.get('cases', [])]
                if run['project']['source_sha256'] not in source_hashes:
                    raise ValueError('Source commitment belongs to another source')
                import hashlib
                actual = hashlib.sha256(json.dumps(samples, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                if actual != expected:
                    raise ValueError('Source sample canonical commitment differs')
                metadata.update(samples=samples, samples_bytes=list(samples_path.read_bytes()), commitment={
                    'kind': 'original_committed_samples', 'sample_commitment': expected,
                    'source_sha256': run['project']['source_sha256'], 'commitment_pointer': pointer,
                    'commitment': {'path': str(commitment_path), 'sha256': sha(commitment_path)}})
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ApplicationError('geometry_samples_invalid', 'Provide the original independently committed source samples and matching source evidence.') from error
        return self.geometry.start(self.root, run, operation='geometry', metadata=metadata)

    def patch_geometry(self, payload):
        if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
            raise ApplicationError('operation_active', 'Wait for the active operation before a geometry correction.')
        from .jobs import atomic_json
        import uuid
        run = self.select_run(payload.get('run_id'))
        work = self.root / run['artifacts']['workspace']['path']
        expected = payload.get('expected_review_sha256')
        if not isinstance(expected, str) or len(expected) != 64:
            raise ApplicationError('invalid_request', 'A current review hash is required for a geometry correction.')
        patch = payload.get('patch')
        if not isinstance(patch, dict):
            raise ApplicationError('invalid_request', 'Provide a validated structured geometry patch.')
        original = json.loads((work / 'review.json').read_text())
        lines = {line['id']: line for line in original['lines']}
        for edit in patch.get('lines', []):
            line = edit.get('line', {})
            old = lines.get(line.get('id'))
            if old is None or any(line.get(key) != old.get(key) for key in ('text', 'text_status', 'page', 'candidate_id')):
                raise ApplicationError('geometry_text_changed', 'Geometry corrections preserve the source-read transcript.')
        if patch.get('drop_lines') or patch.get('dropped_candidates'):
            raise ApplicationError('geometry_text_changed', 'Geometry corrections preserve the source-read inventory.')
        path = work / 'application' / ('geometry-patch-' + uuid.uuid4().hex + '.json')
        atomic_json(path, patch)
        self.process.request(self.root, 'patch', run['project']['run_id'], '--patch', path,
                             '--expected-review-sha256', expected)
        self.publish('geometry_invalidated', root=str(self.root), run_id=run['project']['run_id'])
        return self.select_run(run['project']['run_id'])

    def open_geometry_artifact(self, payload):
        run = self.select_run(payload.get('run_id'))
        work = self.root / run['artifacts']['workspace']['path']
        self.process.request(self.root, 'verify-geometry', run['project']['run_id'], '--prepared')
        try:
            packet = json.loads((work/'geometry-preparation.json').read_text())
            allowed = set(packet['outputs']) | {'geometry-preparation.json', 'geometry-checkpoint.json'}
            name = payload.get('path')
            decisions = {}
            if (work/'geometry-checkpoint.json').is_file():
                checkpoint = json.loads((work/'geometry-checkpoint.json').read_text())
                for key in ('proposal', 'sample_origin', 'recovery_descriptor'):
                    record = checkpoint['evidence'].get(key)
                    if record and Path(record['path']).resolve().is_relative_to(work.resolve()):
                        decisions[str(Path(record['path']).resolve().relative_to(work.resolve()))] = record['sha256']
            if name in decisions:
                self.process.request(self.root, 'verify-geometry', run['project']['run_id'])
                allowed.add(name)
            if name not in allowed:
                raise ValueError('Choose a recorded geometry artifact of this run.')
            path = (work/name).resolve()
            if not path.is_relative_to(work.resolve()) or not path.is_file():
                raise ValueError('Geometry artifact is unavailable or outside this run.')
            from .jobs import sha
            if name in packet['outputs'] and sha(path) != packet['outputs'][name]:
                raise ValueError('Recorded geometry artifact changed.')
            if name in decisions and sha(path) != decisions[name]:
                raise ValueError('Original decision evidence changed.')
            subprocess.Popen(['xdg-open', str(path)], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
            return {'run_id': run['project']['run_id'], 'path': name, 'requested': True,
                'meaning': 'External open requested; this is not evidence of visual examination.'}
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ApplicationError('artifact_unavailable', str(error)) from error

    def start_reading(self, payload):
        if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
            raise ApplicationError('operation_active', 'Another preparation or AI operation is active.')
        run = self.select_run(payload.get('run_id'))
        if not run.get('run'):
            raise ApplicationError('run_profile_required', 'Choose a named run with an immutable profile.')
        readiness = self.context_status(run['project']['run_id'])
        if not readiness.get('autonomous_ocr_ready'):
            raise ApplicationError('reading_preflight_required', 'Verify the exact image/model and context-mode combination in this run before visual reading.')
        model = self.model_diagnostic_status(run['project']['run_id'])
        if (readiness.get('profile_sha256') != run['run']['profile_sha256'] or
                model.get('profile_sha256') != run['run']['profile_sha256'] or
                model.get('runtime') != self.reading.runtime or readiness.get('runtime') != self.reading.runtime or
                readiness.get('context_runtime') != self.reading.context_runtime):
            raise ApplicationError('reading_preflight_changed', 'The run profile or pinned runtime differs from its completed preflight.')
        work = self.root / run['artifacts']['workspace']['path']
        prepared = self.preparation.status(self.root, run['project']['run_id'], work)
        expected = prepared.get('expected', {})
        parameters = run['run']['profile']['parameters']
        if (not prepared.get('checkpoint_valid') or prepared['state'] != 'completed' or
                expected.get('source_sha256') != run['project']['source_sha256'] or
                expected.get('source_path') != str(self.root / run['artifacts']['source']['path']) or
                any(expected.get(key) != parameters[key] for key in ('dpi', 'language'))):
            raise ApplicationError('reading_preparation_required', 'A verified native source preparation with this run profile is required before visual reading.')
        self.process.request(self.root, 'reading-input', run['project']['run_id'])
        return self.reading.start(self.root, run, operation='visual_reading', metadata={'run': run, 'preflight': readiness,
            'model': model, 'previous_reading_attempt_id': payload.get('previous_reading_attempt_id')})

    def start_model_diagnostic(self, payload, operation='vision_diagnostic'):
        if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
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

    def start_context_diagnostic(self, payload):
        if self.preparation.busy() or self.codex.busy() or self.context.busy() or self.reading.busy() or self.geometry.busy():
            raise ApplicationError('operation_active', 'Another preparation or AI operation is active.')
        run = self.select_run(payload.get('run_id'))
        if 'run' not in run:
            raise ApplicationError('run_profile_required', 'Create a named run with a profile before context verification.')
        if run['project']['operation_state'] == 'running':
            raise ApplicationError('project_busy', 'Another process is active for this run.')
        try:
            return self.context.start(self.root, run, operation='context_diagnostic',
                metadata={'previous_context_attempt_id': payload.get('previous_context_attempt_id')})
        except OSError as error:
            raise ApplicationError('context_artifact_failed', f'Cannot preserve context diagnostic: {error}') from None

    def context_status(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ApplicationError('invalid_request', 'Choose an OCR run.')
        result = self.process.request(self.root, 'status', run_id)
        work = self.root / result['artifacts']['workspace']
        context = self.context.status(self.root, run_id, work)
        model = self.codex.status(self.root, run_id, work, operation='vision_diagnostic')
        context['model_verified'] = bool(model.get('combination_verified'))
        context['model_attempt_id'] = model.get('attempt_id')
        context['autonomous_ocr_ready'] = bool(context.get('context_verified') and context['model_verified']
                                              and context.get('state') == 'completed')
        return context

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

    def select_run(self, run_id, *, notify=True):
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
        if notify:
            self.publish('run_selected', run_id=run_id, edition_id=data['edition_id'])
        return data
