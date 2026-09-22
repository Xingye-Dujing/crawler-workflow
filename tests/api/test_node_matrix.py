"""Every node type's operations, driven as NODES rather than as direct calls.

The analyzers have unit tests, and the endpoints have API tests, but for most
operations the piece never covered was the node itself: the settings panel's flat
strings (`columns: "点赞, 阅读"`, `topk: "abc"`, `mode: "ml"`) go through
`_normalize_analysis_params` / `_safe_int` / `_split_columns` before any analyzer
sees them, and a wrong name or a dropped key there is invisible to a test that
calls the analyzer with clean kwargs. Emotion, tendency, keyword, cluster and
correlation had never been executed as a node at all.

Pure-scikit-learn operations run for real and are asserted on their stored rows;
the ones that would need a model or a daemon are asserted on the kwargs the node
hands the analyzer, which is exactly the plumbing under test. Everything here is
offline: OpenRouter and Ollama are never contacted.
"""

import time

import pytest

from services.exporter import DataExporter

pytestmark = [pytest.mark.api, pytest.mark.serial]
RECORDS = [
    {
        '标题': f'标题{i}',
        '正文': f'三亚的海很蓝 文字{i}',
        '点赞': i,
        '阅读': i * 3,
        '城市': 'Sanya' if i % 2 else 'Haikou',
    }
    for i in range(1, 9)
]

# Shaped for the cleaning ops: padded text, a numeric-looking column stored as
# text plus one value that is not, an empty cell, and a fully duplicated row —
# so "dropped 1" can only mean one thing.
CLEAN_RECORDS = [
    {'名称': '  甲  ', '分数': '10', '城市': '北京', '标签': 'A', '序号': 3},
    {'名称': '乙', '分数': '20', '城市': '', '标签': 'A', '序号': 5},
    {'名称': '  丙', '分数': 'abc', '城市': '上海', '标签': 'B', '序号': 1},
    {'名称': '丁', '分数': '40', '城市': '北京', '标签': 'B', '序号': 4},
    {'名称': '丁', '分数': '40', '城市': '北京', '标签': 'B', '序号': 4},
]

RIGHT_RECORDS = [
    {'城市': '北京', '人口': 2100},
    {'城市': '上海', '人口': 2400},
]


def _node(nid, ntype, params=None, operation=''):
    node = {'id': nid, 'type': ntype, 'title': ntype, 'params': params or {}}
    if operation:
        node['operation'] = operation
    return node


def _wf(nodes, conns):
    return {'nodes': nodes, 'connections': conns, 'settings': {'mode': 'serial'}}


def _wait(app_module, timeout=30.0):
    thread = app_module.execution_state.get('thread')
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if thread is not None and not thread.is_alive():
            time.sleep(0.05)
            return True
        time.sleep(0.02)
    return False


def _run_node(
    client,
    app_module,
    paste,
    node_type,
    params,
    operation='',
    extra_nodes=None,
    extra_conns=None,
    extra_inputs=None,
    llm=None,
    records=None,
):
    """upload → (optional extra nodes) → one node of `node_type`, answered with
    the rows the run stored for it.

    `extra_inputs` are nodes wired straight into the target as an additional
    incoming connection — the shape `join_tables` needs, where the second table
    is a second edge rather than a step in the chain.
    """
    body = records or RECORDS
    ds = paste(body, name='matrix.csv')
    chain = [_node('node-1', 'upload', {'dataset_id': ds, 'row_count': len(body)})]
    conns = []
    previous = 'node-1'
    for extra in extra_nodes or []:
        chain.append(extra)
        conns.append({'from': previous, 'to': extra['id']})
        previous = extra['id']
    target = _node('node-target', node_type, params, operation)
    chain.append(target)
    conns.append({'from': previous, 'to': 'node-target'})
    for extra in extra_inputs or []:
        chain.append(extra)
        conns.append({'from': extra['id'], 'to': 'node-target'})
    payload = {'workflow': _wf(chain, conns + list(extra_conns or [])), 'workflow_name': 'matrix'}
    if llm:
        # Emotion and tendency are LLM-capable, so the run is gated on a configured
        # model before the node is ever reached; a name that no transport would
        # answer for is enough, because these tests assert on the hand-off, not on
        # a model's output.
        payload['llm'] = llm
    started = client.post('/api/workflow/execute', json=payload)
    assert started.status_code == 200, started.get_json()
    assert _wait(app_module), 'the run never finished'
    run_id = started.get_json()['run_id']
    store = app_module._RUN_STORE
    return run_id, store.node_statuses(run_id).get('node-target', {}), store.load_rows(run_id, 'node-target')


