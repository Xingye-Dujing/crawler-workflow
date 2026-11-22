"""The AI workspace's durable store, one SQLite file per account.

Every read resolves ``runtime.paths.active()`` at CALL time. The test harness repoints
``Config.DATA_DIR`` at import, and a cached path would keep writing the operator's real tree.

Rows are appended, never renumbered: a message's ``seq`` is ``MAX(seq)+1``. The assistant row is
created as ``streaming`` before the first token, updated while it streams, and settled on stop or
error, so a dead process leaves a visible interruption rather than a vanished answer.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from runtime import paths

from ai.errors import AIError
from ai.types import new_id

#: One memory is a fact the user confirmed, not a transcript: it goes into the context of every
#: later turn, so it has to stay short. Both bounds refuse BY NAME — silently truncating or
#: dropping the oldest row would decide on the user's behalf what the assistant may remember.
MAX_MEMORY_CHARS = 8000
MAX_MEMORIES = 1000

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    skill TEXT NOT NULL DEFAULT '',
    title_source TEXT NOT NULL DEFAULT 'fallback',
    pinned INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    blocks_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'done',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    usage_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_conversation ON messages(conversation_id, seq);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    tool_use_id TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    answer_json TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    answered_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    name TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT 'user_data',
    file_id TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_attachments_conversation ON attachments(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    plan_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    meta_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS agent_steps (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    args_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ai_steps_run ON agent_steps(run_id, seq);
CREATE TABLE IF NOT EXISTS user_skills (
    id TEXT PRIMARY KEY,
    name_key TEXT NOT NULL DEFAULT '',
    description_key TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '[]',
    tools_json TEXT NOT NULL DEFAULT '[]',
    requires_json TEXT NOT NULL DEFAULT '[]',
    suggested_json TEXT NOT NULL DEFAULT '[]',
    ask_policy TEXT NOT NULL DEFAULT 'auto',
    icon TEXT NOT NULL DEFAULT 'spark',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plugins (
    id TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'user',
    installed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prefs (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS monitors (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    spec_json TEXT NOT NULL DEFAULT '{}',
    auto_analyze INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'armed',
    trigger_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_event_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ai_monitors_conversation ON monitors(conversation_id, status);
CREATE TABLE IF NOT EXISTS monitor_events (
    id TEXT PRIMARY KEY,
    monitor_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    event TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    delivered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_monitor_events_pending ON monitor_events(conversation_id, delivered, created_at);
"""


def _db_path() -> str:
    target = paths.active().ai_db
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return target


#: The identity of the db file whose tables this process has already created. ``connect`` used to
#: run the whole schema (and two PRAGMA probes) on EVERY call, which put a schema write on the run
#: thread for each delivered monitor event. Creating tables is a one-time fact, not a per-connection
#: one — but it is a fact about the FILE, not merely its path: a reset that deletes and recreates
#: the db at the same path produced an empty database that every later call trusted as "ready"
#: (``no such table: messages``), and the monitor worker logged a warning for every run event.
def _schema_stamp(path: str) -> tuple:
    try:
        stat = os.stat(path)
    except OSError:
        return ()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


_SCHEMA_READY: dict[str, tuple] = {}
_SCHEMA_LOCK = threading.Lock()


