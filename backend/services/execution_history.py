"""Execution history service.

Persists lightweight per-run metrics (row counts, emotion/tendency
distributions) to SQLite so the UI can chart how things change across runs
over time — e.g. "how has the emotion distribution for this topic shifted
over the last 2 weeks of crawls".

This is intentionally a separate, minimal SQLite table rather than reusing
`models/database.py`'s `Database` class: that class stores the crawled
*data itself* (arbitrary tables), while this stores small, structured
*metrics about a run* (a handful of rows per execution, not the raw
dataset), so keeping them separate avoids mixing concerns and avoids
`Database`'s package-relative import (`from backend.config import Config`)
which assumes a different run context than `app.py` uses.
"""

import logging
import os
import sqlite3
import time

import pandas as pd

from config import Config
from i18n import t

logger = logging.getLogger(__name__)


class ExecutionHistoryService:
    """Records and queries per-run metrics: (run_id, workflow_name, node_id,
    node_type, metric, label, value, timestamp)."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(Config.DATA_DIR, 'history.db')
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._ensure_table()

    def _conn(self):
        """A connection with the schema present.

        The table is created *per connection* rather than once at import, because
        ``history.db`` is a file a user is entitled to delete: cleaning ``data/``
        is a normal thing to do, and a test suite that recycles temp directories
        hits the same path. When the file was gone, every ``/api/history/*``
        endpoint answered 500 with ``no such table: execution_history`` for the
        rest of the process — the console's history panel was dead until a
        restart, and a restart only re-created the table if the file happened to
        still be missing at import time. ``CREATE TABLE IF NOT EXISTS`` on an
        existing schema is cheap and idempotent.
        """
        conn = sqlite3.connect(self.db_path)
        self._create_schema(conn)
        return conn

    def _ensure_table(self):
        conn = sqlite3.connect(self.db_path)
        self._create_schema(conn)
        conn.commit()
        conn.close()

    def _create_schema(self, conn):
        """Create the table and indexes on *conn* — the caller keeps ownership.

        It must not commit or close: :meth:`_conn` calls this on the connection it
        is about to hand to a write, and a schema helper that closed it turned every
        insert into ``Cannot operate on a closed database``.
        """
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                workflow_name TEXT,
                node_id TEXT,
                node_type TEXT,
                metric TEXT NOT NULL,
                label TEXT,
                value REAL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute('CREATE INDEX IF NOT EXISTS idx_history_run ON execution_history(run_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_history_wf ON execution_history(workflow_name)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_history_metric ON execution_history(metric)')

    @staticmethod
    def now() -> str:
        return time.strftime('%Y-%m-%dT%H:%M:%S')

    def record_many(self, rows: list, log_label: str = ''):
        """rows: list of (run_id, workflow_name, node_id, node_type, metric, label, value, timestamp).

        ``log_label`` is for the console line only: a multi-component canvas
        records one entry per component, and two byte-identical "recorded N
        metrics" lines read like a printing bug. The stored name stays the run's
        own, so the history panel's grouping is untouched.
        """
        if not rows:
            return
        conn = self._conn()
        conn.executemany(
            'INSERT INTO execution_history '
            '(run_id, workflow_name, node_id, node_type, metric, label, value, timestamp) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            rows,
        )
        conn.commit()
        conn.close()
        logger.info(t('history.recorded', n=len(rows), wf=log_label or rows[0][1] or ''))

    def list_runs(self, limit: int = 50) -> pd.DataFrame:
        conn = self._conn()
        df = pd.read_sql(
            'SELECT run_id, workflow_name, MIN(timestamp) AS started_at, COUNT(*) AS metric_count '
            'FROM execution_history GROUP BY run_id, workflow_name '
            'ORDER BY started_at DESC LIMIT ?',
            conn,
            params=(limit,),
        )
        conn.close()
        return df

    def list_workflow_names(self) -> list:
        conn = self._conn()
        cur = conn.execute(
            'SELECT DISTINCT workflow_name FROM execution_history '
            'WHERE workflow_name IS NOT NULL ORDER BY workflow_name'
        )
        names = [row[0] for row in cur.fetchall()]
        conn.close()
        return names

    def series(
        self, workflow_name: str = None, metric: str = None, node_id: str = None, limit: int = 2000
    ) -> pd.DataFrame:
        conn = self._conn()
        sql = 'SELECT * FROM execution_history WHERE 1=1'
        params = []
        if workflow_name:
            sql += ' AND workflow_name = ?'
            params.append(workflow_name)
        if metric:
            sql += ' AND metric = ?'
            params.append(metric)
        if node_id:
            sql += ' AND node_id = ?'
            params.append(node_id)
        sql += ' ORDER BY timestamp ASC LIMIT ?'
        params.append(limit)
        df = pd.read_sql(sql, conn, params=params)
        conn.close()
        # Reads written before the recorder started deduplicating can hold the
        # same point twice (an output node re-recording its process's
        # distribution). Dropping exact duplicates at read time cleans those
        # old rows without touching the database — node_id included, or two
        # *different* nodes legitimately reporting the same count in the same
        # second would collapse into one chart point.
        if not df.empty:
            df = df.drop_duplicates(subset=['workflow_name', 'metric', 'label', 'timestamp', 'value', 'node_id'])
        return df

    def clear(self):
        conn = self._conn()
        conn.execute('DELETE FROM execution_history')
        conn.commit()
        conn.close()

    def delete_run(self, run_id: str) -> int:
        """Drop one run's recorded metrics; returns how many rows went.

        The panel lists runs, so a run is the unit the user thinks they are
        deleting. The count is the answer rather than a boolean because an id
        that matches nothing must be reported as such — a row already aged out
        by the retention policy is not a successful deletion.
        """
        conn = self._conn()
        cur = conn.execute('DELETE FROM execution_history WHERE run_id = ?', (str(run_id),))
        conn.commit()
        conn.close()
        logger.info(t('history.run_deleted', rid=run_id, n=cur.rowcount))
        return int(cur.rowcount or 0)
