"""Tests for the stats, history and execution-metric endpoints.

``/api/stats/*`` reads the *in-memory* results of the run that just finished,
which is why they are testable at all: a test can put a node's output into
``execution_state['results']`` and ask the server what it would chart. What
matters is that an empty or half-finished run answers with an empty shape
rather than a stack trace — the console polls these every second while a
workflow is still going.

``/api/history/*`` is the durable counterpart, kept in a separate SQLite file.
The session harness points it at the tmp dir, and the first test here is the
guard that proves it, because ``ExecutionHistoryService`` builds its path at
import time from ``Config.DATA_DIR``.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.api


def _emotion_rows():
    return [
        {'title': 'a', 'emotion': 'Positive'},
        {'title': 'b', 'emotion': 'Negative'},
        {'title': 'c', 'emotion': 'Positive'},
        {'title': 'd', 'emotion': None},
        {'title': 'e'},
    ]


class TestStatsEndpoints:
    def test_emotion_and_tendency_answer_an_empty_shape_before_any_run(self, client):
        for path in ('/api/stats/emotion', '/api/stats/tendency'):
            body = client.get(path).get_json()
            assert body == {'ok': True, 'stats': {'labels': [], 'values': []}}

    def test_summary_is_empty_while_nothing_has_run(self, client):
        assert client.get('/api/stats/summary').get_json() == {'ok': True, 'summary': {}}

    def test_emotion_counts_labels_and_ignores_missing_ones(self, client, app_module):
        app_module.execution_state['results'] = {'node-1': _emotion_rows()}
        stats = client.get('/api/stats/emotion').get_json()['stats']
        # First-seen label order, and the two rows without a usable emotion are
        # simply not counted.
        assert stats['labels'] == ['Positive', 'Negative']
        assert stats['values'] == [2, 1]

    def test_each_stat_reads_only_its_own_column(self, client, app_module):
        app_module.execution_state['results'] = {
            'node-1': [{'title': 'a', 'tendency': 'Positive'}, {'title': 'b', 'emotion': 'Negative'}],
            'node-2': [{'title': 'c', 'tendency': 'Negative'}],
        }
        tendency = client.get('/api/stats/tendency').get_json()['stats']
        assert tendency['labels'] == ['Positive', 'Negative']
        assert tendency['values'] == [1, 1]
        # The other column's single row is picked up by its own endpoint and by
        # nothing else, whichever node it was filed against.
        assert client.get('/api/stats/emotion').get_json()['stats'] == {'labels': ['Negative'], 'values': [1]}

    def test_summary_counts_rows_per_node_and_skips_non_tables(self, client, app_module):
        app_module.execution_state['results'] = {
            'node-1': [{'title': 'a'}, {'title': 'b'}],
            'node-2': [],
            'chart': {'engine': 'echarts', 'option': {'series': []}},
        }
        summary = client.get('/api/stats/summary').get_json()['summary']
        assert summary == {'node-1': {'count': 2, 'sample_keys': ['title']}}

    def test_an_interrupted_run_leaves_the_stats_endpoints_answering(self, client, app_module):
        """Partly filled results must not break the console's polling loop."""
        app_module.execution_state['results'] = {'node-1': None, 'node-2': 'not a table'}
        assert client.get('/api/stats/emotion').get_json()['stats'] == {'labels': [], 'values': []}
        assert client.get('/api/stats/summary').get_json()['summary'] == {}


