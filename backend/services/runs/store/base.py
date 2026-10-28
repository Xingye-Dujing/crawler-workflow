"""The store's connection, schema and the two query helpers every domain mixin uses.

One SQLite file per data root; writes are best-effort (a full disk must not take a run
down) and reads are strict because resume correctness depends on them.
"""

import contextlib
import logging
import os
import sqlite3
import threading
import time
from typing import TYPE_CHECKING

from core.config import Config

if TYPE_CHECKING:
    from services.runs.store import RunStore

logger = logging.getLogger(__name__)


class RowCache:
    """Adapter so the analyzers' per-row cache can live in the database.

    Same three calls the JSONL ``RowCheckpoint`` exposes — ``get``, ``add``,
    ``discard`` — but keyed by *text* (plus the operation/model scope) rather
    than by row index in one dataset. That is what makes it survive a re-crawl:
    the rows shift, the texts do not, so nothing already answered is paid for
    again. ``discard`` is deliberately a no-op: a finished run's answers are
    still valuable to the next run, and are aged out by ``purge`` instead.
    """

    def __init__(self, store: 'RunStore', scope: str):
        self._store = store
        self._scope = scope

    def get(self, _idx, thash: str):
        value = self._store.cache_get(self._scope, thash)
        # The LLM runner expects a record carrying the result tuple.
        return {'r': value} if value is not None else None

    def add(self, _idx, thash: str, result):
        self._store.cache_put(self._scope, thash, list(result))

    def discard(self):
        """Kept on purpose — see the class docstring."""


