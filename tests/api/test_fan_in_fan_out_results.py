"""What the executor REALLY does with a fan-in / fan-out wire — the outcomes the
canvas warns about (see tests/frontend/harness_canvas_ix.mjs ``connect_warnings``).

The frontend proves a warning FIRES for each shape; this file proves the consequence the
warning names is what the run actually produces, so the two never drift apart. Everything
runs offline: uploads stand in for crawlers, ``anomaly``/``tokenize``/``join_tables`` are
deterministic, and no browser or model is touched.

The five silent outcomes pinned here (each was previously untested):
  · an upload reads no upstream at all — a wire into it changes nothing;
  · process / tokenize / visualize take only the FIRST parent, the rest is dropped;
  · an analysis join uses only the first two parents, a third is dropped;
  · a fan-out hands every child the SAME full copy (no split, no overwrite);
  · a feed source takes only the first parent that actually carries rows.
"""

import pytest
from run_wait import run_finished

pytestmark = [pytest.mark.api, pytest.mark.serial, pytest.mark.usefixtures('seeded_logins')]


def _node(nid, ntype, params=None, operation=''):
    node = {'id': nid, 'type': ntype, 'title': ntype, 'params': params or {}}
    if operation:
        node['operation'] = operation
    return node


def _wf(nodes, conns):
    return {'nodes': nodes, 'connections': conns, 'settings': {'mode': 'serial'}}


def _wait(app_module, timeout=30.0):
    return run_finished(app_module, timeout)


def _start(client, app_module, workflow, name):
    started = client.post('/api/workflow/execute', json={'workflow': workflow, 'workflow_name': name})
    assert started.get_json()['ok'] is True, started.get_json()
    assert _wait(app_module), 'the run never finished'
    return started.get_json()['run_id']


# Datasets whose membership makes "which parent won" unmistakable. BIG is ten rows so the
# anomaly node (which scores numeric columns and needs a real sample) settles done rather
# than failing on a stub too short to score.
BIG = [
    {'标记': 'B', '城市': '三亚', '分数': 3, '正文': '三亚湾日落真棒'},
    {'标记': 'B', '城市': '海口', '分数': 5, '正文': '海口骑楼老街'},
    {'标记': 'B', '城市': '博鳌', '分数': 2, '正文': '博鳌小镇安静'},
    {'标记': 'B', '城市': '兴隆', '分数': 7, '正文': '兴隆咖啡香浓'},
    {'标记': 'B', '城市': '文昌', '分数': 4, '正文': '文昌鸡很有名'},
    {'标记': 'B', '城市': '万宁', '分数': 6, '正文': '万宁冲浪胜地'},
    {'标记': 'B', '城市': '琼海', '分数': 1, '正文': '琼海椰林风光'},
    {'标记': 'B', '城市': '东方', '分数': 8, '正文': '东方日照充足'},
    {'标记': 'B', '城市': '临高', '分数': 9, '正文': '临高渔港繁忙'},
    {'标记': 'B', '城市': '澄迈', '分数': 10, '正文': '澄迈老街悠长'},
]
SMALL = [
    {'标记': 'S', '城市': '昆明独有', '分数': 1, '正文': '昆明花海'},
    {'标记': 'S', '城市': '大理独有', '分数': 2, '正文': '大理风花雪月'},
]


