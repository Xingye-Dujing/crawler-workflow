"""The pool's durable state: which login and which exit are usable, and why.

The premise of an account pool is that a platform's control lasts a long time, so the
expensive thing to avoid is *trying again too soon*. That makes this store the feature, not
a cache: a cooldown written before a restart must still be in force after it, and "which
exit did this account burn" must survive the same restart.

Three tables plus an audit trail:

* ``exits``     — the proxy inventory (the IP side). Credentials live here and never leave
  the server in a response.
* ``bindings``  — which exit an account crawls as. Sticky on purpose: a login that changes
  country between two requests is itself a risk signal.
* ``health``    — one row per subject, where a subject is an ACCOUNT or an EXIT, scoped to a
  PLATFORM. A login can be walled on weibo while it is fine on bilibili, and an exit can be
  banned by zhihu while it serves YouTube perfectly, so neither is a global flag.
* ``events``    — what was attempted, with which pair, and what came back. This is what makes
  "why is this account cooling?" answerable a week later, and it carries ``run_id``/``node_id``
  so a run's own use of the pool can be reported without touching ``runs.db``'s schema.

Nothing here imports crawlers or Flask: the executor and the routes both call it, and the
dependency direction has to stay one-way.
"""

import contextlib
import os
import sqlite3
import threading
import time
import uuid

from runtime import paths

