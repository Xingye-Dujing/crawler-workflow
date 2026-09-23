"""Tests for the durable checkpoint store behind 断点续跑 (services/run_store.py).

This store is why an interrupted run resumes instead of re-crawling and
re-paying the LLM for rows already produced, so the tests pin down the three
properties the resume feature silently depends on:

- fingerprints that survive a restart *and* a server upgrade in place
  (stable identity ⇒ the resume banner finds the run it offers),
- staleness rules (changed definition ⇒ stored rows are dropped, unchanged ⇒
  kept),
- dedupe + caps (a resumed crawl never double-collects; a runaway cannot fill
  the disk).
"""

import threading

import pytest

from config import Config
from services.run_store import (
    NODE_DONE,
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_SKIPPED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_INTERRUPTED,
    RUN_RUNNING,
    RowCache,
    RunStore,
    fingerprints_for_workflow,
    item_key,
    node_fingerprint,
    stable_params,
    workflow_fingerprint,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    s = RunStore(str(tmp_path / 'runs.db'))
    yield s
    s._conn.close()


def _wf(nodes=None, conns=None):
    return {'nodes': nodes or [], 'connections': conns or []}


def _node(nid='node-1', ntype='source', operation='', params=None):
    return {'id': nid, 'type': ntype, 'operation': operation, 'params': params or {'keyword': '三亚'}}


def _start(store, run_id='r1', name='wf', fp='fp-a', total=0):
    store.start_run(run_id, name, fp, node_total=total)


# ─── item identity ─────────────────────────────────────────────────────


class TestItemKey:
    def test_url_field_wins_over_text(self):
        a = {'链接': 'https://x/1', '标题': 'T1', '正文': 'B'}
        b = {'链接': 'https://x/1', '标题': 'T2', '正文': '完全不同'}
        assert item_key(a) == item_key(b)

    def test_different_urls_differ(self):
        assert item_key({'链接': 'https://x/1'}) != item_key({'链接': 'https://x/2'})

    def test_all_url_column_variants_are_recognised(self):
        # Crawlers emit different link column names per platform; all must
        # identify equally, else a resumed crawl re-collects the same post.
        keys = {item_key({field: 'https://x/9'}) for field in ('链接', '笔记链接', '文章链接', '原文链接', 'url')}
        assert len(keys) == 1

    def test_text_fallback_ignores_body_tail(self):
        base = {'标题': 'T', '作者': 'A', '正文': '长' * 300}
        tail_changed = {'标题': 'T', '作者': 'A', '正文': '长' * 200 + '不同内容' * 100}
        assert item_key(base) == item_key(tail_changed)

    def test_text_fallback_responds_to_head_changes(self):
        base = {'标题': 'T', '作者': 'A', '正文': '开头相同'}
        other = {'标题': 'T', '作者': 'A', '正文': '开头不同'}
        assert item_key(base) != item_key(other)

    def test_non_dict_items_stay_distinct(self):
        assert item_key('a') != item_key('b')
        assert item_key('a') == item_key('a')

    def test_empty_dict_falls_back_to_json_identity(self):
        assert item_key({}) == item_key({})
        assert item_key({}) != item_key({'x': 1})


# ─── fingerprints ──────────────────────────────────────────────────────


class TestFingerprints:
    def test_node_fingerprint_tracks_definition(self):
        n = _node()
        assert node_fingerprint(n) != node_fingerprint(_node(params={'keyword': '海口'}))
        assert node_fingerprint(n) != node_fingerprint(_node(ntype='process'))
        assert node_fingerprint(n) != node_fingerprint(_node(operation='clean'))

    def test_node_fingerprint_ignores_volatile_params(self):
        # A tidied file name must not invalidate a stored crawl.
        plain = _node(params={'dataset_id': 'd1'})
        relabeled = _node(params={'dataset_id': 'd1', 'dataset_name': '新名字', 'row_count': 999})
        assert node_fingerprint(plain) == node_fingerprint(relabeled)

    def test_stable_params_drops_only_volatile_keys(self):
        kept = stable_params({'dataset_id': 'd1', 'dataset_name': 'n', 'row_count': 5})
        assert kept == {'dataset_id': 'd1'}

    def test_parent_change_cascades_into_child_fingerprint(self):
        parent = _node('node-1')
        child = _node('node-2', ntype='analysis')
        same = node_fingerprint(child, upstream=(node_fingerprint(parent),))
        changed = node_fingerprint(child, upstream=(node_fingerprint(_node(params={'keyword': '别的'})),))
        assert same != changed

    def test_workflow_fingerprint_is_structure_only(self):
        nodes = [_node('node-1'), _node('node-2', ntype='analysis')]
        conns = [{'from': 'node-1', 'to': 'node-2'}]
        wf = _wf(nodes, conns)
        tweaked = _wf(
            [_node('node-1', params={'keyword': '海口'}), _node('node-2', ntype='analysis')],
            conns,
        )
        assert workflow_fingerprint(wf) == workflow_fingerprint(tweaked)
        # ...but adding a node *is* a structure change.
        assert workflow_fingerprint(wf) != workflow_fingerprint(_wf(nodes + [_node('node-3', ntype='output')], conns))

    def test_workflow_fingerprint_stable_across_restart(self, store, sample_rows):
        """The resume banner matches on this hash — a different value after a
        server restart would make every interrupted run unresumable."""
        nodes = [_node('node-1'), _node('node-2', ntype='analysis')]
        wf = _wf(nodes, [{'from': 'node-1', 'to': 'node-2'}])
        fp = workflow_fingerprint(wf)
        _start(store, fp=fp)
        store.append_rows('r1', 'node-1', sample_rows)
        expected = store.load_rows('r1', 'node-1')
        store._conn.close()

        reopened = RunStore(store.db_path)
        try:
            assert workflow_fingerprint(wf) == fp
            assert [r['run_id'] for r in reopened.list_resumable(fp)] == ['r1']
            assert reopened.load_rows('r1', 'node-1') == expected
            assert reopened.get_run('r1') is not None
        finally:
            reopened._conn.close()

    def test_fingerprints_for_workflow_walks_topologically(self):
        nodes = [_node('node-1'), _node('node-2', ntype='analysis'), _node('node-3', ntype='output')]
        conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-3'}]
        fps = fingerprints_for_workflow(_wf(nodes, conns))
        assert set(fps) == {'node-1', 'node-2', 'node-3'}
        # Child identity must embed the parent: changing the source keyword...
        nodes2 = [_node('node-1', params={'keyword': '海口'}), nodes[1], nodes[2]]
        fps2 = fingerprints_for_workflow(_wf(nodes2, conns))
        assert fps['node-3'] != fps2['node-3']

    def test_fingerprints_for_workflow_survives_a_cycle(self):
        # The engine rejects cycles anyway; the fingerprint walk must not loop.
        nodes = [_node('node-1'), _node('node-2'), _node('node-3')]
        conns = [{'from': 'node-1', 'to': 'node-2'}, {'from': 'node-2', 'to': 'node-1'}]
        fps = fingerprints_for_workflow(_wf(nodes, conns))
        assert 'node-3' in fps  # acyclic tail still computed


# ─── startup recovery ───────────────────────────────────────────────────


class TestPromoteStale:
    def test_reopening_promotes_running_to_interrupted(self, store, tmp_path):
        _start(store)
        store.begin_node('r1', 'node-1', 'source', fingerprint='fp')
        store._conn.close()
        promoted = RunStore(str(tmp_path / 'runs.db'))  # same file, fresh process
        try:
            assert promoted.get_run('r1')['status'] == RUN_INTERRUPTED
            assert promoted.node_statuses('r1')['node-1']['status'] == NODE_PARTIAL
        finally:
            promoted._conn.close()

    def test_promotion_touches_nothing_else(self, store):
        _start(store, 'r-done')
        store.finish_run('r-done', RUN_COMPLETED)
        _start(store, 'r-live')
        store.begin_node('r-live', 'n1', 'source')
        ids = store.promote_stale_runs()
        assert ids == ['r-live']
        assert store.get_run('r-done')['status'] == RUN_COMPLETED
        # A second pass is a no-op.
        assert store.promote_stale_runs() == []


# ─── run / node lifecycle ───────────────────────────────────────────────


class TestLifecycle:
    def test_finish_run_counts_non_skipped_nodes(self, store):
        _start(store)
        store.begin_node('r1', 'a', 'source')
        store.finish_node('r1', 'a', NODE_DONE)
        store.begin_node('r1', 'b', 'analysis')
        store.finish_node('r1', 'b', NODE_SKIPPED)
        store.begin_node('r1', 'c', 'output')
        store.finish_node('r1', 'c', NODE_FAILED)
        store.finish_run('r1', RUN_FAILED)
        run = store.get_run('r1')
        assert run['node_done'] == 2  # skipped excluded
        assert run['status'] == RUN_FAILED

    def test_begin_node_same_fingerprint_keeps_rows(self, store, sample_rows):
        _start(store)
        store.begin_node('r1', 'n1', 'source', fingerprint='fp')
        store.append_rows('r1', 'n1', sample_rows)
        store.finish_node('r1', 'n1', NODE_DONE)
        assert store.begin_node('r1', 'n1', 'source', fingerprint='fp') is False
        assert store.row_count('r1', 'n1') == 4  # dedup keeps 4 of 5 (shared URL)
        assert store.load_rows('r1', 'n1')

    def test_begin_node_changed_fingerprint_invalidates(self, store, sample_rows):
        _start(store)
        store.begin_node('r1', 'n1', 'source', fingerprint='fp-a')
        store.append_rows('r1', 'n1', sample_rows)
        store.finish_node('r1', 'n1', NODE_DONE)
        assert store.begin_node('r1', 'n1', 'source', fingerprint='fp-b') is True
        assert store.row_count('r1', 'n1') == 0
        assert store.load_rows('r1', 'n1') == []

    def test_cursor_roundtrip_and_corruption(self, store):
        _start(store)
        store.begin_node('r1', 'n1', 'source')
        assert store.get_cursor('r1', 'n1') is None
        store.save_cursor('r1', 'n1', {'page': 3, 'last': 'x'})
        assert store.get_cursor('r1', 'n1') == {'page': 3, 'last': 'x'}
        store._execute("UPDATE node_runs SET cursor_json = '{broken' WHERE run_id = 'r1' AND node_id = 'n1'")
        assert store.get_cursor('r1', 'n1') is None

    def test_settle_nodes_partial_or_failed_by_rows(self, store, sample_rows):
        _start(store)
        store.begin_node('r1', 'has-rows', 'source')
        store.append_rows('r1', 'has-rows', sample_rows)
        store.begin_node('r1', 'empty', 'analysis')
        assert store.settle_nodes('r1') == 2
        statuses = store.node_statuses('r1')
        assert statuses['has-rows']['status'] == NODE_PARTIAL
        assert statuses['empty']['status'] == NODE_FAILED

    def test_finish_node_stores_cursor_and_truncates_error(self, store):
        _start(store)
        store.begin_node('r1', 'n1', 'source')
        store.finish_node('r1', 'n1', NODE_FAILED, cursor={'page': 2}, error='x' * 5000)
        node = store.node_statuses('r1')['n1']
        assert node['cursor'] == {'page': 2}
        assert len(node['error']) <= 2000


# ─── rows: dedupe, caps, ordering ───────────────────────────────────────


class TestRows:
    def test_append_dedupes_within_batch(self, store, sample_rows):
        _start(store)
        kept, dropped = store.append_rows('r1', 'n1', sample_rows)
        assert (kept, dropped) == (4, 1)  # rows 0/3 share a URL

    def test_append_dedupes_across_batches_when_scoped(self, store, sample_rows):
        _start(store)
        store.append_rows('r1', 'n1', sample_rows[:2], dedupe_scope='sig')
        kept, dropped = store.append_rows('r1', 'n1', sample_rows[:2], dedupe_scope='sig')
        assert (kept, dropped) == (0, 2)
        # No scope ⇒ the store keeps whatever the caller sends.
        kept2, _ = store.append_rows('r1', 'n1', sample_rows[:2])
        assert kept2 == 2

    def test_row_cap_truncates_and_is_visible_in_row_count(self, store, sample_rows, monkeypatch):
        monkeypatch.setattr(Config, 'RUN_MAX_ROWS_PER_NODE', 3)
        _start(store)
        kept, _ = store.append_rows('r1', 'n1', sample_rows)
        assert kept == 3
        assert store.row_count('r1', 'n1') == 3

    def test_the_cap_is_counted_across_appends_not_only_within_one(self, store, sample_rows, monkeypatch):
        """The row budget is a property of the node, not of the call.

        A streaming sink appends one row at a time, so a cap that only looked
        inside the current batch would let a 5,000-row crawl through with the
        limit set to 3.
        """
        monkeypatch.setattr(Config, 'RUN_MAX_ROWS_PER_NODE', 3)
        _start(store)
        assert store.append_rows('r1', 'n1', sample_rows[:2])[0] == 2
        kept, _dropped = store.append_rows('r1', 'n1', sample_rows[2:5])
        assert kept == 1, 'only the slot the cap leaves was taken'
        assert store.row_count('r1', 'n1') == 3

    def test_appending_never_counts_the_table_to_find_the_next_slot(self, store, monkeypatch):
        """The next-slot lookup is an index seek, not a scan.

        ``COUNT(*)`` per appended row made a long crawl quadratic in the size of
        its own table — 5,000 rows cost about 12.5 million row visits just to find
        where to write, on a sink the crawler calls once per scraped item. A
        statement log is the only honest way to pin that without timing the suite.
        """
        statements = []

        class Recorder:
            """Delegates to the real connection, remembering every statement.

            ``sqlite3.Connection`` refuses attribute assignment, so the seam has to
            be the object the store holds rather than a method on it.
            """

            def __init__(self, inner):
                self.inner = inner

            def execute(self, sql, params=()):
                statements.append(' '.join(sql.split()))
                return self.inner.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self.inner, name)

        _start(store)
        monkeypatch.setattr(store, '_conn', Recorder(store._conn))
        for index in range(6):
            store.append_rows('r1', 'n1', [{'标题': f'row{index}', '链接': f'https://x.test/{index}'}])
        monkeypatch.undo()

        counted = [line for line in statements if 'COUNT(*) FROM node_rows' in line]
        assert not counted, f'the row sink counted the table once per append: {len(counted)} times'
        rows = store.load_rows('r1', 'n1')
        assert len(rows) == 6, 'and every row still has to land'
        stored = store._query('SELECT seq FROM node_rows WHERE run_id = ? AND node_id = ? ORDER BY seq', ('r1', 'n1'))
        seqs = [row[0] for row in stored]
        assert seqs == list(range(6)), f'slots must stay dense for the cap to mean anything: {seqs}'

    def test_the_cap_warning_names_the_node_as_the_user_named_it(self, store, sample_rows, monkeypatch, caplog):
        """The store only holds the id, so the caller hands down the label — and
        a console saying ``node-7`` is no use to whoever renamed that box."""
        monkeypatch.setattr(Config, 'RUN_MAX_ROWS_PER_NODE', 2)
        _start(store)
        with caplog.at_level('WARNING'):
            store.append_rows('r1', 'n1', sample_rows, label='周报 #n1')
        assert '周报 #n1' in caplog.text
        caplog.clear()
        with caplog.at_level('WARNING'):
            store.replace_rows('r1', 'n2', sample_rows)
        assert 'n2' in caplog.text, 'without a label the id still has to appear'

    def test_replace_rows_swaps_content_and_keeps_order(self, store, sample_rows):
        _start(store)
        store.append_rows('r1', 'n1', sample_rows)
        replaced = list(reversed(sample_rows[:2]))
        assert store.replace_rows('r1', 'n1', replaced) == 2
        assert store.load_rows('r1', 'n1') == replaced

    def test_replace_rows_respects_cap(self, store, sample_rows, monkeypatch):
        monkeypatch.setattr(Config, 'RUN_MAX_ROWS_PER_NODE', 2)
        _start(store)
        store.replace_rows('r1', 'n1', sample_rows)
        assert store.row_count('r1', 'n1') == 2

    def test_load_rows_skips_unparseable_payloads(self, store, sample_rows):
        _start(store)
        store.append_rows('r1', 'n1', sample_rows[:1])
        store._execute(
            'INSERT INTO node_rows (run_id, node_id, seq, row_key, payload, created_at) '
            "VALUES ('r1','n1',99,'k','{nope','x')"
        )
        rows = store.load_rows('r1', 'n1')
        assert len(rows) == 1

    def test_nan_and_inf_round_trip_as_null(self, store):
        _start(store)
        store.append_rows('r1', 'n1', [{'标题': 't', 'v': float('nan'), 'w': float('inf')}])
        row = store.load_rows('r1', 'n1')[0]
        assert row['v'] is None and row['w'] is None

    def test_latest_rows_prefers_newest_run_pinned_by_fingerprint(self, store, sample_rows):
        _start(store, 'rA', fp='fp-a')
        store.append_rows('rA', 'node-1', sample_rows[:1])
        _start(store, 'rB', fp='fp-b')
        store.append_rows('rB', 'node-1', sample_rows[:2])
        assert store.latest_rows('node-1')[0] == 'rB'
        run_id, rows = store.latest_rows('node-1', fingerprint='fp-a')
        assert (run_id, len(rows)) == ('rA', 1)
        assert store.latest_rows('node-missing') == ('', [])

    def test_row_count_and_pending_status_helpers(self, store):
        _start(store)
        assert store.row_count('r1', 'n-none') == 0
        assert store.node_statuses('r1') == {}


