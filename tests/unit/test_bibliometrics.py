"""Bibliometric construction: counts, normalization, pruning, bursts, citations."""

import json
from pathlib import Path

import pandas as pd
import pytest

from engine.workflow import WorkflowEngine
from services import bibliometrics
from services.biblio_schema import collect_errors, normalize_params, output_columns

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.unit


def _params(**overrides):
    base = {
        'entity_type': 'keyword',
        'time_start': '',
        'time_end': '',
        'slice_years': 1,
        'selection': 'top_n',
        'top_n': 50,
        'top_pct': 10,
        'g_index': 25,
        'min_count': 1,
        'link_measure': 'cosine',
        'max_links_per_node': 10,
        'lrf': 2.5,
        'pruning': 'none',
        'cluster': False,
        'cluster_count': '',
        'label_method': 'llr',
        'top_terms': 5,
        'burst': False,
        'burst_gamma': 1.0,
        'burst_min_duration': 2,
        'burst_weight': 2.0,
        'burst_top': 20,
        'export_files': False,
    }
    base.update(overrides)
    return base


def _keywords():
    return pd.DataFrame(
        [
            {'题名': 't1', '年份': 2018, '关键词': '甲;乙', '作者': 'A;B', '作者单位': 'U1', '摘要': '甲 乙'},
            {'题名': 't2', '年份': 2019, '关键词': '乙;丙', '作者': 'A;C', '作者单位': 'U1', '摘要': '乙 丙'},
            {'题名': 't3', '年份': 2020, '关键词': '甲;丙', '作者': 'B;C', '作者单位': 'U2', '摘要': '甲 丙'},
        ]
    )


def _refs():
    refs = '[1] 张三. 甲文[J]. 甲刊, 2020(1): 1-2.\n[2] 李四. 乙文[J]. 乙刊, 2021(2): 3-4.'
    return pd.DataFrame(
        [
            {
                '题名': '施引一',
                '年份': 2021,
                '参考文献': refs,
                '来源期刊': '甲源',
                '基金': '基金A;基金B',
                '关键词': '甲;乙',
                '摘要': '甲 乙',
                '引用次数': 10,
                '使用次数': 5,
            },
            {
                '题名': '施引二',
                '年份': 2022,
                '参考文献': refs,
                '来源期刊': '乙源',
                '基金': '基金A;基金C',
                '关键词': '乙;丙',
                '摘要': '乙 丙',
                '引用次数': 1,
                '使用次数': 1,
            },
        ]
    )


class TestKeywordNetwork:
    def test_known_counts_and_edges(self):
        result = bibliometrics.build(_keywords(), _params(), 'test')
        rows = {row['节点']: row for row in result['rows']}
        assert set(rows) == {'甲', '乙', '丙'}
        assert {name: row['频次'] for name, row in rows.items()} == {'甲': 2, '乙': 2, '丙': 2}
        assert len(result['edges']) == 3
        links = json.loads(rows['甲']['连接'])
        assert {item['target'] for item in links} == {'乙', '丙'}
        assert all(item['count'] == 1 for item in links)

    def test_build_is_deterministic(self):
        first = bibliometrics.build(_keywords(), _params(), 'test')
        second = bibliometrics.build(_keywords(), _params(), 'test')
        assert first['rows'] == second['rows']

    def test_mst_keeps_a_tree(self):
        result = bibliometrics.build(_keywords(), _params(pruning='mst', pruning_scope='merged'), 'test')
        assert len(result['edges']) == len(result['rows']) - 1

    def test_pathfinder_runs_per_slice_and_reports_its_pruning(self):
        result = bibliometrics.build(_keywords(), _params(pruning='pathfinder'), 'test')
        assert result['edges']
        assert result['summary']['pruning'] == 'pathfinder'

    def test_cluster_columns_only_appear_when_requested(self):
        plain = bibliometrics.build(_keywords(), _params(), 'test')
        assert '聚类' not in plain['rows'][0]
        clustered = bibliometrics.build(_keywords(), _params(cluster=True), 'test')
        assert {'聚类', '聚类标签', '轮廓值'} <= set(clustered['rows'][0])
        assert clustered['summary']['clusters']['k'] >= 1

    def test_a_missing_column_is_refused_by_name(self):
        frame = _keywords().drop(columns=['关键词'])
        with pytest.raises(ValueError, match='关键词'):
            bibliometrics.build(frame, _params(), 'test')

    def test_a_crawled_table_can_map_its_own_columns(self):
        frame = pd.DataFrame(
            [
                {'话题': '甲;乙', '用户名': 'A', '发布时间': '2020-01-03', '标题': 't1', '正文': '甲 乙'},
                {'话题': '乙;丙', '用户名': 'B', '发布时间': '2021-02-04', '标题': 't2', '正文': '乙 丙'},
                {'话题': '甲;丙', '用户名': 'C', '发布时间': '2022-03-05', '标题': 't3', '正文': '甲 丙'},
            ]
        )
        result = bibliometrics.build(
            frame,
            _params(
                entity_type='keyword',
                entity_column='话题',
                year_column='发布时间',
                title_column='标题',
                abstract_column='正文',
            ),
            'crawled',
        )
        assert {row['节点'] for row in result['rows']} == {'甲', '乙', '丙'}
        assert result['summary']['window'] == {'start': 2020, 'end': 2022}

    def test_a_network_without_edges_is_refused(self):
        frame = pd.DataFrame(
            [
                {'题名': 't1', '年份': 2020, '关键词': '甲', '作者': '', '作者单位': '', '摘要': ''},
                {'题名': 't2', '年份': 2021, '关键词': '乙', '作者': '', '作者单位': '', '摘要': ''},
            ]
        )
        with pytest.raises(ValueError):
            bibliometrics.build(frame, _params(), 'test')


