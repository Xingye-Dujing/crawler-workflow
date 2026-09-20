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
        return sqlite3.connect(self.db_path)

    def _ensure_table(self):
        conn = self._conn()
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
        conn.commit()
        conn.close()

    @staticmethod
    def now() -> str:
        return time.strftime('%Y-%m-%dT%H:%M:%S')

    def record_many(self, rows: list):
        """rows: list of (run_id, workflow_name, node_id, node_type, metric, label, value, timestamp)."""
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
        logger.info(t('history.recorded', n=len(rows)))

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
            'SELECT DISTINCT workflow_name FROM execution_history WHERE workflow_name IS NOT NULL ORDER BY workflow_name'
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
        return df

    def clear(self):
        conn = self._conn()
        conn.execute('DELETE FROM execution_history')
        conn.commit()
        conn.close()