class TestFanInSilentOutcomes:
    def test_an_upload_reads_no_upstream_and_keeps_only_its_own_table(self, client, app_module, paste):
        """A wire drawn INTO an upload is silently dead — the node loads its own file,
        not its parent's rows. This is the most confusing of the silent outcomes, so the
        result itself must show it: the upstream's rows never appear."""
        big = paste(BIG, name='fan-big.csv')
        small = paste(SMALL, name='fan-small.csv')
        run_id = _start(
            client,
            app_module,
            _wf(
                [
                    _node('node-1', 'upload', {'dataset_id': big, 'row_count': len(BIG)}),
                    _node('node-2', 'upload', {'dataset_id': small, 'row_count': len(SMALL)}),
                ],
                [{'from': 'node-1', 'to': 'node-2'}],
            ),
            'upload-ignores-upstream',
        )
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-2')
        assert len(rows) == len(SMALL), 'the upload kept its OWN file, untouched by the wire'
        assert {r['城市'] for r in rows} == {'昆明独有', '大理独有'}
        assert all(r['标记'] == 'S' for r in rows), 'no row of the upstream (标记 B) leaked in'

    def test_a_process_node_uses_only_the_first_parent(self, client, app_module, paste):
        """Two parents into a process: the FIRST connection wins and the rest is dropped
        — the exact "first only" the canvas warns about, measured through the run."""
        first = paste(BIG, name='proc-first.csv')
        second = paste(SMALL, name='proc-second.csv')
        run_id = _start(
            client,
            app_module,
            _wf(
                [
                    _node('node-a', 'upload', {'dataset_id': first, 'row_count': len(BIG)}),
                    _node('node-b', 'upload', {'dataset_id': second, 'row_count': len(SMALL)}),
                    _node('node-p', 'process', {'operation': 'anomaly'}, 'anomaly'),
                ],
                [{'from': 'node-a', 'to': 'node-p'}, {'from': 'node-b', 'to': 'node-p'}],
            ),
            'process-first-only',
        )
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-p')
        assert len(rows) == len(BIG), 'the process scored the first parent, not the second'
        assert {r['城市'] for r in rows} >= {'三亚', '海口'}
        assert '昆明独有' not in {r['城市'] for r in rows}, 'the second parent was dropped'

    def test_a_tokenize_node_uses_only_the_first_parent(self, client, app_module, paste):
        first = paste(BIG, name='tok-first.csv')
        second = paste(SMALL, name='tok-second.csv')
        run_id = _start(
            client,
            app_module,
            _wf(
                [
                    _node('node-a', 'upload', {'dataset_id': first, 'row_count': len(BIG)}),
                    _node('node-b', 'upload', {'dataset_id': second, 'row_count': len(SMALL)}),
                    _node('node-t', 'tokenize', {'text_column': '正文', 'output_mode': 'word_freq', 'top_n': 50}),
                ],
                [{'from': 'node-a', 'to': 'node-t'}, {'from': 'node-b', 'to': 'node-t'}],
            ),
            'tokenize-first-only',
        )
        words = {r['word'] for r in app_module._RUN_STORE.load_rows(run_id, 'node-t')}
        assert any('昆明' in w for w in words) is False, 'the second parent’s text never reached the tokenizer'
        assert words, 'the first parent was still tokenized'

    def test_a_visualize_node_uses_only_the_first_parent(self, client, app_module, paste):
        """A chart is built from the FIRST table only; a second wire would not blend
        categories in. Read the spec the run produced."""
        first = paste(BIG, name='viz-first.csv')
        second = paste(SMALL, name='viz-second.csv')
        run_id = _start(
            client,
            app_module,
            _wf(
                [
                    _node('node-a', 'upload', {'dataset_id': first, 'row_count': len(BIG)}),
                    _node('node-b', 'upload', {'dataset_id': second, 'row_count': len(SMALL)}),
                    _node(
                        'node-v',
                        'visualize',
                        {'chart_type': 'bar', 'x_field': '城市', 'y_field': '分数', 'agg': 'sum'},
                    ),
                ],
                [{'from': 'node-a', 'to': 'node-v'}, {'from': 'node-b', 'to': 'node-v'}],
            ),
            'viz-first-only',
        )
        assert run_id
        spec = app_module.execution_state['results'].get('node-v') or {}
        import json as _json

        blob = _json.dumps(spec, ensure_ascii=False)
        assert '昆明独有' not in blob, 'the second parent’s category must not appear in the chart'
        assert 'series' in blob, 'the first parent produced a real chart'

    def test_an_analysis_join_uses_only_the_first_two_parents(self, client, app_module, paste):
        """A join is left = first wire, right = second wire. A THIRD wire is dropped, not
        silently concatenated in — the join only ever reads the first right-hand table."""
        left = paste([{'城市': '三亚', '序号': 1}, {'城市': '海口', '序号': 2}], name='join-left.csv')
        right = paste([{'城市': '三亚', '人口': 100}, {'城市': '海口', '人口': 200}], name='join-right.csv')
        third = paste([{'城市': '消失城', '幽灵列': 9}], name='join-third.csv')
        run_id = _start(
            client,
            app_module,
            _wf(
                [
                    _node('node-l', 'upload', {'dataset_id': left, 'row_count': 2}),
                    _node('node-r', 'upload', {'dataset_id': right, 'row_count': 2}),
                    _node('node-x', 'upload', {'dataset_id': third, 'row_count': 1}),
                    _node(
                        'node-j',
                        'analysis',
                        {'operation': 'join_tables', 'join_how': 'left', 'left_on': '城市', 'right_on': '城市'},
                        'join_tables',
                    ),
                ],
                [
                    {'from': 'node-l', 'to': 'node-j'},
                    {'from': 'node-r', 'to': 'node-j'},
                    {'from': 'node-x', 'to': 'node-j'},
                ],
            ),
            'join-three-parents',
        )
        status = app_module._RUN_STORE.node_statuses(run_id).get('node-j', {})
        assert status.get('status') == 'done', status.get('error')
        rows = app_module._RUN_STORE.load_rows(run_id, 'node-j')
        assert len(rows) == 2, 'the join kept the LEFT table’s rows only'
        assert {'人口', '城市'} <= set(rows[0]), 'the SECOND wire joined as the right table'
        assert '幽灵列' not in set(rows[0]), 'the THIRD wire was dropped, not merged'
        assert '消失城' not in {r['城市'] for r in rows}


