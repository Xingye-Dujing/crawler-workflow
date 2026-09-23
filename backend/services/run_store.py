"""Durable run state: what every node produced, where a crawl got to, and what
the model has already answered.

The problem this solves: a run used to live entirely in memory. Kill the server
mid-crawl, hit an error 700 rows into a paid analysis, or lose the connection
while a browser is scrolling, and *everything* was gone — the rows already
scraped, the answers already paid for, and any notion of where the crawl had
reached. The next attempt started from zero, re-fetched items that were already
collected, and paid the model twice for the same text.

``RunStore`` puts that state in SQLite (``data/runs.db``) as it is produced:

- ``runs``       one row per execution: identity, status, timing.
- ``node_runs``  one row per node per run: status, row count, crawl cursor.
- ``node_rows``  the rows a node produced, in order — the data itself.
- ``item_seen``  fingerprints of crawled items, so a resumed crawl never
                 collects the same post twice.
- ``llm_cache``  answers keyed by (operation, model, column, text). A re-run —
                 even after re-crawling, even in another workflow — gets the
                 same text back for free instead of paying for it again.

Identity is deliberately split in two:

- ``workflow_fingerprint`` (structure: node ids, types, wiring) answers "is this
  the same workflow?" so the UI can offer to continue an interrupted run even
  after a parameter was tweaked.
- ``node_fingerprint`` (type, operation, parameters, *and the fingerprints of
  its parents*) answers "is this node's stored output still valid?" — so editing
  a chart type re-runs only that node, and changing a crawler's keyword
  invalidates the source and everything downstream of it.

Everything here is best-effort on the write side: a full disk or a locked
database must never take a run down with it. Reads are relied on for
correctness, so they are strict.
"""

import contextlib
import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time

import pandas as pd

from config import Config
from i18n import t

logger = logging.getLogger(__name__)

# Run lifecycle. `running` only ever exists while a process is alive: on startup
# every leftover `running` row is promoted to `interrupted`, which is exactly
# the case "the server died mid-run" that resume exists for.
RUN_RUNNING = 'running'
RUN_INTERRUPTED = 'interrupted'
RUN_COMPLETED = 'completed'
RUN_FAILED = 'failed'
RUN_ABANDONED = 'abandoned'

# Node lifecycle. `partial` is the one that carries real work forward: the node
# died, but the rows it already produced are kept and handed downstream.
NODE_PENDING = 'pending'
NODE_RUNNING = 'running'
NODE_DONE = 'done'
NODE_PARTIAL = 'partial'
NODE_FAILED = 'failed'
NODE_SKIPPED = 'skipped'
NODE_RESTORED = 'restored'

RESUMABLE_RUN_STATUS = (RUN_INTERRUPTED, RUN_FAILED, RUN_RUNNING)

# Column names the crawlers in this project actually emit, best identity first.
_URL_FIELDS = ('链接', '笔记链接', '文章链接', '链接地址', '原文链接', '网址', 'URL', 'url', 'link')
_TITLE_FIELDS = ('标题', 'title')
_AUTHOR_FIELDS = ('作者', '发布者', '公众号', '博主', 'author')
_BODY_FIELDS = ('正文', '内容', '摘要', 'body', 'content')


def _dumps(value) -> str:
    # sort_keys=True is a correctness property, not cosmetics: this output
    # feeds node fingerprints, and dict key order coming from a different
    # client (or a re-save) must not read as a changed node definition.
    return json.dumps(_clean(value), ensure_ascii=False, sort_keys=True)


