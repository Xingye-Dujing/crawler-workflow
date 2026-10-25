"""Canvas history: named snapshots of a canvas, and one layout baseline per workflow.

A workflow file is "what the canvas is now"; this store is "what the canvas has been".
The user saves a snapshot before a risky edit (or after a layout they like), and can
restore it later. Snapshots are deliberately independent of workflow files: a snapshot
can outlive a rename, and restoring one never deletes a file.

The layout baseline is the same snapshot used as a *positions* source for the second
auto-layout strategy. It is keyed by workflow name (a saved file's stem), so two
workflows that share a history table do not steal each other's arrangement. The payload
lives in ``canvas_snapshots``; ``layout_baselines`` holds only the pointer, and it is
cleared when the snapshot it names is deleted.

Why SQLite and not one JSON file: a snapshot carries a whole canvas, and a list must not
read every payload to render a table. A row per snapshot keeps listing cheap and makes
"the 101st save" a named refusal instead of an increasingly slow rewrite.
"""

import contextlib
import json
import os
import sqlite3
import threading
import time
import uuid

from config import Config
from i18n import t

#: A manual history is a curated list, not an unbounded log. When it is full the save is
#: REFUSED by name — silently dropping the oldest entry is how a history you trusted goes
#: missing the one state you wanted.
MAX_SNAPSHOTS = 100
MAX_LABEL = 80
MAX_WORKFLOW_NAME = 120

LAYOUT_STRATEGIES = ('algorithm', 'baseline')


class HistoryFullError(RuntimeError):
    """The store already holds MAX_SNAPSHOTS entries."""


class SnapshotCorruptError(RuntimeError):
    """A row exists but its payload is not the JSON this store wrote."""


def _now() -> float:
    # A float, not a second-resolution stamp: two saves can land in the same second, and
    # ordering by a truncated value made "the latest snapshot" depend on Chinese code-point
    # order (the same bug biblio snapshots paid for). rowid breaks the remaining tie.
    return time.time()