class BaseMixin:
    _ADDED_COLUMNS = (
        ('runs', 'wf_count', 'INTEGER DEFAULT 1'),
        ('node_runs', 'component', 'INTEGER DEFAULT 0'),
        ('node_runs', 'component_name', "TEXT DEFAULT ''"),
        # Legacy: once a run could be silently upgraded from 无头 to a visible window (a captcha
        # site, or a comment panel that "had to" be scrolled) and this recorded it so the chip told
        # the truth. #148 gave a headless Chrome a desktop fingerprint and every such platform and
        # panel was measured serving rows headless, so nothing forces a window any more and nothing
        # writes this. The column stays (SQLite drop = table rebuild, and old rows still carry a
        # meaningful 0/1) and the chip that read it is gone.
        ('runs', 'forced_visible', 'INTEGER DEFAULT 0'),
        # The user-facing workflows that were switched OFF (node-disabled or their whole type
        # disabled) for this attempt, joined by ' + '. They never run and own no node rows, so the
        # record otherwise reads as "this canvas had fewer workflows than the user drew". Stored
        # here so the panel can name them under 跳过 instead of leaving them silently absent.
        ('runs', 'skipped_workflows', "TEXT DEFAULT ''"),
    )

    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.RUNS_DB
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.DatabaseError):
            # Write-ahead logging lets the UI read state while a run writes it.
            self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._ensure_tables()

    def close(self) -> None:
        """Release the connection, or do nothing if it is already gone.

        Same rule as :meth:`DatasetStore.close`: a close that skips ``self._lock`` can finalise
        the SQLite handle while a worker thread is inside ``execute`` on it, and that is a fault,
        not an exception.
        """
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _ensure_tables(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    -- Insertion order is the only reliable ordering: two runs
                    -- started in the same second share a timestamp, and
                    -- "newest first" then becomes arbitrary.
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    workflow_name TEXT,
                    workflow_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT,
                    headless INTEGER DEFAULT 1,
                    llm_provider TEXT,
                    llm_model TEXT,
                    lang TEXT,
                    node_total INTEGER DEFAULT 0,
                    node_done INTEGER DEFAULT 0,
                    -- How many connected components (user-facing workflows) this
                    -- one run executed: >1 is what makes the record 并行, and the
                    -- name field carries all their labels joined.
                    wf_count INTEGER DEFAULT 1,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS node_runs (
                    run_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    node_type TEXT,
                    title TEXT,
                    fingerprint TEXT,
                    status TEXT NOT NULL,
                    row_count INTEGER DEFAULT 0,
                    cursor_json TEXT,
                    error TEXT,
                    -- Which workflow (connected component) of the canvas this node
                    -- belonged to, and what that component was called. One run is one
                    -- record even when the canvas holds several workflows, so without
                    -- these two the record could not say which rows came from 热门榜
                    -- and which from 周排行榜 — the user's complaint about a serial run.
                    component INTEGER DEFAULT 0,
                    component_name TEXT DEFAULT '',
                    started_at TEXT,
                    updated_at TEXT,
                    finished_at TEXT,
                    PRIMARY KEY (run_id, node_id)
                );
                CREATE TABLE IF NOT EXISTS node_rows (
                    run_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    row_key TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT,
                    PRIMARY KEY (run_id, node_id, seq)
                );
                CREATE TABLE IF NOT EXISTS item_seen (
                    scope TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    first_run_id TEXT,
                    created_at TEXT,
                    PRIMARY KEY (scope, item_key)
                );
                CREATE TABLE IF NOT EXISTS llm_cache (
                    scope TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    value TEXT,
                    created_at TEXT,
                    PRIMARY KEY (scope, cache_key)
                );
                -- The durable boundary for a NEW crawl of the same source node: unlike the
                -- per-run cursor, this survives the run that wrote it and is read by the next
                -- scheduled/manual run. scoped by node fingerprint, so a changed keyword/mode/
                -- account starts fresh rather than inheriting another crawl's boundary.
                CREATE TABLE IF NOT EXISTS source_watermarks (
                    scope TEXT PRIMARY KEY,
                    platform TEXT NOT NULL DEFAULT '',
                    field TEXT NOT NULL DEFAULT '',
                    last_key TEXT NOT NULL DEFAULT '',
                    run_id TEXT NOT NULL DEFAULT '',
                    updated_at TEXT
                );
                -- Which files a run wrote into the export folder. The export listing is a flat
                -- scan of the directory and carries no run identity (and shard names only embed
                -- the record when 「分片带记录时间戳」 is on, which defaults off), so without this
                -- table "clear everything one run produced" cannot be answered at all. ``node_id``
                -- scopes the 分片-of-one-node clear; it is '' for run-level files (report, manual
                -- save). ``(run_id, name)`` is the key so a live snapshot rewritten every batch
                -- records once, not once per publish.
                CREATE TABLE IF NOT EXISTS run_files (
                    run_id TEXT NOT NULL,
                    node_id TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, name)
                );
                -- The run console, persisted one physical line per row. Until this existed the
                -- console lived only in an in-memory, per-run-reset buffer (capped, and wiped by
                -- the NEXT run), so a finished run's early lines were unrecoverable — you could not
                -- review a past run's log after refreshing late, starting another run, or a restart.
                -- ``seq`` is the per-run line order (MAX(seq)+1, never COUNT(*), matching node_rows);
                -- ``wf_idx``/``wf_name`` reconstruct the per-workflow tabs of a parallel run; ``level``
                -- is best-effort (handler-derived WARN/ERROR, else info) so the viewer can filter.
                -- Rows are deleted with their run (delete_run cascades), so retention bounds growth.
                CREATE TABLE IF NOT EXISTS run_log (
                    run_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    ts TEXT,
                    wf_idx INTEGER,
                    wf_name TEXT DEFAULT '',
                    level TEXT DEFAULT 'info',
                    line TEXT NOT NULL,
                    PRIMARY KEY (run_id, seq)
                );
                CREATE INDEX IF NOT EXISTS idx_runs_wf ON runs(workflow_fingerprint, started_at);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
                CREATE INDEX IF NOT EXISTS idx_node_runs_status ON node_runs(run_id, status);
                CREATE INDEX IF NOT EXISTS idx_run_files_run ON run_files(run_id, node_id, kind);
                CREATE INDEX IF NOT EXISTS idx_run_log_wf ON run_log(run_id, wf_idx, seq);
                -- The waiting run queue, mirrored from the in-memory _RUN_QUEUE so a restart
                -- does not silently drop the requests the user already parked. `position` is the
                -- drain order (0..n-1, rewritten wholesale on every change — the queue is capped
                -- at QUEUE_MAX, so a full replace is cheap and cannot drift). `payload` is the
                -- exact POST body the entry will replay on drain.
                CREATE TABLE IF NOT EXISTS run_queue (
                    position INTEGER PRIMARY KEY,
                    id TEXT NOT NULL,
                    workflow_name TEXT,
                    node_count INTEGER DEFAULT 0,
                    lang TEXT,
                    queued_at TEXT,
                    payload TEXT NOT NULL
                );
                """
            )
            self._conn.commit()
        self._ensure_columns()
        self.promote_stale_runs()

    def _ensure_columns(self):
        for table, column, declaration in self._ADDED_COLUMNS:
            with self._lock:
                have = {row[1] for row in self._conn.execute(f'PRAGMA table_info({table})')}
                if column in have:
                    continue
                self._conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
                self._conn.commit()

    @staticmethod
    def now() -> str:
        return time.strftime('%Y-%m-%dT%H:%M:%S')

    @staticmethod
    def _duration_seconds(started, finished):
        """Whole seconds the run occupied (``finished_at`` − ``started_at``), or None while it is
        still open (``finished_at`` null) or a stamp does not parse.

        ``started_at`` is deliberately never refreshed on a 继续 (the record's date is when this work
        began), so a resumed run's duration is its TOTAL wall-clock elapsed across every attempt — the
        honest reading of "运行时长", not just the last attempt."""
        if not started or not finished:
            return None
        fmt = '%Y-%m-%dT%H:%M:%S'
        try:
            t0 = time.mktime(time.strptime(str(started), fmt))
            t1 = time.mktime(time.strptime(str(finished), fmt))
        except (ValueError, OverflowError, TypeError):
            return None
        return max(0, int(round(t1 - t0)))

    def _execute(self, sql: str, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()
