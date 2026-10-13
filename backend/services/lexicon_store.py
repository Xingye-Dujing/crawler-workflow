"""SQLite-backed store for user-editable word lists the analysis pipeline reads.

Two kinds live here: ``stopword`` (extra words to drop from every frequency table) and
``userdict`` (jieba domain terms that must survive tokenisation as whole words). It mirrors
``dataset_store.py`` on purpose — same WAL + RLock so the panel can read while a run worker
reads, same lazy-singleton access through ``stores.get_lexicon_store`` — because a lexicon is
a writable, many-record, per-record-CRUD collection, which is exactly that shape.

A ``version`` counter lets the analyzers cache the effective stopword set in-process and
invalidate it only when something actually changed, instead of hitting SQLite per token.
"""

import contextlib
import os
import sqlite3
import threading
import time

from config import Config

#: The two word-list kinds the manager exposes.
KINDS = ('stopword', 'userdict')
#: A single term longer than this is almost certainly a paste mistake, not a word.
_MAX_TERM_LEN = 64


class LexiconStore:
    """The editable word lists (stopwords + jieba domain terms)."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.LEXICON_DB
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.DatabaseError):
            # WAL lets the panel list terms while a run's analyzer reads them.
            self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._ensure_tables()

    # ── schema ──────────────────────────────────────────────────

    def _ensure_tables(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS lexicon_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    term TEXT NOT NULL,
                    weight INTEGER,
                    created_at TEXT,
                    UNIQUE (kind, term)
                );
                CREATE TABLE IF NOT EXISTS lexicon_meta (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO lexicon_meta (key, value) VALUES ('version', 0);
                CREATE INDEX IF NOT EXISTS idx_lexicon_kind ON lexicon_entries(kind);
                """
            )
            self._conn.commit()

    @staticmethod
    def now() -> str:
        return time.strftime('%Y-%m-%dT%H:%M:%S')

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        # Under the same lock every query takes — closing the handle while a worker is
        # mid-execute faults the process rather than raising (see dataset_store.close).
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ── version (cache invalidation) ────────────────────────────

    def version(self) -> int:
        rows = self._query("SELECT value FROM lexicon_meta WHERE key = 'version'")
        return int(rows[0]['value']) if rows else 0

    def _bump_version(self):
        self._execute("UPDATE lexicon_meta SET value = value + 1 WHERE key = 'version'")

    # ── reads ───────────────────────────────────────────────────

    def list(self, kind: str = None, limit: int = 5000) -> list:
        if kind:
            rows = self._query(
                'SELECT kind, term, weight, created_at FROM lexicon_entries WHERE kind = ? ORDER BY term LIMIT ?',
                (kind, limit),
            )
        else:
            rows = self._query(
                'SELECT kind, term, weight, created_at FROM lexicon_entries ORDER BY kind, term LIMIT ?', (limit,)
            )
        return [dict(r) for r in rows]

    def terms(self, kind: str) -> list:
        """Just the term strings for one kind — what the analyzers consume."""
        return [
            r['term'] for r in self._query('SELECT term FROM lexicon_entries WHERE kind = ? ORDER BY term', (kind,))
        ]

    def count(self, kind: str = None) -> int:
        if kind:
            rows = self._query('SELECT COUNT(*) AS n FROM lexicon_entries WHERE kind = ?', (kind,))
        else:
            rows = self._query('SELECT COUNT(*) AS n FROM lexicon_entries')
        return int(rows[0]['n']) if rows else 0

    def counts(self) -> dict:
        return {kind: self.count(kind) for kind in KINDS}

    # ── writes ──────────────────────────────────────────────────

    def add(self, kind: str, terms) -> dict:
        """Insert terms (a list, or one blob split on newline / comma / 、). Returns
        ``{added, skipped}`` — a term already present is skipped, never duplicated."""
        if kind not in KINDS:
            raise ValueError(f'unknown lexicon kind: {kind}')
        cleaned = self._normalize(kind, terms)
        added = 0
        skipped = 0
        now = self.now()
        with self._lock:
            for term, weight in cleaned:
                exists = self._conn.execute(
                    'SELECT 1 FROM lexicon_entries WHERE kind = ? AND term = ?', (kind, term)
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
                self._conn.execute(
                    'INSERT INTO lexicon_entries (kind, term, weight, created_at) VALUES (?, ?, ?, ?)',
                    (kind, term, weight, now),
                )
                added += 1
            self._conn.commit()
            if added:
                self._bump_version()
        return {'added': added, 'skipped': skipped}

    def remove(self, kind: str, term: str) -> int:
        term = str(term or '').strip()
        if not term:
            return 0
        cur = self._execute('DELETE FROM lexicon_entries WHERE kind = ? AND term = ?', (kind, term))
        if cur.rowcount:
            self._bump_version()
        return cur.rowcount

    def clear(self, kind: str = None) -> int:
        if kind:
            cur = self._execute('DELETE FROM lexicon_entries WHERE kind = ?', (kind,))
        else:
            cur = self._execute('DELETE FROM lexicon_entries')
        if cur.rowcount:
            self._bump_version()
        return cur.rowcount

    @staticmethod
    def _normalize(kind: str, terms):
        """Split a blob or take a list, strip each, drop blanks and over-long, dedupe
        within the batch. ``userdict`` keeps an optional trailing integer as the jieba freq."""
        if isinstance(terms, str):
            pieces = terms.replace('，', ',').replace('、', ',').replace('\r', '\n').replace('\n', ',').split(',')
        elif isinstance(terms, (list, tuple, set)):
            pieces = [str(t) for t in terms]
        else:
            pieces = [str(terms)] if terms else []
        seen = set()
        out = []
        for raw in pieces:
            token = raw.strip()
            if not token:
                continue
            weight = None
            if kind == 'userdict':
                parts = token.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    token, weight = parts[0], int(parts[1])
                    if len(token) > _MAX_TERM_LEN:
                        continue
                elif len(token) > _MAX_TERM_LEN:
                    continue
            elif len(token) > _MAX_TERM_LEN:
                continue
            if token in seen:
                continue
            seen.add(token)
            out.append((token, weight))
        return out
