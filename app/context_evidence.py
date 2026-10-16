"""Read-only verification of actual run-local context-mode SQLite evidence."""
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .jobs import JobError


def inspect_stores(storage, workspace, thread_id, oracle, minimum_bytes):
    storage, workspace = Path(storage).resolve(), Path(workspace).resolve()
    content = list((storage / 'content').glob('*.db'))
    sessions = list((storage / 'sessions').glob('*.db'))
    if len(content) != 1 or len(sessions) != 1 or any(path.is_symlink() for path in content + sessions):
        raise JobError('context_evidence_invalid', 'Exactly one own content store and one own session store are required.')
    try:
        with sqlite3.connect('file:' + quote(str(content[0])) + '?mode=ro', uri=True) as database:
            chunks, stored_bytes = database.execute('SELECT count(*), coalesce(sum(length(content)),0) FROM chunks').fetchone()
            records = database.execute('SELECT content FROM chunks WHERE chunks MATCH ?', ('CONTEXT_DIAGNOSTIC_RECORD',)).fetchall()
            sources = database.execute('SELECT count(*) FROM sources').fetchone()[0]
            if stored_bytes < minimum_bytes // 2 or not any(oracle in row[0] for row in records):
                raise JobError('context_evidence_invalid', 'The large output and exact run-local record are not in the actual FTS5 store.')
        with sqlite3.connect('file:' + quote(str(sessions[0])) + '?mode=ro', uri=True) as database:
            meta = database.execute('SELECT project_dir, compact_count FROM session_meta WHERE session_id=?', (thread_id,)).fetchone()
            events = database.execute('SELECT count(*) FROM session_events WHERE session_id=?', (thread_id,)).fetchone()[0]
            resume = database.execute('SELECT length(snapshot), event_count, consumed FROM session_resume WHERE session_id=?', (thread_id,)).fetchone()
            if not meta or Path(meta[0]).resolve() != workspace or meta[1] < 1 or events < 1 or not resume or resume[0] < 1 or resume[1] < 1:
                raise JobError('context_evidence_invalid', 'Actual session events and compaction snapshot are missing or belong to a different run/thread.')
    except (sqlite3.Error, OSError, ValueError) as error:
        raise JobError('context_evidence_invalid', f'Cannot verify context databases: {error}') from None
    return {'content_database': str(content[0]), 'session_database': str(sessions[0]), 'workspace': str(workspace),
            'sources': sources, 'chunks': chunks, 'stored_content_characters': stored_bytes,
            'session_id': thread_id, 'session_events': events, 'compact_count': meta[1],
            'snapshot_characters': resume[0], 'snapshot_events': resume[1], 'snapshot_consumed': bool(resume[2])}