class TestProcessNodeOperations:
    """The operations the 处理 node offers, executed through the node."""

    def test_keyword_extraction_with_tfidf(self, client, app_module, paste):
        _run, status, rows = _run_node(
            client, app_module, paste, 'process', {'operation': 'keyword', 'method': 'tfidf', 'topk': '3'}, 'keyword'
        )
        assert status['status'] == 'done', status.get('error')
        # merge defaults to true: the whole corpus collapses into one keyword list.
        assert rows and {'method', 'keyword', 'weight'} <= set(rows[0]), rows[:1]
        assert len(rows) <= 3, 'topk is the ceiling on the merged list'

    def test_keyword_extraction_per_row_when_merge_is_off(self, client, app_module, paste):
        _run, status, rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'keyword', 'method': 'tfidf', 'topk': '2', 'merge': 'false'},
            'keyword',
        )
        assert status['status'] == 'done', status.get('error')
        assert {'row', 'method', 'keyword', 'weight'} <= set(rows[0]), rows[:1]
        assert len({row['row'] for row in rows}) > 1, 'each input row keeps its own keywords'

    def test_textrank_answers_empty_for_text_too_short_to_rank(self, client, app_module, paste):
        """TextRank needs a co-occurrence graph, so a title-sized snippet legitimately
        yields nothing. The node must report an empty table rather than fail or
        invent a keyword — that distinction is what a user reads as "no result".
        """
        _run, status, rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'keyword', 'method': 'textrank', 'text_column': '标题', 'merge': 'false'},
            'keyword',
        )
        assert status['status'] == 'done', status.get('error')
        assert rows == []

    def test_clustering_with_kmeans(self, client, app_module, paste):
        _run, status, rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'cluster', 'cluster_method': 'kmeans', 'n_clusters': '2'},
            'cluster',
        )
        assert status['status'] == 'done', status.get('error')
        assert rows and 'cluster' in rows[0]
        assert len({row['cluster'] for row in rows}) <= 2

    def test_clustering_with_dbscan(self, client, app_module, paste):
        _run, status, rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'cluster', 'cluster_method': 'dbscan', 'eps': '0.5', 'min_samples': '2'},
            'cluster',
        )
        assert status['status'] == 'done', status.get('error')
        assert rows and 'cluster' in rows[0]

    def test_correlation_with_each_method(self, client, app_module, paste):
        for method in ('pearson', 'spearman', 'kendall'):
            _run, status, rows = _run_node(
                client,
                app_module,
                paste,
                'process',
                {'operation': 'correlation', 'corr_method': method, 'columns': '点赞, 阅读'},
                'correlation',
            )
            assert status['status'] == 'done', (method, status.get('error'))
            assert rows, method
            assert {row['method'] for row in rows} == {method}
            assert all(abs(row['correlation']) <= 1 for row in rows)

    def test_correlation_with_a_single_numeric_column_answers_with_an_empty_table(self, client, app_module, paste):
        """One column has no pair to report. An empty table with the right columns
        is the honest answer; a row of zeros would be a fabricated finding."""
        _run, status, rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'correlation', 'columns': '点赞'},
            'correlation',
        )
        assert status['status'] == 'done', status.get('error')
        assert rows == []

    def test_correlation_refuses_a_selection_of_only_text_columns(self, client, app_module, paste):
        _run, status, _rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'correlation', 'columns': '城市,标题'},
            'correlation',
        )
        assert status['status'] == 'failed', 'a text-only selection is a wrong setting, not "no correlation"'
        assert '城市' in (status.get('error') or ''), status.get('error')

    def test_emotion_and_tendency_hand_their_mode_to_the_analyzer(self, client, app_module, paste, monkeypatch):
        """These two reach for a model or a daemon, so the node's contract here is
        that the configured mode and column actually arrive at the analyzer."""
        seen = []

        def spy(module_name, class_name, extra):
            module = __import__(f'analyzers.{module_name}', fromlist=[class_name])
            cls = getattr(module, class_name)

            def fake_analyze(self, df, text_column='正文', ctx=None, **kwargs):
                seen.append({'text_column': text_column, 'mode': getattr(self, 'mode', None)})
                out = df.copy()
                out[extra] = 'x'
                return out

            monkeypatch.setattr(cls, 'analyze_dataframe', fake_analyze, raising=True)

        spy('emotion', 'EmotionAnalyzer', '情感')
        spy('tendency', 'TendencyAnalyzer', '倾向')
        for operation in ('emotion', 'tendency'):
            for mode in ('llm', 'ml'):
                _run, status, _rows = _run_node(
                    client,
                    app_module,
                    paste,
                    'process',
                    {'operation': operation, 'mode': mode, 'text_column': '正文'},
                    operation,
                    llm={'provider': 'ollama', 'model': 'a-model-the-test-never-calls'},
                )
                assert status['status'] == 'done', status.get('error')
        assert [entry['mode'] for entry in seen] == ['llm', 'ml', 'llm', 'ml'], seen
        assert all(entry['text_column'] == '正文' for entry in seen)


