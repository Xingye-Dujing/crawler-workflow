"""Projects, captures and the snapshot diff — the durable half of Phase 3.

The diff is the part worth pinning: it is the answer to "did my corpus change, or did I change
the knobs?", and every way of getting it wrong reads as a finding. So each case states what moved
between two captures and asserts the diff says exactly that — including the sections that are
empty, because a diff that reports no parameter change when one happened is the dangerous kind of
quiet.
"""

import pytest

from services.biblio.store import DIFF_LIMIT, BiblioStore, compare_snapshots

pytestmark = pytest.mark.unit


def _snapshot(nodes, edges, params=None, shape='nodes', project_id='p1', label=''):
    return {
        'project_id': project_id,
        'label': label,
        'shape': shape,
        'params': params or {},
        'nodes': nodes,
        'edges': edges,
    }


class TestCompare:
    def test_a_node_that_grew_is_reported_as_changed_not_as_added(self):
        diff = compare_snapshots(
            _snapshot([{'节点': '甲', '频次': 3}], []),
            _snapshot([{'节点': '甲', '频次': 9}], []),
        )
        assert diff['nodes']['added']['total'] == 0
        assert diff['nodes']['removed']['total'] == 0
        assert diff['nodes']['changed']['items'] == [{'name': '甲', 'columns': {'频次': {'a': 3, 'b': 9}}}]

    def test_nodes_that_appear_and_vanish_are_listed_both_ways(self):
        diff = compare_snapshots(
            _snapshot([{'节点': '甲', '频次': 3}], []),
            _snapshot([{'节点': '乙', '频次': 4}], []),
        )
        assert diff['nodes']['added']['items'] == ['乙']
        assert diff['nodes']['removed']['items'] == ['甲']
        assert diff['nodes']['common'] == 0

    def test_an_undirected_edge_is_the_same_edge_whatever_order_the_rows_came_in(self):
        """A node table lists every link from BOTH ends. Comparing the raw rows would report a
        weight change on every edge that merely arrived in the other direction."""
        left = compare_snapshots(
            _snapshot([], [{'source': '甲', 'target': '乙', 'weight': 2.0, 'count': 1}]),
            _snapshot([], [{'source': '乙', 'target': '甲', 'weight': 2.0, 'count': 1}]),
        )
        assert left['edges']['added']['total'] == 0
        assert left['edges']['removed']['total'] == 0
        assert left['edges']['weight_changed']['total'] == 0

    def test_a_weight_change_reports_both_numbers(self):
        diff = compare_snapshots(
            _snapshot([], [{'source': '甲', 'target': '乙', 'weight': 2.0, 'count': 1}]),
            _snapshot([], [{'source': '甲', 'target': '乙', 'weight': 5.0, 'count': 3}]),
        )
        # The pair is reported in canonical order (an undirected edge has no first endpoint) —
        # 乙 before 甲 is code-point order, not the row's own order.
        assert diff['edges']['weight_changed']['items'] == [{'source': '乙', 'target': '甲', 'a': 2.0, 'b': 5.0}]

    def test_a_reclustered_corpus_names_the_cluster_that_changed_label_and_size(self):
        diff = compare_snapshots(
            _snapshot(
                [{'节点': '甲', '聚类': '0', '聚类标签': '旧名'}, {'节点': '乙', '聚类': '0', '聚类标签': '旧名'}],
                [],
            ),
            _snapshot(
                [{'节点': '甲', '聚类': '0', '聚类标签': '新名'}, {'节点': '丙', '聚类': '0', '聚类标签': '新名'}],
                [],
            ),
        )
        assert diff['clusters']['relabeled']['items'] == [{'cluster': '0', 'a': '旧名', 'b': '新名'}]
        assert diff['clusters']['size_changed']['items'] == []

    def test_a_lost_cluster_is_reported_as_removed_not_as_zero(self):
        diff = compare_snapshots(
            _snapshot([{'节点': '甲', '聚类': '0', '聚类标签': '甲组'}], []),
            _snapshot([{'节点': '甲'}], []),
        )
        assert diff['clusters']['removed']['items'] == ['0']
        assert diff['clusters']['b'] == 0

    def test_burst_appearance_and_strength_are_both_compared(self):
        diff = compare_snapshots(
            _snapshot([{'节点': '甲', '突现强度': 2.0}, {'节点': '乙', '突现强度': 0}], []),
            _snapshot([{'节点': '甲', '突现强度': 3.5}, {'节点': '丙', '突现强度': 1.2}], []),
        )
        assert diff['bursts']['a'] == 1 and diff['bursts']['b'] == 2
        assert diff['bursts']['added']['items'] == ['丙']
        assert diff['bursts']['strength_changed']['items'] == [{'name': '甲', 'a': 2.0, 'b': 3.5}]

    def test_the_parameter_that_moved_is_named(self):
        """This is the difference between "the network changed" and "I changed the slicing"."""
        diff = compare_snapshots(
            _snapshot([], [], {'slice_years': 2, 'top_n': 50}),
            _snapshot([], [], {'slice_years': 3, 'top_n': 50}),
        )
        assert diff['params_differ']['items'] == [{'name': 'slice_years', 'a': 2, 'b': 3}]

    def test_a_parameter_the_older_capture_never_had_is_a_difference_not_a_crash(self):
        """The comparison indexed the LEFT dict while iterating both key sets, so the first capture
        filed after a parameter was ADDED raised ``KeyError`` against every snapshot older than it —
        which is every user's history the day a setting ships."""
        diff = compare_snapshots(
            _snapshot([], [], {'top_n': 50}),
            _snapshot([], [], {'top_n': 50, 'counting': 'fractional'}),
        )
        assert diff['params_differ']['items'] == [{'name': 'counting', 'a': None, 'b': 'fractional'}]

    def test_a_diff_section_says_how_much_it_cut(self):
        wide_a = [{'节点': f'词{i}', '频次': 1} for i in range(DIFF_LIMIT + 25)]
        diff = compare_snapshots(_snapshot([], []), _snapshot(wide_a, []))
        assert diff['nodes']['added']['total'] == len(wide_a)
        assert len(diff['nodes']['added']['items']) == DIFF_LIMIT
        assert diff['diff_limit'] == DIFF_LIMIT

    def test_two_identical_captures_differ_in_nothing(self):
        rows = [{'节点': '甲', '频次': 2, '聚类': '0', '聚类标签': '甲组'}]
        edges = [{'source': '甲', 'target': '乙', 'weight': 1.0, 'count': 1}]
        diff = compare_snapshots(_snapshot(rows, edges, {'top_n': 50}), _snapshot(rows, edges, {'top_n': 50}))
        for section in ('nodes', 'edges', 'clusters', 'bursts', 'params_differ'):
            payload = diff[section]
            totals = [value['total'] for value in payload.values() if isinstance(value, dict) and 'total' in value]
            assert not any(totals), (section, payload)
        assert diff['same_shape'] is True

    def test_a_different_shape_is_said_out_loud(self):
        """Comparing a node table against a dual-map table is a mistake, not a result."""
        diff = compare_snapshots(_snapshot([], [], shape='nodes'), _snapshot([], [], shape='dual_map'))
        assert diff['same_shape'] is False