class TestBurst:
    def test_a_known_spike_is_found(self):
        bursts = bibliometrics.kleinberg_bursts([0, 0, 0, 10, 10, 0], [10] * 6, 1.0, 2, 2.0)
        assert bursts
        assert bursts[0]['start'] == 3
        assert bursts[0]['end'] == 4
        assert bursts[0]['strength'] > 0

    def test_a_flat_series_is_not_a_burst(self):
        assert bibliometrics.kleinberg_bursts([1, 1, 1, 1], [5, 5, 5, 5], 1.0, 2, 2.0) == []


class TestCitations:
    def test_document_cocitation_uses_shared_references(self):
        result = bibliometrics.build(_refs(), _params(entity_type='document_cocitation', burst=False), 'test')
        assert {row['节点'] for row in result['rows']} == {'甲文', '乙文'}
        assert len(result['edges']) == 1
        assert result['edges'][0]['count'] == 2

    def test_author_and_journal_cocitation(self):
        authors = bibliometrics.build(_refs(), _params(entity_type='author_cocitation', burst=False), 'test')
        journals = bibliometrics.build(_refs(), _params(entity_type='journal_cocitation', burst=False), 'test')
        assert {row['节点'] for row in authors['rows']} == {'张三', '李四'}
        assert {row['节点'] for row in journals['rows']} == {'甲刊', '乙刊'}

    def test_bibliographic_coupling_connects_citing_papers(self):
        result = bibliometrics.build(_refs(), _params(entity_type='bibliographic_coupling', burst=False), 'test')
        assert {row['节点'] for row in result['rows']} == {'施引一', '施引二'}
        assert len(result['edges']) == 1

    def test_missing_references_refuse_the_citation_mode(self):
        with pytest.raises(ValueError):
            bibliometrics.build(_keywords(), _params(entity_type='document_cocitation', burst=False), 'test')

    def test_coupling_cannot_use_burst(self):
        with pytest.raises(ValueError):
            normalize_params(_params(entity_type='bibliographic_coupling', burst=True), 'test')

    def test_coupling_defaults_to_no_burst_when_the_box_is_absent(self):
        params = _params(entity_type='bibliographic_coupling')
        params.pop('burst')
        assert normalize_params(params, 'test')['burst'] is False