# ─── dedupe ledger & caches ─────────────────────────────────────────────


class TestCaches:
    def test_claim_item_is_first_wins(self, store):
        assert store.claim_item('sig', 'k1', 'r1') is True
        assert store.claim_item('sig', 'k1', 'r2') is False
        assert store.claim_item('other', 'k1', 'r2') is True  # scope-isolated

    def test_forget_items_empties_scope_only(self, store):
        store.claim_item('s1', 'a')
        store.claim_item('s2', 'b')
        assert store.forget_items('s1') == 1
        assert store.claim_item('s2', 'b') is False
        assert store.claim_item('s1', 'a') is True

    def test_delete_run_keeps_item_claims(self, store, sample_rows):
        _start(store)
        store.append_rows('r1', 'n1', sample_rows, dedupe_scope='sig')
        store.delete_run('r1')
        assert store.load_rows('r1', 'n1') == []
        # The crawl already paid for those items; a new run must still skip them.
        kept, dropped = store.append_rows('r1', 'n1', sample_rows, dedupe_scope='sig')
        assert (kept, dropped) == (0, 5)

    def test_forget_run_items_releases_only_that_runs_claims(self, store, sample_rows):
        _start(store)
        store.append_rows('r1', 'n1', sample_rows[:2], dedupe_scope='sig')
        _start(store, 'r2')
        store.append_rows('r2', 'n1', sample_rows[2:3], dedupe_scope='sig')
        assert store.forget_run_items('r1') == 2
        assert store.claim_item('sig', item_key(sample_rows[0]), 'rX') is True
        assert store.claim_item('sig', item_key(sample_rows[2]), 'rX') is False

    def test_llm_cache_put_get_and_prefixed_clear(self, store):
        store.cache_put('emotion|qwen|正文|abc', 'k', ['pos', 0.9])
        assert store.cache_get('emotion|qwen|正文|abc', 'k') == ['pos', 0.9]
        assert store.cache_get('missing', 'k') is None
        store.cache_put('tendency|qwen', 'k2', ['neg'])
        assert store.cache_clear('emotion') == 1
        assert store.cache_get('tendency|qwen', 'k2') == ['neg']
        assert store.cache_clear() == 1

    def test_row_cache_adapter(self, store):
        cache = RowCache(store, 'emotion|qwen3.5:9b|正文')
        assert cache.get(0, 'h1') is None
        cache.add(0, 'h1', ('pos', 0.8))
        assert cache.get(9, 'h1') == {'r': ['pos', 0.8]}  # index-free by design
        cache.discard()  # must remain a no-op: answers stay valuable

    def test_purge_skips_cache_entries_inside_window(self, store):
        store.cache_put('s', 'k', ['fresh'])
        assert store.purge()['cache_entries'] == 0
        assert store.cache_get('s', 'k') == ['fresh']


