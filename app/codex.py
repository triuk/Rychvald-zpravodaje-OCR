"""Pinned Codex process diagnostics; source evidence stays bound to an attempt.

The native JSON-RPC child is the replaceable process boundary. A completed
vision diagnostic is deliberately separate from autonomous OCR readiness.
"""
from datetime import datetime, timezone
import copy
import fcntl
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import threading
import time
import uuid
from urllib.parse import urlparse

from .jobs import JobError, atomic_json, sha

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'gpt-6.1-sol'
EFFORT = 'high'
PROMPT = ('Vizuálně přečti text pouze na přiloženém obrázku. Vrať pouze přesný přepis, '
          'zachovej diakritiku, interpunkci a pořadí řádků. Pokud část nelze bezpečně přečíst, '
          'napiš na jejím místě [NEČITELNÉ]. Nehledej text v souborech, nepoužívej nástroje '
          'ani OCR kandidáty. Toto je pouze diagnostické čtení obrázku, nikoli dokončený přepis vydání.')


def now():
    return datetime.now(timezone.utc).isoformat()


def process_identity(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def default_runtime():
    lock = json.loads((ROOT / 'native/codex-runtime.json').read_text())
    bundled = ROOT / lock['binary']
    executable = bundled if bundled.exists() else Path(lock['development_binary'])
    return {'kind': 'native', 'version': lock['version'], 'command': [str(executable), 'app-server', '--stdio',
            '--disable', 'plugins', '--disable', 'hooks', '--disable', 'shell_tool',
            '--disable', 'skill_mcp_dependency_install', '-c', 'mcp_servers={}'],
            'files': [{'path': str(executable), 'sha256': lock['sha256']},
                      *[{'path': str(executable.parent / item['name']), 'sha256': item['sha256']}
                        for item in lock['companions']]]}


def scrub(value):
    """Keep usage/event fields verbatim; authentication material is not OCR history."""
    private = {'accessToken', 'refreshToken', 'idToken', 'apiKey', 'authorization', 'email', 'authUrl'}
    if isinstance(value, dict):
        return {key: '[redacted]' if key in private else scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


class RpcProcess:
    def __init__(self, command, workspace, stderr, record, cancelled, env=None):
        self.record, self.cancelled = record, cancelled
        self.messages = queue.Queue()
        self.identifier = 0
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=stderr, cwd=workspace, start_new_session=True,
                                        text=True, encoding='utf-8', bufsize=1, env=env)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError()
                    self.record('server', value)
                    self.messages.put(value)
                except (ValueError, TypeError):
                    self.messages.put(JobError('codex_protocol_invalid', 'Codex stdout is not a JSON-RPC object.'))
                    return
        except (OSError, UnicodeError):
            self.messages.put(JobError('codex_protocol_invalid', 'Cannot decode the Codex protocol stream.'))
        finally:
            self.messages.put(None)

    def send(self, value):
        self.record('client', value)
        try:
            self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise JobError('codex_process_terminated', 'Codex process ended before accepting a request.') from None

    def receive(self, deadline):
        while True:
            if self.cancelled():
                raise JobError('diagnostic_interrupted', 'Diagnostic attempt was interrupted.')
            if time.monotonic() >= deadline:
                raise JobError('codex_timeout', 'Codex did not complete the requested operation in time.')
            try:
                value = self.messages.get(timeout=min(.2, max(.001, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if value is None:
                raise JobError('codex_process_terminated', 'Codex closed its protocol stream.')
            if isinstance(value, Exception):
                raise value
            return value

    def request(self, method, params, notify, timeout=45):
        self.identifier += 1
        identifier = self.identifier
        self.send({'id': identifier, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while True:
            message = self.receive(deadline)
            if message.get('id') == identifier and 'method' not in message:
                if 'error' in message:
                    error = message['error']
                    raise JobError('codex_request_rejected', f"{method}: {error.get('message', 'Request rejected')}")
                if 'result' not in message:
                    raise JobError('codex_protocol_invalid', 'Codex response has no result.')
                return message['result']
            notify(message)

    def close(self):
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
            except ProcessLookupError:
                self.process.wait()
        self.process.stdin.close()
        self.reader.join(timeout=2)
        self.process.stdout.close()


class CodexJobs:
    namespace = 'codex-attempts'

    def __init__(self, publish, runtime=None):
        self.publish = publish
        self.runtime = copy.deepcopy(runtime) if runtime is not None else default_runtime()
        self._lock = threading.RLock()
        self._active = None

    def busy(self):
        with self._lock:
            return self._active is not None

    def start(self, root, run, image_path=None, operation='vision_diagnostic', metadata=None):
        with self._lock:
            if self._active is not None:
                raise JobError('operation_active', 'A Codex diagnostic is already active.')
            parameters = run['run']['profile']['parameters']
            if parameters['model'] != MODEL or parameters['reasoning_effort'] != EFFORT:
                raise JobError('model_configuration_unsupported', 'Diagnostic requires exactly gpt-6.1-sol with high effort.')
            work = root / run['artifacts']['workspace']['path']
            source, suffix = None, None
            if operation == 'vision_diagnostic':
                source = Path(image_path).expanduser().resolve() if isinstance(image_path, str) and image_path.strip() else work / 'raster/page-1.png'
                try:
                    if not source.is_file() or not 0 < source.stat().st_size <= 20 * 1024 * 1024:
                        raise ValueError()
                    with source.open('rb') as stream:
                        header = stream.read(8)
                    suffix = '.png' if header == b'\x89PNG\r\n\x1a\n' else '.jpg' if header.startswith(b'\xff\xd8\xff') else None
                    if suffix is None:
                        raise ValueError()
                except (OSError, ValueError):
                    raise JobError('diagnostic_image_invalid', 'Choose an existing prepared PNG/JPEG image, at most 20 MiB.') from None
            attempt_id = uuid.uuid4().hex
            directory = work / 'application' / self.namespace / attempt_id
            workspace = directory / 'workspace'
            workspace.mkdir(parents=True)
            image_record = None
            if source is not None:
                image = workspace / ('image' + suffix)
                shutil.copyfile(source, image)
                image_record = {'source_path': str(source), 'path': str(image.relative_to(root)), 'sha256': sha(image)}
            artifacts = {name: str((directory / filename).relative_to(root)) for name, filename in
                         [('protocol', 'protocol.jsonl'), ('stderr', 'stderr.log'), ('request', 'request.json'), ('attempt', 'attempt.json')]}
            manifest = {'schema_version': 1, 'operation': operation, 'attempt_id': attempt_id,
                        'run_id': run['project']['run_id'], 'root': str(root), 'state': 'starting',
                        'started_at': now(), 'ended_at': None, 'requested': {'model': MODEL, 'reasoning_effort': EFFORT},
                        'effective': None, 'thread_id': None, 'turn_id': None, 'answer': None,
                        'profile_sha256': run['run']['profile_sha256'], 'image': image_record,
                        'prompt': PROMPT if source is not None else None, 'runtime': self.runtime,
                        'native_runtime': self.runtime['kind'] == 'native', 'authenticated': None,
                        'owner_pid': os.getpid(), 'owner_start_ticks': process_identity(os.getpid()),
                        'pid': None, 'process_group': None, 'process_start_ticks': None,
                        'usage_events': [], 'reroutes': [], 'tool_events': [], 'events': [], 'error': None,
                        'combination_verified': False, 'autonomous_ocr_ready': False, 'artifacts': artifacts}
            atomic_json(directory / 'attempt.json', manifest)
            atomic_json(directory / 'request.json', {'operation': operation, 'profile_sha256': manifest['profile_sha256'],
                                                     'prompt': manifest['prompt'], 'image': image_record})
            job = {'manifest': manifest, 'directory': directory, 'workspace': workspace,
                   'history': root / run['artifacts']['history']['path'], 'cancel': False, 'rpc': None,
                   'metadata': copy.deepcopy(metadata)}
            self._active = job
            job['thread'] = threading.Thread(target=self._run, args=(job,), name=f'Codex-{attempt_id}', daemon=True)
            result = copy.deepcopy(manifest)
            job['thread'].start()
            return result

    def _event(self, job, kind, **details):
        value = job['manifest']
        event = {'schema_version': 1, 'event_id': f"{value['attempt_id']}:{len(value['events'])}",
                 'run_id': value['run_id'], 'attempt_id': value['attempt_id'], 'step_id': getattr(self, 'step_id', 'model_diagnostic'),
                 'timestamp': now(), 'type': kind, **details}
        value['events'].append(event)
        with job['history'].open('a+', encoding='utf-8') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.seek(0)
            contents = stream.read()
            if contents and not contents.endswith('\n'):
                raise JobError('history_incomplete', 'Preserved history has an incomplete final event; explicit recovery is required.')
            stream.seek(0, 2)
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        atomic_json(job['directory'] / 'attempt.json', value)
        self.publish('codex_progress', root=value['root'], run_id=value['run_id'], event=event)

    def _run(self, job):
        value = job['manifest']
        started = time.monotonic()
        trace_lock = threading.Lock()

        def trace(direction, message):
            with trace_lock, (job['directory'] / 'protocol.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'timestamp': now(), 'elapsed_seconds': time.monotonic() - started,
                                         'direction': direction, 'message': scrub(message)}, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

        def notify(message):
            if 'method' not in message:
                raise JobError('codex_protocol_invalid', 'Unmatched Codex response identifier.')
            if 'id' in message:
                job['rpc'].send({'id': message['id'], 'error': {'code': -32601, 'message': 'Diagnostic does not execute tools or approvals.'}})
                raise JobError('diagnostic_tool_used', 'Diagnostic requested a client tool or approval.')
            method, params = message['method'], message.get('params', {})
            thread_id = params.get('threadId') or params.get('thread', {}).get('id')
            if thread_id is not None:
                if value['thread_id'] is not None and thread_id != value['thread_id']:
                    raise JobError('codex_identity_mismatch', 'Event belongs to another Codex thread.')
                value['thread_id'] = thread_id
            turn_id = params.get('turnId') or params.get('turn', {}).get('id')
            if turn_id is not None:
                if value['turn_id'] is not None and value['turn_id'] != turn_id:
                    raise JobError('codex_identity_mismatch', 'Event belongs to another Codex turn.')
                value['turn_id'] = turn_id
            if method == 'thread/tokenUsage/updated':
                value['usage_events'].append(copy.deepcopy(params))
            elif method == 'model/rerouted':
                value['reroutes'].append(copy.deepcopy(params))
            elif method in ('item/started', 'item/completed'):
                item = params.get('item', {})
                if item.get('type') == 'agentMessage' and method == 'item/completed':
                    value['answer'] = item.get('text')
                elif item.get('type') not in ('agentMessage', 'userMessage', 'reasoning'):
                    value['tool_events'].append(copy.deepcopy(params))
            elif method == 'turn/completed':
                value['terminal_turn'] = copy.deepcopy(params['turn'])
            self._event(job, 'codex_notification', method=method, thread_id=value['thread_id'], turn_id=value['turn_id'])

        try:
            self._event(job, 'codex_attempt_started')
            for item in self.runtime['files']:
                path = Path(item['path'])
                if not path.is_file() or sha(path) != item['sha256']:
                    raise JobError('codex_runtime_invalid', 'Pinned Codex runtime resource is missing or changed.')
            with (job['directory'] / 'stderr.log').open('w', encoding='utf-8') as stderr:
                rpc = RpcProcess(self.runtime['command'], job['workspace'], stderr, trace, lambda: job['cancel'])
                job['rpc'] = rpc
                value.update(state='running', pid=rpc.process.pid, process_group=rpc.process.pid,
                             process_start_ticks=process_identity(rpc.process.pid))
                self._event(job, 'codex_process_started', pid=rpc.process.pid)
                initialized = rpc.request('initialize', {'clientInfo': {'name': 'rychvald-ocr', 'version': '1.0'},
                    'capabilities': {'experimentalApi': True}}, notify)
                value['client_capabilities'] = initialized
                rpc.send({'method': 'initialized'})
                account = rpc.request('account/read', {'refreshToken': False}, notify)
                if value['operation'] == 'login' and not account.get('account'):
                    login = rpc.request('account/login/start', {'type': 'chatgpt'}, notify)
                    url = urlparse(login.get('authUrl', ''))
                    if not (url.scheme == 'https' or url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1', '::1')):
                        raise JobError('codex_login_invalid', 'Codex returned an unsupported browser sign-in URL.')
                    job['login_url'] = login['authUrl']
                    value.update(state='awaiting_login', login_id=login['loginId'])
                    self._event(job, 'codex_login_pending', login_id=value['login_id'])
                    deadline = time.monotonic() + 180
                    while True:
                        message = rpc.receive(deadline)
                        notify(message)
                        if message.get('method') == 'account/login/completed':
                            completed = message['params']
                            if completed.get('loginId') != value['login_id']:
                                raise JobError('codex_login_invalid', 'Sign-in completion belongs to another login.')
                            if not completed.get('success'):
                                raise JobError('codex_login_failed', str(completed.get('error') or 'ChatGPT sign-in failed.'))
                            break
                    job.pop('login_url', None)
                    account = rpc.request('account/read', {'refreshToken': False}, notify)
                value['account'] = scrub(account)
                value['authenticated'] = bool(account.get('account') and account['account'].get('type') == 'chatgpt')
                if value['operation'] == 'check_account':
                    value['state'] = 'completed'
                    return
                if not account.get('account') or account['account'].get('type') != 'chatgpt':
                    raise JobError('chatgpt_account_required', 'Sign in to Codex using a ChatGPT account before image diagnostics.')
                if value['operation'] == 'login':
                    value['state'] = 'completed'
                    return
                cursor, found, cursors = None, None, set()
                while True:
                    catalog = rpc.request('model/list', {'cursor': cursor, 'limit': 100}, notify)
                    found = next((item for item in catalog['data'] if item.get('model') == MODEL), found)
                    cursor = catalog.get('nextCursor')
                    if cursor is None:
                        break
                    if cursor in cursors:
                        raise JobError('codex_protocol_invalid', 'Codex model catalog did not advance its cursor.')
                    cursors.add(cursor)
                if found is None or 'image' not in found.get('inputModalities', []) or not any(
                        item.get('reasoningEffort') == EFFORT for item in found.get('supportedReasoningEfforts', [])):
                    raise JobError('model_capability_unavailable', 'Codex does not explicitly advertise gpt-6.1-sol, high and image input.')
                value['declared_model'] = found
                thread = rpc.request('thread/start', {'model': MODEL, 'cwd': str(job['workspace']),
                    'config': {'model_reasoning_effort': EFFORT}, 'approvalPolicy': 'never', 'sandbox': 'read-only',
                    'developerInstructions': 'Read only the attached diagnostic image. Do not invoke tools or inspect text files.'}, notify)
                if value['thread_id'] is not None and value['thread_id'] != thread['thread']['id']:
                    raise JobError('codex_identity_mismatch', 'Thread response differs from the observed thread.')
                value['thread_id'] = thread['thread']['id']
                value['effective'] = {'model': thread.get('model'), 'reasoning_effort': thread.get('reasoningEffort'),
                                      'source': 'thread/start'}
                if thread.get('model') != MODEL or thread.get('reasoningEffort') != EFFORT:
                    raise JobError('model_configuration_mismatch', 'Codex thread did not confirm the exact requested model and high effort.')
                params = {'threadId': value['thread_id'], 'model': MODEL, 'effort': EFFORT,
                          'input': [{'type': 'text', 'text': PROMPT}, {'type': 'localImage',
                                     'path': str(Path(value['root']) / value['image']['path'])}]}
                atomic_json(job['directory'] / 'request.json', {'thread': thread, 'turn': params,
                            'profile_sha256': value['profile_sha256'], 'image': value['image']})
                value['submitted_at'] = now()
                self._event(job, 'codex_turn_submitting', thread_id=value['thread_id'])
                turn = rpc.request('turn/start', params, notify)
                returned_id = turn['turn']['id']
                if value['turn_id'] is not None and value['turn_id'] != returned_id:
                    raise JobError('codex_identity_mismatch', 'Turn response differs from the observed turn.')
                value['turn_id'] = returned_id
                self._event(job, 'codex_turn_submitted', thread_id=value['thread_id'], turn_id=returned_id)
                deadline = time.monotonic() + 180
                while 'terminal_turn' not in value:
                    notify(rpc.receive(deadline))
                status = value['terminal_turn']['status']
                if status != 'completed':
                    raise JobError('codex_turn_' + status, str(value['terminal_turn'].get('error') or f'Codex turn ended as {status}.'))
                if value['reroutes']:
                    raise JobError('model_rerouted', 'The diagnostic was redirected to another model and cannot verify the requested combination.')
                if value['tool_events']:
                    raise JobError('diagnostic_tool_used', 'Tool execution cannot substitute for the attached-image diagnostic.')
                if not isinstance(value['answer'], str) or not value['answer'].strip():
                    raise JobError('diagnostic_answer_missing', 'Completed Codex turn supplied no image transcription.')
                value.update(state='completed', combination_verified=True)
        except Exception as error:
            value.update(state='interrupted' if job['cancel'] or getattr(error, 'code', None) == 'codex_turn_interrupted' else 'failed',
                         error={'code': getattr(error, 'code', 'codex_protocol_invalid'), 'message': str(error)})
        finally:
            if job['rpc'] is not None:
                job['rpc'].close()
                value['process_returncode'] = job['rpc'].process.returncode
            value.update(ended_at=now(), elapsed_seconds=max(0, time.monotonic() - started))
            try:
                self._event(job, 'codex_attempt_' + value['state'], state=value['state'], error=value['error'],
                            thread_id=value['thread_id'], turn_id=value['turn_id'])
            finally:
                with self._lock:
                    atomic_json(job['directory'] / 'attempt.json', value)
                    self._active = None
                self.publish('codex_finished', root=value['root'], run_id=value['run_id'], state=value['state'])

    def status(self, root, run_id, work, operation=None):
        try:
            return self._status(root, run_id, work, operation)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise JobError('attempt_invalid', f'Cannot read preserved Codex attempt: {error}') from None

    def _status(self, root, run_id, work, operation=None):
        paths = list((work / 'application' / self.namespace).glob('*/attempt.json'))
        if not paths:
            return {'run_id': run_id, 'state': 'not_started', 'autonomous_ocr_ready': False}
        values = [json.loads(path.read_text()) for path in paths]
        if operation is not None:
            values = [value for value in values if value.get('operation') == operation]
        if not values:
            return {'run_id': run_id, 'state': 'not_started', 'autonomous_ocr_ready': False}
        value = max(values, key=lambda item: item['started_at'])
        if value['root'] != str(root) or value['run_id'] != run_id:
            raise JobError('attempt_invalid', 'Saved Codex attempt belongs to a different run.')
        if value['image'] is not None:
            image = (root / value['image']['path']).resolve()
            if not image.is_relative_to(work.resolve()) or not image.is_file() or sha(image) != value['image']['sha256']:
                value.update(state='invalidated', combination_verified=False,
                             error={'code': 'diagnostic_image_changed', 'message': 'Preserved diagnostic image is missing or changed.'})
        with self._lock:
            if self._active is not None and self._active['manifest']['attempt_id'] == value['attempt_id']:
                value['login_url'] = self._active.get('login_url')
                if value['state'] not in ('starting', 'running', 'awaiting_login'):
                    # A terminal event can precede worker cleanup. Public
                    # completion waits for ownership release and final write.
                    value['state'] = 'running'
                    value['combination_verified'] = False
                    if 'reading_complete' in value:
                        value['reading_complete'] = False
        return value

    def close(self):
        with self._lock:
            job = self._active
            if job is not None:
                job['cancel'] = True
        if job is not None:
            job['thread'].join(timeout=8)
