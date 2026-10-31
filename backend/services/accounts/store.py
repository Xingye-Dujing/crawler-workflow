"""SQLite storage for accounts, server-side sessions and the audit trail.

One connection for the store's lifetime, guarded by a lock — the same shape as the other stores in
``services/`` — because the gate reads a session on every request and the scheduler asks for the
account list from its own thread. WAL lets those readers coexist with the rare writer.

The session table stores only :func:`services.accounts.security.token_hash` of the cookie value;
the audit table deliberately has no foreign key to ``users`` so deleting an account never deletes
the record of what it did.
"""

import contextlib
import os
import sqlite3
import threading

from core.config import Config

AUDIT_KEEP = 5000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id              TEXT PRIMARY KEY,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash        TEXT NOT NULL,
    role                 TEXT NOT NULL CHECK (role IN ('admin','user')),
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    must_change_password INTEGER NOT NULL DEFAULT 0,
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         REAL NOT NULL DEFAULT 0,
    created_at           REAL NOT NULL,
    updated_at           REAL NOT NULL,
    password_changed_at  REAL NOT NULL,
    last_login_at        REAL,
    last_login_ip        TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    sid_hash     TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    csrf_token   TEXT NOT NULL,
    created_at   REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    expires_at   REAL NOT NULL,
    revoked_at   REAL,
    user_agent   TEXT,
    ip           TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions (expires_at);
CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    user_id  TEXT,
    username TEXT,
    event    TEXT NOT NULL,
    ip       TEXT,
    detail   TEXT
);
"""


class AccountsStore:
    """Users, sessions and audit rows in ``data/accounts.db``."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.ACCOUNTS_DB
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.DatabaseError):
            self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._conn.execute('PRAGMA foreign_keys=ON')
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ─── low-level helpers ───

    def _one(self, sql: str, params=()):
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def _all(self, sql: str, params=()) -> list:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def _write(self, sql: str, params=()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.rowcount

    # ─── users ───

    def has_users(self) -> bool:
        row = self._one('SELECT 1 AS present FROM users LIMIT 1')
        return row is not None

    def count_active_admins(self, excluding: str = '') -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'active' AND user_id != ?",
            (str(excluding or ''),),
        )
        return int(row['n'])

    def get_user(self, user_id: str):
        return self._one('SELECT * FROM users WHERE user_id = ?', (str(user_id or ''),))

    def get_user_by_username(self, username: str):
        return self._one('SELECT * FROM users WHERE username = ? COLLATE NOCASE', (str(username or '').strip(),))

    def list_users(self) -> list:
        return self._all('SELECT * FROM users ORDER BY created_at, user_id')

    def insert_user(
        self, *, user_id: str, username: str, password_hash: str, role: str, must_change_password: bool, now: float
    ) -> dict:
        self._write(
            'INSERT INTO users (user_id, username, password_hash, role, must_change_password,'
            ' created_at, updated_at, password_changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (user_id, username, password_hash, role, int(bool(must_change_password)), now, now, now),
        )
        return self.get_user(user_id)

    def update_password(self, user_id: str, password_hash: str, *, must_change_password: bool, now: float) -> None:
        self._write(
            'UPDATE users SET password_hash = ?, must_change_password = ?, updated_at = ?,'
            ' password_changed_at = ?, failed_attempts = 0, locked_until = 0 WHERE user_id = ?',
            (password_hash, int(bool(must_change_password)), now, now, user_id),
        )

    def record_failure(self, user_id: str, failures: int, locked_until: float, now: float) -> None:
        self._write(
            'UPDATE users SET failed_attempts = ?, locked_until = ?, updated_at = ? WHERE user_id = ?',
            (int(failures), float(locked_until), now, user_id),
        )

    def record_login(self, user_id: str, now: float, ip: str) -> None:
        self._write(
            'UPDATE users SET failed_attempts = 0, locked_until = 0, last_login_at = ?,'
            ' last_login_ip = ?, updated_at = ? WHERE user_id = ?',
            (now, str(ip or ''), now, user_id),
        )

    def set_status(self, user_id: str, status: str, now: float) -> None:
        self._write('UPDATE users SET status = ?, updated_at = ? WHERE user_id = ?', (status, now, user_id))

    def delete_user(self, user_id: str) -> None:
        self._write('DELETE FROM users WHERE user_id = ?', (user_id,))

    # ─── sessions ───

    def insert_session(
        self,
        *,
        sid_hash: str,
        user_id: str,
        csrf_token: str,
        created_at: float,
        expires_at: float,
        user_agent: str,
        ip: str,
    ) -> None:
        self._write(
            'INSERT INTO sessions (sid_hash, user_id, csrf_token, created_at, last_seen_at,'
            ' expires_at, user_agent, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                sid_hash,
                user_id,
                csrf_token,
                created_at,
                created_at,
                expires_at,
                str(user_agent or '')[:200],
                str(ip or ''),
            ),
        )

    def get_session(self, sid_hash: str):
        return self._one(
            'SELECT s.sid_hash, s.user_id, s.csrf_token, s.created_at, s.last_seen_at,'
            ' s.expires_at, s.revoked_at, u.username, u.role, u.status, u.must_change_password'
            ' FROM sessions s JOIN users u ON u.user_id = s.user_id WHERE s.sid_hash = ?',
            (sid_hash,),
        )

    def touch_session(self, sid_hash: str, now: float) -> None:
        self._write('UPDATE sessions SET last_seen_at = ? WHERE sid_hash = ?', (now, sid_hash))

    def revoke_session(self, sid_hash: str, now: float) -> None:
        self._write('UPDATE sessions SET revoked_at = ? WHERE sid_hash = ? AND revoked_at IS NULL', (now, sid_hash))

    def revoke_user_sessions(self, user_id: str, now: float, keep_sid_hash: str = '') -> int:
        return self._write(
            'UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND sid_hash != ?',
            (now, user_id, str(keep_sid_hash or '')),
        )

    def purge_expired_sessions(self, now: float) -> int:
        return self._write(
            'DELETE FROM sessions WHERE expires_at <= ? OR (revoked_at IS NOT NULL AND revoked_at <= ?)',
            (now, now - 7 * 24 * 3600),
        )

    # ─── audit ───

    def audit(
        self, *, event: str, user_id: str = '', username: str = '', ip: str = '', detail: str = '', now: float
    ) -> None:
        self._write(
            'INSERT INTO audit_log (ts, user_id, username, event, ip, detail) VALUES (?, ?, ?, ?, ?, ?)',
            (now, str(user_id or ''), str(username or ''), event, str(ip or ''), str(detail or '')),
        )
        self._write(
            'DELETE FROM audit_log WHERE id <= (SELECT COALESCE(MAX(id), 0) - ? FROM audit_log)',
            (AUDIT_KEEP,),
        )

    def list_audit(self, limit: int = 200) -> list:
        return self._all('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (max(1, min(int(limit), 500)),))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