class TestHistoryEndpoints:
    @pytest.fixture
    def recorded(self, client, app_module, data_root):
        """File a handful of metric rows under a name no other test uses."""

        def _record(workflow_name, rows):
            assert Path(app_module.history_service.db_path) == data_root / 'data' / 'history.db'
            stamp = app_module.history_service.now()
            app_module.history_service.record_many(
                [
                    (f'hist-{workflow_name}', workflow_name, nid, ntype, metric, label, value, stamp)
                    for nid, ntype, metric, label, value in rows
                ]
            )
            return workflow_name

        return _record

    def test_the_import_time_history_service_is_the_tmp_one(self, app_module, data_root):
        """``history_service`` is built while ``app`` is imported, so this is the
        one path a test could silently write into the real repository."""
        assert Path(app_module.history_service.db_path) == data_root / 'data' / 'history.db'

    def test_runs_are_grouped_per_execution_with_workflow_names(self, client, recorded):
        rows = [('node-1', 'upload', 'rows', 'count', 6), ('node-2', 'analysis', 'rows', 'count', 4)]
        name = recorded('hist-panel', rows)
        body = client.get('/api/history/runs', query_string={'limit': 50}).get_json()
        mine = [run for run in body['runs'] if run['workflow_name'] == name]
        assert len(mine) == 1
        assert mine[0]['metric_count'] == 2
        assert set(mine[0]) == {'run_id', 'workflow_name', 'started_at', 'metric_count'}
        assert name in body['workflow_names']

    def test_series_can_be_filtered_by_metric_and_node(self, client, recorded):
        name = recorded(
            'hist-filters',
            [
                ('node-1', 'upload', 'rows', 'count', 6),
                ('node-2', 'process', 'emotion', 'Positive', 4),
                ('node-2', 'process', 'emotion', 'Negative', 2),
            ],
        )
        everything = client.get('/api/history/series', query_string={'workflow_name': name}).get_json()['rows']
        assert len(everything) == 3
        emotions = client.get(
            '/api/history/series', query_string={'workflow_name': name, 'metric': 'emotion'}
        ).get_json()['rows']
        assert {row['label'] for row in emotions} == {'Positive', 'Negative'}
        by_node = client.get(
            '/api/history/series', query_string={'workflow_name': name, 'node_id': 'node-2'}
        ).get_json()['rows']
        assert len(by_node) == 2
        # An unknown name filters everything out rather than falling back.
        other = client.get('/api/history/series', query_string={'workflow_name': 'no-such-wf'}).get_json()
        assert other == {'ok': True, 'rows': []}

    def test_limit_bounds_the_page_not_the_whole_store(self, client, recorded):
        name = recorded('hist-limit', [(f'node-{i}', 'upload', 'rows', 'count', float(i)) for i in range(5)])
        capped = client.get('/api/history/runs', query_string={'limit': 1}).get_json()
        assert len(capped['runs']) == 1
        # The name list is not paginated, so it still knows about the run.
        assert name in capped['workflow_names']

    def test_clear_empties_the_history_panel(self, client, recorded):
        name = recorded('hist-clear', [('node-1', 'upload', 'rows', 'count', 1)])
        assert client.get('/api/history/runs').get_json()['runs'] != []
        assert client.post('/api/history/clear').get_json() == {'ok': True, 'message': 'History cleared'}
        body = client.get('/api/history/runs').get_json()
        assert body['runs'] == []
        assert body['workflow_names'] == []
        assert name not in body['workflow_names']

    # ``series()`` de-duplicates identical points at read time to clean up rows
    # Read-time dedupe of legacy duplicate rows must key on node_id too, or
    # two *different* nodes that reported the same metric, label, value and
    # second collapse into one point and the history panel loses a line.
    def test_two_nodes_reporting_the_same_number_both_survive(self, client, recorded):
        name = recorded(
            'hist-two-nodes',
            [('node-2', 'analysis', 'rows', 'count', 4.0), ('node-3', 'output', 'rows', 'count', 4.0)],
        )
        stored = client.get('/api/history/runs', query_string={'limit': 50}).get_json()['runs']
        assert [run['metric_count'] for run in stored if run['workflow_name'] == name] == [2]
        rows = client.get('/api/history/series', query_string={'workflow_name': name}).get_json()['rows']
        assert {row['node_id'] for row in rows} == {'node-2', 'node-3'}