class TestCapture:
    """`snapshot_capture` splits a stored table into nodes and edges before it is filed."""

    def test_a_nodes_table_loses_its_adjacency_to_the_edge_list_once(self):
        from services.biblio.metrics import snapshot_capture

        rows = [
            {'节点': '甲', '频次': 3, '连接': '[{"target": "乙", "value": 1.0, "count": 2}]'},
            {'节点': '乙', '频次': 2, '连接': '[{"target": "甲", "value": 1.0, "count": 2}]'},
        ]
        captured = snapshot_capture(rows)
        assert [row['节点'] for row in captured['nodes']] == ['甲', '乙']
        assert all('连接' not in row for row in captured['nodes']), 'the same fact twice is how they drift'
        assert len(captured['edges']) == 1, 'the link is listed from both ends of the node table'
        # stored under the canonical (code-point) endpoint pair, the way the diff compares them
        assert captured['edges'][0] == {'source': '乙', 'target': '甲', 'weight': 1.0, 'count': 2}

    def test_a_dual_map_table_keeps_its_nodes_not_only_its_links(self):
        """A dual-map table names entities in ``source`` and marks a node row by an empty
        ``target``; reading only ``节点`` captured its links and lost every node."""
        from services.biblio.metrics import snapshot_capture

        rows = [
            {'map': 'journal', 'source': '甲刊', 'target': '', 'weight': 14},
            {'map': 'category', 'source': '公共管理', 'target': '', 'weight': 9},
            {'map': 'journal', 'source': '甲刊', 'target': '乙刊', 'weight': 3},
            {'map': 'overlay', 'source': '甲刊', 'target': '公共管理', 'weight': 5},
        ]
        captured = snapshot_capture(rows)
        assert {row['节点'] for row in captured['nodes']} == {'甲刊', '公共管理'}
        assert {'source': '乙刊', 'target': '甲刊', 'weight': 3.0, 'count': 0} in captured['edges']
        assert sum(1 for e in captured['edges'] if '公共管理' in (e['source'], e['target'])) == 1


