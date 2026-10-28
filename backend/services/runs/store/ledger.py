"""The ledger domains: runs, queue, files and the persisted console log."""

import contextlib
import json
import logging
import os

from i18n import t

from .identity import (
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_PENDING,
    NODE_SKIPPED,
    RESUMABLE_RUN_STATUS,
    RUN_INTERRUPTED,
    RUN_RUNNING,
    RUN_STOPPING,
)

logger = logging.getLogger(__name__)


class QueueMixin:
    def save_queue(self, entries: list[dict]) -> None:
        """Mirror the in-memory queue to disk, exactly and in order.

        A wholesale replace (the queue is capped at QUEUE_MAX, so this is a handful of
        rows), which cannot drift the way an incremental upsert would if a drain popped
        and another path re-inserted. Called under the queue lock by ``app._mirror_queue``.
        """
        with self._lock:
            self._conn.execute('DELETE FROM run_queue')
            for position, entry in enumerate(entries):
                self._conn.execute(
                    'INSERT INTO run_queue (position, id, workflow_name, node_count, lang, queued_at, payload) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (
                        position,
                        entry['id'],
                        entry.get('workflow_name') or '',
                        int(entry.get('nodes') or 0),
                        entry.get('lang') or '',
                        entry.get('queued_at') or '',
                        json.dumps(entry.get('data')),
                    ),
                )
            self._conn.commit()

    def load_queue(self) -> list[dict]:
        """The parked requests in drain order, or [] when nothing survived the restart.

        A row whose payload will not parse is skipped rather than half-resurrected —
        replaying a corrupt body would fail minutes later in a worker nobody watches.
        """
        rows = self._query(
            'SELECT id, workflow_name, node_count, lang, queued_at, payload FROM run_queue ORDER BY position'
        )
        entries = []
        for row in rows:
            try:
                data = json.loads(row['payload'])
            except (ValueError, TypeError):
                continue
            entries.append(
                {
                    'id': row['id'],
                    'workflow_name': row['workflow_name'] or '',
                    'nodes': row['node_count'],
                    'data': data,
                    'lang': row['lang'] or '',
                    'queued_at': row['queued_at'] or '',
                }
            )
        return entries

    def promote_stale_runs(self, statuses=(RUN_RUNNING, RUN_STOPPING), only=None, note: str = '') -> list:
        """A run left in *statuses* belongs to a worker that is no longer writing it,
        so it is by definition interrupted — and resumable. Returns the ids promoted.

        ``only`` restricts the claim to the ids a caller can prove it owns. Startup
        passes nothing (every leftover row there belongs to a dead process by
        definition); a caller asking the same question of a *running* server must pass
        its own, or a second instance would settle another one's live run.

        ``note`` says which of the two it was, because the user reads that word.
        """
        placeholders = ', '.join('?' * len(statuses))
        rows = self._query(f'SELECT run_id FROM runs WHERE status IN ({placeholders})', tuple(statuses))
        ids = [row['run_id'] for row in rows if only is None or row['run_id'] in only]
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
                (RUN_INTERRUPTED, stamp, self._finished_count(run_id), note or t('run.interrupted_by_restart'), run_id),
            )
        if ids:
            logger.warning(t('run.promoted', n=len(ids)))
        return ids

    def mark_stopping(self, run_id: str) -> bool:
        """Say at once that this run is being stopped, before the verdict exists.

        Returns False when the row is not running any more, so a run that settled
        between the Stop request and this call keeps the answer it actually gave.
        """
        cur = self._execute(
            'UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ? AND status = ?',
            (RUN_STOPPING, self.now(), run_id, RUN_RUNNING),
        )
        return bool(cur.rowcount)


