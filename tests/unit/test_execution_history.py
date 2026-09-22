"""Tests for services/execution_history.py — the cross-run metrics ledger.

This table is what powers "how has the emotion mix moved over the last two
weeks", so the pinned behaviour is about *queryability*: an 8-tuple per metric
row, runs newest-first, series oldest-first, and read-time de-duplication that
cleans rows written before the recorder learned to dedupe — without ever
needing a migration.

Every test gets its own SQLite file: the default path is the real
``data/history.db``.
"""

import os

import pytest

from services.execution_history import ExecutionHistoryService as History

pytestmark = pytest.mark.unit

COLUMNS = ['id', 'run_id', 'workflow_name', 'node_id', 'node_type', 'metric', 'label', 'value', 'timestamp']


def _row(run_id, workflow, node, metric, label, value, timestamp, node_type='analysis'):
    return (run_id, workflow, node, node_type, metric, label, value, timestamp)


@pytest.fixture
def history(tmp_path):
    return History(db_path=str(tmp_path / 'history.db'))


@pytest.fixture
def recorded(history):
    history.record_many(
        [
            _row('r1', '周报', 'node-1', 'emotion', 'Joy', 3.0, '2024-05-01T10:00:00'),
            _row('r1', '周报', 'node-1', 'emotion', 'Sadness', 1.0, '2024-05-01T10:00:00'),
            _row('r1', '周报', 'node-2', 'rows', '', 12.0, '2024-05-01T10:05:00', node_type='output'),
            _row('r2', '周报', 'node-1', 'emotion', 'Joy', 5.0, '2024-05-08T09:00:00'),
            _row('r3', '月报', 'node-1', 'tendency', 'Positive', 2.0, '2024-05-09T09:00:00'),
        ]
    )
    return history


class TestRecording:
    def test_the_table_is_created_on_construction(self, history):
        assert history.list_runs().empty
        assert history.series().columns.tolist() == COLUMNS

    def test_tuples_land_verbatim(self, history):
        history.record_many([_row('rA', 'wf', 'n1', 'emotion', 'Joy', 2.0, '2024-01-01T00:00:00')])
        row = history.series().iloc[0]
        assert (row['run_id'], row['workflow_name'], row['metric'], row['label'], row['value']) == (
            'rA',
            'wf',
            'emotion',
            'Joy',
            2.0,
        )

    def test_an_empty_batch_is_a_no_op(self, history):
        history.record_many([])
        assert history.series().empty

    def test_a_second_instance_sees_the_same_file(self, history, tmp_path):
        history.record_many([_row('r1', 'wf', 'n1', 'rows', '', 4.0, '2024-02-02T00:00:00')])
        assert len(History(db_path=str(tmp_path / 'history.db')).series()) == 1


class TestListingRuns:
    def test_runs_are_grouped_with_their_earliest_timestamp(self, recorded):
        runs = recorded.list_runs().to_dict('records')
        assert [r['run_id'] for r in runs] == ['r3', 'r2', 'r1']
        assert runs[-1]['started_at'] == '2024-05-01T10:00:00'
        assert runs[-1]['metric_count'] == 3

    def test_limit_caps_the_page(self, recorded):
        assert len(recorded.list_runs(limit=2)) == 2

    def test_the_same_run_under_two_names_stays_distinct(self, history):
        history.record_many(
            [
                _row('r1', 'wf-a', 'n1', 'rows', '', 1.0, '2024-01-01T00:00:00'),
                _row('r1', 'wf-b', 'n1', 'rows', '', 2.0, '2024-01-01T00:00:00'),
            ]
        )
        assert len(history.list_runs()) == 2

    def test_workflow_names_are_distinct_and_sorted(self, recorded):
        assert recorded.list_workflow_names() == sorted(['周报', '月报'])

    def test_runs_without_a_name_are_not_listed_as_names(self, history):
        history.record_many([_row('r1', None, 'n1', 'rows', '', 1.0, '2024-01-01T00:00:00')])
        assert history.list_workflow_names() == []
        assert len(history.list_runs()) == 1


class TestSeries:
    def test_series_is_chronological(self, recorded):
        points = recorded.series(metric='emotion')['timestamp'].tolist()
        assert points == sorted(points)

    @pytest.mark.parametrize(
        'kwargs, expected',
        [
            ({'workflow_name': '周报'}, 4),
            ({'metric': 'emotion'}, 3),
            ({'node_id': 'node-2'}, 1),
            ({'workflow_name': '周报', 'metric': 'emotion'}, 3),
            ({'metric': 'nope'}, 0),
            ({'workflow_name': 'nope'}, 0),
        ],
    )
    def test_filters_narrow_the_series(self, recorded, kwargs, expected):
        assert len(recorded.series(**kwargs)) == expected

    def test_limit_applies_after_ordering(self, recorded):
        assert len(recorded.series(limit=2)) == 2

    def test_exact_duplicates_from_older_writers_are_folded_at_read_time(self, history):
        row = _row('r1', 'wf', 'node-9', 'emotion', 'Joy', 3.0, '2024-03-01T00:00:00')
        history.record_many([row, tuple(row)])
        assert len(history.series()) == 1

    def test_genuinely_different_points_are_kept(self, history):
        history.record_many(
            [
                _row('r1', 'wf', 'n1', 'emotion', 'Joy', 3.0, '2024-03-01T00:00:00'),
                _row('r1', 'wf', 'n1', 'emotion', 'Joy', 4.0, '2024-03-01T00:00:00'),
            ]
        )
        assert len(history.series()) == 2

    def test_node_identity_survives_a_filter(self, recorded):
        rows = recorded.series(node_id='node-1', metric='emotion')
        assert set(rows['node_id']) == {'node-1'}
        assert set(rows['node_type']) == {'analysis'}


class TestClearing:
    def test_clear_empties_the_ledger_but_keeps_the_table(self, recorded):
        recorded.clear()
        assert recorded.series().empty
        assert recorded.list_runs().empty
        assert recorded.list_workflow_names() == []
        recorded.record_many([_row('r9', 'wf', 'n1', 'rows', '', 1.0, '2024-04-01T00:00:00')])
        assert len(recorded.series()) == 1

    def test_now_is_a_sortable_timestamp(self, history):
        stamp = history.now()
        assert len(stamp) == 19 and stamp[4] == '-' and stamp[10] == 'T'


class TestTheFileMayBeDeleted:
    """``history.db`` is a file the user is entitled to remove.

    The schema used to be created once, when the module was imported, so deleting
    it left every history endpoint raising ``no such table: execution_history``
    for the rest of the process — a permanently broken 历史 panel with no
    explanation, curable only by restarting the server.
    """

    def test_a_deleted_database_is_recreated_on_the_next_read(self, history, tmp_path):
        history.record_many([_row('r1', 'wf', 'n1', 'rows', '', 5.0, '2024-01-01T00:00:00')])
        assert len(history.list_runs()) == 1
        os.remove(history.db_path)
        assert len(history.list_runs()) == 0
        assert len(history.series()) == 0
        assert history.list_workflow_names() == []

    def test_a_deleted_database_still_accepts_writes(self, history):
        os.remove(history.db_path)
        history.record_many([_row('r2', 'wf', 'n1', 'rows', '', 7.0, '2024-01-02T00:00:00')])
        assert len(history.list_runs()) == 1

    def test_a_never_seen_database_answers_rather_than_raising(self, tmp_path):
        fresh = History(db_path=str(tmp_path / 'brand-new' / 'history.db'))
        assert len(fresh.list_runs()) == 0 and len(fresh.series()) == 0