class TestProcessNodeParameterEdges:
    """Values the panel can produce that no unit test of the helper covered.

    `_safe_int`/`_safe_float` were tested on their own; what matters to a user is
    that a blank, a negative or a typo in a node's field cannot make the node
    invent rows, hang, or quietly fall back to a different operation.
    """

    @pytest.mark.parametrize('topk', ['0', '-5', 'abc', '', '1e400', '999999'])
    def test_keyword_survives_any_topk(self, client, app_module, paste, topk):
        _run, status, rows = _run_node(
            client, app_module, paste, 'process', {'operation': 'keyword', 'topk': topk}, 'keyword'
        )
        assert status['status'] == 'done', status.get('error')
        assert rows, f'topk={topk!r} must not empty the table'

    @pytest.mark.parametrize('columns', ['', '   ', ',,,', '不存在的列', '点赞, 城市'])
    def test_whitespace_and_unknown_column_lists_are_survivable(self, client, app_module, paste, columns):
        _run, status, rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'anomaly', 'columns': columns},
            'anomaly',
        )
        # An operation that cannot be computed answers with a reason now rather
        # than with a table of fabricated zero scores.
        assert status['status'] in ('done', 'failed'), status
        if status['status'] == 'failed':
            assert status.get('error')

    @pytest.mark.parametrize('contamination', ['0', '0.9', '-1', 'abc', '0.05'])
    def test_contamination_is_clamped_into_its_range(self, client, app_module, paste, contamination):
        _run, status, rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'anomaly', 'contamination': contamination},
            'anomaly',
        )
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == len(RECORDS)

    def test_unknown_operation_on_a_process_node_says_so_and_settles_the_node(self, client, app_module, paste):
        _run, status, rows = _run_node(
            client, app_module, paste, 'process', {'operation': 'not-a-real-op'}, 'not-a-real-op'
        )
        assert rows == [], 'an unimplemented operation must not pretend to have produced data'
        assert status['status'] in ('done', 'failed'), status

    def test_text_column_naming_a_numeric_column_is_not_a_crash(self, client, app_module, paste):
        _run, status, rows = _run_node(
            client,
            app_module,
            paste,
            'process',
            {'operation': 'keyword', 'text_column': '点赞', 'topk': '2'},
            'keyword',
        )
        assert status['status'] in ('done', 'failed'), status