class RunsMixin:
    BIBLIO_KINDS = ('biblio_', 'latex')

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
        skipped_workflows: str = '',
    ):
        llm = llm or {}
        stamp = self.now()
        # A resumed run rewrites the description of what this run IS, not just its
        # status: the attempt after a 继续 may run in the other mode, in a visible
        # window, or under a label the user has since edited. Left at their
        # first-attempt values, the record's 并行/串行 and 无头/窗口 chips described a
        # run that never happened (the invariant they exist to state), and the stale
        # ``workflow_name`` broke the lookup every preview/chart/export probe uses —
        # the browser asks under the name on the canvas now. ``started_at`` is
        # deliberately NOT refreshed: the record's date is when this work began.
        self._execute(
            'INSERT INTO runs (run_id, workflow_name, workflow_fingerprint, status, mode, headless, '
            'llm_provider, llm_model, lang, node_total, node_done, wf_count, skipped_workflows, '
            'started_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?) '
            'ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at, '
            'llm_provider = excluded.llm_provider, llm_model = excluded.llm_model, '
            'workflow_name = excluded.workflow_name, workflow_fingerprint = excluded.workflow_fingerprint, '
            'mode = excluded.mode, headless = excluded.headless, lang = excluded.lang, '
            'node_total = excluded.node_total, node_done = excluded.node_done, wf_count = excluded.wf_count, '
            'skipped_workflows = excluded.skipped_workflows, '
            'forced_visible = 0, finished_at = NULL, note = NULL',
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
                skipped_workflows,
                stamp,
                stamp,
            ),
        )

    def finish_run(self, run_id: str, status: str, note: str = '', attempted=None):
        stamp = self.now()
        done = self._finished_count(run_id, attempted)
        self._execute(
            'UPDATE runs SET status = ?, updated_at = ?, finished_at = ?, node_done = ?, note = ? WHERE run_id = ?',
            (status, stamp, stamp, done, note, run_id),
        )

    def _finished_count(self, run_id: str, attempted=None) -> int:
        """Nodes this run really finished — the number the console prints.

        ``failed`` and ``partial`` are excluded on purpose: a node that died or
        starved visited the canvas but produced nothing downstream can rely on.
        The executor already refuses to count them as done (``completed_nodes``),
        and ``node_done`` is what the run-records table renders as ``n/N`` — so
        one answer, not the two the record and the console used to disagree about.
        ``restored`` counts: those rows are in hand, which is the whole test.

        ``attempted`` scopes the count to the node ids this attempt actually ran.
        A ``node_runs`` row survives a canvas edit (AGENTS: the record also keeps
        nodes the canvas deleted), so on a ``继续`` after a node was removed or
        disabled, its old ``done`` row would otherwise push ``node_done`` past a
        ``node_total`` re-set to the smaller graph — the panel reading ``4/3``.
        ``None`` keeps the whole-record count (used by startup recovery, where no
        attempt was re-run to have shrunk the graph).
        """
        sql = 'SELECT COUNT(*) AS n FROM node_runs WHERE run_id = ? AND status NOT IN (?, ?, ?, ?)'
        params: list = [run_id, NODE_PENDING, NODE_SKIPPED, NODE_FAILED, NODE_PARTIAL]
        if attempted is not None:
            ids = list(attempted)
            if not ids:
                return 0
            sql += ' AND node_id IN (' + ', '.join('?' * len(ids)) + ')'
            params.extend(ids)
        rows = self._query(sql, tuple(params))
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
            # Per-node wall time, the same reading as the run's duration_seconds: whole seconds
            # between the node's own started_at and finished_at, None while it is still open.
            # Timestamps are second-granularity, so there is no sub-second precision to report —
            # a fast node legitimately reads 0, never a fabricated millisecond.
            node['duration_seconds'] = self._duration_seconds(node.get('started_at'), node.get('finished_at'))
            nodes.append(node)
        run['nodes'] = nodes
        run['duration_seconds'] = self._duration_seconds(run.get('started_at'), run.get('finished_at'))
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
            run['duration_seconds'] = self._duration_seconds(run.get('started_at'), run.get('finished_at'))
            out.append(run)
        return out

    def run_ids(self) -> set[str]:
        """Every run id currently in the table — for reconciling the 置顶 locks
        against records that actually exist (a lock whose run is gone is a dead key)."""
        return {str(row['run_id']) for row in self._query('SELECT run_id FROM runs')}

    def delete_run(self, run_id: str) -> dict:
        """Drop a run and its rows. Crawled-item claims are deliberately kept:
        they are keyed by crawl signature, not by run, so "I already collected
        this post" stays true after the run that collected it is gone."""
        counts = {}
        # The table names are a fixed tuple written right here, never input.
        # ``run_files`` goes with it: it is per-run bookkeeping of what that record wrote, and a
        # map pointing at a record that no longer exists could never be queried anyway — the file
        # themselves are left alone (a deleted record's exports are the user's to keep or clear).
        # ``run_log`` too: the console lines are per-run bookkeeping, so the retention policy that
        # deletes the run also reclaims its (potentially large) log — the growth cap for storing
        # every line rather than a bounded tail.
        for table in ('node_rows', 'node_runs', 'runs', 'run_files', 'run_log'):
            cur = self._execute(f'DELETE FROM {table} WHERE run_id = ?', (run_id,))
            counts[table] = cur.rowcount
        return counts

    def run_ledger(self) -> list:
        """Every run that wrote files, newest first, with its record header and file rows.

        Backs the export panel's 智能清除 selectors; a run with no ledger rows never appears
        (there is nothing to clear), so the list is only ever actionable entries.
        """
        out = []
        for row in self._query('SELECT DISTINCT run_id FROM run_files'):
            run_id = str(row['run_id'])
            files = self.files_for_run(run_id)
            if not files:
                continue
            run = self.get_run(run_id) or {}
            out.append(
                {
                    'run_id': run_id,
                    'workflow_name': run.get('workflow_name') or '',
                    'started_at': run.get('started_at') or '',
                    'status': run.get('status') or '',
                    'node_ids': sorted({f['node_id'] for f in files if f['node_id']}),
                    'files': files,
                }
            )
        out.sort(key=lambda rec: rec['started_at'], reverse=True)
        return out

    def list_biblio_runs(self, limit: int = 50) -> list:
        """Runs that hold at least one bibliometrics node, newest first, with those nodes.

        The workspace asks the server which runs ARE bibliometric and what each node left
        behind: a browser that decided this from the canvas would offer a run whose node
        produced no rows, and hide a paid-for run whose canvas was since rewired.
        """
        limit = max(1, int(limit))
        grouped: dict[str, dict] = {}
        order: list[str] = []
        for row in self._query(
            'SELECT r.run_id, r.workflow_name, r.started_at, r.status, '
            '       n.node_id, n.title, n.status AS node_status, n.row_count, n.component_name '
            "FROM node_runs n JOIN runs r ON r.run_id = n.run_id WHERE n.node_type = 'biblio' "
            'ORDER BY r.seq DESC, n.node_id',
            (),
        ):
            run_id = str(row['run_id'])
            if run_id not in grouped:
                if len(order) >= limit:
                    break
                grouped[run_id] = {
                    'run_id': run_id,
                    'workflow_name': row['workflow_name'] or '',
                    'started_at': row['started_at'] or '',
                    'status': row['status'] or '',
                    'nodes': [],
                }
                order.append(run_id)
            files = [
                entry
                for entry in self.files_for_run(run_id, node_id=str(row['node_id']))
                if str(entry.get('kind') or '').startswith(self.BIBLIO_KINDS[0])
                or str(entry.get('kind') or '') == self.BIBLIO_KINDS[1]
            ]
            grouped[run_id]['nodes'].append(
                {
                    'node_id': str(row['node_id']),
                    'title': row['title'] or '',
                    'status': row['node_status'] or '',
                    'row_count': int(row['row_count'] or 0),
                    'component_name': row['component_name'] or '',
                    'files': files,
                }
            )
        return [grouped[run_id] for run_id in order]

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
            'run_log_lines': count('SELECT COUNT(*) AS n FROM run_log'),
            'bytes': size,
        }