class WorkflowHistoryStore:
    """Named canvas snapshots plus the per-workflow layout-baseline pointer."""

    #: The API lists this beside the rows so the panel can say how much room is left.
    MAX_SNAPSHOTS = MAX_SNAPSHOTS

    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.WORKFLOW_HISTORY_DB
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.DatabaseError):
            self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._ensure_tables()

    # ── schema ──────────────────────────────────────────────────────

    def _ensure_tables(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS canvas_snapshots (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    workflow_name TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    node_count INTEGER NOT NULL DEFAULT 0,
                    edge_count INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS canvas_snapshots_created
                    ON canvas_snapshots (created_at);
                CREATE TABLE IF NOT EXISTS layout_baselines (
                    workflow_name TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL DEFAULT 'algorithm',
                    snapshot_id TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    def _execute(self, sql: str, params=()):
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def _query(self, sql: str, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def counts(self) -> dict:
        snapshots = self._query('SELECT COUNT(*) AS n FROM canvas_snapshots')[0]['n']
        baselines = self._query('SELECT COUNT(*) AS n FROM layout_baselines')[0]['n']
        return {'snapshots': int(snapshots), 'baselines': int(baselines)}

    # ── snapshots ───────────────────────────────────────────────────

    @staticmethod
    def _header(row: sqlite3.Row) -> dict:
        return {
            'id': str(row['id']),
            'label': str(row['label'] or ''),
            'workflow_name': str(row['workflow_name'] or ''),
            'created_at': float(row['created_at']),
            'nodes': int(row['node_count']),
            'connections': int(row['edge_count']),
        }

    @staticmethod
    def _validate(workflow, label, workflow_name) -> tuple:
        if not isinstance(workflow, dict) or not isinstance(workflow.get('nodes'), list):
            raise ValueError(t('wfHistory.invalid'))
        label = str(label or '').strip()
        workflow_name = str(workflow_name or '').strip()
        if len(label) > MAX_LABEL:
            raise ValueError(t('wfHistory.labelTooLong', n=MAX_LABEL))
        if len(workflow_name) > MAX_WORKFLOW_NAME:
            raise ValueError(t('wfHistory.workflowNameTooLong', n=MAX_WORKFLOW_NAME))
        connections = workflow.get('connections')
        if connections is not None and not isinstance(connections, list):
            raise ValueError(t('wfHistory.invalid'))
        try:
            payload = json.dumps(workflow, ensure_ascii=False, separators=(',', ':'))
        except (TypeError, ValueError) as e:
            raise ValueError(t('wfHistory.unserializable')) from e
        return label, workflow_name, payload

    def save_snapshot(self, workflow, label: str = '', workflow_name: str = '') -> dict:
        """Store one canvas state. Raises ValueError (bad input) or HistoryFullError."""
        label, workflow_name, payload = self._validate(workflow, label, workflow_name)
        node_count = len(workflow.get('nodes') or [])
        edge_count = len(workflow.get('connections') or [])
        snapshot_id = uuid.uuid4().hex[:12]
        created_at = _now()
        with self._lock:
            total = self._conn.execute('SELECT COUNT(*) FROM canvas_snapshots').fetchone()[0]
            if total >= self.MAX_SNAPSHOTS:
                raise HistoryFullError(t('wfHistory.full', max=self.MAX_SNAPSHOTS))
            self._conn.execute(
                'INSERT INTO canvas_snapshots '
                '(id, label, workflow_name, created_at, node_count, edge_count, payload) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (snapshot_id, label, workflow_name, created_at, node_count, edge_count, payload),
            )
            self._conn.commit()
        return {
            'id': snapshot_id,
            'label': label,
            'workflow_name': workflow_name,
            'created_at': created_at,
            'nodes': node_count,
            'connections': edge_count,
        }

    def rename_snapshot(self, snapshot_id: str, label: str) -> dict | None:
        """Change one snapshot's label without touching its payload or timestamp.

        A blank label is allowed: that is the same "untitled" a blank save produces,
        and renaming an untitled snapshot to blank must not turn into a refusal.
        """
        clean = str(label or '').strip()
        if len(clean) > MAX_LABEL:
            raise ValueError(t('wfHistory.labelTooLong', n=MAX_LABEL))
        wanted = str(snapshot_id or '')
        with self._lock:
            rows = self._conn.execute(
                'SELECT id, label, workflow_name, created_at, node_count, edge_count '
                'FROM canvas_snapshots WHERE id = ?',
                (wanted,),
            ).fetchall()
            if not rows:
                return None
            self._conn.execute('UPDATE canvas_snapshots SET label = ? WHERE id = ?', (clean, wanted))
            self._conn.commit()
            header = self._header(rows[0])
            header['label'] = clean
            return header

    def list_snapshots(self) -> list:
        rows = self._query(
            'SELECT id, label, workflow_name, created_at, node_count, edge_count '
            'FROM canvas_snapshots ORDER BY created_at DESC, rowid DESC'
        )
        return [self._header(row) for row in rows]

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        rows = self._query('SELECT * FROM canvas_snapshots WHERE id = ?', (str(snapshot_id or ''),))
        if not rows:
            return None
        row = rows[0]
        try:
            workflow = json.loads(row['payload'])
        except (TypeError, ValueError) as e:
            raise SnapshotCorruptError(t('wfHistory.corrupt', id=str(row['id']))) from e
        meta = self._header(row)
        meta['workflow'] = workflow
        return meta

    def delete_snapshot(self, snapshot_id: str) -> tuple:
        """Drop one snapshot and any baseline pointing at it.

        Returns ``(deleted, cleared_workflows)``. The second list exists so the caller can
        SAY that an auto-layout strategy lost its baseline, rather than letting the next
        run silently fall back to the algorithm.
        """
        wanted = str(snapshot_id or '')
        with self._lock:
            pointer = self._conn.execute(
                'SELECT workflow_name FROM layout_baselines WHERE snapshot_id = ?', (wanted,)
            ).fetchall()
            cleared = [str(row['workflow_name']) for row in pointer]
            if cleared:
                self._conn.execute(
                    "UPDATE layout_baselines SET strategy = 'algorithm', snapshot_id = '', updated_at = ? "
                    'WHERE snapshot_id = ?',
                    (_now(), wanted),
                )
            cursor = self._conn.execute('DELETE FROM canvas_snapshots WHERE id = ?', (wanted,))
            self._conn.commit()
            return cursor.rowcount > 0, cleared

    # ── layout baseline ─────────────────────────────────────────────

    def get_layout(self, workflow_name: str) -> dict:
        """The workflow's layout strategy and, when it is ``baseline``, the snapshot header.

        A pointer to a missing snapshot is reported as ``baseline_missing`` — the layout
        button can then refuse by name instead of quietly running the algorithm while the
        settings still say 「按历史基准」.
        """
        name = str(workflow_name or '').strip()
        rows = self._query('SELECT * FROM layout_baselines WHERE workflow_name = ?', (name,))
        if not rows:
            return {'workflow_name': name, 'strategy': 'algorithm', 'snapshot': None, 'baseline_missing': False}
        row = rows[0]
        strategy = str(row['strategy'] or 'algorithm')
        snapshot = None
        snapshot_id = str(row['snapshot_id'] or '')
        if snapshot_id:
            found = self._query(
                'SELECT id, label, workflow_name, created_at, node_count, edge_count '
                'FROM canvas_snapshots WHERE id = ?',
                (snapshot_id,),
            )
            if found:
                snapshot = self._header(found[0])
        return {
            'workflow_name': name,
            'strategy': strategy,
            'snapshot': snapshot,
            'baseline_missing': strategy == 'baseline' and snapshot is None,
        }

    def set_layout(self, workflow_name: str, strategy: str, snapshot_id: str = '') -> dict:
        name = str(workflow_name or '').strip()
        if not name:
            raise ValueError(t('wfHistory.workflowRequired'))
        if len(name) > MAX_WORKFLOW_NAME:
            raise ValueError(t('wfHistory.workflowNameTooLong', n=MAX_WORKFLOW_NAME))
        strategy = str(strategy or '').strip()
        if strategy not in LAYOUT_STRATEGIES:
            raise ValueError(t('wfHistory.badStrategy', strategy=strategy))
        wanted = str(snapshot_id or '').strip()
        if strategy == 'baseline':
            if not wanted:
                raise ValueError(t('wfHistory.baselineRequired'))
            found = self._query('SELECT id FROM canvas_snapshots WHERE id = ?', (wanted,))
            if not found:
                raise ValueError(t('wfHistory.missing', id=wanted))
        else:
            wanted = ''
        self._execute(
            'INSERT INTO layout_baselines (workflow_name, strategy, snapshot_id, updated_at) '
            'VALUES (?, ?, ?, ?) '
            'ON CONFLICT(workflow_name) DO UPDATE SET strategy = excluded.strategy, '
            'snapshot_id = excluded.snapshot_id, updated_at = excluded.updated_at',
            (name, strategy, wanted, _now()),
        )
        return self.get_layout(name)

    def rename_layout(self, old: str, new: str) -> None:
        """Move a workflow's baseline with the file it belongs to.

        A baseline is keyed by the saved file's stem, so a rename that did not move this
        row would leave the renamed canvas silently on the algorithm while its old name
        kept a pointer nobody can see. A row already at the target (possible only after a
        delete/recreate) is replaced by the moved one.
        """
        old = str(old or '').strip()
        new = str(new or '').strip()
        if not old or not new or old == new:
            return
        with self._lock:
            self._conn.execute('DELETE FROM layout_baselines WHERE workflow_name = ?', (new,))
            self._conn.execute(
                'UPDATE layout_baselines SET workflow_name = ?, updated_at = ? WHERE workflow_name = ?',
                (new, _now(), old),
            )
            self._conn.commit()

    def delete_layout(self, workflow_name: str) -> None:
        """Drop a deleted workflow's baseline (its snapshots stay: history is independent)."""
        name = str(workflow_name or '').strip()
        if not name:
            return
        self._execute('DELETE FROM layout_baselines WHERE workflow_name = ?', (name,))
