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
from contextlib import contextmanager
from datetime import UTC

from runtime import paths

from ai.types import new_id

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
"""


def _db_path() -> str:
    target = paths.active().ai_db
    os.makedirs(os.path.dirname(target), exist_ok=True)
    return target


@contextmanager
def connect():
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript(SCHEMA)
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(user_skills)').fetchall()}
    if 'name' not in columns:
        conn.execute("ALTER TABLE user_skills ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    if 'description' not in columns:
        conn.execute("ALTER TABLE user_skills ADD COLUMN description TEXT NOT NULL DEFAULT ''")
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
                    {} if name in ('meta', 'usage', 'answer', 'plan', 'args', 'manifest', 'permissions') else []
                )
        else:
            data[name] = {} if name in ('meta', 'usage', 'answer', 'plan', 'args', 'manifest', 'permissions') else []
    return data


def now() -> str:
    from datetime import datetime

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


def list_conversations(limit: int = 80) -> list:
    with connect() as conn:
        rows = conn.execute(
            'SELECT c.*, '
            '(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count '
            'FROM conversations c WHERE c.archived = 0 ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ?',
            (max(1, int(limit)),),
        ).fetchall()
    return [_row(row) for row in rows]


def get_conversation(conversation_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM conversations WHERE id = ?', (conversation_id,)).fetchone()
    return _row(row)


def touch_conversation(conversation_id: str, **fields) -> None:
    allowed = {
        key: value
        for key, value in fields.items()
        if key in ('title', 'title_source', 'provider', 'model', 'skill', 'pinned')
    }
    allowed['updated_at'] = now()
    assignments = ', '.join(f'{key} = ?' for key in allowed)
    with connect() as conn:
        conn.execute(f'UPDATE conversations SET {assignments} WHERE id = ?', (*allowed.values(), conversation_id))


def delete_conversation(conversation_id: str) -> bool:
    with connect() as conn:
        for table in ('messages', 'questions', 'agent_steps', 'agent_runs', 'usage'):
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
        conn.execute(
            "UPDATE questions SET answer_json = ?, status = 'answered', answered_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (json.dumps(answer, ensure_ascii=False), stamp, question_id),
        )
    return get_question(question_id)


def abandon_questions(conversation_id: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE questions SET status = 'abandoned' WHERE conversation_id = ? AND status = 'pending'",
            (conversation_id,),
        )
    return cur.rowcount


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


def list_steps(run_id: str) -> list:
    with connect() as conn:
        rows = conn.execute('SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq', (run_id,)).fetchall()
    return [_row(row) for row in rows]


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


def list_memories() -> list:
    with connect() as conn:
        rows = conn.execute('SELECT * FROM memories ORDER BY created_at DESC').fetchall()
    return [_row(row) for row in rows]


def save_memory(text: str) -> dict:
    memory_id = new_id('mem')
    with connect() as conn:
        conn.execute('INSERT INTO memories (id, text, created_at) VALUES (?, ?, ?)', (memory_id, text, now()))
    return {'id': memory_id, 'text': text}


def delete_memory(memory_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
    return cur.rowcount > 0


def mark_interrupted() -> int:
    """Boot recovery: an assistant row left ``streaming`` cannot still be streaming."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE messages SET status = 'interrupted', updated_at = ? WHERE status = 'streaming'", (now(),)
        )
    return cur.rowcount


def purge_older_than(days: int) -> int:
    if days <= 0:
        return 0
    from datetime import datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with connect() as conn:
        cur = conn.execute('DELETE FROM conversations WHERE updated_at < ?', (cutoff,))
    return cur.rowcount