class FilesMixin:
    def record_file(self, run_id: str, node_id: str, path_or_name, kind: str) -> bool:
        """Register one file a run wrote into the export folder, by basename.

        Only the basename is kept (never a path): every reader of this table deletes through
        the export browser, which resolves a *name* inside ``EXPORT_DIR`` and refuses anything
        that escapes it — so a stored absolute path would be both a traversal surface and a
        lie after the folder moves. Idempotent on ``(run_id, name)``: a live snapshot rewritten
        each batch updates in place rather than stacking duplicate rows. Bookkeeping must never
        take down an export, so callers guard this; a failure here only costs one ledger row.
        """
        name = os.path.basename(str(path_or_name or '').replace('\\', '/'))
        if not run_id or not name:
            return False
        self._execute(
            'INSERT INTO run_files(run_id, node_id, name, kind, created_at) VALUES(?,?,?,?,?) '
            'ON CONFLICT(run_id, name) DO UPDATE SET kind=excluded.kind, node_id=excluded.node_id',
            (str(run_id), str(node_id or ''), name, str(kind or ''), self.now()),
        )
        return True

    def find_file(self, name: str) -> dict | None:
        """The ledger row for one exported file, by basename — the resolver a request that
        arrives with only a NAME has to pass through.

        ``run_files`` stores basenames only, so this is the one way to ask "did we write this?".
        A newest-first single row: the same file name re-recorded by a later run is the same
        bytes on disk (the export folder is flat and names are stamped), and the row is only
        ever used to attribute the result back to a run and a node.
        """
        clean = os.path.basename(str(name or '').replace('\\', '/'))
        if not clean:
            return None
        sql = 'SELECT run_id, node_id, name, kind FROM run_files WHERE name = ? ORDER BY rowid DESC'
        for row in self._query(sql, (clean,)):
            return dict(row)
        return None

    def files_for_run(self, run_id: str, node_id: str = None, kind: str = None) -> list:
        """The files a run wrote, optionally narrowed to one node and/or one kind."""
        sql = 'SELECT name, kind, node_id FROM run_files WHERE run_id = ?'
        params: list = [str(run_id)]
        if node_id is not None:
            sql += ' AND node_id = ?'
            params.append(str(node_id))
        if kind is not None:
            sql += ' AND kind = ?'
            params.append(str(kind))
        sql += ' ORDER BY name'
        return [dict(row) for row in self._query(sql, tuple(params))]

    def forget_run_files(self, run_id: str) -> int:
        """Drop a run's file map (used once its files are cleared from disk)."""
        return self._execute('DELETE FROM run_files WHERE run_id = ?', (str(run_id),)).rowcount

    def forget_file(self, name) -> int:
        """Forget every ledger row pointing at a file *name* that has since been deleted by
        any other door (a single delete, the 清空 sweep), so the map never promises a file that
        is already gone. Matched by basename, the same form ``record_file`` stored."""
        name = os.path.basename(str(name or '').replace('\\', '/'))
        if not name:
            return 0
        return self._execute('DELETE FROM run_files WHERE name = ?', (name,)).rowcount

    def clear_all(self, exclude_run_ids=()) -> dict:
        """Delete every run record, and the crawled-item claims those runs made with them.

        This is the panel's 清空 button, and it releases the ``item_seen`` ledger the way
        ``purge`` does rather than the way a single ``delete_run`` does. The difference is what
        each one is a promise about: deleting one record is a user tidying a history whose
        crawl they still know was paid for, while emptying every record is a request to start
        from nothing — keeping the claims would leave a ledger that points at rows which no
        longer exist, and the next crawl of the same canvas would hand back fewer rows than it
        was asked for with no table left anywhere that could explain the gap.

        The LLM answer cache deliberately survives this: a stored answer is paid for by its
        prompt, not by the run row, and clearing history must not make the next run re-pay
        questions this machine already knows the answers to.

        *exclude_run_ids* is the run a worker is still writing (a serial pass closes one
        record per workflow, hence a set); deleting rows under its feet would destroy state
        mid-flight.
        """
        excluded = {str(rid) for rid in exclude_run_ids if rid}
        totals = {'runs': 0, 'node_rows': 0, 'node_runs': 0, 'item_claims': 0}
        for row in self._query('SELECT run_id FROM runs'):
            run_id = str(row['run_id'])
            if run_id in excluded:
                continue
            counts = self.delete_run(run_id)
            for table in ('node_rows', 'node_runs'):
                totals[table] += int(counts.get(table) or 0)
            totals['item_claims'] += int(self.forget_run_items(run_id) or 0)
            totals['runs'] += 1
        if not excluded:
            # Emptying the history is starting from nothing; a watermark pointing at a
            # deleted crawl would make the next run skip rows whose provenance is gone.
            self._execute('DELETE FROM source_watermarks')
        return totals