# ─── purge / stats ──────────────────────────────────────────────────────


class TestPurgeAndStats:
    def _aged_run(self, store, run_id, name, status, started_at=None):
        _start(store, run_id, name=name)
        if started_at:
            store._execute('UPDATE runs SET started_at = ? WHERE run_id = ?', (started_at, run_id))
        if status != RUN_RUNNING:
            store.finish_run(run_id, status)

    def test_age_cutoff_removes_everything_older(self, store):
        self._aged_run(store, 'ancient', 'wf', RUN_COMPLETED, started_at='2020-01-01T00:00:00')
        self._aged_run(store, 'fresh', 'wf', RUN_INTERRUPTED)
        removed = store.purge(keep_per_workflow=50, keep_days=30)['runs']
        assert removed == 1
        assert store.get_run('ancient') is None
        assert store.get_run('fresh') is not None

    def test_per_workflow_cap_favours_interrupted_runs(self, store):
        # 3 completed + 1 interrupted under one name, keep=1: the interrupted
        # one survives because somebody may still continue it.
        for i, status in enumerate([RUN_COMPLETED, RUN_INTERRUPTED, RUN_COMPLETED, RUN_COMPLETED]):
            _start(store, f'r{i}', name='wf')
            if status != RUN_RUNNING:
                store.finish_run(f'r{i}', status)
        removed = store.purge(keep_per_workflow=1, keep_days=3650)['runs']
        assert removed == 3
        alive = [r['run_id'] for r in store.list_resumable(include_finished=True)]
        assert alive == ['r1']

    def test_purge_removes_rows_of_doomed_runs(self, store, sample_rows):
        self._aged_run(store, 'old', 'wf', RUN_COMPLETED, started_at='2019-05-05T00:00:00')
        store.begin_node('old', 'n1', 'source')
        store.append_rows('old', 'n1', sample_rows)
        store.purge(keep_per_workflow=50, keep_days=30)
        assert store.row_count('old', 'n1') == 0

    def test_stats_counts_everything_it_tracks(self, store, sample_rows):
        _start(store)
        store.begin_node('r1', 'n1', 'source')
        store.append_rows('r1', 'n1', sample_rows)
        store.finish_run('r1', RUN_COMPLETED)
        store.cache_put('s', 'k', ['v'])
        stats = store.stats()
        assert stats['runs'] == 1
        assert stats['interrupted'] == 0
        assert stats['node_rows'] == 4
        assert stats['cache_entries'] == 1
        assert stats['bytes'] > 0

    def test_list_resumable_orders_newest_first_by_seq(self, store):
        for i in range(3):
            _start(store, f'r{i}', name='wf')
            store.finish_run(f'r{i}', RUN_INTERRUPTED)
        # Interrupted runs also keep running status in RESUMABLE — completed excluded:
        _start(store, 'done', name='wf')
        store.finish_run('done', RUN_COMPLETED)
        ids = [r['run_id'] for r in store.list_resumable()]
        assert ids == ['r2', 'r1', 'r0']
        assert all(r['resumable'] for r in store.list_resumable())


# ─── concurrency ────────────────────────────────────────────────────────


class TestConcurrency:
    def test_parallel_appends_under_shared_dedupe_scope(self, store, sample_rows):
        """Several worker threads claim rows simultaneously; the scope ledger
        must hand each unique item to exactly one writer."""
        _start(store)
        results = []

        def worker(chunk):
            results.append(store.append_rows('r1', 'n1', chunk, dedupe_scope='sig'))

        threads = [threading.Thread(target=worker, args=(sample_rows,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total_kept = sum(k for k, _ in results)
        total_dropped = sum(d for _, d in results)
        # 4 workers × 5 rows: exactly the 4 unique items survive somewhere,
        # everything else loses either the shared claim or its own in-batch
        # duplicate (row 3 mirrors row 0 in every worker's copy).
        assert total_kept == 4
        assert total_dropped == 16
        assert store.row_count('r1', 'n1') == 4

    def test_parallel_claims_are_atomic(self, store):
        winners = []

        def claim(i):
            winners.append(store.claim_item('race', 'same-key', f'r{i}'))

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(1 for w in winners if w) == 1
