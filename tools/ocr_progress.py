"""Opt-in durable progress, separate from the bounded stdout JSON protocol."""

from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import threading
import time
import uuid

from ocr_projects import ProjectError


class ProgressReporter:
    def __init__(self, path, *, run_id, work, attempt_id=None):
        self.path = Path(path).resolve() if path is not None else None
        self.run_id = run_id
        self.attempt_id = attempt_id or uuid.uuid4().hex
        self.started = time.monotonic()
        self._starts = {}
        self._lock = threading.RLock()
        self._sequence = 0
        if self.path is None:
            return
        if (not self.path.is_relative_to(Path(work).resolve()) or
                len(self.attempt_id) != 32 or any(c not in '0123456789abcdef' for c in self.attempt_id)):
            raise ProjectError('progress_invalid', 'Progress must belong to the selected workspace and a valid attempt identity.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            for line in self.path.read_text(encoding='utf-8').splitlines():
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                    if event.get('attempt_id') == self.attempt_id:
                        self._sequence = max(self._sequence, event['sequence'])
                except (ValueError, KeyError, TypeError):
                    raise ProjectError('progress_invalid', 'Existing progress history is invalid; preserve it.') from None

    def emit(self, event_type, step_id='preparation', **data):
        if self.path is None:
            return
        with self._lock:
            now = time.monotonic()
            if event_type in ('step_started', 'unit_started'):
                self._starts[step_id] = now
            duration = None
            if event_type in ('step_completed', 'step_failed', 'unit_completed', 'unit_cached'):
                duration = max(0, now - self._starts.pop(step_id, now))
            self._sequence += 1
            event = {'schema_version': 1, 'event_id': f'{self.attempt_id}:{self._sequence:06d}',
                     'sequence': self._sequence, 'attempt_id': self.attempt_id, 'run_id': self.run_id,
                     'type': event_type, 'step_id': step_id,
                     'timestamp': datetime.now(timezone.utc).isoformat(),
                     'elapsed_seconds': max(0, now - self.started), **data}
            if duration is not None:
                event['duration_seconds'] = duration
            encoded = json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n'
            with self.path.open('a', encoding='utf-8') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                stream.write(encoded)
                stream.flush()
                import os
                os.fsync(stream.fileno())

    def failed(self, error):
        failure = {'code': getattr(error, 'code', 'prepare_failed'), 'message': str(error),
                   'detail': str(error.__cause__) if error.__cause__ is not None else None}
        for step_id in list(self._starts):
            self.emit('step_failed', step_id, error=failure)
        self.emit('attempt_failed', error=failure)
