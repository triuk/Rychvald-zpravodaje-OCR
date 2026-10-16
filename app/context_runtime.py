"""Pinned offline context-mode closure and process-local Codex configuration."""
import json
import os
from pathlib import Path
import shlex
import subprocess

from .codex import ROOT
from .jobs import JobError, sha
from tools.prepare_context_runtime import digest

EVENTS = {'SessionStart': 'sessionstart', 'PreToolUse': 'pretooluse', 'PostToolUse': 'posttooluse',
          'PreCompact': 'precompact', 'UserPromptSubmit': 'userpromptsubmit', 'Stop': 'stop'}
TOOLS = ['ctx_execute', 'ctx_execute_file', 'ctx_batch_execute', 'ctx_index', 'ctx_search', 'ctx_stats']


def toml(value):
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(key) + '=' + toml(item) for key, item in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(toml(item) for item in value) + ']'
    return json.dumps(value, ensure_ascii=False)


def default_context_runtime():
    lock = json.loads((ROOT / 'native/context-runtime.json').read_text())
    bundled = ROOT / lock['node']['bundled_path']
    node = bundled if bundled.is_file() else Path(lock['node']['development_path'])
    package = Path(os.environ.get('RYCHVALD_CONTEXT_RUNTIME', ROOT / lock['runtime_directory'])).resolve()
    files = [{'path': str(node), 'sha256': lock['node']['sha256']}]
    interpreters = []
    for item in lock['interpreters']:
        path = ROOT / 'runtime/bin' / item['name']
        path = path if path.is_file() else Path(item['development_path'])
        files.append({'path': str(path), 'sha256': item['sha256']})
        interpreters.append({'name': item['name'], 'path': str(path)})
    return {'kind': 'native', 'version': lock['version'], 'node': str(node), 'package': str(package),
            'tree_sha256': lock['prepared_tree_sha256'], 'files': files, 'interpreters': interpreters,
            'probe_command': [str(node), '--input-type=module', '-e',
                'import {DatabaseSync} from "node:sqlite"; const d=new DatabaseSync(":memory:");'
                'd.exec("CREATE VIRTUAL TABLE verification USING fts5(value)");d.close();'
                'console.log(JSON.stringify({node:process.version,sqlite_fts5:true}))']}


def verify_resources(runtime, codex):
    for item in [*runtime.get('files', []), *codex['files']]:
        path = Path(item['path'])
        if not path.is_file() or sha(path) != item['sha256']:
            raise JobError('context_runtime_invalid', 'Pinned context/Codex resource is missing or changed.')
    package = Path(runtime['package'])
    if runtime.get('kind') == 'native':
        files = {str(path.relative_to(package)): path for path in package.rglob('*') if path.is_file()}
        if not files or any(path.is_symlink() for path in package.rglob('*')) or digest(files) != runtime['tree_sha256']:
            raise JobError('context_runtime_invalid', 'Prepared context-mode dependency closure is missing or changed.')
    try:
        result = subprocess.run(runtime['probe_command'], capture_output=True, text=True, timeout=15, check=True)
        capability = json.loads(result.stdout)
        if not capability.get('sqlite_fts5'):
            raise ValueError()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise JobError('context_runtime_invalid', 'Pinned Node/SQLite FTS5 probe failed.') from None
    return capability


def configuration(runtime, codex, workspace, storage):
    binary = workspace / '.runtime-bin'
    binary.mkdir(exist_ok=True)
    executables = [{'name': 'node', 'path': runtime['node']}, {'name': 'codex', 'path': codex['command'][0]},
                   *runtime.get('interpreters', [])]
    for item in executables:
        link = binary / item['name']
        if link.is_symlink():
            link.unlink()
        if link.exists():
            raise JobError('context_runtime_invalid', 'Runtime command path was replaced.')
        link.symlink_to(item['path'])
    temporary, home = storage / 'tmp', storage / 'config'
    temporary.mkdir(parents=True, exist_ok=True)
    home.mkdir(exist_ok=True)
    context_env = {'CONTEXT_MODE_PLATFORM': 'codex', 'CONTEXT_MODE_PROJECT_DIR': str(workspace),
                   'CONTEXT_MODE_DIR': str(storage), 'TMPDIR': str(temporary), 'CODEX_HOME': str(home),
                   'PATH': str(binary) + os.pathsep + '/usr/bin:/bin'}
    hooks = {}
    commands = {}
    for event, script in EVENTS.items():
        entry = Path(runtime['package']) / 'hooks/codex' / (script + '.mjs')
        command = shlex.join(['/usr/bin/env', *[key + '=' + val for key, val in context_env.items()], runtime['node'], str(entry)])
        handler = {'type': 'command', 'command': command, 'timeout': 30, 'additionalContextLimit': 8000}
        group = {'hooks': [handler]}
        if event == 'PreToolUse':
            group['matcher'] = 'local_shell|shell|shell_command|exec_command|Bash|Shell|apply_patch|Edit|Write|grep_files|ctx_execute|ctx_execute_file|ctx_batch_execute|ctx_search|ctx_index|mcp__'
        hooks[event] = [group]
        commands[command] = event[0].lower() + event[1:]
    mcp = {'context_mode': {'command': runtime['node'], 'args': [str(Path(runtime['package']) / 'server.bundle.mjs')],
                           'env': context_env, 'startup_timeout_sec': 45, 'tool_timeout_sec': 90,
                           'enabled_tools': TOOLS, 'required': True,
                           'tools': {tool: {'approval_mode': 'approve'} for tool in TOOLS}}}
    return {'hooks': hooks, 'mcp_servers': mcp, 'commands': commands, 'context_environment': context_env,
            'process_environment': {**os.environ, **{k: v for k, v in context_env.items() if k != 'CODEX_HOME'}}}


def command(codex, settings, trust=None):
    result = [*codex['command'][:3], '--disable', 'plugins', '--enable', 'hooks', '--enable', 'shell_tool',
              '--disable', 'skill_mcp_dependency_install', '--disable', 'unified_exec', '-c', 'features.node_repl=false',
              '-c', 'mcp_servers=' + toml(settings['mcp_servers'])]
    for event, entries in settings['hooks'].items():
        result += ['-c', 'hooks.' + event + '=' + toml(entries)]
    if trust:
        result += ['-c', 'hooks.state=' + toml(trust)]
    return result


def verify_hooks(result, settings, trusted=False, expected=None):
    entries = result.get('data', [])
    if len(entries) != 1 or entries[0].get('errors'):
        raise JobError('context_hooks_invalid', 'Codex could not resolve exactly one hook scope.')
    hooks = entries[0]['hooks']
    if len(hooks) != len(EVENTS) or {item.get('command') for item in hooks} != set(settings['commands']):
        raise JobError('context_hooks_invalid', 'Effective hooks differ from vetted application hooks.')
    for item in hooks:
        if not item.get('enabled') or item.get('source') != 'sessionFlags' or item.get('handlerType') != 'command':
            raise JobError('context_hooks_invalid', 'Hook source/enabled state is not the vetted session configuration.')
        if item.get('eventName') != settings['commands'][item['command']]:
            raise JobError('context_hooks_invalid', 'Hook event mapping differs from the vetted definition.')
        if trusted and (item.get('trustStatus') != 'trusted' or expected.get(item['key'], {}).get('trusted_hash') != item['currentHash']):
            raise JobError('context_hook_untrusted', 'Codex did not trust the exact vetted hook definition.')
    return {item['key']: {'trusted_hash': item['currentHash']} for item in hooks}