class TestPhaseTwoContracts:
    def test_document_is_the_cite_space_name_for_bibliographic_coupling(self):
        coupling = bibliometrics.build(_refs(), _params(entity_type='bibliographic_coupling', burst=False), 'test')
        document = bibliometrics.build(_refs(), _params(entity_type='document', burst=False), 'test')
        assert {row['节点'] for row in document['rows']} == {row['节点'] for row in coupling['rows']}

    def test_journal_coupling_connects_source_journals_by_shared_references(self):
        result = bibliometrics.build(_refs(), _params(entity_type='journal', burst=False), 'test')
        assert {row['节点'] for row in result['rows']} == {'甲源', '乙源'}
        assert len(result['edges']) == 1

    def test_funder_cooccurrence_builds_grant_links(self):
        result = bibliometrics.build(_refs(), _params(entity_type='funder', burst=False), 'test')
        assert {row['节点'] for row in result['rows']} == {'基金A', '基金B', '基金C'}
        assert any(edge['source'] == '基金A' and edge['target'] == '基金B' for edge in result['edges'])
        assert any(edge['source'] == '基金A' and edge['target'] == '基金C' for edge in result['edges'])

    def test_min_tc_uses_the_mapped_citation_count_column(self):
        result = bibliometrics.build(
            _refs(),
            _params(min_tc=5, selection='threshold', threshold_c=1),
            'test',
        )
        assert {row['节点'] for row in result['rows']} == {'甲', '乙'}

    def test_edge_threshold_cc_removes_weak_pairs(self):
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': '甲;乙;丙', '摘要': ''},
                {'题名': 'b', '年份': 2021, '关键词': '甲;乙', '摘要': ''},
            ]
        )
        kept = bibliometrics.build(frame, _params(selection='threshold', threshold_c=1), 'test')
        pruned = bibliometrics.build(frame, _params(selection='threshold', threshold_c=1, threshold_cc=2), 'test')
        assert len(pruned['edges']) < len(kept['edges'])
        assert all(edge['count'] >= 2 for edge in pruned['edges'])

    def test_largest_component_drops_small_islands(self):
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
                {'题名': 'b', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
                {'题名': 'c', '年份': 2021, '关键词': '丙;丁', '摘要': ''},
                {'题名': 'd', '年份': 2021, '关键词': '丙;丁', '摘要': ''},
            ]
        )
        result = bibliometrics.build(
            frame,
            _params(selection='threshold', threshold_c=1, largest_component=True),
            'test',
        )
        assert {row['节点'] for row in result['rows']} == {'丙', '丁'}
        assert any('最大连通分量' in note or 'largest connected component' in note for note in result['notes'])

    def test_cite_space_node_names_alias_the_same_constructions(self):
        journal = bibliometrics.build(_refs(), _params(entity_type='journal', burst=False), 'test')
        source = bibliometrics.build(_refs(), _params(entity_type='source', burst=False), 'test')
        funder = bibliometrics.build(_refs(), _params(entity_type='funder', burst=False), 'test')
        grant = bibliometrics.build(_refs(), _params(entity_type='grant', burst=False), 'test')
        document = bibliometrics.build(_refs(), _params(entity_type='document_cocitation', burst=False), 'test')
        article = bibliometrics.build(_refs(), _params(entity_type='article', burst=False), 'test')
        assert {row['节点'] for row in source['rows']} == {row['节点'] for row in journal['rows']}
        assert {row['节点'] for row in grant['rows']} == {row['节点'] for row in funder['rows']}
        assert {row['节点'] for row in article['rows']} == {row['节点'] for row in document['rows']}

    def test_mst_pruning_scope_can_run_per_slice_or_merged(self):
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': '甲;乙;丙', '摘要': ''},
                {'题名': 'b', '年份': 2021, '关键词': '甲;乙;丙', '摘要': ''},
            ]
        )
        slices = bibliometrics.build(frame, _params(pruning='mst', pruning_scope='slices'), 'test')
        merged = bibliometrics.build(frame, _params(pruning='mst', pruning_scope='merged'), 'test')
        assert len(merged['edges']) == len(merged['rows']) - 1
        assert len(slices['edges']) >= len(merged['edges'])
        assert any('MST 剪枝（slices）' in note or 'MST pruning (slices)' in note for note in slices['notes'])
        assert any('MST 剪枝（merged）' in note or 'MST pruning (merged)' in note for note in merged['notes'])

    def test_citation_metrics_are_emitted_only_when_the_data_has_them(self):
        with_metrics = bibliometrics.build(_refs(), _params(entity_type='author_cocitation', burst=False), 'test')
        assert all('总被引' in row and 'H指数' in row for row in with_metrics['rows'])
        assert max(row['H指数'] for row in with_metrics['rows']) >= 1
        without = bibliometrics.build(_keywords(), _params(), 'test')
        assert all('总被引' not in row for row in without['rows'])
        assert '总被引' not in output_columns(_params(), list(_keywords().columns))
        assert '总被引' in output_columns(_params(), list(_refs().columns))

    def test_output_shape_columns_are_a_contract(self):
        assert output_columns(_params(output_shape='edges')) == ['source', 'target', 'weight', 'count']
        assert output_columns(_params(output_shape='clusters', cluster=True)) == [
            '聚类',
            '聚类标签',
            '节点数',
            '节点',
            '轮廓值',
        ]
        assert output_columns(_params(output_shape='bursts', burst=True)) == [
            '节点',
            '突现起始',
            '突现结束',
            '突现强度',
        ]

    def test_a_shape_that_its_switch_missing_is_refused_by_name(self):
        assert any('clusters' in message for message in collect_errors(_params(output_shape='clusters'), 'test'))
        assert any('bursts' in message for message in collect_errors(_params(output_shape='bursts'), 'test'))

    def test_exports_write_graphml_gml_and_json(self, tmp_path):
        result = bibliometrics.build(_keywords(), _params(cluster=True, burst=True), 'test')
        files = bibliometrics.export_result(result, str(tmp_path), 'demo')
        assert files['biblio_graphml'].endswith('_graph.graphml')
        assert files['biblio_gml'].endswith('_graph.gml')
        assert files['biblio_json'].endswith('_graph.json')
        snapshot = json.loads((tmp_path / 'demo_graph.json').read_text(encoding='utf-8'))
        assert snapshot['summary']['entity_type'] == 'keyword'
        assert snapshot['nodes']
        assert snapshot['edges']