class TestStore:
    @pytest.fixture
    def store(self, tmp_path):
        opened = BiblioStore(str(tmp_path / 'biblio.db'))
        try:
            yield opened
        finally:
            opened.close()

    def test_a_fresh_store_holds_nothing(self, store):
        assert store.counts() == {'projects': 0, 'snapshots': 0}

    def test_a_project_round_trips_and_its_snapshots_cascade_with_it(self, store):
        project = store.create_project('数字治理', '跟踪五年')
        assert store.list_projects()[0]['snapshots'] == 0
        store.add_snapshot(project_id=project['project_id'], label='2020 基线', nodes=[{'节点': '甲'}], edges=[])
        store.add_snapshot(project_id=project['project_id'], label='2021', nodes=[{'节点': '乙'}], edges=[])
        assert store.list_projects()[0]['snapshots'] == 2
        assert store.rename_project(project['project_id'], '数字治理：改名') is True
        assert store.get_project(project['project_id'])['name'] == '数字治理：改名'
        assert store.delete_project(project['project_id']) == 2
        assert store.counts() == {'projects': 0, 'snapshots': 0}

    def test_an_empty_name_is_not_a_project(self, store):
        assert store.create_project('  ').get('name') == ''
        assert store.rename_project('whatever', '   ') is False

    def test_newest_first_means_newest_even_inside_one_second(self, store):
        """``created_at`` is second-granular, so captures filed together tie — and the tie used to
        be broken by LABEL, which for Chinese names is codepoint order and has nothing to do with
        time. A monitor asks for "the capture before this one"; an alphabetical answer is wrong."""
        project = store.create_project('排序')
        for label in ('第三次', '基线', '第二次'):
            store.add_snapshot(project_id=project['project_id'], label=label, nodes=[], edges=[])
        assert [entry['label'] for entry in store.list_snapshots(project['project_id'])] == [
            '第二次',
            '基线',
            '第三次',
        ]

    def test_a_list_never_carries_the_captured_rows(self, store):
        """The list backs a picker; shipping every captured table through it would be the panel's
        whole payload for a row the user has not chosen."""
        project = store.create_project('P')
        store.add_snapshot(
            project_id=project['project_id'],
            label='A',
            nodes=[{'节点': '甲'} for _ in range(50)],
            edges=[{'source': '甲', 'target': '乙', 'weight': 1.0}],
        )
        header = store.list_snapshots(project['project_id'])[0]
        assert 'nodes' not in header and 'edges' not in header
        assert header['node_count'] == 50 and header['edge_count'] == 1
        detail = store.get_snapshot(header['snapshot_id'])
        assert len(detail['nodes']) == 50

    def test_params_verified_is_stored_as_a_flag_not_a_mood(self, store):
        project = store.create_project('P')
        unverified = store.add_snapshot(project_id=project['project_id'], label='A', params={'top_n': 5})
        assert unverified['params_verified'] == 0
        checked = store.add_snapshot(
            project_id=project['project_id'], label='B', params={'top_n': 5}, params_verified=True
        )
        assert checked['params_verified'] == 1

    def test_a_missing_snapshot_answers_none_not_an_empty_one(self, store):
        assert store.get_snapshot('nope') is None
        assert store.delete_snapshot('nope') is False
        assert store.compare('nope', 'also-nope') is None