class TestFanOutOutcome:
    def test_a_fan_out_hands_every_child_the_same_full_copy(self, client, app_module, paste):
        """Splitting one node’s output across two branches is safe: BOTH children receive
        the complete set of rows — nothing is divided or overwritten between them."""
        src = paste(BIG, name='fanout-src.csv')
        run_id = _start(
            client,
            app_module,
            _wf(
                [
                    _node('node-1', 'upload', {'dataset_id': src, 'row_count': len(BIG)}),
                    _node('node-p1', 'process', {'operation': 'anomaly'}, 'anomaly'),
                    _node('node-p2', 'process', {'operation': 'anomaly'}, 'anomaly'),
                ],
                [{'from': 'node-1', 'to': 'node-p1'}, {'from': 'node-1', 'to': 'node-p2'}],
            ),
            'fan-out-both-children',
        )
        store = app_module._RUN_STORE
        assert store.row_count(run_id, 'node-p1') == len(BIG)
        assert store.row_count(run_id, 'node-p2') == len(BIG), 'a second branch got the same full table, not a slice'


class TestMultiInputLog:
    def test_a_second_parent_is_named_in_the_console(self, client, app_module, paste):
        """The silent "first only" behaviour is not fully silent: the console states how
        many parents arrived and which one won, so a mistaken fan-in is diagnosable."""
        first = paste(BIG, name='log-first.csv')
        second = paste(SMALL, name='log-second.csv')
        run_id = _start(
            client,
            app_module,
            _wf(
                [
                    _node('node-a', 'upload', {'dataset_id': first, 'row_count': len(BIG)}),
                    _node('node-b', 'upload', {'dataset_id': second, 'row_count': len(SMALL)}),
                    _node('node-p', 'process', {'operation': 'anomaly'}, 'anomaly'),
                ],
                [{'from': 'node-a', 'to': 'node-p'}, {'from': 'node-b', 'to': 'node-p'}],
            ),
            'multi-input-log',
        )
        assert run_id
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert ('条上游连线' in blob) or ('incoming connections' in blob), blob[-400:]


class TestFeedSourceTakesFirstDataParent:
    def test_feed_parent_rows_returns_the_first_parent_that_carries_rows(self, app_module):
        """A feed source reads the FIRST parent that actually holds a data table — a
        name node (no rows) is skipped, and any parent after the first is ignored. This is
        the backend fact behind the canvas's "uses at most one upstream" warning."""
        rows_a = [{'正文': 'a'}]
        rows_b = [{'正文': 'b'}]
        # a name-like empty parent first, then two data parents → the FIRST data parent wins
        assert app_module._feed_parent_rows([('node-1', []), ('node-2', rows_a), ('node-3', rows_b)]) == rows_a
        # an immediately-data-bearing parent wins and the rest is ignored
        assert app_module._feed_parent_rows([('node-1', rows_a), ('node-2', rows_b)]) == rows_a
        # nothing carries rows → no feed (a crawl with no upstream table)
        assert app_module._feed_parent_rows([('node-1', []), ('node-2', None)]) is None