class TestAnalysisNodeOperations:
    """Every cleaning op the 分析 node offers, driven through a real run.

    These are the kwargs `_normalize_analysis_params` builds out of the panel's
    flat strings, so a key spelled there and read differently by
    `DataAnalysisService` shows up here as wrong data rather than as a passing
    unit test of the helper.
    """

    def _run(self, client, app_module, paste, op, params, **kwargs):
        return _run_node(client, app_module, paste, 'analysis', params, op, records=CLEAN_RECORDS, **kwargs)

    def test_select_columns_keeps_only_the_named_columns(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'select_columns', {'columns': '名称, 城市'})
        assert status['status'] == 'done', status.get('error')
        assert set(rows[0]) == {'名称', '城市'}
        assert len(rows) == len(CLEAN_RECORDS)

    def test_strip_whitespace_targets_the_named_column_only(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'strip_whitespace', {'columns': '名称'})
        assert status['status'] == 'done', status.get('error')
        assert rows[0]['名称'] == '甲'
        assert rows[2]['名称'] == '丙'
        # The untouched column still carries its padding, so the selection is real.
        assert any(record['名称'].startswith(' ') for record in CLEAN_RECORDS)

    def test_strip_whitespace_without_a_selection_covers_every_text_column(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'strip_whitespace', {'columns': ''})
        assert status['status'] == 'done', status.get('error')
        assert rows[0]['名称'] == '甲'
        assert rows[0]['标签'] == 'A'

    def test_drop_null_honours_any_versus_all(self, client, app_module, paste):
        _run, status, any_rows = self._run(client, app_module, paste, 'drop_null', {'how': 'any'})
        assert status['status'] == 'done', status.get('error')
        assert len(any_rows) == len(CLEAN_RECORDS) - 1, 'the one empty cell drops its row'

        _run, status, all_rows = self._run(client, app_module, paste, 'drop_null', {'how': 'all'})
        assert status['status'] == 'done', status.get('error')
        assert len(all_rows) == len(CLEAN_RECORDS), 'no row is empty in every column'

    def test_fill_null_with_a_literal_value(self, client, app_module, paste):
        _run, status, rows = self._run(
            client, app_module, paste, 'fill_null', {'columns': '城市', 'value': '未知', 'method': ''}
        )
        assert status['status'] == 'done', status.get('error')
        assert rows[1]['城市'] == '未知'
        assert rows[0]['城市'] == '北京', 'filled cells do not overwrite real ones'

    def test_fill_null_with_forward_fill(self, client, app_module, paste):
        _run, status, rows = self._run(
            client, app_module, paste, 'fill_null', {'columns': '城市', 'value': '', 'method': 'ffill'}
        )
        assert status['status'] == 'done', status.get('error')
        assert rows[1]['城市'] == '北京', 'ffill copies the previous row down'

    def test_drop_duplicates_on_a_named_column(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'drop_duplicates', {'columns': '名称'})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == 4
        assert len({row['名称'] for row in rows}) == 4

    def test_drop_duplicates_without_a_selection_uses_the_whole_row(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'drop_duplicates', {'columns': ''})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == 4, 'only the byte-identical last row is a duplicate'

    def test_filter_rows_with_each_comparison(self, client, app_module, paste):
        cases = {
            ('eq', '北京'): 3,
            ('ne', '北京'): 2,
            ('contains', '上'): 1,
            ('not_contains', '上'): 4,
            ('is_null', ''): 1,
            ('not_null', ''): 4,
        }
        for (op, value), expected in cases.items():
            _run, status, rows = self._run(
                client, app_module, paste, 'filter_rows', {'column': '城市', 'op': op, 'value': value}
            )
            assert status['status'] == 'done', (op, status.get('error'))
            assert len(rows) == expected, (op, value, rows)

    def test_filter_rows_on_a_numeric_column(self, client, app_module, paste):
        _run, status, rows = self._run(
            client, app_module, paste, 'filter_rows', {'column': '序号', 'op': 'gte', 'value': '4'}
        )
        assert status['status'] == 'done', status.get('error')
        assert sorted(row['序号'] for row in rows) == [4, 4, 5]

    def test_filter_rows_in_list(self, client, app_module, paste):
        _run, status, rows = self._run(
            client, app_module, paste, 'filter_rows', {'column': '城市', 'op': 'in', 'value': '北京,上海'}
        )
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == 4

    def test_rename_columns_applies_the_pair(self, client, app_module, paste):
        _run, status, rows = self._run(
            client, app_module, paste, 'rename_columns', {'rename_from': '名称', 'rename_to': '名字'}
        )
        assert status['status'] == 'done', status.get('error')
        assert '名字' in rows[0] and '名称' not in rows[0]

    def test_convert_type_to_int_coerces_the_unparseable_cell(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'convert_type', {'column': '分数', 'dtype': 'int'})
        assert status['status'] == 'done', status.get('error')
        assert rows[0]['分数'] == 10
        assert str(rows[2]['分数']).lower() in ('none', 'nan', ''), 'abc has no integer reading'

    def test_convert_type_to_str(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'convert_type', {'column': '序号', 'dtype': 'str'})
        assert status['status'] == 'done', status.get('error')
        assert rows[0]['序号'] == '3'

    def test_sort_rows_ascending_and_descending(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'sort_rows', {'column': '序号'})
        assert status['status'] == 'done', status.get('error')
        assert [row['序号'] for row in rows] == [1, 3, 4, 4, 5]

        _run, status, rows = self._run(client, app_module, paste, 'sort_rows', {'column': '序号', 'ascending': 'false'})
        assert status['status'] == 'done', status.get('error')
        assert [row['序号'] for row in rows] == [5, 4, 4, 3, 1]

    def test_sample_rows_without_a_bound_changes_nothing(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'sample_rows', {'n': '', 'frac': ''})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == len(CLEAN_RECORDS), 'an empty 行数 must not silently become "keep 1"'

    def test_sample_rows_with_a_count_and_a_seed_is_reproducible(self, client, app_module, paste):
        _run, status, first = self._run(client, app_module, paste, 'sample_rows', {'n': '2', 'seed': '7'})
        assert status['status'] == 'done', status.get('error')
        assert len(first) == 2
        _run, status, second = self._run(client, app_module, paste, 'sample_rows', {'n': '2', 'seed': '7'})
        assert status['status'] == 'done', status.get('error')
        assert [row['序号'] for row in first] == [row['序号'] for row in second]

    def test_sample_rows_with_a_fraction(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'sample_rows', {'frac': '0.4', 'seed': '1'})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == 2

    def test_groupby_agg_sums_the_value_column(self, client, app_module, paste):
        _run, status, rows = self._run(
            client,
            app_module,
            paste,
            'groupby_agg',
            {'group_col': '城市', 'agg_col': '序号', 'agg_func': 'sum'},
        )
        assert status['status'] == 'done', status.get('error')
        assert {row['城市']: row['序号'] for row in rows} == {'北京': 11, '上海': 1, '': 5}

    def test_groupby_agg_renames_the_aggregated_column(self, client, app_module, paste):
        _run, status, rows = self._run(
            client,
            app_module,
            paste,
            'groupby_agg',
            {'group_col': '标签', 'agg_col': '序号', 'agg_func': 'count'},
        )
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == 2

    def test_join_tables_merges_the_second_incoming_connection(self, client, app_module, paste):
        right = paste(RIGHT_RECORDS, name='matrix-right.csv')
        _run, status, rows = self._run(
            client,
            app_module,
            paste,
            'join_tables',
            {'join_how': 'left', 'left_on': '城市', 'right_on': '城市'},
            extra_inputs=[_node('node-right', 'upload', {'dataset_id': right, 'row_count': len(RIGHT_RECORDS)})],
        )
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == len(CLEAN_RECORDS)
        assert {'人口', '城市'} <= set(rows[0])
        by_city = {row['城市']: row.get('人口') for row in rows}
        assert by_city['北京'] == 2100
        assert str(by_city['']).lower() in ('none', 'nan', ''), 'an unmatched left row survives with no match'

    def test_join_tables_without_a_second_connection_fails_loudly(self, client, app_module, paste):
        _run, status, rows = self._run(
            client, app_module, paste, 'join_tables', {'left_on': '城市', 'right_on': '城市'}
        )
        assert status['status'] == 'failed', 'a join with one table must not answer with the left table'
        assert rows == []

    def test_column_calc_adds_the_derived_column(self, client, app_module, paste):
        _run, status, rows = self._run(
            client, app_module, paste, 'column_calc', {'new_col': '两倍', 'expr': '序号 * 2'}
        )
        assert status['status'] == 'done', status.get('error')
        assert [row['两倍'] for row in rows] == [6, 10, 2, 8, 8]

    def test_column_calc_with_an_unparseable_expression_keeps_the_table(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'column_calc', {'new_col': '坏', 'expr': '序号 @@ 2'})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == len(CLEAN_RECORDS)
        assert '坏' not in rows[0], 'a failed expression must not add an all-null column'

    def test_bin_column_with_a_bucket_count(self, client, app_module, paste):
        _run, status, rows = self._run(
            client, app_module, paste, 'bin_column', {'column': '序号', 'bins': '2', 'bin_new_col': '档'}
        )
        assert status['status'] == 'done', status.get('error')
        assert len({row['档'] for row in rows}) == 2

    def test_bin_column_with_explicit_edges_and_labels(self, client, app_module, paste):
        _run, status, rows = self._run(
            client,
            app_module,
            paste,
            'bin_column',
            {'column': '序号', 'bins': '0,2,4,6', 'bin_labels': '低,中,高', 'bin_new_col': '档'},
        )
        assert status['status'] == 'done', status.get('error')
        assert [row['档'] for row in rows] == ['中', '高', '低', '中', '中'], '0-2 / 2-4 / 4-6 by 序号'

    def test_unknown_operation_on_an_analysis_node_fails_the_node(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, 'flatten_strings', {})
        assert status['status'] == 'failed', status
        assert 'flatten_strings' in (status.get('error') or '')
        assert rows == [], 'a refused op must not export an empty table as if it were the answer'

    def test_a_step_pipeline_runs_in_order(self, client, app_module, paste):
        ds = paste(CLEAN_RECORDS, name='matrix.csv')
        steps = [
            {'op': 'drop_duplicates', 'params': {'columns': ['名称']}},
            {'op': 'filter_rows', 'params': {'column': '城市', 'op': 'not_null', 'value': ''}},
            {'op': 'sort_rows', 'params': {'column': '序号', 'ascending': False}},
        ]
        chain = [
            _node('node-1', 'upload', {'dataset_id': ds, 'row_count': len(CLEAN_RECORDS)}),
            _node('node-target', 'analysis', {'steps': steps}),
        ]
        started = client.post(
            '/api/workflow/execute',
            json={'workflow': _wf(chain, [{'from': 'node-1', 'to': 'node-target'}]), 'workflow_name': 'matrix'},
        )
        assert started.status_code == 200, started.get_json()
        assert _wait(app_module), 'the run never finished'
        rows = app_module._RUN_STORE.load_rows(started.get_json()['run_id'], 'node-target')
        # Dedupe keeps one 丁, then the empty-cell 乙 is filtered out — 5 rows in,
        # three out, in descending 序号 order.
        assert [row['序号'] for row in rows] == [4, 3, 1]