class TestContracts:
    def test_output_columns_are_conditional(self):
        assert '聚类' not in output_columns(_params())
        assert '聚类' in output_columns(_params(cluster=True))
        assert '突现强度' not in output_columns(_params())
        assert '突现强度' in output_columns(_params(burst=True))

    def test_bad_parameter_names_the_box(self):
        with pytest.raises(ValueError, match='entity_type'):
            normalize_params(_params(entity_type='nope'), 'test')

    def test_reversed_time_range_is_refused(self):
        with pytest.raises(ValueError):
            normalize_params(_params(time_start=2022, time_end=2020), 'test')

    def test_a_non_numeric_year_is_refused_without_crashing(self):
        with pytest.raises(ValueError, match='time_start'):
            normalize_params(_params(time_start='abc'), 'test')

    def test_a_name_wire_counts_as_an_input_wire(self):
        workflow = {
            'nodes': [
                {'id': 'n', 'type': 'name', 'title': 'n', 'params': {'workflow_name': 'x'}, 'x': 0, 'y': 0},
                {'id': 'u', 'type': 'upload', 'title': 'u', 'params': {'dataset_id': 'x'}, 'x': 0, 'y': 0},
                {'id': 'b', 'type': 'biblio', 'title': 'b', 'params': {}, 'x': 0, 'y': 0},
            ],
            'connections': [{'from': 'n', 'to': 'b'}, {'from': 'u', 'to': 'b'}],
            'settings': {},
        }
        codes = [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed()]
        assert 'engine.biblio_multi_input' in codes

    def test_cluster_labels_name_the_member_fallback(self):
        import networkx as nx

        from services import biblio_cluster

        graph = nx.Graph()
        graph.add_weighted_edges_from([('甲', '乙', 1.0), ('丙', '丁', 1.0)])
        result = biblio_cluster.cluster_graph(graph, ['甲', '乙', '丙', '丁'], {}, [], 2, 'tfidf', 3)
        assert result['fallback'] is True
        assert result['summary']['method'] == 'members'
        assert '甲' in result['members']['甲']['cluster_label']

    def test_the_demo_workflow_validates(self):
        path = ROOT / 'data' / 'workflows' / '文献计量演示：CNKI 与 CSSCI 知识图谱.json'
        workflow = json.loads(path.read_text(encoding='utf-8'))
        assert WorkflowEngine(workflow).validate() == []
        biblio_params = [n['params'] for n in workflow['nodes'] if n['type'] == 'biblio']
        assert biblio_params and all('year_column' in params for params in biblio_params)
