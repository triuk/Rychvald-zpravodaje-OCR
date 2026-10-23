"""Release capture/build/install public seams, using the selected real resources."""
import json
import hashlib
import os
import selectors
import signal
import shutil
from pathlib import Path
import subprocess
import sys
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROOF = Path(os.environ.get('OCR_RELEASE_ARTIFACTS', ROOT / '.scratch/release-proof'))


class ReleaseCaptureTests(unittest.TestCase):
    def test_missing_reviewed_selection_cannot_create_capture(self):
        target = PROOF / 'missing-selection-capture'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_bundle.py'),
            'capture-release', '--selection', str(PROOF / 'absent-selection.json'),
            '--inputs', str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'package_failed')
        self.assertFalse(target.exists())

    def test_reviewed_capture_builds_offline_and_installs_complete_application(self):
        proof = PROOF / ('offline-' + str(time.time_ns()))
        proof.mkdir(parents=True)
        inputs, archive, installed = proof / 'inputs', proof / 'release.tar.gz', proof / 'installed ž'

        def command(*arguments):
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_bundle.py'),
                *map(str, arguments)], capture_output=True, text=True)
            (proof / (str(arguments[0]) + '.stdout')).write_text(result.stdout)
            (proof / (str(arguments[0]) + '.stderr')).write_text(result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)

        command('capture-release', '--selection', ROOT / 'native/release-inputs.json', '--inputs', inputs)
        built = command('build-release', '--inputs', inputs, '--output', archive)
        command('install', '--archive', archive, '--sha256', built['sha256'], '--destination', installed)
        self.assertTrue((installed / 'bin/rychvald-ocr-gui').is_file())
        self.assertTrue((installed / 'native/geometry-adapter-compatibility.json').is_file())
        self.assertTrue((installed / 'app/run_queue.py').is_file())
        self.assertEqual(json.loads((installed / 'provenance/release.json').read_text())['prepared_context'],
                         'e6304ac4d20283362feda2d5287b8e008af48c9b7e3fb949414aa1f89fdd2c17')
        (PROOF / 'latest-helper-installation.txt').write_text(str(installed) + '\n')

    def test_serve_reports_real_loopback_webui_and_closes_on_signal(self):
        installed = Path((PROOF / 'latest-helper-installation.txt').read_text().strip())
        registry = installed.parent / 'persistent-data'
        registry.mkdir(exist_ok=True)
        # The selected native WebUI optionally discovers host GTK. An empty root
        # keeps this browser-free server test within the declared runtime closure.
        vector = ['/usr/bin/bwrap', '--unshare-user', '--unshare-ipc', '--unshare-uts',
            '--unshare-cgroup', '--die-with-parent',
            '--new-session', '--clearenv', '--ro-bind', str(installed), '/app',
            '--bind', str(registry), '/data', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--dir', '/bin', '--ro-bind', str(installed / 'runtime/native/bash'), '/bin/sh',
            '--symlink', '/app/lib', '/lib64', '--chdir', '/tmp',
            '--setenv', 'LD_LIBRARY_PATH', '/app/lib', '--setenv', 'PATH', '/poisoned',
            '--setenv', 'PYTHONPATH', '/poisoned-python', '--setenv', 'PYTHONHOME', '/poisoned-home',
            '--setenv', 'RYCHVALD_CONTEXT_BIN', '/poisoned-context',
            '--setenv', 'RYCHVALD_CODEX_RUNTIME', '/poisoned-codex',
            '/app/bin/rychvald-ocr-gui', '--root', '/data', '--serve']
        with (installed.parent / 'serve.stderr').open('w') as stderr:
            process = subprocess.Popen(vector, stdout=subprocess.PIPE, stderr=stderr,
                                       text=True, start_new_session=True)
            try:
                ready = selectors.DefaultSelector()
                ready.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(ready.select(25), 'Installed WebUI did not report readiness')
                line = process.stdout.readline()
                self.assertTrue(line, (installed.parent / 'serve.stderr').read_text())
                event = json.loads(line)
                self.assertEqual(event['status'], 'ready', event)
                self.assertTrue(event['url'].startswith('http://localhost:') or
                                event['url'].startswith('http://127.0.0.1:'), event)
                with urllib.request.urlopen(event['url'], timeout=5) as response:
                    self.assertIn('Rychvald', response.read().decode())
                os.kill(event['pid'], signal.SIGTERM)
                self.assertEqual(process.wait(timeout=15), 0)
                (installed.parent / 'serve-ready.json').write_text(json.dumps(event) + '\n')
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=15)

    def test_selected_context_runs_original_hooks_and_real_mcp_without_host_runtime(self):
        installed = Path((PROOF / 'latest-helper-installation.txt').read_text().strip())
        proof = installed.parent / ('context-proof-' + str(time.time_ns()))
        proof.mkdir()
        script = proof / 'context-check.py'
        script.write_text('''import json, os, pathlib, subprocess, sys
assert not pathlib.Path('/usr').exists() and not pathlib.Path('/home').exists()
app = pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '/app')
assert app==pathlib.Path('/app') or not pathlib.Path('/app').exists()
sys.path.insert(0, str(app))
os.environ.update(RYCHVALD_BUNDLE_ROOT=str(app), RYCHVALD_CONTEXT_DESCRIPTOR=str(app/'native/bundled-context.json'), RYCHVALD_CODEX_RUNTIME=str(app/'runtime/codex/codex'))
from app.context_runtime import default_context_runtime, verify_resources, configuration
from app.codex import default_runtime
r, c = default_context_runtime(), default_runtime()
capability = verify_resources(r, c)
work, storage = pathlib.Path('/work/context-work'), pathlib.Path('/work/context-store')
work.mkdir(exist_ok=True); storage.mkdir(exist_ok=True)
settings = configuration(r, c, work, storage)
binary = pathlib.Path(settings['context_environment']['PATH'])
assert binary.parent == work / '.runtime-bin' and not binary.is_symlink()
for event, groups in settings['hooks'].items():
 command = groups[0]['hooks'][0]['command']
 result = subprocess.run(command, shell=True, input=json.dumps({'cwd':str(work),'session_id':'offline-release-check','hook_event_name':event}),capture_output=True,text=True,timeout=20)
 assert result.returncode == 0, (event,result.returncode,command,result.stdout,result.stderr)
mcp = settings['mcp_servers']['context_mode']
cases = [('javascript', 'console.log(["offline","release","javascript","ok"].join("-")); process.exitCode=0;', 'offline-release-javascript-ok'), ('python', 'import sys; print("-".join(["offline","release","python","ok"])); sys.exit(0)', 'offline-release-python-ok'), ('shell', 'printf "%s-%s-%s-%s\\\\n" offline release shell ok; exit 0', 'offline-release-shell-ok')]
messages = [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'release-offline-check','version':'1'}}}, {'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}]
messages += [{'jsonrpc':'2.0','id':index,'method':'tools/call','params':{'name':'ctx_execute','arguments':{'language':language,'code':code}}} for index,(language,code,marker) in enumerate(cases,3)]
result = subprocess.run([mcp['command'],*mcp['args']],input=''.join(json.dumps(m)+'\\n' for m in messages),cwd=work,env={**os.environ,**mcp['env']},capture_output=True,text=True,timeout=30)
assert result.returncode == 0, result.stderr
replies = [json.loads(line) for line in result.stdout.splitlines()]
pathlib.Path('/work/mcp-replies-'+app.name+'.json').write_text(json.dumps(replies,indent=2))
listed = next(v for v in replies if v.get('id')==2)
assert {'ctx_execute','ctx_search'} <= {t['name'] for t in listed['result']['tools']}, listed
executed = {}
for index,(language,code,marker) in enumerate(cases,3):
 called = next(v for v in replies if v.get('id')==index)
 assert not called.get('error') and called['result'].get('isError',False) is False, called
 text = ''.join(block['text'] for block in called['result']['content'] if block['type']=='text')
 actual_stdout = text.split('```',2)[2].strip()
 assert actual_stdout == marker and marker not in code, (language,actual_stdout,called)
 executed[language] = {'mcp_call':called,'actual_stdout':actual_stdout}
launchers = {}
for name,args,marker in [('node',['-e',cases[0][1]],cases[0][2]),('python3',['-c',cases[1][1]],cases[1][2]),('bash',['-c',cases[2][1]],cases[2][2]),('sh',['-c',cases[2][1]],cases[2][2])]:
 launched = subprocess.run([str(binary/name),*args],capture_output=True,text=True,env={**os.environ,**settings['context_environment']})
 launchers[name] = {'exit_code':launched.returncode,'stdout':launched.stdout,'stderr':launched.stderr}
 assert launched.returncode == 0 and launched.stdout.strip()==marker, (name,launchers[name])
print(json.dumps({'capability':capability,'original_hooks':len(settings['hooks']),'mcp_execution':executed,'launchers':launchers,'binary':str(binary),'host_usr_visible':False,'host_home_visible':False}))
''')
        vector = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
            '--ro-bind', str(installed), '/app', '--bind', str(proof), '/work',
            '--ro-bind', str(script), '/checks/context.py', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--dir', '/bin', '--ro-bind', str(installed / 'runtime/native/bash'), '/bin/sh',
            '--symlink', '/app/lib', '/lib64', '--chdir', '/work',
            '--setenv', 'LD_LIBRARY_PATH', '/app/lib', '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
            '--setenv', 'PATH', '/poisoned', '--setenv', 'PYTHONHOME', '/poisoned',
            '--setenv', 'PYTHONPATH', '/poisoned',
            '/app/lib/ld-linux-x86-64.so.2', '--inhibit-cache', '--library-path', '/app/lib',
            '/app/bin/python3.14', '-I', '-B', '/checks/context.py']
        result = subprocess.run(vector, capture_output=True, text=True, timeout=100)
        (proof / 'context-check.stdout').write_text(result.stdout)
        (proof / 'context-check.stderr').write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence['original_hooks'], 6)
        self.assertTrue(evidence['capability']['sqlite_fts5'])
        before = {str(path.relative_to(proof)): path.read_bytes()
                  for path in (proof / 'context-work/.runtime-bin').rglob('*') if path.is_file()}
        moved = [item.replace('/app', '/replacement', 1) if item.startswith('/app') else item for item in vector]
        moved += ['/replacement']
        result = subprocess.run(moved, capture_output=True, text=True, timeout=100)
        (proof / 'context-relocated.stdout').write_text(result.stdout)
        (proof / 'context-relocated.stderr').write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        relocated = json.loads(result.stdout)
        self.assertNotEqual(relocated['binary'], evidence['binary'])
        for name, payload in before.items():
            self.assertEqual((proof / name).read_bytes(), payload)

    def test_tampered_capture_or_gui_closure_fails_before_native_wrapper_import(self):
        installed = Path((PROOF / 'latest-helper-installation.txt').read_text().strip())
        proof = installed.parent / 'tamper'
        proof.mkdir()
        inputs = proof / 'inputs'
        shutil.copytree(installed.parent / 'inputs', inputs, copy_function=os.link)
        native_sha = '59b7230ee0a6608ea6fa5bd38cf327851c0a0cc980976b13793723d25dacf768'
        (inputs / native_sha).unlink()
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_bundle.py'), 'build-release',
            '--inputs', str(inputs), '--output', str(proof / 'forbidden.tar.gz')],capture_output=True,text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'input_mismatch')
        self.assertFalse((proof / 'forbidden.tar.gz').exists())
        broken = proof / 'broken-prefix'
        shutil.copytree(installed, broken, copy_function=os.link)
        for name, payload in [('lib/python3.14/site-packages/webui/webui-linux-clang-x64/libwebui-2.so', None),
                              ('lib/libstdc++.so.6', b'changed dependency')]:
            with self.subTest(resource=name):
                target = broken / name
                target.unlink()
                if payload is not None:
                    target.write_bytes(payload)
                try:
                    result = subprocess.run([str(broken / 'bin/rychvald-ocr-gui'), '--serve', '--root', str(proof / 'data')],capture_output=True,text=True,timeout=20)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout)['error']['code'], 'installation_invalid')
                    self.assertFalse(result.stderr, result.stderr)
                    self.assertFalse((proof / 'data').exists())
                finally:
                    if target.exists():
                        target.unlink()
                    os.link(installed / name, target)

    def test_z_release_reproduces_relocates_and_preserves_native_A1_A11_and_data_on_replacement(self):
        installed = Path((PROOF / 'latest-helper-installation.txt').read_text().strip())
        proof = installed.parent
        repeat = proof / 'repeat.tar.gz'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_bundle.py'), 'build-release',
            '--inputs', str(proof / 'inputs'), '--output', str(repeat)],capture_output=True,text=True)
        (proof / 'repeat-build.stdout').write_text(result.stdout)
        (proof / 'repeat-build.stderr').write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive_sha = json.loads((proof / 'build-release.stdout').read_text())['sha256']
        self.assertEqual(json.loads(result.stdout)['sha256'], archive_sha)
        relocated = proof / 'relocated č'
        installed.rename(relocated)
        (PROOF / 'latest-helper-installation.txt').write_text(str(relocated) + '\n')
        work = proof / 'native-work'
        work.mkdir()
        fixture = proof / 'native-fixture.py'
        shutil.copyfile(ROOT / 'tests/bundle_workflow_fixture.py', fixture)
        vector = ['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv',
            '--bind',str(relocated),'/app','--bind',str(work),'/work',
            '--ro-bind',str(fixture),'/checks/fixture.py','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
            '--dir','/bin','--ro-bind',str(relocated / 'runtime/native/bash'),'/bin/sh',
            '--symlink','/app/lib','/lib64','--setenv','LD_LIBRARY_PATH','/app/lib',
            '--setenv','PATH','/poisoned','--setenv','TESSDATA_PREFIX','/wrong-models',
            '--setenv','PYTHONPATH','/wrong-python','--setenv','PYTHONHOME','/wrong-home',
            '--setenv','PYTHONDONTWRITEBYTECODE','1','/app/lib/ld-linux-x86-64.so.2',
            '--inhibit-cache','--library-path','/app/lib','/app/bin/python3.14','-I','-B','/checks/fixture.py']
        result = subprocess.run(vector,capture_output=True,text=True,timeout=180)
        (proof / 'A1-A11.stdout').write_text(result.stdout)
        (proof / 'A1-A11.stderr').write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads((work / 'package-evidence.json').read_text())
        self.assertEqual(set(evidence['criteria']), {f'A{i}' for i in range(1,12)})
        self.assertTrue(all(evidence['criteria'].values()))
        self.assertFalse(evidence['host_usr_visible'])
        self.assertFalse(evidence['host_home_visible'])
        data = work / 'projects ž'
        before = {str(p.relative_to(data)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in data.rglob('*') if p.is_file()}
        replacement = proof / 'replacement'
        result = subprocess.run([sys.executable,'-B',str(ROOT / 'tools/ocr_bundle.py'),'install',
            '--archive',str(repeat),'--sha256',archive_sha,'--destination',str(replacement)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        for prefix in (relocated,replacement):
            result = subprocess.run([str(prefix / 'bin/rychvald-ocr'),'--root',str(data),'--json','list'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        after = {str(p.relative_to(data)):hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in data.rglob('*') if p.is_file()}
        self.assertEqual(after,before)
        (proof / 'release-verification.json').write_text(json.dumps({'archive_sha256':archive_sha,
            'reproducible':True,'native_criteria':evidence['criteria'],'relocated':str(relocated),
            'replacement':str(replacement),'data_files_preserved':len(before)},indent=2)+'\n')


if __name__ == '__main__':
    unittest.main()
