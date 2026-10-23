"""Durable projects and snapshots for the bibliometrics workspace.

A run record says what happened; it does not say which of those outcomes the researcher
decided to keep. This store holds the kept ones: a **project** is a named subject of study, and
a **snapshot** is one bibliometrics node's captured result — the node table, the edge list, the
parameters that produced it, and the run/node it came from.

Why the parameters travel with the capture: the point of comparing two snapshots is asking
"did the corpus grow, or did I change the slicing?". A diff that reports node churn without
naming the parameter that moved says half the truth, so the differing parameter names are part
of the answer, not a guess the browser makes later.

Two rules the rest of the project insists on and this keeps:
  * every comparison is computed HERE, on stored data — the panel labels an answer, it never
    assembles one;
  * a list that had to be capped says so (`*_total` beside the list), because a truncated diff
    presented as a complete one is a wrong diff.
"""

import contextlib
import hashlib
import json
import os
import sqlite3
import threading
import time

from config import Config

#: Columns that describe a node's neighbourhood rather than the node. The edges are captured
#: separately, so storing `连接` inside every node row would double the payload and let the two
#: copies of the same fact disagree.
_DERIVED_COLUMNS = ('连接', '年份序列')
#: How many names a diff section lists before capping. A real corpus can differ by thousands of
#: terms; the panel shows the head plus the total, which is what a person reads anyway.
DIFF_LIMIT = 60


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _pair(row: dict) -> tuple:
    """An undirected edge key, so a self-same edge listed once either way compares equal."""
    left = str(row.get('source') or '')
    right = str(row.get('target') or '')
    return (left, right) if left <= right else (right, left)


def _number(value, default=None):
    try:
        text = str(value).strip()
        return default if text == '' else float(text)
    except (TypeError, ValueError):
        return default