class TestTokenizeNodeModes:
    """The three output shapes, and what a `0` in 最大词数 actually means.

    The panel labels the field "留空=全部词", so the empty string is the only
    spelling of "no limit"; a typed number is a real limit. That distinction is
    what these tests hold, because the field arrives as a string either way.
    """

    WORDS = ['三亚的海滩很美 三亚的海', '海口骑楼老街 海口很好', '三亚的海滩 三亚阳光', '广州的早茶很好喝']

    def _run(self, client, app_module, paste, params):
        records = [{'正文': text} for text in self.WORDS]
        return _run_node(
            client,
            app_module,
            paste,
            'tokenize',
            {'text_column': '正文', **params},
            records=records,
        )

    def test_word_freq_is_a_labelled_frequency_table(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, {'output_mode': 'word_freq'})
        assert status['status'] == 'done', status.get('error')
        assert {'word', 'frequency'} <= set(rows[0])
        # 三亚 and 海 appear in three of the four posts, so they must outrank one-offs.
        assert rows[0]['frequency'] >= rows[-1]['frequency'], 'sorted by frequency'

    def test_word_freq_honours_a_top_n(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, {'output_mode': 'word_freq', 'top_n': '2'})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == 2

    def test_zero_is_clamped_to_one_word_rather_than_meaning_all(self, client, app_module, paste):
        """The field's own placeholder says "留空=全部词" — blank is the only way to
        ask for everything. A 0 is below the usable range, so it reads as the
        smallest legal request: the single top word, not the whole dictionary.
        """
        _run, status, rows = self._run(client, app_module, paste, {'output_mode': 'word_freq', 'top_n': '0'})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == 1, 'a 0 must not silently mean "no limit", nor drop every word'

    def test_blank_is_the_all_words_reading(self, client, app_module, paste):
        _run, status, blank = self._run(client, app_module, paste, {'output_mode': 'word_freq', 'top_n': ''})
        assert status['status'] == 'done', status.get('error')
        _run, status, limited = self._run(client, app_module, paste, {'output_mode': 'word_freq', 'top_n': '3'})
        assert len(blank) > len(limited) == 3, 'blank is the wider answer the placeholder promises'

    def test_words_only_drops_the_counts(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, {'output_mode': 'words_only'})
        assert status['status'] == 'done', status.get('error')
        assert set(rows[0]) == {'word'}, 'no frequency column, for a downstream that only needs tokens'

    def test_csv_line_collapses_every_word_into_one_cell(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, {'output_mode': 'csv_line'})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == 1
        assert set(rows[0]) == {'words'}
        assert ' ' in rows[0]['words'], 'space-joined so a text miner can read it as one document'

    def test_a_garbage_top_n_falls_back_instead_of_failing(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, {'output_mode': 'word_freq', 'top_n': 'abc'})
        assert status['status'] == 'done', status.get('error')
        assert rows, 'unparseable text is the panel default (120 words), not an error'


RICH_RECORDS = [
    {'city': '三亚', 'district': '海棠区', 'likes': 10, 'text': '三亚的海滩很美'},
    {'city': '三亚', 'district': '天涯区', 'likes': 4, 'text': '海风和阳光都不错'},
    {'city': '海口', 'district': '海棠区', 'likes': 7, 'text': '骑楼老街值得逛'},
    {'city': '海口', 'district': '龙华区', 'likes': 2, 'text': '海口早茶很好吃'},
]


