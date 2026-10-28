"""Per-node progress: statuses, cursors, the row sink and the dedupe/answer caches."""

import contextlib
import json
import logging

from core.config import Config

from i18n import t

from .identity import (
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_RUNNING,
    _dumps,
    item_key,
)

logger = logging.getLogger(__name__)


class NodesMixin:
    def get_node_status(self, run_id: str, node_id: str):
        """The stored status of one node in one run, or None when it never ran there.

        The single-node rerun asks only this: does the target already hold a completed
        (done/restored) result worth re-executing downstream from?"""
        rows = self._query('SELECT status FROM node_runs WHERE run_id = ? AND node_id = ?', (run_id, node_id))
        return rows[0]['status'] if rows else None

    def invalidate_nodes(self, run_id: str, node_ids: list) -> int:
        """Drop every stored result for ``node_ids`` in one run, so a resume re-runs exactly them.

        Deleting the ``node_rows`` (the data) AND the ``node_runs`` row (its done/restored status
        and cursor) is what makes the reuse predicate treat these nodes as never-run while leaving
        every OTHER node's kept rows in place to be reused. Returns how many node records were
        cleared — one per targeted node that had a row.

        The deleted rows' dedupe claims go with them. A crawl's ``item_seen`` scope is
        ``'item:'+node_fingerprint``, and a rerun reuses the SAME fingerprint (the node was not
        edited), so leaving the claims in place meant every freshly fetched item hit "already
        collected" and was dropped: the user pressed 重跑节点, the crawl really ran, and it settled
        with zero rows on a canvas whose data they had just deleted. Only what THIS run bought for
        THESE nodes is released — an earlier run's identical claim still dedupes as it always did.
        """
        cleared = 0
        released = 0
        with self._lock:
            for node_id in node_ids:
                # Read the fingerprint BEFORE the row goes: it is the only key back to the
                # claims this node bought, and the node_runs row is where it is stored.
                row = self._conn.execute(
                    'SELECT fingerprint FROM node_runs WHERE run_id = ? AND node_id = ?', (run_id, node_id)
                ).fetchone()
                fingerprint = (row[0] if row else None) or ''
                if fingerprint:
                    released += self._conn.execute(
                        'DELETE FROM item_seen WHERE scope = ? AND first_run_id = ?',
                        ('item:' + str(fingerprint), run_id),
                    ).rowcount
                self._conn.execute('DELETE FROM node_rows WHERE run_id = ? AND node_id = ?', (run_id, node_id))
                cleared += self._conn.execute(
                    'DELETE FROM node_runs WHERE run_id = ? AND node_id = ?', (run_id, node_id)
                ).rowcount
            self._conn.commit()
        if released:
            logger.info(t('run.claims_released', n=released, rid=run_id))
        return cleared

    def begin_node(
        self,
        run_id: str,
        node_id: str,
        node_type: str,
        title: str = '',
        fingerprint: str = '',
        component: int = 0,
        component_name: str = '',
    ) -> bool:
        """Mark a node as running. Returns True when stored rows had to be
        dropped because the node's own definition changed — those rows describe
        a different node and must not be restorable.

        ``component``/``component_name`` say which workflow of the canvas the node was
        executed in. They are refreshed on every visit rather than kept from the first:
        rewiring the canvas between attempts moves nodes between components, and a record
        that still said 「热门榜」 for a node the user had since connected to 周排行榜
        would be a wrong claim in a plausible column.
        """
        stamp = self.now()
        previous = self._query('SELECT fingerprint FROM node_runs WHERE run_id = ? AND node_id = ?', (run_id, node_id))
        stale = bool(previous) and previous[0]['fingerprint'] not in (None, '', fingerprint)
        if stale:
            self._execute('DELETE FROM node_rows WHERE run_id = ? AND node_id = ?', (run_id, node_id))
        self._execute(
            'INSERT INTO node_runs (run_id, node_id, node_type, title, fingerprint, status, row_count, '
            'component, component_name, started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?) '
            'ON CONFLICT(run_id, node_id) DO UPDATE SET status = excluded.status, node_type = excluded.node_type, '
            'title = excluded.title, fingerprint = excluded.fingerprint, updated_at = excluded.updated_at, '
            'component = excluded.component, component_name = excluded.component_name, '
            'row_count = CASE WHEN ? THEN 0 ELSE node_runs.row_count END, '
            'cursor_json = CASE WHEN ? THEN NULL ELSE node_runs.cursor_json END',
            (
                run_id,
                node_id,
                node_type,
                title,
                fingerprint,
                NODE_RUNNING,
                max(0, int(component or 0)),
                str(component_name or ''),
                stamp,
                stamp,
                1 if stale else 0,
                # A cursor is the position *of the rows that survived*. When the node's
                # definition changed the rows are dropped and the count reset, so the old
                # offset now describes a different crawl: leaving it made a re-keyed source
                # resume at the previous keyword's page over an empty seed and under-collect.
                1 if stale else 0,
            ),
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


class RowsMixin:
    def load_rows_page(self, run_id: str, node_id: str, offset: int = 0, limit: int = 200) -> tuple[int, list]:
        """One page of a node's stored rows plus the total row count.

        A bibliometric node table is one row per entity and can be thousands deep; the
        workspace pages it instead of materialising the whole run node into one response.
        """
        total = self._query(
            'SELECT COUNT(*) AS n FROM node_rows WHERE run_id = ? AND node_id = ?', (str(run_id), str(node_id))
        )
        count = int(total[0]['n']) if total else 0
        rows = self._query(
            'SELECT payload FROM node_rows WHERE run_id = ? AND node_id = ? ORDER BY seq LIMIT ? OFFSET ?',
            (str(run_id), str(node_id), max(1, int(limit)), max(0, int(offset))),
        )
        out = []
        for row in rows:
            try:
                out.append(json.loads(row['payload']))
            except (TypeError, ValueError):
                continue
        return count, out

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
        capped = False
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
                    # The cap is NOT a ledger dedupe: leave ``dropped`` alone so the caller can
                    # tell the two apart, and record only that a warning is owed — never log here.
                    # logger.warning runs through the console handler, which takes _completed_lock
                    # and then the durable sink re-enters append_log → this same RLock; another
                    # thread adding a log holds _completed_lock and wants this RLock — a textbook
                    # AB-BA deadlock that froze the worker AND /api/workflow/status.
                    capped = True
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
        if capped:
            logger.warning(t('run.row_limit', nid=label or node_id, limit=limit))
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

    def forget_run_items(self, run_id: str) -> int:
        """Drop the "already crawled" claims this run made.

        Starting over means collecting everything again, including what was
        fetched before — anything else would silently hand back fewer rows than
        the user asked for. Only this run's claims go; earlier runs keep theirs.
        """
        cur = self._execute('DELETE FROM item_seen WHERE first_run_id = ?', (run_id,))
        return cur.rowcount
