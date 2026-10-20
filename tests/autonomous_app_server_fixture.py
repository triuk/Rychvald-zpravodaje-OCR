"""Controlled peer for the full public action; never genuine model evidence."""
from pathlib import Path
import runpy
import sqlite3
import sys

fixtures = Path(__file__).resolve().parent
peer_mode = next((value for value in sys.argv[1:] if value in
    ('waive_output', 'drop_output', 'template_output', 'tamper_output', 'tamper_geometry',
     'absolute_input_evidence', 'outside_evidence')), 'full_run')
if Path('reading-packet.json').exists():
    filename, mode = 'reading_app_server_fixture.py', 'full_run'
elif Path('diagnostic-data.txt').exists():
    # Explicit controlled protocol/store fixture, not the installed plugin.
    store = Path.cwd().parent / 'store'
    for name in ('content', 'sessions'):
        (store / name).mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store / 'content/fixture.db') as db:
        db.executescript('CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(content); CREATE TABLE IF NOT EXISTS sources(id);')
        db.execute('DELETE FROM chunks')
        db.execute('INSERT INTO chunks VALUES(?)', (Path('diagnostic-data.txt').read_text(),))
    with sqlite3.connect(store / 'sessions/fixture.db') as db:
        db.executescript('CREATE TABLE IF NOT EXISTS session_meta(session_id,project_dir,compact_count);'
            'CREATE TABLE IF NOT EXISTS session_events(session_id); CREATE TABLE IF NOT EXISTS session_resume(session_id,snapshot,event_count,consumed);'
            'DELETE FROM session_meta; DELETE FROM session_events; DELETE FROM session_resume;')
        db.execute('INSERT INTO session_meta VALUES(?,?,1)', ('context-fixture-thread', str(Path.cwd())))
        db.execute('INSERT INTO session_events VALUES(?)', ('context-fixture-thread',))
        db.execute('INSERT INTO session_resume VALUES(?,?,1,0)', ('context-fixture-thread', 'Explicit controlled snapshot'))
    filename, mode = 'context_app_server_fixture.py', 'full_protocol'
elif Path('image.png').exists():
    filename, mode = 'codex_app_server_fixture.py', 'success'
else:
    filename, mode = 'geometry_app_server_fixture.py', peer_mode
sys.argv.insert(1, mode)
runpy.run_path(str(fixtures / filename), run_name='__main__')