def compare_snapshots(a: dict, b: dict) -> dict:
    """What changed between two captured tables, as data — names, counts and capped lists."""
    a_nodes = {str(row.get('节点') or ''): row for row in a.get('nodes') or () if row.get('节点')}
    b_nodes = {str(row.get('节点') or ''): row for row in b.get('nodes') or () if row.get('节点')}
    a_nodes.pop('', None)
    b_nodes.pop('', None)
    added = sorted(set(b_nodes) - set(a_nodes))
    removed = sorted(set(a_nodes) - set(b_nodes))
    common = sorted(set(a_nodes) & set(b_nodes))

    changed = []
    for name in common:
        left, right = a_nodes[name], b_nodes[name]
        moves = {}
        for column in sorted(set(left) & set(right)):
            if column in _DERIVED_COLUMNS or column == '节点':
                continue
            if str(left[column]) == str(right[column]):
                continue
            moves[column] = {'a': left[column], 'b': right[column]}
        if moves:
            changed.append({'name': name, 'columns': moves})
    changed.sort(key=lambda item: (-len(item['columns']), item['name']))

    a_edges = {_pair(row): row for row in a.get('edges') or () if row.get('source') and row.get('target')}
    b_edges = {_pair(row): row for row in b.get('edges') or () if row.get('source') and row.get('target')}
    edge_added = sorted(set(b_edges) - set(a_edges))
    edge_removed = sorted(set(a_edges) - set(b_edges))
    weight_changed = []
    for pair in sorted(set(a_edges) & set(b_edges)):
        left = _number(a_edges[pair].get('weight'), 0.0) or 0.0
        right = _number(b_edges[pair].get('weight'), 0.0) or 0.0
        if left != right:
            weight_changed.append({'source': pair[0], 'target': pair[1], 'a': left, 'b': right})
    weight_changed.sort(key=lambda item: (-abs(item['b'] - item['a']), item['source'], item['target']))

    def clusters(snapshot):
        sizes: dict[str, int] = {}
        labels: dict[str, str] = {}
        for row in snapshot.get('nodes') or ():
            key = str(row.get('聚类') if row.get('聚类') not in (None, '') else '')
            if key == '':
                continue
            sizes[key] = sizes.get(key, 0) + 1
            label = str(row.get('聚类标签') or '')
            if label:
                labels.setdefault(key, label)
        return sizes, labels

    a_sizes, a_labels = clusters(a)
    b_sizes, b_labels = clusters(b)
    relabeled = [
        {'cluster': key, 'a': a_labels[key], 'b': b_labels[key]}
        for key in sorted(set(a_labels) & set(b_labels))
        if a_labels[key] != b_labels[key]
    ]
    size_changed = [
        {'cluster': key, 'a': a_sizes[key], 'b': b_sizes[key]}
        for key in sorted(set(a_sizes) & set(b_sizes))
        if a_sizes[key] != b_sizes[key]
    ]

    def bursts(snapshot):
        out = {}
        for row in snapshot.get('nodes') or ():
            name = str(row.get('节点') or '')
            strength = _number(row.get('突现强度'))
            if not name or strength is None or strength <= 0:
                continue
            out[name] = strength
        return out

    a_bursts, b_bursts = bursts(a), bursts(b)
    burst_strength = sorted(
        (
            {'name': name, 'a': a_bursts[name], 'b': b_bursts[name]}
            for name in set(a_bursts) & set(b_bursts)
            if a_bursts[name] != b_bursts[name]
        ),
        key=lambda item: (-abs(item['b'] - item['a']), item['name']),
    )

    a_params = a.get('params') or {}
    b_params = b.get('params') or {}
    params_differ = sorted(
        (
            {'name': key, 'a': a_params[key], 'b': b_params.get(key)}
            for key in set(a_params) | set(b_params)
            if str(a_params.get(key)) != str(b_params.get(key))
        ),
        key=lambda item: item['name'],
    )

    def capped(names):
        return {'total': len(names), 'items': names[:DIFF_LIMIT]}

    def capped_rows(rows, key):
        rows.sort(key=key)
        return {'total': len(rows), 'items': rows[:DIFF_LIMIT]}

    return {
        'a': _header(a),
        'b': _header(b),
        'same_shape': str(a.get('shape') or '') == str(b.get('shape') or ''),
        'same_project': str(a.get('project_id') or '') == str(b.get('project_id') or ''),
        'nodes': {
            'a': len(a_nodes),
            'b': len(b_nodes),
            'common': len(common),
            'added': capped(added),
            'removed': capped(removed),
            'changed': capped_rows(changed, lambda item: (-len(item['columns']), item['name'])),
        },
        'edges': {
            'a': len(a_edges),
            'b': len(b_edges),
            'added': capped_rows(
                [{'source': p[0], 'target': p[1]} for p in edge_added], lambda item: (item['source'], item['target'])
            ),
            'removed': capped_rows(
                [{'source': p[0], 'target': p[1]} for p in edge_removed], lambda item: (item['source'], item['target'])
            ),
            'weight_changed': {'total': len(weight_changed), 'items': weight_changed[:DIFF_LIMIT]},
        },
        'clusters': {
            'a': len(a_sizes),
            'b': len(b_sizes),
            'added': capped(sorted(set(b_sizes) - set(a_sizes))),
            'removed': capped(sorted(set(a_sizes) - set(b_sizes))),
            'relabeled': {'total': len(relabeled), 'items': relabeled[:DIFF_LIMIT]},
            'size_changed': {'total': len(size_changed), 'items': size_changed[:DIFF_LIMIT]},
        },
        'bursts': {
            'a': len(a_bursts),
            'b': len(b_bursts),
            'added': capped(sorted(set(b_bursts) - set(a_bursts))),
            'removed': capped(sorted(set(a_bursts) - set(b_bursts))),
            'strength_changed': {'total': len(burst_strength), 'items': burst_strength[:DIFF_LIMIT]},
        },
        'params_differ': {'total': len(params_differ), 'items': params_differ[:DIFF_LIMIT]},
        'diff_limit': DIFF_LIMIT,
    }