def _run_chart(client, app_module, paste, params, records=None):
    """upload → visualize, answered with the chart spec the run produced.

    A visualize node has no rows — its output is a spec dict that only reaches
    the browser through ``chart_results`` — so the row store cannot confirm it.
    """
    body = records or RICH_RECORDS
    ds = paste(body, name='chart.csv')
    chain = [
        _node('node-1', 'upload', {'dataset_id': ds, 'row_count': len(body)}),
        _node('node-target', 'visualize', params),
    ]
    started = client.post(
        '/api/workflow/execute',
        json={
            'workflow': _wf(chain, [{'from': 'node-1', 'to': 'node-target'}]),
            'workflow_name': 'chart',
        },
    )
    assert started.status_code == 200, started.get_json()
    assert _wait(app_module), 'the run never finished'
    run_id = started.get_json()['run_id']
    status = app_module._RUN_STORE.node_statuses(run_id).get('node-target', {})
    # `chart_results` is the status payload's filtered view: a refused chart must
    # be absent from it, which is what keeps a broken spec off the canvas.
    spec = client.get('/api/workflow/status').get_json()['chart_results'].get('node-target')
    return status, spec


class TestVisualizeNodeChartTypes:
    """The node path, which the endpoint tests do not cover.

    The node builds its own kwargs (`tokenize` is coerced, `wordcloud_style` is
    only forwarded when non-empty, `agg` defaults to sum) and its refusal has to
    settle the node *failed* rather than hand downstream a half spec.
    """

    @pytest.mark.parametrize(
        'params, series_type',
        [
            ({'chart_type': 'bar', 'x_field': 'city', 'y_field': 'likes'}, 'bar'),
            ({'chart_type': 'line', 'x_field': 'city', 'y_field': 'likes'}, 'line'),
            ({'chart_type': 'pie', 'x_field': 'city'}, 'pie'),
            ({'chart_type': 'scatter', 'x_field': 'city', 'y_field': 'likes'}, 'scatter'),
            ({'chart_type': 'box', 'x_field': 'city', 'y_field': 'likes'}, 'boxplot'),
            ({'chart_type': 'heatmap', 'x_field': 'city', 'y_field': 'district', 'value_field': 'likes'}, 'heatmap'),
            ({'chart_type': 'sankey', 'x_field': 'city', 'y_field': 'district', 'value_field': 'likes'}, 'sankey'),
            ({'chart_type': 'map', 'x_field': 'city', 'value_field': 'likes'}, 'map'),
            ({'chart_type': 'wordcloud', 'x_field': 'city', 'value_field': 'likes'}, 'wordCloud'),
        ],
    )
    def test_every_chart_type_the_panel_offers_reaches_the_browser(
        self, client, app_module, paste, params, series_type
    ):
        status, spec = _run_chart(client, app_module, paste, params)
        assert status['status'] == 'done', status.get('error')
        assert spec and spec['engine'] == 'echarts', spec
        assert spec['option']['series'][0]['type'] == series_type, params

    def test_a_title_reaches_the_spec(self, client, app_module, paste):
        _status, spec = _run_chart(
            client, app_module, paste, {'chart_type': 'bar', 'x_field': 'city', 'y_field': 'likes', 'title': '按城市'}
        )
        assert spec['option']['title']['text'] == '按城市'

    def test_the_average_aggregation_differs_from_the_sum(self, client, app_module, paste):
        _s, total = _run_chart(
            client,
            app_module,
            paste,
            {'chart_type': 'bar', 'x_field': 'district', 'y_field': 'likes', 'agg': 'sum'},
        )
        _s, mean = _run_chart(
            client,
            app_module,
            paste,
            {'chart_type': 'bar', 'x_field': 'district', 'y_field': 'likes', 'agg': 'mean'},
        )
        assert total['option']['series'][0]['data'] != mean['option']['series'][0]['data']

    def test_tokenize_turns_a_text_column_into_words(self, client, app_module, paste):
        _s, spec = _run_chart(
            client, app_module, paste, {'chart_type': 'wordcloud', 'x_field': 'text', 'tokenize': True}
        )
        names = {entry['name'] for entry in spec['option']['series'][0]['data']}
        assert 'city' not in names and 'district' not in names
        assert len(names) > len({record['city'] for record in RICH_RECORDS}), 'segmented, not label-counted'

    def test_a_wordcloud_style_adds_per_word_colours(self, client, app_module, paste):
        _s, plain = _run_chart(
            client, app_module, paste, {'chart_type': 'wordcloud', 'x_field': 'city', 'value_field': 'likes'}
        )
        _s, styled = _run_chart(
            client,
            app_module,
            paste,
            {'chart_type': 'wordcloud', 'x_field': 'city', 'value_field': 'likes', 'wordcloud_style': 'vibrant'},
        )
        assert len(plain['option']['series'][0]['data']) == len(styled['option']['series'][0]['data'])

    def test_the_matplotlib_engine_returns_an_image_not_a_spec(self, client, app_module, paste):
        status, spec = _run_chart(
            client,
            app_module,
            paste,
            {'chart_type': 'bar', 'x_field': 'city', 'y_field': 'likes', 'engine': 'matplotlib'},
        )
        assert status['status'] == 'done', status.get('error')
        assert spec['engine'] == 'matplotlib'
        assert spec['image'].startswith('data:image/png;base64,')

    def test_a_field_that_is_not_there_fails_the_node_with_the_name(self, client, app_module, paste):
        status, spec = _run_chart(client, app_module, paste, {'chart_type': 'bar', 'x_field': '不存在'})
        assert status['status'] == 'failed', status
        assert '不存在' in (status.get('error') or '')
        assert spec is None, 'a refused chart must not surface in chart_results'