class LogMixin:
    def append_log(self, run_id: str, rows: list) -> int:
        """Persist console lines for a run in one batch. Each row is a
        ``(ts, wf_idx, wf_name, level, line)`` tuple, in the order produced.

        ``seq`` is the next free slot via ``MAX(seq)+1`` (never ``COUNT(*)``) — same rule as
        ``node_rows``: the PK is ``(run_id, seq)`` so the max is an index seek, and this is called
        once per flush (many lines), not per line, so the read happens once per batch. Returns the
        number of rows written.
        """
        if not rows:
            return 0
        with self._lock:
            start = self._conn.execute(
                'SELECT COALESCE(MAX(seq), -1) + 1 FROM run_log WHERE run_id = ?', (run_id,)
            ).fetchone()[0]
            batch = []
            for offset, (ts, wf_idx, wf_name, level, line) in enumerate(rows):
                batch.append((run_id, start + offset, ts, wf_idx, wf_name or '', level or 'info', line))
            self._conn.executemany(
                'INSERT OR REPLACE INTO run_log (run_id, seq, ts, wf_idx, wf_name, level, line) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                batch,
            )
            self._conn.commit()
        return len(batch)

    def read_log(
        self,
        run_id: str,
        wf_idx: int = None,
        level: str = None,
        q: str = None,
        before_seq: int = None,
        limit: int = 500,
    ) -> dict:
        """One page of a run's persisted console, oldest→newest, for the after-the-fact viewer.

        Filters are optional: ``wf_idx`` (a parallel run's tab), ``level``, and ``q`` (a substring
        search). ``before_seq`` walks older ("加载更早"): it returns the ``limit`` lines immediately
        older than that seq, so the newest page passes no ``before_seq`` and each older page passes
        the smallest seq it already has. We take ``limit+1`` newest-first to learn ``has_more``
        without a second query, then flip back to chronological order for display. Every value is a
        bound parameter — never string-interpolated — so the search text cannot reach the SQL.
        """
        where = ['run_id = ?']
        params: list = [run_id]
        if wf_idx is not None:
            where.append('wf_idx = ?')
            params.append(int(wf_idx))
        if level:
            where.append('level = ?')
            params.append(level)
        if q:
            # A SUBSTRING test, not a LIKE pattern: the search box takes what the user typed, and
            # LIKE would read their ``%``/``_`` as wildcards — filtering ``100%`` then matched every
            # 「1000 行」 line too, and the .txt download (which re-uses these filters and promises
            # 「所见即所存」) exported rows the user never asked to see. ``instr`` compares bytes.
            where.append('instr(line, ?) > 0')
            params.append(q)
        if before_seq is not None:
            where.append('seq < ?')
            params.append(int(before_seq))
        cap = max(1, int(limit))
        clause = ' AND '.join(where)
        fetched = self._query(
            f'SELECT seq, ts, wf_idx, wf_name, level, line FROM run_log WHERE {clause} ORDER BY seq DESC LIMIT ?',
            (*params, cap + 1),
        )
        has_more = len(fetched) > cap
        page = fetched[:cap]
        rows = [
            {
                'seq': r['seq'],
                'ts': r['ts'],
                'wf_idx': r['wf_idx'],
                'wf_name': r['wf_name'],
                'level': r['level'],
                'line': r['line'],
            }
            for r in reversed(page)
        ]
        min_seq = rows[0]['seq'] if rows else None
        max_seq = rows[-1]['seq'] if rows else None
        return {'rows': rows, 'has_more': has_more, 'min_seq': min_seq, 'max_seq': max_seq}