#: How many audit rows survive. The table is a working record, not an archive: the useful
#: question is "what happened to this pair lately", and an unbounded table would grow with
#: every crawled row forever.
EVENT_KEEP = 5000

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS exits (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        scheme TEXT NOT NULL DEFAULT 'http',
        host TEXT NOT NULL DEFAULT '',
        port INTEGER NOT NULL DEFAULT 0,
        username TEXT NOT NULL DEFAULT '',
        password TEXT NOT NULL DEFAULT '',
        platforms TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bindings (
        platform TEXT NOT NULL,
        account TEXT NOT NULL,
        exit_id TEXT NOT NULL DEFAULT '',
        since REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (platform, account)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS health (
        kind TEXT NOT NULL,
        platform TEXT NOT NULL,
        subject TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'ok',
        cool_until REAL NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '',
        strikes INTEGER NOT NULL DEFAULT 0,
        last_attempt_at REAL NOT NULL DEFAULT 0,
        last_ok_at REAL NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (kind, platform, subject)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL DEFAULT 0,
        kind TEXT NOT NULL DEFAULT '',
        platform TEXT NOT NULL DEFAULT '',
        account TEXT NOT NULL DEFAULT '',
        exit_id TEXT NOT NULL DEFAULT '',
        run_id TEXT NOT NULL DEFAULT '',
        node_id TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        rows INTEGER NOT NULL DEFAULT 0
    )
    """,
)

_LOCK = threading.RLock()


def db_path() -> str:
    """The pool database of the scope this thread speaks for, resolved at call time.

    Never cached: the one process serves several accounts, and a module-level path would
    file account B's cooldown in account A's tree (the rule
    ``tests/unit/gates/test_account_paths_resolve_at_call.py`` exists for).
    """
    return paths.active().pool_db


def connect() -> sqlite3.Connection:
    """A short-lived connection with the schema guaranteed present."""
    path = db_path()
    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout = 5000')
    for statement in _SCHEMA:
        conn.execute(statement)
    conn.commit()
    return conn


def _rows(conn, sql: str, params: tuple = ()) -> list:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _one(conn, sql: str, params: tuple = ()) -> dict:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else {}


# ─── Exits (the IP side) ────────────────────────────────────────────────────


def _exit_row(row: dict, secret: bool = False) -> dict:
    """One exit as a caller may see it.

    ``password`` is dropped and replaced by ``has_auth`` unless the caller explicitly asked
    for the secret — the browser never needs it, and the log must never be able to print it
    by accident (a dict render is one ``repr`` away).
    """
    out = dict(row)
    out['enabled'] = bool(out.get('enabled'))
    out['allowed_platforms'] = [p for p in str(out.get('platforms') or '').split(',') if p]
    out['has_auth'] = bool(out.get('username') or out.get('password'))
    if not secret:
        out.pop('password', None)
        out.pop('username', None)
    return out


def list_exits(platform: str = '', include_disabled: bool = True) -> list:
    """Every exit, optionally only those that serve *platform* (empty ``platforms`` = all)."""
    with _LOCK, contextlib.closing(connect()) as conn:
        rows = [_exit_row(row) for row in _rows(conn, 'SELECT * FROM exits ORDER BY created_at, id')]
    if not include_disabled:
        rows = [row for row in rows if row['enabled']]
    if platform:
        rows = [row for row in rows if not row['allowed_platforms'] or platform in row['allowed_platforms']]
    return rows


def get_exit(exit_id: str) -> dict:
    if not str(exit_id or '').strip():
        return {}
    with _LOCK, contextlib.closing(connect()) as conn:
        row = _one(conn, 'SELECT * FROM exits WHERE id = ?', (str(exit_id),))
    return _exit_row(row) if row else {}


def exit_secret(exit_id: str) -> dict:
    """The exit including its credentials — for the browser, never for a response."""
    with _LOCK, contextlib.closing(connect()) as conn:
        row = _one(conn, 'SELECT * FROM exits WHERE id = ?', (str(exit_id),))
    return _exit_row(row, secret=True) if row else {}


def save_exit(payload: dict) -> dict:
    """Create or update one exit. A blank ``password``/``username`` keeps the stored one.

    The keep-on-blank rule exists because the panel never receives the secret back: a form
    that always posted the (blank) field would otherwise erase a working credential on every
    unrelated edit. Sending an explicit ``clear_auth: true`` is the way to remove it.
    """
    scheme = str(payload.get('scheme') or 'http').strip().lower()
    if scheme not in ('http', 'https', 'socks5'):
        raise ValueError(f'Unsupported proxy scheme: {scheme}')
    host = str(payload.get('host') or '').strip()
    if not host or any(ch in host for ch in ' \t\r\n/'):
        raise ValueError('Proxy host is required')
    try:
        port = int(payload.get('port') or 0)
    except (TypeError, ValueError):
        raise ValueError('Proxy port is not a number') from None
    if not 1 <= port <= 65535:
        raise ValueError('Proxy port is out of range')
    exit_id = str(payload.get('id') or '').strip()
    created = time.strftime('%Y-%m-%d %H:%M:%S')
    platforms = payload.get('platforms')
    if isinstance(platforms, (list, tuple)):
        platforms = ','.join(str(p).strip() for p in platforms if str(p).strip())
    name = str(payload.get('name') or '').strip() or host
    with _LOCK, contextlib.closing(connect()) as conn:
        existing = _one(conn, 'SELECT * FROM exits WHERE id = ?', (exit_id,)) if exit_id else {}
        if not exit_id:
            exit_id = 'p_' + uuid.uuid4().hex[:10]
        if payload.get('clear_auth'):
            username = password = ''
        else:
            username = str(payload.get('username') or '').strip() or str(existing.get('username') or '')
            password = str(payload.get('password') or '') or str(existing.get('password') or '')
        conn.execute(
            'INSERT INTO exits '
            '(id, name, scheme, host, port, username, password, platforms, enabled, note, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET name=excluded.name, scheme=excluded.scheme, host=excluded.host, '
            'port=excluded.port, username=excluded.username, password=excluded.password, '
            'platforms=excluded.platforms, enabled=excluded.enabled, note=excluded.note',
            (
                exit_id,
                name,
                scheme,
                host,
                port,
                username,
                password,
                str(platforms or ''),
                int(bool(payload.get('enabled', True))),
                str(payload.get('note') or ''),
                str(existing.get('created_at') or created),
            ),
        )
        conn.commit()
    return get_exit(exit_id)


def delete_exit(exit_id: str) -> bool:
    """Remove an exit and every binding that pointed at it. Cooldown rows go with it."""
    with _LOCK, contextlib.closing(connect()) as conn:
        cur = conn.execute('DELETE FROM exits WHERE id = ?', (str(exit_id),))
        conn.execute('DELETE FROM bindings WHERE exit_id = ?', (str(exit_id),))
        conn.execute("DELETE FROM health WHERE kind = 'exit' AND subject = ?", (str(exit_id),))
        conn.commit()
        return cur.rowcount > 0


# ─── Bindings ───────────────────────────────────────────────────────────────


def binding_exit_id(platform: str, account: str) -> str:
    with _LOCK, contextlib.closing(connect()) as conn:
        row = _one(conn, 'SELECT exit_id FROM bindings WHERE platform = ? AND account = ?', (platform, account))
    return str(row.get('exit_id') or '')


def bind(platform: str, account: str, exit_id: str) -> None:
    with _LOCK, contextlib.closing(connect()) as conn:
        conn.execute(
            'INSERT INTO bindings (platform, account, exit_id, since) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(platform, account) DO UPDATE SET exit_id=excluded.exit_id, since=excluded.since',
            (platform, account, str(exit_id or ''), time.time()),
        )
        conn.commit()


# ─── Health ─────────────────────────────────────────────────────────────────


def _health_row(row: dict) -> dict:
    out = dict(row)
    until = float(out.get('cool_until') or 0)
    out['cool_until'] = until
    out['cool_until_local'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(until)) if until else ''
    return out


def health_rows(platform: str = '') -> list:
    sql = 'SELECT * FROM health'
    params: tuple = ()
    if platform:
        sql += ' WHERE platform = ?'
        params = (platform,)
    sql += ' ORDER BY kind, platform, subject'
    with _LOCK, contextlib.closing(connect()) as conn:
        return [_health_row(row) for row in _rows(conn, sql, params)]


def get_health(kind: str, platform: str, subject: str) -> dict:
    with _LOCK, contextlib.closing(connect()) as conn:
        row = _one(
            conn,
            'SELECT * FROM health WHERE kind = ? AND platform = ? AND subject = ?',
            (kind, platform, subject),
        )
    return _health_row(row) if row else {}


def _write_health(**values) -> None:
    keys = (
        'kind',
        'platform',
        'subject',
        'state',
        'cool_until',
        'reason',
        'strikes',
        'last_attempt_at',
        'last_ok_at',
        'note',
    )
    columns = ', '.join(keys)
    slots = ', '.join('?' * len(keys))
    updates = ', '.join(f'{key}=excluded.{key}' for key in keys[3:])
    with _LOCK, contextlib.closing(connect()) as conn:
        conn.execute(
            f'INSERT INTO health ({columns}) VALUES ({slots}) '
            f'ON CONFLICT(kind, platform, subject) DO UPDATE SET {updates}',
            tuple(values.get(key) for key in keys),
        )
        conn.commit()


def touch(kind: str, platform: str, subject: str) -> None:
    """Stamp "an attempt is starting" without changing the state.

    Written at claim time, not at verdict time, so a process killed mid-crawl still leaves
    the fact that this pair was used — which is what the least-recently-used ordering and
    the "was that exit tried today?" question read.
    """
    current = get_health(kind, platform, subject)
    _write_health(
        kind=kind,
        platform=platform,
        subject=subject,
        state=current.get('state') or 'ok',
        cool_until=float(current.get('cool_until') or 0),
        reason=current.get('reason') or '',
        strikes=int(current.get('strikes') or 0),
        last_attempt_at=time.time(),
        last_ok_at=float(current.get('last_ok_at') or 0),
        note=current.get('note') or '',
    )


def mark_ok(kind: str, platform: str, subject: str) -> None:
    """A real answer that the session/exit works: clear the cooldown and the strike count."""
    current = get_health(kind, platform, subject)
    now = time.time()
    _write_health(
        kind=kind,
        platform=platform,
        subject=subject,
        state='ok',
        cool_until=0.0,
        reason='',
        strikes=0,
        last_attempt_at=now,
        last_ok_at=now,
        note=current.get('note') or '',
    )


def mark_cooldown(kind: str, platform: str, subject: str, seconds: float, reason: str, detail: str = '') -> dict:
    """Put one subject into a timed cooldown. Returns the row as written."""
    current = get_health(kind, platform, subject)
    now = time.time()
    strikes = int(current.get('strikes') or 0) + 1
    _write_health(
        kind=kind,
        platform=platform,
        subject=subject,
        state='cooling',
        cool_until=now + max(0.0, float(seconds)),
        reason=reason,
        strikes=strikes,
        last_attempt_at=now,
        last_ok_at=float(current.get('last_ok_at') or 0),
        note=str(detail or '')[:400],
    )
    return get_health(kind, platform, subject)


def set_disabled(kind: str, platform: str, subject: str, disabled: bool, note: str = '') -> None:
    """Manual stop. A disabled subject never comes back on a clock — only a person can."""
    if not disabled:
        mark_ok(kind, platform, subject)
        return
    current = get_health(kind, platform, subject)
    _write_health(
        kind=kind,
        platform=platform,
        subject=subject,
        state='disabled',
        cool_until=0.0,
        reason='manual',
        strikes=0,
        last_attempt_at=float(current.get('last_attempt_at') or 0),
        last_ok_at=float(current.get('last_ok_at') or 0),
        note=str(note or current.get('note') or '')[:400],
    )


def reset(kind: str, platform: str, subject: str = '') -> int:
    """Clear cooldowns now — the human override. Empty ``subject`` clears a whole kind/platform."""
    with _LOCK, contextlib.closing(connect()) as conn:
        if subject:
            cur = conn.execute(
                "UPDATE health SET state = 'ok', cool_until = 0, reason = '', strikes = 0 "
                'WHERE kind = ? AND platform = ? AND subject = ?',
                (kind, platform, subject),
            )
        elif platform:
            cur = conn.execute(
                "UPDATE health SET state = 'ok', cool_until = 0, reason = '', strikes = 0 "
                'WHERE kind = ? AND platform = ?',
                (kind, platform),
            )
        else:
            cur = conn.execute(
                "UPDATE health SET state = 'ok', cool_until = 0, reason = '', strikes = 0 WHERE kind = ?",
                (kind,),
            )
        conn.commit()
        return cur.rowcount


# ─── Events ─────────────────────────────────────────────────────────────────


def record_event(
    *,
    kind: str = '',
    platform: str = '',
    account: str = '',
    exit_id: str = '',
    run_id: str = '',
    node_id: str = '',
    reason: str = '',
    detail: str = '',
    rows: int = 0,
) -> None:
    with _LOCK, contextlib.closing(connect()) as conn:
        conn.execute(
            'INSERT INTO events (at, kind, platform, account, exit_id, run_id, node_id, reason, detail, rows) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                time.time(),
                kind,
                platform,
                account,
                exit_id,
                run_id,
                node_id,
                reason,
                str(detail or '')[:400],
                int(rows),
            ),
        )
        # Prune in the same transaction so a long run cannot leave the table unbounded.
        conn.execute(
            'DELETE FROM events WHERE id <= (SELECT MAX(id) - ? FROM events)',
            (EVENT_KEEP,),
        )
        conn.commit()


def recent_events(limit: int = 100) -> list:
    limit = max(1, min(500, int(limit or 100)))
    with _LOCK, contextlib.closing(connect()) as conn:
        rows = _rows(conn, 'SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))
    for row in rows:
        row['at_local'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(row.get('at') or 0)))
    return rows