class _ReplayCrawler:
    """A crawler whose result never changes, so the only thing a second run can
    react to is the row ledger."""

    rows = [{'标题': 'a'}, {'标题': 'b'}, {'标题': 'c'}]

    def __init__(self, *args, **kwargs):
        self._sink = None

    def set_sink(self, sink):
        self._sink = sink

    def set_cursor_sink(self, sink):
        pass

    def seed(self, saved):
        pass

    def close(self):
        pass

    def search(self, *args, **kwargs):
        kept = []
        for item in type(self).rows:
            if self._sink is None or self._sink(item):
                kept.append(item)
        return kept


def _source_workflow(params):
    return _wf([_node('node-1', 'source', params)], [])


class TestSourceNodeRecrawl:
    """重新采集 is the escape hatch for "the platform changed, crawl it again".

    Without it a second run of the same workflow collects nothing, because the
    ledger's whole job is to refuse rows already paid for — which is correct and
    also confusing unless the checkbox exists.
    """

    def _run(self, client, app_module, monkeypatch, params):
        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _ReplayCrawler())
        started = client.post(
            '/api/workflow/execute',
            json={'workflow': _source_workflow(params), 'workflow_name': 'recrawl'},
        )
        assert started.status_code == 200, started.get_json()
        assert _wait(app_module), 'the run never finished'
        run_id = started.get_json()['run_id']
        return run_id, app_module._RUN_STORE.load_rows(run_id, 'node-1')

    def test_a_second_run_of_the_same_workflow_collects_nothing(self, client, app_module, monkeypatch):
        params = {'platform': 'zhihu', 'keyword': '三亚', 'target_count': 3}
        _first, first_rows = self._run(client, app_module, monkeypatch, params)
        assert len(first_rows) == 3
        _second, second_rows = self._run(client, app_module, monkeypatch, params)
        assert second_rows == [], 'the ledger must refuse the three rows it already holds'

    def test_recrawl_releases_the_ledger_for_this_node_only(self, client, app_module, monkeypatch):
        plain = {'platform': 'zhihu', 'keyword': '三亚', 'target_count': 3}
        _first, _rows = self._run(client, app_module, monkeypatch, plain)
        run_id, rows = self._run(client, app_module, monkeypatch, {**plain, 'recrawl': True})
        assert len(rows) == 3, 'the checkbox means "collect again"'
        blob = '\n'.join(client.get('/api/workflow/status').get_json()['logs'])
        assert 'recrawl' in blob.lower() or '重新采集' in blob, blob
        # The release is scoped to this node: a second 重新采集 run of a workflow
        # whose other nodes have their own history must not wipe theirs.
        assert app_module._RUN_STORE.row_count(run_id, 'node-1') == 3


class TestCommentNodeFilesAndLimits:
    """The 评论 node's own knobs: how many comments per article, and how the
    result is split across files on disk.

    Neither had reached a test: ``per_article_file`` appears in the executor and
    in the node default and nowhere else, and ``comment_limit``'s ``0`` is the
    one value that means "everything" rather than "nothing".
    """

    class _FakeCrawler:
        driver = None

        def close(self):
            pass

    def _install(self, app_module, monkeypatch, session_class):
        import crawlers.comments as comments_module

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: self._FakeCrawler())
        monkeypatch.setattr(comments_module, 'CommentSession', session_class)

    def _run(self, client, app_module, params, session_class, name='cmt'):
        started = client.post(
            '/api/workflow/execute',
            json={'workflow': _wf([_node('node-1', 'comment', params)], []), 'workflow_name': name},
        )
        assert started.status_code == 200, started.get_json()
        assert _wait(app_module), 'the run never finished'
        return started.get_json()['run_id']

    @staticmethod
    def _two_url_session():
        class _Session:
            seen = []

            def __init__(self, driver, log=None):
                pass

            def crawl_zhihu(self, url, limit):
                type(self).seen.append((url, limit))
                return [{'文章URL': url, '评论内容': f'{url}-1'}, {'文章URL': url, '评论内容': f'{url}-2'}], 'ok'

        return _Session

    def test_the_limit_is_handed_to_the_engine_untouched(self, client, app_module, monkeypatch):
        session = self._two_url_session()
        self._install(app_module, monkeypatch, session)
        urls = 'https://www.zhihu.com/question/1/answer/1\nhttps://www.zhihu.com/question/2/answer/2'
        self._run(
            client,
            app_module,
            {'platform': 'zhihu', 'urls': urls, 'comment_limit': '0'},
            session,
            name='cmt-zero',
        )
        assert [limit for _url, limit in session.seen] == [0, 0], '0 means "every comment", not "none"'

    def test_a_typed_limit_reaches_the_engine_as_a_number(self, client, app_module, monkeypatch):
        session = self._two_url_session()
        self._install(app_module, monkeypatch, session)
        urls = 'https://www.zhihu.com/question/1/answer/1'
        self._run(client, app_module, {'urls': urls, 'comment_limit': '5'}, session, name='cmt-five')
        assert session.seen == [('https://www.zhihu.com/question/1/answer/1', 5)]

    @pytest.mark.parametrize('raw', ['-3', 'abc', ''])
    def test_an_unusable_limit_becomes_no_limit_not_a_negative_fetch(self, client, app_module, monkeypatch, raw):
        session = self._two_url_session()
        self._install(app_module, monkeypatch, session)
        self._run(
            client, app_module, {'urls': 'https://www.zhihu.com/question/1/answer/1', 'comment_limit': raw}, session
        )
        assert session.seen[0][1] == 0, f'comment_limit={raw!r} must not be handed over as a negative'

    @staticmethod
    def _merged(export_dir, prefix):
        """Final merged files only — the ``.partNNN`` pieces are kept on disk by
        design (``keep_parts`` defaults to on) and are not the answer here."""
        names = sorted(path.name for path in export_dir.glob(f'{prefix}*.csv'))
        return [name for name in names if '.part' not in name]

    def test_per_article_file_writes_one_file_per_article(self, client, app_module, monkeypatch, data_root):
        session = self._two_url_session()
        self._install(app_module, monkeypatch, session)
        urls = 'https://www.zhihu.com/question/1/answer/1\nhttps://www.zhihu.com/question/2/answer/2'
        run_id = self._run(
            client,
            app_module,
            {'urls': urls, 'per_article_file': True, 'part_size': 1},
            session,
            name='cmt-per-article',
        )
        assert len(app_module._RUN_STORE.load_rows(run_id, 'node-1')) == 4
        merged = self._merged(data_root / 'data' / 'exports', 'cmt-per-article')
        assert len(merged) == 2, merged
        assert {name.rsplit('-', 1)[-1] for name in merged} == {'01.csv', '02.csv'}, merged

    def test_without_the_checkbox_one_file_holds_every_article(self, client, app_module, monkeypatch, data_root):
        session = self._two_url_session()
        self._install(app_module, monkeypatch, session)
        urls = 'https://www.zhihu.com/question/1/answer/1\nhttps://www.zhihu.com/question/2/answer/2'
        self._run(
            client,
            app_module,
            {'urls': urls, 'per_article_file': False, 'part_size': 1},
            session,
            name='cmt-one-file',
        )
        merged = self._merged(data_root / 'data' / 'exports', 'cmt-one-file')
        assert len(merged) == 1, merged