def _clean(value):
    """JSON-safe copy: NaN/Inf become null instead of the invalid literals
    ``json.dumps`` would otherwise emit, which no strict reader accepts."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in value]
    with contextlib.suppress(TypeError, ValueError):
        if pd.isna(value):
            return None
    return str(value)


def _sha1(*parts) -> str:
    joined = '\x1e'.join('' if part is None else str(part) for part in parts)
    return hashlib.sha1(joined.encode('utf-8')).hexdigest()


def first_text(item: dict, fields) -> str:
    for field in fields:
        value = str(item.get(field) or '').strip()
        if value:
            return value
    return ''


def item_key(item) -> str:
    """Fingerprint of one crawled item — "have I already got this?".

    A link is the best identity when the crawler captured one. Otherwise title
    + author + the head of the body: enough to recognise the same post after a
    re-crawl, while ignoring the parts that change between visits (like/comment
    counts, "展开全文" artefacts, whitespace).
    """
    if not isinstance(item, dict):
        return _sha1('raw', item)
    link = first_text(item, _URL_FIELDS)
    if link:
        return _sha1('url', link)
    parts = [
        first_text(item, _TITLE_FIELDS),
        first_text(item, _AUTHOR_FIELDS),
        first_text(item, _BODY_FIELDS)[:200],
    ]
    if any(parts):
        return _sha1('text', *parts)
    return _sha1('json', _dumps(item))


# The two labels an Upload node carries about its file. They are left out of a
# fingerprint because they *follow* from ``dataset_id`` and describe nothing
# new — so re-saving a workflow with a tidied name does not invalidate a single
# stored row. The id itself is deliberately part of the fingerprint: files are
# stored durably now, so it identifies real input, and pointing a node at a
# different file must invalidate everything downstream of it.
_VOLATILE_PARAMS = frozenset({'dataset_name', 'row_count'})


def stable_params(params) -> dict:
    return {k: v for k, v in (params or {}).items() if str(k) not in _VOLATILE_PARAMS}


def node_fingerprint(node: dict, upstream: tuple = ()) -> str:
    """What makes a node's stored output reusable.

    Type, operation, parameters, and the fingerprints of its parents — so
    changing a chart type invalidates just that node, while changing a
    crawler's keyword invalidates it and everything wired after it. Input
    metadata (`_VOLATILE_PARAMS`) is left out.
    """
    return _sha1(
        node.get('type', ''),
        node.get('operation', ''),
        _dumps(stable_params(node.get('params'))),
        '|'.join(sorted(upstream)),
    )


def workflow_fingerprint(workflow: dict) -> str:
    """Identity of the workflow *structure*: node ids, node types and the
    wiring — deliberately not the parameters. That is what the resume banner
    matches on, so tweaking a setting still finds the interrupted run."""
    nodes = workflow.get('nodes') or []
    conns = workflow.get('connections') or []
    return _sha1(
        _dumps(sorted((str(n.get('id')), str(n.get('type'))) for n in nodes if isinstance(n, dict))),
        _dumps(sorted((str(c.get('from')), str(c.get('to'))) for c in conns if isinstance(c, dict))),
    )


def fingerprints_for_workflow(workflow: dict) -> dict:
    """{node_id: node_fingerprint} for a whole workflow definition.

    Parents are resolved first (topological order via Kahn's algorithm) so a
    node's fingerprint can include its ancestors'. A cycle — which the engine
    rejects anyway — just stops the walk and leaves the rest without parent
    fingerprints rather than looping forever.
    """
    nodes = {str(n.get('id')): n for n in (workflow.get('nodes') or []) if isinstance(n, dict)}
    parents = {}
    children = {nid: [] for nid in nodes}
    for conn in workflow.get('connections') or []:
        if not isinstance(conn, dict):
            continue
        src, dst = str(conn.get('from')), str(conn.get('to'))
        if src in nodes and dst in nodes:
            parents.setdefault(dst, []).append(src)
            children.setdefault(src, []).append(dst)

    out = {}
    queue = [nid for nid in nodes if not parents.get(nid)]
    while queue:
        nid = queue.pop(0)
        upstream = tuple(out.get(p, '') for p in parents.get(nid, []))
        out[nid] = node_fingerprint(nodes[nid], upstream)
        for child in children.get(nid, []):
            if all(p in out or p not in nodes for p in parents.get(child, [])):
                queue.append(child)
    return out


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

    def get(self, idx, thash: str):
        value = self._store.cache_get(self._scope, thash)
        # The LLM runner expects a record carrying the result tuple.
        return {'r': value} if value is not None else None

    def add(self, idx, thash: str, result):
        self._store.cache_put(self._scope, thash, list(result))

    def discard(self):
        """Kept on purpose — see the class docstring."""


class RunStore:
    """SQLite-backed run state. One connection, guarded — writes come from the
    run thread, the LLM worker threads and request handlers alike."""

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

    # ── schema ──────────────────────────────────────────────────

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
                CREATE INDEX IF NOT EXISTS idx_runs_wf ON runs(workflow_fingerprint, started_at);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
                CREATE INDEX IF NOT EXISTS idx_node_runs_status ON node_runs(run_id, status);
                """
            )
            self._conn.commit()
        self._ensure_columns()
        self.promote_stale_runs()

    #: Columns that post-date the CREATE TABLE above. ``CREATE TABLE IF NOT
    #: EXISTS`` leaves an existing database in the shape it was created in, so a
    #: run recorded before a field existed would have nothing for the panel to
    #: read; ``ADD COLUMN`` with a default gives every old row that value without
    #: rewriting the table. The names are a literal tuple written right here.
    _ADDED_COLUMNS = (('runs', 'wf_count', 'INTEGER DEFAULT 1'),)

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

    def _execute(self, sql: str, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ── startup recovery ────────────────────────────────────────

    def promote_stale_runs(self) -> list:
        """A run left in 'running' belongs to a process that is no longer alive
        (this one just started), so it is by definition interrupted — and
        resumable. Returns the run ids promoted."""
        rows = self._query('SELECT run_id FROM runs WHERE status = ?', (RUN_RUNNING,))
        ids = [row['run_id'] for row in rows]
        for run_id in ids:
            stamp = self.now()
            # One rule for closing a node that never reached finish_node, shared
            # with the end-of-run path. The bulk UPDATE this replaces only moved the
            # status and left ``row_count`` at the 0 ``begin_node`` wrote — and
            # ``row_count`` is what the run record shows as 已存行数 AND what the
            # 续跑 node sorts by to find "the fullest node to adopt". So a crawl
            # killed at row 900 came back claiming it had kept nothing: the user
            # read an empty record, discarded it, and threw away paid-for rows.
            self.settle_nodes(run_id)
            self._execute(
                'UPDATE runs SET status = ?, updated_at = ?, node_done = ?, note = ? WHERE run_id = ?',
                (RUN_INTERRUPTED, stamp, self._finished_count(run_id), t('run.interrupted_by_restart'), run_id),
            )
        if ids:
            logger.warning(t('run.promoted', n=len(ids)))
        return ids

    # ── run lifecycle ───────────────────────────────────────────

    def start_run(
        self,
        run_id: str,
        workflow_name: str,
        fingerprint: str,
        mode: str = 'serial',
        headless: bool = True,
        llm: dict = None,
        lang: str = 'zh',
        node_total: int = 0,
        wf_count: int = 1,
    ):
        llm = llm or {}
        stamp = self.now()
        self._execute(
            'INSERT INTO runs (run_id, workflow_name, workflow_fingerprint, status, mode, headless, '
            'llm_provider, llm_model, lang, node_total, node_done, wf_count, started_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?) '
            'ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at, '
            'llm_provider = excluded.llm_provider, llm_model = excluded.llm_model, '
            'node_total = excluded.node_total, wf_count = excluded.wf_count, finished_at = NULL, note = NULL',
            (
                run_id,
                workflow_name,
                fingerprint,
                RUN_RUNNING,
                mode,
                1 if headless else 0,
                llm.get('provider', ''),
                llm.get('model', ''),
                lang,
                node_total,
                max(1, int(wf_count or 1)),
                stamp,
                stamp,
            ),
        )

    def finish_run(self, run_id: str, status: str, note: str = ''):
        stamp = self.now()
        done = self._finished_count(run_id)
        self._execute(
            'UPDATE runs SET status = ?, updated_at = ?, finished_at = ?, node_done = ?, note = ? WHERE run_id = ?',
            (status, stamp, stamp, done, note, run_id),
        )

    def _finished_count(self, run_id: str) -> int:
        """Nodes this run really finished — the number the console prints.

        ``failed`` and ``partial`` are excluded on purpose: a node that died or
        starved visited the canvas but produced nothing downstream can rely on.
        The executor already refuses to count them as done (``completed_nodes``),
        and ``node_done`` is what the run-records table renders as ``n/N`` — so
        one answer, not the two the record and the console used to disagree about.
        ``restored`` counts: those rows are in hand, which is the whole test.
        """
        rows = self._query(
            'SELECT COUNT(*) AS n FROM node_runs WHERE run_id = ? AND status NOT IN (?, ?, ?, ?)',
            (run_id, NODE_PENDING, NODE_SKIPPED, NODE_FAILED, NODE_PARTIAL),
        )
        return int(rows[0]['n']) if rows else 0

    def get_run(self, run_id: str) -> dict | None:
        rows = self._query('SELECT * FROM runs WHERE run_id = ?', (run_id,))
        if not rows:
            return None
        run = dict(rows[0])
        nodes = []
        for row in self._query('SELECT * FROM node_runs WHERE run_id = ? ORDER BY started_at, node_id', (run_id,)):
            node = dict(row)
            with contextlib.suppress(TypeError, ValueError):
                node['cursor'] = json.loads(node.pop('cursor_json') or 'null')
            nodes.append(node)
        run['nodes'] = nodes
        return run

    def list_resumable(self, fingerprint: str = None, limit: int = 20, include_finished: bool = False) -> list:
        """Runs worth offering to resume, newest first.

        Defaults to the unfinished ones — a completed run has nothing to
        continue. ``include_finished`` adds the rest so the same endpoint can
        back a history list.
        """
        sql = 'SELECT * FROM runs'
        params = []
        if fingerprint:
            sql += ' WHERE workflow_fingerprint = ?'
            params.append(fingerprint)
        if not include_finished:
            sql += (' AND' if fingerprint else ' WHERE') + ' status IN (?, ?, ?)'
            params.extend(RESUMABLE_RUN_STATUS)
        sql += ' ORDER BY seq DESC LIMIT ?'
        params.append(max(1, int(limit)))

        out = []
        for row in self._query(sql, tuple(params)):
            run = dict(row)
            nodes = [dict(r) for r in self._query('SELECT * FROM node_runs WHERE run_id = ?', (run['run_id'],))]
            run['nodes'] = nodes
            run['resumable'] = run['status'] in RESUMABLE_RUN_STATUS
            run['partial_nodes'] = [n['node_id'] for n in nodes if n['status'] in (NODE_PARTIAL, NODE_FAILED)]
            run['rows_kept'] = sum(int(n.get('row_count') or 0) for n in nodes)
            out.append(run)
        return out

    def delete_run(self, run_id: str) -> dict:
        """Drop a run and its rows. Crawled-item claims are deliberately kept:
        they are keyed by crawl signature, not by run, so "I already collected
        this post" stays true after the run that collected it is gone."""
        counts = {}
        # The table names are a fixed tuple written right here, never input.
        for table in ('node_rows', 'node_runs', 'runs'):
            cur = self._execute(f'DELETE FROM {table} WHERE run_id = ?', (run_id,))
            counts[table] = cur.rowcount
        return counts

    def forget_run_items(self, run_id: str) -> int:
        """Drop the "already crawled" claims this run made.

        Starting over means collecting everything again, including what was
        fetched before — anything else would silently hand back fewer rows than
        the user asked for. Only this run's claims go; earlier runs keep theirs.
        """
        cur = self._execute('DELETE FROM item_seen WHERE first_run_id = ?', (run_id,))
        return cur.rowcount

    def purge(self, keep_per_workflow: int = None, keep_days: int = None, exclude_run_id: str = '') -> dict:
        """Age out old runs. Finished runs go before interrupted ones, and the
        most recent ``keep_per_workflow`` per workflow always stay.
        ``exclude_run_id`` is the run a live thread is still writing — deleting
        its rows mid-run would silently destroy the very state being built."""
        keep = Config.RUN_KEEP_PER_WORKFLOW if keep_per_workflow is None else int(keep_per_workflow)
        days = Config.RUN_KEEP_DAYS if keep_days is None else int(keep_days)
        cutoff = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - max(0, days) * 86400))

        doomed = set()
        # 1. Too old to be worth continuing, whatever its status.
        rows = self._query('SELECT run_id FROM runs WHERE started_at < ?', (cutoff,))
        doomed.update(row['run_id'] for row in rows)
        # 2. Beyond the per-workflow cap. Interrupted runs are counted first,
        # so the ones someone may still want to continue survive the trim.
        grouped = {}
        for row in self._query('SELECT workflow_name, run_id, status, seq FROM runs'):
            grouped.setdefault(row['workflow_name'] or '', []).append(dict(row))
        for runs in grouped.values():
            ordered = sorted(runs, key=lambda r: r['seq'], reverse=True)
            interrupted = [r for r in ordered if r['status'] == RUN_INTERRUPTED]
            finished = [r for r in ordered if r['status'] != RUN_INTERRUPTED]
            keep_ids = {r['run_id'] for r in (interrupted + finished)[: max(0, keep)]}
            doomed.update(r['run_id'] for r in ordered if r['run_id'] not in keep_ids)
        doomed.discard(exclude_run_id)

        removed = 0
        for run_id in doomed:
            self.delete_run(run_id)
            removed += 1
        # 3. The answer cache is the other thing that grows without bound.
        cache_cutoff = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - max(1, days) * 86400))
        cur = self._execute('DELETE FROM llm_cache WHERE created_at < ?', (cache_cutoff,))
        seen_cutoff = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - max(1, days) * 86400))
        cur2 = self._execute('DELETE FROM item_seen WHERE created_at < ?', (seen_cutoff,))
        return {
            'runs': removed,
            'cache_entries': cur.rowcount,
            'seen_keys': cur2.rowcount,
        }

    def stats(self) -> dict:
        def count(sql, params=()):
            rows = self._query(sql, params)
            return int(rows[0]['n']) if rows else 0

        size = 0
        for suffix in ('', '-wal', '-shm'):
            with contextlib.suppress(OSError):
                size += os.path.getsize(self.db_path + suffix)
        return {
            'runs': count('SELECT COUNT(*) AS n FROM runs'),
            'interrupted': count('SELECT COUNT(*) AS n FROM runs WHERE status = ?', (RUN_INTERRUPTED,)),
            'node_rows': count('SELECT COUNT(*) AS n FROM node_rows'),
            'cache_entries': count('SELECT COUNT(*) AS n FROM llm_cache'),
            'seen_keys': count('SELECT COUNT(*) AS n FROM item_seen'),
            'bytes': size,
        }

    # ── node state ──────────────────────────────────────────────

    def begin_node(self, run_id: str, node_id: str, node_type: str, title: str = '', fingerprint: str = '') -> bool:
        """Mark a node as running. Returns True when stored rows had to be
        dropped because the node's own definition changed — those rows describe
        a different node and must not be restorable."""
        stamp = self.now()
        previous = self._query('SELECT fingerprint FROM node_runs WHERE run_id = ? AND node_id = ?', (run_id, node_id))
        stale = bool(previous) and previous[0]['fingerprint'] not in (None, '', fingerprint)
        if stale:
            self._execute('DELETE FROM node_rows WHERE run_id = ? AND node_id = ?', (run_id, node_id))
        self._execute(
            'INSERT INTO node_runs (run_id, node_id, node_type, title, fingerprint, status, row_count, '
            'started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?) '
            'ON CONFLICT(run_id, node_id) DO UPDATE SET status = excluded.status, node_type = excluded.node_type, '
            'title = excluded.title, fingerprint = excluded.fingerprint, updated_at = excluded.updated_at, '
            'row_count = CASE WHEN ? THEN 0 ELSE node_runs.row_count END',
            (run_id, node_id, node_type, title, fingerprint, NODE_RUNNING, stamp, stamp, 1 if stale else 0),
        )
        return stale

    def finish_node(self, run_id: str, node_id: str, status: str, cursor: dict = None, error: str = ''):
        stamp = self.now()
        count = self.row_count(run_id, node_id)
        cursor_json = _dumps(cursor) if cursor is not None else None
        self._execute(
            'UPDATE node_runs SET status = ?, row_count = ?, updated_at = ?, finished_at = ?, error = ?, '
            'cursor_json = COALESCE(?, cursor_json) WHERE run_id = ? AND node_id = ?',
            (status, count, stamp, stamp, error[:2000], cursor_json, run_id, node_id),
        )

    def save_cursor(self, run_id: str, node_id: str, cursor: dict):
        """Where a crawl got to. Written as it advances, not at the end, so the
        position survives whatever kills the run."""
        self._execute(
            'UPDATE node_runs SET cursor_json = ?, updated_at = ? WHERE run_id = ? AND node_id = ?',
            (_dumps(cursor), self.now(), run_id, node_id),
        )

    def get_cursor(self, run_id: str, node_id: str) -> dict | None:
        rows = self._query('SELECT cursor_json FROM node_runs WHERE run_id = ? AND node_id = ?', (run_id, node_id))
        if not rows or not rows[0]['cursor_json']:
            return None
        with contextlib.suppress(TypeError, ValueError):
            return json.loads(rows[0]['cursor_json'])
        return None

    def settle_nodes(self, run_id: str) -> int:
        """Close every node still marked ``running`` when the run ends.

        Nodes only ever leave ``running`` through ``finish_node``, which a kill
        never reaches — so whatever interrupted the run leaves them claiming to
        be alive. Rows already handed over make them partial (and therefore
        resumable); nothing produced means failed. The stored ``row_count``
        cannot be trusted here: it is only written by ``finish_node``, which is
        exactly the call that was skipped, so the live count is taken from the
        rows themselves and written back.
        """
        rows = self._query('SELECT node_id FROM node_runs WHERE run_id = ? AND status = ?', (run_id, NODE_RUNNING))
        stamp = self.now()
        for row in rows:
            live = self.row_count(run_id, row['node_id'])
            status = NODE_PARTIAL if live > 0 else NODE_FAILED
            self._execute(
                'UPDATE node_runs SET status = ?, row_count = ?, finished_at = ?, updated_at = ? '
                'WHERE run_id = ? AND node_id = ?',
                (status, live, stamp, stamp, run_id, row['node_id']),
            )
        return len(rows)

    def node_statuses(self, run_id: str) -> dict:
        """{node_id: {status, row_count, fingerprint, error, cursor}} — what the
        engine needs to decide which nodes can be restored instead of re-run."""
        out = {}
        for row in self._query('SELECT * FROM node_runs WHERE run_id = ?', (run_id,)):
            node = dict(row)
            with contextlib.suppress(TypeError, ValueError):
                node['cursor'] = json.loads(node.pop('cursor_json') or 'null')
            out[node['node_id']] = node
        return out

    # ── rows ────────────────────────────────────────────────────

    def append_rows(self, run_id: str, node_id: str, rows: list, dedupe_scope: str = None, label: str = '') -> tuple:
        """Append rows as they are produced. Returns (kept, dropped).

        With ``dedupe_scope`` set, a row whose fingerprint was already collected
        under that scope is dropped — that is what stops a resumed crawl from
        re-adding posts it already has, and what makes the same item arriving
        from two pages count once.

        ``label`` is the node's user-facing name (`title #id`): the storage layer
        knows only the id, and a cap warning that says ``node-7`` is no use to
        whoever named that box. The caller resolves it, so this stays one rule.
        """
        if not rows:
            return 0, 0
        limit = Config.RUN_MAX_ROWS_PER_NODE
        with self._lock:
            # ``MAX(seq)+1`` and not ``COUNT(*)``: the primary key is
            # (run_id, node_id, seq), so the maximum is a single index seek while a
            # count visits every stored row — and this runs once per scraped row,
            # which made a long crawl quadratic in the size of its own table (5,000
            # rows meant ~12.5 million row visits just to find the next slot).
            # The two answers agree because ``seq`` is dense: rows are only ever
            # appended here or rewritten wholesale by ``replace_rows``, never
            # deleted one at a time.
            seq = self._conn.execute(
                'SELECT COALESCE(MAX(seq), -1) + 1 FROM node_rows WHERE run_id = ? AND node_id = ?',
                (run_id, node_id),
            ).fetchone()[0]
            existing = seq
            stamp = self.now()
            kept = 0
            dropped = 0
            batch = []
            seen_batch = set()
            for row in rows:
                if existing + kept >= limit:
                    logger.warning(t('run.row_limit', nid=label or node_id, limit=limit))
                    break
                key = item_key(row)
                if key in seen_batch:
                    dropped += 1
                    continue
                seen_batch.add(key)
                if dedupe_scope and not self._claim_item_locked(dedupe_scope, key, run_id, stamp):
                    dropped += 1
                    continue
                batch.append((run_id, node_id, seq + kept, key, _dumps(row), stamp))
                kept += 1
            if batch:
                self._conn.executemany(
                    'INSERT OR REPLACE INTO node_rows (run_id, node_id, seq, row_key, payload, created_at) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    batch,
                )
            self._conn.commit()
        return kept, dropped

    def replace_rows(self, run_id: str, node_id: str, rows: list, label: str = ''):
        """Store a node's complete output at once. Atomic nodes (pandas
        transforms, charts, exports) have no meaningful intermediate state, so
        their durable form is simply "the result"."""
        with self._lock:
            self._conn.execute('DELETE FROM node_rows WHERE run_id = ? AND node_id = ?', (run_id, node_id))
            self._conn.commit()
        limit = Config.RUN_MAX_ROWS_PER_NODE
        if len(rows) > limit:
            logger.warning(t('run.row_limit', nid=label or node_id, limit=limit))
            rows = rows[:limit]
        stamp = self.now()
        payload = [(run_id, node_id, i, item_key(row), _dumps(row), stamp) for i, row in enumerate(rows)]
        with self._lock:
            self._conn.executemany(
                'INSERT OR REPLACE INTO node_rows (run_id, node_id, seq, row_key, payload, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                payload,
            )
            self._conn.commit()
        return len(rows)

    def load_rows(self, run_id: str, node_id: str) -> list:
        """The rows a node produced, in the order it produced them."""
        out = []
        for row in self._query(
            'SELECT payload FROM node_rows WHERE run_id = ? AND node_id = ? ORDER BY seq', (run_id, node_id)
        ):
            try:
                out.append(json.loads(row['payload']))
            except (TypeError, ValueError):
                continue
        return out

    def latest_rows(self, node_id: str, fingerprint: str = '', workflow_name: str = '', workflow_names=None) -> tuple:
        """The newest rows this node ever produced → (run_id, rows).

        This is what lets a preview answer after a page refresh — and after a
        restart: ``execution_state['results']`` is memory-only, but the rows a
        node produced were filed here as they were made. ``fingerprint`` pins
        the lookup to one workflow shape, which a caller that knows it should
        pass (node ids like "node-2" repeat across workflows).

        ``workflow_names`` is the same pin, over several spellings: a run that
        executed two workflows records them as ``A + B``, while the same canvas
        filed its earlier runs under ``A`` alone. Listing both keeps a preview
        working across that change without ever dropping the identity requirement.
        """
        sql = (
            'SELECT r.run_id, MAX(r.seq) AS seq FROM node_rows n JOIN runs r ON r.run_id = n.run_id WHERE n.node_id = ?'
        )
        params = [str(node_id)]
        if fingerprint:
            sql += ' AND r.workflow_fingerprint = ?'
            params.append(fingerprint)
        names = [str(name).strip() for name in (workflow_names or []) if str(name or '').strip()]
        if workflow_name and workflow_name not in names:
            names.insert(0, workflow_name)
        if names:
            sql += ' AND r.workflow_name IN (' + ', '.join('?' * len(names)) + ')'
            params.extend(names)
        sql += ' GROUP BY r.run_id ORDER BY seq DESC LIMIT 5'
        for row in self._query(sql, tuple(params)):
            rows = self.load_rows(row['run_id'], node_id)
            if rows:
                return row['run_id'], rows
        return '', []

    def row_count(self, run_id: str, node_id: str) -> int:
        rows = self._query('SELECT COUNT(*) AS n FROM node_rows WHERE run_id = ? AND node_id = ?', (run_id, node_id))
        return int(rows[0]['n']) if rows else 0

    # ── crawled-item dedupe ─────────────────────────────────────

    def claim_item(self, scope: str, key: str, run_id: str = '') -> bool:
        """True the first time this item is seen under *scope*, False after."""
        with self._lock:
            ok = self._claim_item_locked(scope, key, run_id, self.now())
            self._conn.commit()
        return ok

    def _claim_item_locked(self, scope: str, key: str, run_id: str, stamp: str) -> bool:
        cur = self._conn.execute(
            'INSERT OR IGNORE INTO item_seen (scope, item_key, first_run_id, created_at) VALUES (?, ?, ?, ?)',
            (scope, key, run_id, stamp),
        )
        return cur.rowcount > 0

    def forget_items(self, scope: str) -> int:
        cur = self._execute('DELETE FROM item_seen WHERE scope = ?', (scope,))
        return cur.rowcount

    # ── LLM answer cache ────────────────────────────────────────

    def cache_get(self, scope: str, key: str):
        rows = self._query('SELECT value FROM llm_cache WHERE scope = ? AND cache_key = ?', (scope, key))
        if not rows:
            return None
        with contextlib.suppress(TypeError, ValueError):
            return json.loads(rows[0]['value'])
        return None

    def cache_put(self, scope: str, key: str, value):
        self._execute(
            'INSERT OR REPLACE INTO llm_cache (scope, cache_key, value, created_at) VALUES (?, ?, ?, ?)',
            (scope, key, _dumps(value), self.now()),
        )

    def cache_clear(self, prefix: str = '') -> int:
        if prefix:
            cur = self._execute('DELETE FROM llm_cache WHERE scope LIKE ?', (prefix + '%',))
        else:
            cur = self._execute('DELETE FROM llm_cache')
        return cur.rowcount