def _header(snapshot: dict) -> dict:
    """The describing half of a snapshot — what the panel prints beside its numbers."""
    return {
        key: snapshot.get(key)
        for key in (
            'snapshot_id',
            'project_id',
            'label',
            'created_at',
            'run_id',
            'node_id',
            'workflow_name',
            'shape',
            'entity_type',
            'params_verified',
            'node_count',
            'edge_count',
        )
    }


#: The same projection, under a name the API can import instead of re-deriving it.
snapshot_header = _header


class BiblioStore:
    """Projects and captured bibliometrics tables."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.BIBLIO_DB
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.DatabaseError):
            # WAL lets the panel read the list while a run is still writing its own records.
            self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._ensure_tables()

    # ── schema ──────────────────────────────────────────────────

    def _ensure_tables(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS biblio_projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS biblio_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    created_at TEXT,
                    run_id TEXT NOT NULL DEFAULT '',
                    node_id TEXT NOT NULL DEFAULT '',
                    workflow_name TEXT NOT NULL DEFAULT '',
                    workflow_fingerprint TEXT NOT NULL DEFAULT '',
                    dataset_id TEXT NOT NULL DEFAULT '',
                    entity_type TEXT NOT NULL DEFAULT '',
                    shape TEXT NOT NULL DEFAULT '',
                    params_verified INTEGER NOT NULL DEFAULT 0,
                    node_count INTEGER NOT NULL DEFAULT 0,
                    edge_count INTEGER NOT NULL DEFAULT 0,
                    params_json TEXT NOT NULL DEFAULT '{}',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    nodes_json TEXT NOT NULL DEFAULT '[]',
                    edges_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS biblio_snapshots_project
                    ON biblio_snapshots (project_id, created_at);
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
        # Under the same lock every query takes — closing the handle while a worker is
        # mid-execute faults the process rather than raising (see dataset_store.close).
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def counts(self) -> dict:
        """Project and snapshot totals — the fresh-store tripwire the test harness reads."""
        projects = self._query('SELECT COUNT(*) AS n FROM biblio_projects')[0]['n']
        snapshots = self._query('SELECT COUNT(*) AS n FROM biblio_snapshots')[0]['n']
        return {'projects': int(projects), 'snapshots': int(snapshots)}

    # ── projects ────────────────────────────────────────────────

    def create_project(self, name: str, note: str = '') -> dict:
        name = str(name or '').strip()
        stamp = _now()
        project_id = hashlib.sha1(f'{name}|{stamp}|{os.getpid()}'.encode()).hexdigest()[:12]
        self._execute(
            'INSERT INTO biblio_projects (project_id, name, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            (project_id, name, str(note or '').strip(), stamp, stamp),
        )
        return self.get_project(project_id)

    def list_projects(self) -> list:
        rows = self._query(
            'SELECT p.*, (SELECT COUNT(*) FROM biblio_snapshots s WHERE s.project_id = p.project_id) AS snapshots '
            'FROM biblio_projects p ORDER BY p.updated_at DESC, p.name'
        )
        return [dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict | None:
        rows = self._query('SELECT * FROM biblio_projects WHERE project_id = ?', (str(project_id),))
        return dict(rows[0]) if rows else None

    def rename_project(self, project_id: str, name: str, note: str = None) -> bool:
        name = str(name or '').strip()
        if not name:
            return False
        if note is None:
            changed = self._execute(
                'UPDATE biblio_projects SET name = ?, updated_at = ? WHERE project_id = ?',
                (name, _now(), str(project_id)),
            )
        else:
            changed = self._execute(
                'UPDATE biblio_projects SET name = ?, note = ?, updated_at = ? WHERE project_id = ?',
                (name, str(note).strip(), _now(), str(project_id)),
            )
        return changed.rowcount > 0

    def delete_project(self, project_id: str) -> int:
        """Drop a project and every snapshot under it; returns how many snapshots went with it."""
        rows = self._query('SELECT snapshot_id FROM biblio_snapshots WHERE project_id = ?', (str(project_id),))
        removed = len(rows)
        with self._lock:
            self._conn.execute('DELETE FROM biblio_snapshots WHERE project_id = ?', (str(project_id),))
            self._conn.execute('DELETE FROM biblio_projects WHERE project_id = ?', (str(project_id),))
            self._conn.commit()
        return removed

    # ── snapshots ───────────────────────────────────────────────

    def add_snapshot(
        self,
        *,
        project_id: str,
        label: str = '',
        run_id: str = '',
        node_id: str = '',
        workflow_name: str = '',
        workflow_fingerprint: str = '',
        dataset_id: str = '',
        entity_type: str = '',
        shape: str = '',
        params: dict | None = None,
        summary: dict | None = None,
        nodes: list | None = None,
        edges: list | None = None,
        params_verified: bool = False,
    ) -> dict:
        stamp = _now()
        node_rows = list(nodes or ())
        edge_rows = list(edges or ())
        seed = f'{project_id}|{node_id}|{run_id}|{label}|{stamp}|{len(node_rows)}'
        snapshot_id = hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]
        self._execute(
            'INSERT INTO biblio_snapshots (snapshot_id, project_id, label, created_at, run_id, node_id, '
            'workflow_name, workflow_fingerprint, dataset_id, entity_type, shape, node_count, edge_count, '
            'params_json, summary_json, nodes_json, edges_json, params_verified) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                snapshot_id,
                str(project_id),
                str(label or '').strip(),
                stamp,
                str(run_id or ''),
                str(node_id or ''),
                str(workflow_name or ''),
                str(workflow_fingerprint or ''),
                str(dataset_id or ''),
                str(entity_type or ''),
                str(shape or ''),
                len(node_rows),
                len(edge_rows),
                _dumps(params or {}),
                _dumps(summary or {}),
                _dumps(node_rows),
                _dumps(edge_rows),
                1 if params_verified else 0,
            ),
        )
        self._execute('UPDATE biblio_projects SET updated_at = ? WHERE project_id = ?', (stamp, str(project_id)))
        return self.get_snapshot(snapshot_id)

    def list_snapshots(self, project_id: str = None) -> list:
        """Snapshot headers, newest first — never the captured rows (those are per-detail)."""
        sql = (
            'SELECT snapshot_id, project_id, label, created_at, run_id, node_id, workflow_name, '
            'entity_type, shape, params_verified, node_count, edge_count FROM biblio_snapshots'
        )
        params: list = []
        if project_id:
            sql += ' WHERE project_id = ?'
            params.append(str(project_id))
        sql += ' ORDER BY created_at DESC, label'
        return [dict(row) for row in self._query(sql, tuple(params))]

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        rows = self._query('SELECT * FROM biblio_snapshots WHERE snapshot_id = ?', (str(snapshot_id),))
        if not rows:
            return None
        snapshot = dict(rows[0])
        snapshot['params'] = _loads(snapshot.pop('params_json', ''), {})
        snapshot['summary'] = _loads(snapshot.pop('summary_json', ''), {})
        snapshot['nodes'] = _loads(snapshot.pop('nodes_json', ''), [])
        snapshot['edges'] = _loads(snapshot.pop('edges_json', ''), [])
        return snapshot

    def delete_snapshot(self, snapshot_id: str) -> bool:
        changed = self._execute('DELETE FROM biblio_snapshots WHERE snapshot_id = ?', (str(snapshot_id),))
        return changed.rowcount > 0

    def compare(self, a_id: str, b_id: str) -> dict | None:
        left, right = self.get_snapshot(a_id), self.get_snapshot(b_id)
        if left is None or right is None:
            return None
        return compare_snapshots(left, right)