class TestOutputNodeOperations:
    """The 输出 node passes its input through, and only writes for the formats
    it knows. A Save node that silently wrote nothing would be the worst kind of
    failure: the run is green and the file the user went to open does not exist.
    """

    def _run(self, client, app_module, paste, params, operation='save'):
        return _run_node(client, app_module, paste, 'output', params, operation, records=RICH_RECORDS)

    @pytest.mark.parametrize('fmt', sorted(DataExporter.SUPPORTED_FORMATS))
    def test_every_supported_format_lands_a_file(self, client, app_module, paste, data_root, fmt):
        _run, status, rows = self._run(client, app_module, paste, {'format': fmt, 'filename': 'matrix-out'})
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == len(RICH_RECORDS), 'the node passes its input downstream'
        written = sorted(path.name for path in (data_root / 'data' / 'exports').glob('matrix-out*'))
        assert written, f'{fmt} produced no file'

    def test_the_format_is_taken_from_the_extension_when_left_out(self, client, app_module, paste, data_root):
        _run, status, _rows = self._run(client, app_module, paste, {'filename': 'matrix-inferred.xlsx', 'format': ''})
        assert status['status'] == 'done', status.get('error')
        assert (data_root / 'data' / 'exports' / 'matrix-inferred.xlsx').exists()

    def test_an_unwritable_format_fails_the_node_rather_than_passing_quietly(
        self, client, app_module, paste, data_root
    ):
        _run, status, rows = self._run(client, app_module, paste, {'format': 'parquet', 'filename': 'matrix-bad'})
        assert status['status'] == 'failed', status
        assert rows == [], 'a node that refused to write must not hand on rows as if it had saved them'
        assert not list((data_root / 'data' / 'exports').glob('matrix-bad*'))

    def test_the_legacy_save_csv_alias_still_writes_a_csv(self, client, app_module, paste, data_root):
        _run, status, _rows = _run_node(
            client,
            app_module,
            paste,
            'output',
            {'filename': 'matrix-legacy'},
            'save_csv',
            records=RICH_RECORDS,
        )
        assert status['status'] == 'done', status.get('error')
        assert (data_root / 'data' / 'exports' / 'matrix-legacy.csv').exists()

    def test_a_name_that_is_not_a_file_is_cleaned_not_followed(self, client, app_module, paste, data_root):
        _run, status, _rows = self._run(client, app_module, paste, {'format': 'csv', 'filename': '../../escape'})
        assert status['status'] == 'done', status.get('error')
        written = sorted(path.name for path in (data_root / 'data' / 'exports').iterdir())
        assert written and all(not name.startswith('..') and '/' not in name for name in written), written
        assert not (data_root / 'escape.csv').exists(), 'the export directory must not be escapable'

    def test_an_operation_it_does_not_own_is_a_passthrough(self, client, app_module, paste):
        _run, status, rows = self._run(client, app_module, paste, {'filename': 'matrix-none'}, 'archive')
        assert status['status'] == 'done', status.get('error')
        assert len(rows) == len(RICH_RECORDS), 'an unknown op must still not lose the table'
