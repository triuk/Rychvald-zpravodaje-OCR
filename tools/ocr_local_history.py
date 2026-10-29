"""Durable observations of native work, independent of its small stdout protocol.

One journal belongs to one native process admission. Child workflow processes
append to that journal under a file lock; they never invent another admission.
The parent/child spans are observations, not additive elapsed-time counters.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import threading
import time
import uuid

from ocr_projects import atomic_json

TRACE_ENV = 'OCR_LOCAL_TRACE'
PARENT_ENV = 'OCR_LOCAL_PARENT_STEP'
OPERATIONS = {
    'prepare', 'resume', 'patch', 'reading-input', 'publish-reading', 'check-reading',
    'prepare-geometry', 'publish-geometry', 'prepare-output-review', 'publish-output-review',
    'reserve-correction', 'publish-correction', 'check-correction', 'bind-correction',
    'prepare-correction-geometry', 'settle-correction', 'export', 'validate',
    'prepare-correction-export', 'render-correction-export', 'adopt-correction-patch',
    'adopt-correction-outcome', 'capture-installed-origin',
}
_local = threading.local()


def now():
    return datetime.now(timezone.utc).isoformat()


def process_identity(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def phase_for(operation):
    if operation in ('prepare', 'resume', 'capture-installed-origin'):
        return 'preparation'
    if operation in ('patch', 'reading-input', 'publish-reading', 'check-reading'):
        return 'reading'
    if operation in ('prepare-geometry', 'publish-geometry'):
        return 'geometry'
    return 'assembly'


def file_records(paths):
    """Document existing files named by an operation; do not follow directories."""
    records = []
    seen = set()
    for value in paths:
        path = Path(value)
        if str(path) in seen or not path.is_file():
            continue
        seen.add(str(path))
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        records.append({'path': str(path.resolve()), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size})
    return records


def command_files(command):
    return file_records(value for value in command[1:] if isinstance(value, (str, Path)) and str(value) and not str(value).startswith('-'))


class NativeTrace:
    def __init__(self, path, manifest):
        self.path = Path(path)
        self.manifest = manifest
        self.events = self.path.with_suffix('.jsonl')
        self.local = threading.local()
        self.closed = False

    @classmethod
    def begin(cls, registry, args):
        if args.operation not in OPERATIONS or not getattr(args, 'project_id', None):
            return None
        record = registry.get(args.project_id)
        work = (registry.root / record['artifacts']['workspace']).resolve()
        directory = work / 'application/local-attempts'
        directory.mkdir(parents=True, exist_ok=True)
        identifier = getattr(args, 'attempt_id', None) or uuid.uuid4().hex
        # A supplied preparation attempt is shared with its existing progress
        # channel; never replace an earlier native journal on a repeated call.
        if (directory / f'{identifier}.json').exists():
            identifier = uuid.uuid4().hex
        command = [sys.executable, str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
        manifest = {'schema_version': 1, 'attempt_id': identifier,
                    'run_id': record['project']['run_id'], 'edition_id': record['project']['source_sha256'],
                    'root': str(registry.root), 'work': str(work), 'operation': args.operation,
                    'phase': phase_for(args.operation), 'state': 'running', 'started_at': now(), 'ended_at': None,
                    'pid': os.getpid(), 'process_start_ticks': process_identity(os.getpid()),
                    'progress_attempt_id': getattr(args, 'attempt_id', None),
                    'command': command, 'tool': {'name': 'ocr_projects', 'version': platform.python_version(),
                                                 'runtime': 'Python ' + platform.python_version()},
                    'parameters': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                    'owner': None, 'error': None}
        try:
            owner = json.loads(os.environ.get('OCR_LOCAL_OWNER', 'null'))
            if isinstance(owner, dict):
                manifest['owner'] = owner
        except ValueError:
            pass
        trace = cls(directory / f'{identifier}.json', manifest)
        atomic_json(trace.path, manifest)
        os.environ[TRACE_ENV] = str(trace.path)
        os.environ[PARENT_ENV] = 'root'
        _local.trace = trace
        trace.emit('started', 'root', scope='native_operation', operation=args.operation,
                   tool=manifest['tool'], command=command, parameters=manifest['parameters'],
                   inputs=command_files(command), parent_step_id=None)
        return trace

    def emit(self, event_type, step_id, **data):
        event = {'schema_version': 1, 'event_id': uuid.uuid4().hex,
                 'attempt_id': self.manifest['attempt_id'], 'run_id': self.manifest['run_id'],
                 'edition_id': self.manifest['edition_id'], 'phase': self.manifest['phase'],
                 'step_id': step_id, 'type': event_type, 'timestamp': now(), **data}
        with self.events.open('a', encoding='utf-8') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.write(json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def parent(self):
        return getattr(self.local, 'parent', os.environ.get(PARENT_ENV, 'root'))

    @contextmanager
    def span(self, *, operation, tool, command=None, inputs=None, outputs=None, scope='tool'):
        identifier, started, previous = uuid.uuid4().hex, time.monotonic(), self.parent()
        command = list(map(str, command or []))
        self.emit('started', identifier, parent_step_id=previous, scope=scope, operation=operation,
                  tool=tool, command=command, inputs=inputs if inputs is not None else command_files(command))
        self.local.parent = identifier
        value = {'state': 'completed', 'error': None}
        try:
            yield value
        except BaseException as error:
            value.update(state='interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'failed',
                         error={'code': getattr(error, 'code', type(error).__name__), 'message': str(error)})
            raise
        finally:
            self.local.parent = previous
            self.emit(value.pop('state'), identifier, duration_seconds=max(0, time.monotonic() - started),
                      outputs=file_records(outputs or []), **value)

    def progress(self, kind, identifier, data):
        """Retain in-process/cache units even when stdout progress is disabled."""
        step = 'progress:' + identifier
        if kind in ('step_started', 'unit_started'):
            previous = self.parent()
            # ProgressReporter may wrap other progress units in the same thread.
            parents = getattr(self.local, 'progress_parents', {})
            parents[step] = previous
            self.local.progress_parents = parents
            self.local.parent = step
            self.emit('started', step, scope='unit', parent_step_id=previous,
                      operation=data.get('unit_kind', identifier.split(':')[0]),
                      tool=data.get('tool', {'name': 'ocr_projects', 'version': platform.python_version()}),
                      command=data.get('command', []), inputs=data.get('inputs', []), parameters=data)
        elif kind in ('step_completed', 'unit_completed', 'unit_cached', 'step_failed'):
            self.local.parent = getattr(self.local, 'progress_parents', {}).pop(step, 'root')
            outputs = data.get('outputs', [])
            if isinstance(outputs, dict):
                outputs = [{'path': str(Path(self.manifest['work']) / name), 'sha256': digest}
                           for name, digest in outputs.items()]
            self.emit({'unit_cached': 'cached', 'step_failed': 'failed'}.get(kind, 'completed'), step,
                      origin=data.get('origin', 'same_run_cache' if kind == 'unit_cached' else 'computed'),
                      import_provenance=data.get('import_provenance'), outputs=outputs,
                      error=data.get('error'), details=data)

    def finish(self, *, result=None, error=None):
        if self.closed:
            return
        self.closed = True
        state = 'failed' if error else 'completed'
        result = result or {}
        outputs = []
        for name, value in result.get('artifacts', {}).items():
            if name not in ('source', 'history', 'profile_snapshot', 'run_manifest') and isinstance(value, str):
                outputs.append(Path(self.manifest['root']) / value)
        self.emit(state, 'root', outputs=file_records(outputs), error=error,
                  result={'validation': (result.get('project') or {}).get('validation'), 'counts': result.get('counts')})
        self.manifest.update(state=state, ended_at=now(), error=error)
        atomic_json(self.path, self.manifest)


def active_trace():
    path = os.environ.get(TRACE_ENV)
    if not path:
        return None
    trace = getattr(_local, 'trace', None)
    if trace is not None and str(trace.path) == path:
        return trace
    path = Path(path).resolve()
    value = json.loads(path.read_text())
    if (value.get('schema_version') != 1 or
            path.parent != Path(value['work']).resolve() / 'application/local-attempts' or
            not path.is_relative_to(Path(value['root']).resolve()) or path.stem != value['attempt_id']):
        raise ValueError('Local history context belongs to a different workspace/admission.')
    trace = NativeTrace(path, value)
    _local.trace = trace
    return trace


def child_environment(base):
    result = dict(base)
    trace = active_trace()
    if trace is not None:
        result[TRACE_ENV] = str(trace.path)
        result[PARENT_ENV] = trace.parent()
    return result


def progress_event(kind, step_id, data):
    trace = active_trace()
    if trace is not None:
        trace.progress(kind, step_id, data)