@contextmanager
def connect():
    path = _db_path()
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    stamp = _schema_stamp(path)
    with _SCHEMA_LOCK:
        ready = bool(stamp) and _SCHEMA_READY.get(path) == stamp
    if not ready:
        conn.executescript(SCHEMA)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(user_skills)').fetchall()}
        if 'name' not in columns:
            conn.execute("ALTER TABLE user_skills ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if 'description' not in columns:
            conn.execute("ALTER TABLE user_skills ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        with _SCHEMA_LOCK:
            # Re-stat after the writes: the schema changed the file's size and mtime.
            _SCHEMA_READY[path] = _schema_stamp(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row(row) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for key in (
        'blocks_json',
        'usage_json',
        'meta_json',
        'questions_json',
        'answer_json',
        'plan_json',
        'args_json',
        'result_json',
        'context_json',
        'tools_json',
        'requires_json',
        'suggested_json',
        'permissions_json',
        'manifest_json',
        'spec_json',
        'payload_json',
    ):
        if key not in data:
            continue
        raw = data.pop(key)
        name = key[:-5]
        if isinstance(raw, str) and raw:
            try:
                data[name] = json.loads(raw)
            except ValueError:
                data[name] = (
                    {}
                    if name in ('meta', 'usage', 'answer', 'plan', 'args', 'manifest', 'permissions', 'spec', 'payload')
                    else []
                )
        else:
            data[name] = (
                {}
                if name in ('meta', 'usage', 'answer', 'plan', 'args', 'manifest', 'permissions', 'spec', 'payload')
                else []
            )
    return data


def now() -> str:

    return datetime.now(UTC).isoformat()


def create_conversation(provider: str = '', model: str = '', skill: str = 'auto') -> dict:
    conversation_id = new_id('c')
    stamp = now()
    with connect() as conn:
        conn.execute(
            'INSERT INTO conversations (id, title, provider, model, skill, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (conversation_id, '', provider, model, skill, stamp, stamp),
        )
    return get_conversation(conversation_id)


def list_conversations(limit: int = 80, q: str = '', archived: bool = False, offset: int = 0) -> list:
    """Conversations newest-first, optionally narrowed to a title match.

    ``q`` is matched by SQLite, not by the browser: the list in memory is a page (80 rows), so a
    client-side filter would report "not found" for a conversation that exists past the page. The
    LIKE metacharacters in the user's text are escaped, or a search for ``100%`` would match all.
    """
    limit = min(500, max(1, int(limit)))
    offset = max(0, int(offset))
    clauses = ['c.archived = ?']
    params: list = [1 if archived else 0]
    needle = str(q or '').strip()
    if needle:
        escaped = needle.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        clauses.append("c.title LIKE ? ESCAPE '\\'")
        params.append(f'%{escaped}%')
    params.extend([limit, offset])
    with connect() as conn:
        rows = conn.execute(
            'SELECT c.*, '
            '(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count '
            'FROM conversations c WHERE ' + ' AND '.join(clauses) + ' '
            'ORDER BY c.pinned DESC, c.updated_at DESC, c.rowid DESC LIMIT ? OFFSET ?',
            tuple(params),
        ).fetchall()
    return [_row(row) for row in rows]


def get_conversation(conversation_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM conversations WHERE id = ?', (conversation_id,)).fetchone()
    return _row(row)


def touch_conversation(conversation_id: str, bump: bool = True, **fields) -> None:
    """Update stored fields; ``bump`` keeps the conversation from looking newly active.

    Pinning or archiving is not activity: bumping ``updated_at`` for those moved an UNpinned chat
    to the top of a list ordered by recency, which is the opposite of what the click said.
    """
    allowed = {
        key: value
        for key, value in fields.items()
        if key in ('title', 'title_source', 'provider', 'model', 'skill', 'pinned', 'archived')
    }
    if bump:
        allowed['updated_at'] = now()
    if not allowed:
        return
    assignments = ', '.join(f'{key} = ?' for key in allowed)
    with connect() as conn:
        conn.execute(f'UPDATE conversations SET {assignments} WHERE id = ?', (*allowed.values(), conversation_id))


def delete_conversation(conversation_id: str) -> bool:
    with connect() as conn:
        # An armed monitor outlives its conversation only as a machine-written turn that reappears
        # in a conversation the user deleted. Both its rows and its pending deliveries go with it.
        for table in (
            'messages',
            'questions',
            'agent_steps',
            'agent_runs',
            'usage',
            'attachments',
            'monitors',
            'monitor_events',
        ):
            if table == 'agent_steps':
                conn.execute(
                    'DELETE FROM agent_steps WHERE run_id IN (SELECT id FROM agent_runs WHERE conversation_id = ?)',
                    (conversation_id,),
                )
            else:
                conn.execute(f'DELETE FROM {table} WHERE conversation_id = ?', (conversation_id,))
        cur = conn.execute('DELETE FROM conversations WHERE id = ?', (conversation_id,))
    return cur.rowcount > 0


def _next_seq(conn, conversation_id: str) -> int:
    row = conn.execute(
        'SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM messages WHERE conversation_id = ?', (conversation_id,)
    ).fetchone()
    return int(row['n'])


def append_message(
    conversation_id: str,
    role: str,
    content: str = '',
    blocks: list | None = None,
    status: str = 'done',
    provider: str = '',
    model: str = '',
    meta: dict | None = None,
    usage: dict | None = None,
) -> dict:
    message_id = new_id('m')
    stamp = now()
    with connect() as conn:
        seq = _next_seq(conn, conversation_id)
        conn.execute(
            'INSERT INTO messages '
            '(id, conversation_id, seq, role, content, blocks_json, status, provider, model, usage_json, '
            'created_at, updated_at, meta_json) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                message_id,
                conversation_id,
                seq,
                role,
                content,
                json.dumps(blocks or [], ensure_ascii=False),
                status,
                provider,
                model,
                json.dumps(usage or {}, ensure_ascii=False),
                stamp,
                stamp,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        conn.execute('UPDATE conversations SET updated_at = ? WHERE id = ?', (stamp, conversation_id))
    return get_message(message_id)


def update_message(message_id: str, **fields) -> dict | None:
    allowed = {}
    for key in ('content', 'status', 'usage', 'meta'):
        if key not in fields:
            continue
        value = fields[key]
        if key in ('usage', 'meta'):
            allowed[f'{key}_json'] = json.dumps(value or {}, ensure_ascii=False)
        else:
            allowed[key] = value
    if 'blocks' in fields:
        allowed['blocks_json'] = json.dumps(fields['blocks'] or [], ensure_ascii=False)
    allowed['updated_at'] = now()
    assignments = ', '.join(f'{key} = ?' for key in allowed)
    with connect() as conn:
        conn.execute(f'UPDATE messages SET {assignments} WHERE id = ?', (*allowed.values(), message_id))
    return get_message(message_id)


def get_message(message_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM messages WHERE id = ?', (message_id,)).fetchone()
    return _row(row)


def list_messages(conversation_id: str, limit: int = 400) -> list:
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq DESC LIMIT ?',
            (conversation_id, max(1, int(limit))),
        ).fetchall()
    return [_row(row) for row in reversed(rows)]


def count_messages(conversation_id: str) -> int:
    """How many rows this conversation holds, regardless of the page a reader asks for.

    The agent reads a bounded tail; the inspector must be able to say how much of the start that
    tail left out instead of reporting ``dropped: 0`` over a silently forgotten first half.
    """
    with connect() as conn:
        row = conn.execute(
            'SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?',
            (conversation_id,),
        ).fetchone()
    return int(row['n']) if row is not None else 0


def create_question(conversation_id: str, message_id: str, tool_use_id: str, questions: list) -> dict:
    question_id = new_id('q')
    stamp = now()
    with connect() as conn:
        conn.execute(
            'INSERT INTO questions (id, conversation_id, message_id, tool_use_id, questions_json, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (question_id, conversation_id, message_id, tool_use_id, json.dumps(questions, ensure_ascii=False), stamp),
        )
    return get_question(question_id)


def get_question(question_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
    return _row(row)


def pending_questions(conversation_id: str) -> list:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM questions WHERE conversation_id = ? AND status = 'pending' ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
    return [_row(row) for row in rows]


def answer_question(question_id: str, answer: dict) -> dict | None:
    stamp = now()
    with connect() as conn:
        cur = conn.execute(
            "UPDATE questions SET answer_json = ?, status = 'answered', answered_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (json.dumps(answer, ensure_ascii=False), stamp, question_id),
        )
        # A duplicate concurrent answer must be told it lost. Returning get_question() here
        # reported success even when the conditional UPDATE matched nothing, so two POSTs
        # appended two tool results and resumed the same turn twice.
        if cur.rowcount != 1:
            return None
    return get_question(question_id)


def add_attachment(
    conversation_id: str,
    name: str,
    mime: str,
    size: int,
    sha256: str,
    purpose: str,
    file_id: str,
    path: str,
) -> dict:
    attachment_id = new_id('att')
    with connect() as conn:
        conn.execute(
            'INSERT INTO attachments (id, conversation_id, name, mime, size, sha256, purpose, file_id, path, '
            'created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (attachment_id, conversation_id, name, mime, int(size), sha256, purpose, file_id, path, now()),
        )
    return get_attachment(attachment_id)


def get_attachment(attachment_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM attachments WHERE id = ?', (attachment_id,)).fetchone()
    return _row(row)


def list_attachments(conversation_id: str) -> list:
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM attachments WHERE conversation_id = ? ORDER BY created_at',
            (conversation_id,),
        ).fetchall()
    return [_row(row) for row in rows]


def find_attachment_by_digest(sha256: str) -> dict | None:
    """The newest uploaded copy of these exact bytes, from any conversation.

    Uploading the same file in a second conversation used to send the bytes again, parse them
    again and pay again. The provider already holds this ``file_id``, so the second conversation
    gets its own attachment row pointing at the same upload.
    """
    text = str(sha256 or '')
    if not text:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM attachments WHERE sha256 = ? AND file_id != '' ORDER BY created_at DESC LIMIT 1",
            (text,),
        ).fetchone()
    return _row(row)


def list_attachments_everywhere(limit: int = 60) -> list:
    """The newest file uploads across every conversation, one row per distinct content.

    Local-only uploads (a provider with no Files API) are included: the picker used to hide them,
    so a file the user had just attached could not be named with ``@`` in the next turn.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM attachments WHERE sha256 != '' GROUP BY sha256 ORDER BY MAX(created_at) DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [_row(row) for row in rows]


def delete_attachment(attachment_id: str) -> dict | None:
    row = get_attachment(attachment_id)
    if row is None:
        return None
    with connect() as conn:
        conn.execute('DELETE FROM attachments WHERE id = ?', (attachment_id,))
    return row


def create_run(conversation_id: str, message_id: str) -> dict:
    run_id = new_id('r')
    with connect() as conn:
        conn.execute(
            'INSERT INTO agent_runs (id, conversation_id, message_id, created_at) VALUES (?, ?, ?, ?)',
            (run_id, conversation_id, message_id, now()),
        )
    return get_run(run_id)


def get_run(run_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM agent_runs WHERE id = ?', (run_id,)).fetchone()
    return _row(row)


def update_run(run_id: str, **fields) -> None:
    allowed = {}
    for key in ('status', 'plan', 'meta', 'ended_at'):
        if key not in fields:
            continue
        if key in ('plan', 'meta'):
            allowed[f'{key}_json'] = json.dumps(fields[key] or [], ensure_ascii=False)
        else:
            allowed[key] = fields[key]
    if not allowed:
        return
    assignments = ', '.join(f'{key} = ?' for key in allowed)
    with connect() as conn:
        conn.execute(f'UPDATE agent_runs SET {assignments} WHERE id = ?', (*allowed.values(), run_id))


def add_step(run_id: str, title: str, tool: str = '', args: dict | None = None, status: str = 'running') -> dict:
    step_id = new_id('s')
    with connect() as conn:
        row = conn.execute(
            'SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM agent_steps WHERE run_id = ?', (run_id,)
        ).fetchone()
        conn.execute(
            'INSERT INTO agent_steps (id, run_id, seq, title, tool, status, args_json, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (step_id, run_id, int(row['n']), title, tool, status, json.dumps(args or {}, ensure_ascii=False), now()),
        )
    return get_step(step_id)


def get_step(step_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM agent_steps WHERE id = ?', (step_id,)).fetchone()
    return _row(row)


def update_step(step_id: str, **fields) -> None:
    allowed = {}
    for key in ('status', 'result', 'title'):
        if key not in fields:
            continue
        if key == 'result':
            allowed['result_json'] = json.dumps(fields[key], ensure_ascii=False)
        else:
            allowed[key] = fields[key]
    if fields.get('status') in ('done', 'failed'):
        allowed['ended_at'] = now()
    if not allowed:
        return
    assignments = ', '.join(f'{key} = ?' for key in allowed)
    with connect() as conn:
        conn.execute(f'UPDATE agent_steps SET {assignments} WHERE id = ?', (*allowed.values(), step_id))


def save_usage(conversation_id: str, message_id: str, provider: str, model: str, usage: dict) -> None:
    with connect() as conn:
        conn.execute(
            'INSERT INTO usage (id, conversation_id, message_id, provider, model, prompt_tokens, completion_tokens, '
            'cached_tokens, reasoning_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                new_id('u'),
                conversation_id,
                message_id,
                provider,
                model,
                int(usage.get('prompt_tokens') or 0),
                int(usage.get('completion_tokens') or 0),
                int(usage.get('cached_tokens') or 0),
                int(usage.get('reasoning_tokens') or 0),
                now(),
            ),
        )


def usage_summary() -> dict:
    with connect() as conn:
        row = conn.execute(
            'SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, '
            'COALESCE(SUM(completion_tokens), 0) AS completion_tokens, '
            'COALESCE(SUM(cached_tokens), 0) AS cached_tokens, '
            'COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens FROM usage'
        ).fetchone()
    return dict(row) if row else {}


def conversation_usage(conversation_id: str) -> list:
    """Token counts for ONE conversation, per ``(provider, model)`` — the spend panel's input.

    Grouped, because a conversation can switch models mid-way (a fallen-back provider, a user's
    picker change) and each model has its own price: one blended number would be a number nobody
    could check.
    """
    with connect() as conn:
        rows = conn.execute(
            'SELECT provider, model, '
            'COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, '
            'COALESCE(SUM(completion_tokens), 0) AS completion_tokens, '
            'COALESCE(SUM(cached_tokens), 0) AS cached_tokens, '
            'COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens, '
            'COUNT(*) AS calls '
            'FROM usage WHERE conversation_id = ? GROUP BY provider, model '
            'ORDER BY prompt_tokens DESC',
            (conversation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def token_usage(conversation_id: str = '', since: str = '') -> dict:
    """Tokens already spent, scoped to one conversation and/or a UTC-since timestamp.

    A budget needs the spend SO FAR, not a per-model price breakdown: cached tokens are a subset of
    the prompt, so only prompt + completion count. Both filters are optional; with neither, this is
    the all-time account total (the store itself is one SQLite file per account).
    """
    clauses = []
    params: list = []
    if conversation_id:
        clauses.append('conversation_id = ?')
        params.append(conversation_id)
    if since:
        clauses.append('created_at >= ?')
        params.append(since)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with connect() as conn:
        row = conn.execute(
            'SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens, '
            'COALESCE(SUM(cached_tokens), 0) AS cached, COUNT(*) AS calls FROM usage' + where,
            tuple(params),
        ).fetchone()
    return dict(row) if row else {'tokens': 0, 'cached': 0, 'calls': 0}


def list_user_skills() -> list:
    with connect() as conn:
        rows = conn.execute('SELECT * FROM user_skills ORDER BY updated_at DESC').fetchall()
    return [_row(row) for row in rows]


def get_user_skill(skill_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM user_skills WHERE id = ?', (skill_id,)).fetchone()
    return _row(row)


def save_user_skill(skill: dict) -> dict:
    stamp = now()
    with connect() as conn:
        existing = conn.execute('SELECT id FROM user_skills WHERE id = ?', (skill['id'],)).fetchone()
        if existing is None:
            conn.execute(
                'INSERT INTO user_skills (id, name_key, description_key, name, description, prompt, context_json, '
                'tools_json, requires_json, suggested_json, ask_policy, icon, version, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    skill['id'],
                    skill.get('name_key') or '',
                    skill.get('description_key') or '',
                    skill.get('name') or '',
                    skill.get('description') or '',
                    skill['prompt'],
                    json.dumps(skill.get('context') or [], ensure_ascii=False),
                    json.dumps(skill.get('tools') or [], ensure_ascii=False),
                    json.dumps(skill.get('requires') or [], ensure_ascii=False),
                    json.dumps(skill.get('suggested') or [], ensure_ascii=False),
                    skill.get('ask_policy') or 'auto',
                    skill.get('icon') or 'spark',
                    int(skill.get('version') or 1),
                    stamp,
                    stamp,
                ),
            )
        else:
            conn.execute(
                'UPDATE user_skills SET name_key = ?, description_key = ?, name = ?, description = ?, prompt = ?, '
                'context_json = ?, tools_json = ?, requires_json = ?, suggested_json = ?, ask_policy = ?, icon = ?, '
                'version = ?, updated_at = ? WHERE id = ?',
                (
                    skill.get('name_key') or '',
                    skill.get('description_key') or '',
                    skill.get('name') or '',
                    skill.get('description') or '',
                    skill['prompt'],
                    json.dumps(skill.get('context') or [], ensure_ascii=False),
                    json.dumps(skill.get('tools') or [], ensure_ascii=False),
                    json.dumps(skill.get('requires') or [], ensure_ascii=False),
                    json.dumps(skill.get('suggested') or [], ensure_ascii=False),
                    skill.get('ask_policy') or 'auto',
                    skill.get('icon') or 'spark',
                    int(skill.get('version') or 1),
                    stamp,
                    skill['id'],
                ),
            )
    return get_user_skill(skill['id'])


def delete_user_skill(skill_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute('DELETE FROM user_skills WHERE id = ?', (skill_id,))
    return cur.rowcount > 0


def list_plugins() -> list:
    with connect() as conn:
        rows = conn.execute('SELECT * FROM plugins ORDER BY installed_at DESC').fetchall()
    return [_row(row) for row in rows]


def save_plugin(manifest: dict, permissions: list, source: str = 'user') -> dict:
    plugin_id = str(manifest.get('id') or '')
    with connect() as conn:
        conn.execute(
            'INSERT INTO plugins (id, manifest_json, enabled, permissions_json, source, installed_at) '
            'VALUES (?, ?, 1, ?, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET manifest_json = excluded.manifest_json, '
            'permissions_json = excluded.permissions_json, source = excluded.source',
            (
                plugin_id,
                json.dumps(manifest, ensure_ascii=False),
                json.dumps(permissions, ensure_ascii=False),
                source,
                now(),
            ),
        )
    return get_plugin(plugin_id)


def get_plugin(plugin_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM plugins WHERE id = ?', (plugin_id,)).fetchone()
    return _row(row)


def set_plugin_enabled(plugin_id: str, enabled: bool) -> bool:
    with connect() as conn:
        cur = conn.execute('UPDATE plugins SET enabled = ? WHERE id = ?', (1 if enabled else 0, plugin_id))
    return cur.rowcount > 0


def delete_plugin(plugin_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute('DELETE FROM plugins WHERE id = ?', (plugin_id,))
    return cur.rowcount > 0


def list_memories(limit: int = 0) -> list:
    """Confirmed memories, newest first. ``limit=0`` means every row (the studio lists them all)."""
    sql = 'SELECT * FROM memories ORDER BY created_at DESC, rowid DESC'
    params: tuple = ()
    if limit:
        sql += ' LIMIT ?'
        params = (max(1, int(limit)),)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(row) for row in rows]


def _memory_key(text: str) -> str:
    return ' '.join(str(text or '').split()).casefold()


def save_memory(text: str) -> dict:
    """Store one confirmed fact, idempotently.

    A duplicate is not an error: the same sentence reaching the store twice (an artifact applied
    twice, a retried request) means the fact is already known, so the existing row is returned with
    ``duplicate: True``. A store that is FULL refuses by name — evicting the oldest memory would let
    a chat silently rewrite what the user chose to keep.
    """
    cleaned = str(text or '').strip()
    if not cleaned:
        raise AIError('ai.apiNoText', kind='bad_request')
    if len(cleaned) > MAX_MEMORY_CHARS:
        raise AIError('ai.memoryTooLong', kind='bad_request', limit=MAX_MEMORY_CHARS)
    key = _memory_key(cleaned)
    with connect() as conn:
        rows = conn.execute('SELECT * FROM memories ORDER BY created_at DESC').fetchall()
        for row in rows:
            if _memory_key(row['text']) == key:
                return {**_row(row), 'duplicate': True}
        if len(rows) >= MAX_MEMORIES:
            raise AIError('ai.memoryFull', kind='bad_request', limit=MAX_MEMORIES)
        memory_id = new_id('mem')
        stamp = now()
        conn.execute('INSERT INTO memories (id, text, created_at) VALUES (?, ?, ?)', (memory_id, cleaned, stamp))
    return {'id': memory_id, 'text': cleaned, 'created_at': stamp}


def delete_memory(memory_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
    return cur.rowcount > 0


def get_pref(key: str, default: str = '') -> str:
    """One per-account preference (``ai.db`` follows the signed-in account's tree).

    Used for facts that are the USER's machine, not the server's policy — the working folder is one
    of those, so it cannot live in the system-level settings file.
    """
    with connect() as conn:
        row = conn.execute('SELECT value FROM prefs WHERE key = ?', (str(key),)).fetchone()
    return str(row['value']) if row is not None else default


def set_pref(key: str, value: str) -> str:
    with connect() as conn:
        conn.execute(
            'INSERT INTO prefs (key, value, updated_at) VALUES (?, ?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at',
            (str(key), str(value or ''), now()),
        )
    return str(value or '')


def mark_interrupted(conversation_id: str = '') -> int:
    """Settle rows left ``streaming``: at boot, or the moment a stream's reader goes away.

    A row that is still ``streaming`` cannot still be streaming; with ``conversation_id`` the sweep
    is limited to the turn whose connection just closed, so a concurrent answer elsewhere is safe.

    A live node-trace row is exempt: it is streamed by a background run worker, not by an SSE reader
    this sweep owns, and is settled by that worker when the model call ends. Interrupting it here
    (the boot sweep runs on every page load) cut a demo's live trace in half. But the exemption must
    not be permanent — if the worker was killed, nothing ever settles the row and it shows "still
    streaming" forever. ``updated_at`` is the worker's heartbeat (buffered writes still touch it
    every few hundred ms): a trace row stale for over a minute is orphaned and gets swept.
    """

    stamp = now()
    stale_before = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    sql = (
        "UPDATE messages SET status = 'interrupted', updated_at = ? "
        "WHERE status = 'streaming' AND ("
        "meta_json NOT LIKE '%node_trace_stream%' OR updated_at < ?"
        ')'
    )
    params: tuple = (stamp, stale_before)
    if conversation_id:
        sql += ' AND conversation_id = ?'
        params += (conversation_id,)
    with connect() as conn:
        cur = conn.execute(sql, params)
    return cur.rowcount


def purge_older_than(days: int) -> int:
    if days <= 0:
        return 0

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with connect() as conn:
        cur = conn.execute('DELETE FROM conversations WHERE updated_at < ?', (cutoff,))
        # Monitors and deliveries belong to a conversation; one whose conversation is gone cannot
        # be displayed, armed or served, so keeping the row would only leak.
        conn.execute('DELETE FROM monitors WHERE conversation_id NOT IN (SELECT id FROM conversations)')
        conn.execute('DELETE FROM monitor_events WHERE conversation_id NOT IN (SELECT id FROM conversations)')
        conn.execute('DELETE FROM monitor_events WHERE created_at < ?', (cutoff,))
    return cur.rowcount


# ─── Run monitors ─────────────────────────────────────────────────────────


def add_monitor(conversation_id: str, spec: dict, auto_analyze: bool = False) -> dict:
    monitor_id = new_id('mon')
    with connect() as conn:
        conn.execute(
            'INSERT INTO monitors (id, conversation_id, spec_json, auto_analyze, status, created_at) '
            "VALUES (?, ?, ?, ?, 'armed', ?)",
            (monitor_id, conversation_id, json.dumps(spec, ensure_ascii=False), 1 if auto_analyze else 0, now()),
        )
    return get_monitor(monitor_id)


def get_monitor(monitor_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM monitors WHERE id = ?', (monitor_id,)).fetchone()
    return _row(row)


def list_monitors(conversation_id: str = '', active_only: bool = False) -> list:
    sql = 'SELECT * FROM monitors'
    clauses, params = [], []
    if conversation_id:
        clauses.append('conversation_id = ?')
        params.append(conversation_id)
    if active_only:
        clauses.append("status = 'armed'")
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    sql += ' ORDER BY created_at DESC'
    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row(row) for row in rows]


def delete_monitor(monitor_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute('DELETE FROM monitors WHERE id = ?', (monitor_id,))
    return cur.rowcount > 0


def touch_monitor(monitor_id: str, max_triggers: int = 0) -> dict | None:
    """Count one trigger and retire the monitor when its budget is spent.

    The increment is in the row (``trigger_count = trigger_count + 1``) so a burst of events on
    several threads cannot collapse into one, the same rule the login failure window follows.
    """
    stamp = now()
    with connect() as conn:
        conn.execute(
            'UPDATE monitors SET trigger_count = trigger_count + 1, last_event_at = ? WHERE id = ?',
            (stamp, monitor_id),
        )
        row = conn.execute('SELECT * FROM monitors WHERE id = ?', (monitor_id,)).fetchone()
        if row is not None and max_triggers and int(row['trigger_count']) >= max_triggers:
            conn.execute("UPDATE monitors SET status = 'done' WHERE id = ?", (monitor_id,))
    return _row(row)


def add_monitor_event(monitor_id: str, conversation_id: str, event: str, payload: dict) -> dict:
    event_id = new_id('mev')
    with connect() as conn:
        conn.execute(
            'INSERT INTO monitor_events (id, monitor_id, conversation_id, event, payload_json, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (event_id, monitor_id, conversation_id, event, json.dumps(payload, ensure_ascii=False), now()),
        )
    return {
        'id': event_id,
        'monitor_id': monitor_id,
        'conversation_id': conversation_id,
        'event': event,
        'payload': payload,
    }


def list_monitor_events(conversation_id: str = '', pending_only: bool = False, limit: int = 50) -> list:
    sql = 'SELECT * FROM monitor_events'
    clauses, params = [], []
    if conversation_id:
        clauses.append('conversation_id = ?')
        params.append(conversation_id)
    if pending_only:
        clauses.append('delivered = 0')
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    sql += ' ORDER BY created_at ASC LIMIT ?'
    params.append(max(1, int(limit)))
    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row(row) for row in rows]


def ack_monitor_event(event_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute('UPDATE monitor_events SET delivered = 1 WHERE id = ?', (event_id,))
    return cur.rowcount > 0


def pending_monitor_count() -> int:
    with connect() as conn:
        row = conn.execute('SELECT COUNT(*) AS n FROM monitor_events WHERE delivered = 0').fetchone()
    return int(row['n'] if row is not None else 0)
