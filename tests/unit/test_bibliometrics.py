"""Bibliometric construction: counts, normalization, pruning, bursts, citations."""

import json
from pathlib import Path

import pandas as pd
import pytest

from engine.workflow import WorkflowEngine
from i18n import t
from services import bibliometrics
from services.biblio_schema import (
    VARIATION_COLUMNS,
    classify_shape,
    collect_errors,
    normalize_params,
    output_columns,
)

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

    def test_a_person_can_name_a_cluster(self):
        """LLR picks a label from the corpus; sometimes the researcher already knows what the
        group is. The override wins, and the summary says which method actually produced the
        labels rather than the one that was asked for."""
        asked = sorted({row['聚类'] for row in bibliometrics.build(_keywords(), _params(cluster=True), 'test')['rows']})
        first = asked[0]
        result = bibliometrics.build(_keywords(), _params(cluster=True, cluster_labels=f'#{first}=人工命名'), 'test')
        landed = {row['聚类标签'] for row in result['rows'] if str(row['聚类']) == str(first)}
        assert landed == {'人工命名'}
        assert '+manual' in result['summary']['clusters']['method']
        assert any('人工簇标签已应用' in note for note in result['notes'])

    def test_a_cluster_label_without_the_hash_still_lands(self):
        result = bibliometrics.build(_keywords(), _params(cluster=True, cluster_labels='0=裸键'), 'test')
        assert any(row['聚类标签'] == '裸键' for row in result['rows'] if str(row['聚类']) == '0')

    def test_a_label_for_a_cluster_that_is_not_there_is_named_not_dropped(self):
        """A stale line from an earlier slicing is a fact the user should see; silently ignoring
        it leaves them believing the cluster is called that."""
        result = bibliometrics.build(_keywords(), _params(cluster=True, cluster_labels='#77=不存在的簇'), 'test')
        assert any('#77' in note and '未生效' in note for note in result['notes'])
        assert not any('人工簇标签已应用' in note for note in result['notes'])

    def test_cluster_labels_without_clustering_are_refused_by_name(self):
        from services.biblio_schema import collect_errors

        errors = collect_errors({'entity_type': 'keyword', 'cluster': False, 'cluster_labels': '#0=x'}, 'test')
        assert any('cluster_labels' in error or '聚类' in error for error in errors)

    def test_provenance_columns_appear_only_for_a_fused_table(self):
        """A plain literature table says nothing about which corpora use a term; growing an
        empty 来源 column would let the output look like a fusion that never happened."""
        plain = bibliometrics.build(_keywords(), _params(), 'test')
        assert '来源' not in plain['rows'][0] and '跨源' not in plain['rows'][0]
        fused = [dict(row, 来源='文献') for row in _keywords().to_dict('records')]
        import pandas as _pd

        result = bibliometrics.build(_pd.DataFrame(fused), _params(), 'test')
        assert {'来源', '跨源'} <= set(result['rows'][0])
        assert all(row['来源'] == '文献' and row['跨源'] is False for row in result['rows'])

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

    def test_alias_and_exclusion_rules_run_before_the_graph(self):
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': 'AI;人工智能;噪声', '摘要': ''},
                {'题名': 'b', '年份': 2020, '关键词': 'AI;人工智能;噪声', '摘要': ''},
            ]
        )
        result = bibliometrics.build(
            frame,
            _params(aliases='人工智能=AI', exclude_values='噪声'),
            'test',
        )
        assert {row['节点'] for row in result['rows']} == {'人工智能'}
        assert any('别名合并' in note or 'Alias merge' in note for note in result['notes'])
        assert any('排除列表' in note or 'Exclusion list' in note for note in result['notes'])

    def test_citation_expansion_uses_references_from_records_in_the_table(self):
        frame = pd.DataFrame(
            [
                {'题名': 'A', '年份': 2021, '参考文献': '[1] B. B.'},
                {'题名': 'B', '年份': 2020, '参考文献': '[1] C. C.\n[2] D. D.'},
                {'题名': 'E', '年份': 2022, '参考文献': '[1] C. C.\n[2] D. D.'},
            ]
        )
        direct = bibliometrics.build(frame, _params(entity_type='document_cocitation', burst=False), 'test')
        expanded = bibliometrics.build(
            frame,
            _params(entity_type='document_cocitation', burst=False, citation_expansion=1),
            'test',
        )
        assert {row['节点'] for row in direct['rows']} == {'C', 'D'}
        assert {row['节点'] for row in expanded['rows']} == {'B', 'C', 'D'}
        assert len(expanded['edges']) > len(direct['edges'])
        assert any('引文扩展' in note or 'Citation expansion' in note for note in expanded['notes'])

    def test_dual_map_output_uses_a_journal_category_basemap(self):
        records = pd.DataFrame(
            [
                {
                    '题名': 'A',
                    '年份': 2021,
                    '来源期刊': '甲源',
                    '学科': '公共管理',
                    '参考文献': '[1] 张三. 甲文[J]. 甲刊, 2020(1): 1-2.\n[2] 李四. 乙文[J]. 乙刊, 2021(2): 3-4.',
                },
                {
                    '题名': 'B',
                    '年份': 2022,
                    '来源期刊': '乙源',
                    '学科': '信息科学',
                    '参考文献': '[1] 张三. 甲文[J]. 甲刊, 2020(1): 1-2.\n[2] 李四. 乙文[J]. 乙刊, 2021(2): 3-4.',
                },
            ]
        )
        basemap = pd.DataFrame({'期刊': ['甲源', '乙源'], '学科': ['公共管理', '信息科学']})
        result = bibliometrics.build(
            records,
            _params(entity_type='journal', output_shape='dual_map', basemap_dataset_id='x', burst=False),
            'dual',
            basemap_df=basemap,
        )
        sides = {row['map'] for row in result['rows']}
        assert {'journal', 'category', 'overlay'} <= sides
        assert any(row['source'] and row['target'] and row['map'] == 'overlay' for row in result['rows'])
        assert result['summary']['output_shape'] == 'dual_map'
        # x/y are also a table cell the workspace and the CSV show, so a layout artifact
        # (97.36842105263159) must not reach them. Edge rows carry neither, by design.
        placed = [row for row in result['rows'] if str(row['y']) != '']
        assert placed and all(float(row['y']) == round(float(row['y']), 2) for row in placed)

    def test_dual_map_without_basemap_is_refused_by_name(self):
        with pytest.raises(ValueError, match='basemap'):
            normalize_params(_params(output_shape='dual_map'), 'test')


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
        # The scope is named with the interface's own word, not the stored token: a Chinese
        # console line reading 「MST 剪枝（slices）」 is half a sentence in two languages.
        assert any('MST' in note and t('biblio.pruning_scope.slices') in note for note in slices['notes'])
        assert any('MST' in note and t('biblio.pruning_scope.merged') in note for note in merged['notes'])

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


@pytest.mark.parametrize(
    ('columns', 'shape'),
    [
        (['节点', '频次', '连接', '突现强度', '突现起始', '突现结束'], 'nodes'),
        (['source', 'target', 'weight', 'count'], 'edges'),
        (['聚类', '聚类标签', '节点数', '节点', '轮廓值'], 'clusters'),
        (['节点', '突现起始', '突现结束', '突现强度'], 'bursts'),
        (['map', 'source', 'target', 'weight', 'label', 'x', 'y'], 'dual_map'),
        (['whatever'], ''),
        ([], ''),
    ],
)
def test_a_stored_table_reads_back_the_shape_it_was_emitted_as(columns, shape):
    """The workspace labels a run's table with this, and the run record keeps no parameters —
    so the columns are the only honest evidence, and no evidence must answer "unknown"."""
    from services.biblio_schema import classify_shape

    assert classify_shape(columns) == shape


def test_every_output_shape_reads_back():
    """One direction without the other is how a new shape would silently lose its label."""
    from services.biblio_schema import OUTPUT_SHAPES, classify_shape

    for shape in OUTPUT_SHAPES:
        assert classify_shape(output_columns({'output_shape': shape})) == shape


def _edges(*triples):
    """``(a, b, weight)`` in canonical-pair form, as ``_prune`` hands them over."""
    return {(a, b) if a < b else (b, a): {'weight': weight} for a, b, weight in triples}


def _pf(r='inf', lmax=0, dmax=1.0):
    return {'pathfinder_r': r, 'pathfinder_lmax': lmax, 'pathfinder_dmax': dmax}


class TestPathfinderReduction:
    """Mantel's PFNET reimplemented from the published definition, on hand-computed networks.

    Similarity is read as distance ``d = 1 - s``; a link survives iff its own distance is no
    longer than the best indirect path between its endpoints under the chosen r-norm."""

    TRIANGLE = _edges(('A', 'B', 0.5), ('B', 'C', 0.5), ('A', 'C', 0.4))

    def test_the_bottleneck_norm_drops_the_dominated_chord(self):
        # A→B→C costs max(0.5, 0.5) = 0.5, better than the chord's own 0.6.
        assert bibliometrics._pfnet_keys(self.TRIANGLE, _pf('inf')) == {('A', 'B'), ('B', 'C')}

    def test_the_sum_and_euclidean_norms_keep_it_because_two_links_really_do_cost_more(self):
        # 0.5 + 0.5 = 1.0 and √(0.5²+0.5²) ≈ 0.707, both worse than 0.6.
        assert bibliometrics._pfnet_keys(self.TRIANGLE, _pf('1')) == set(self.TRIANGLE)
        assert bibliometrics._pfnet_keys(self.TRIANGLE, _pf('2')) == set(self.TRIANGLE)

    def test_the_depth_limit_decides_whether_a_long_way_round_counts(self):
        chain = _edges(('A', 'B', 0.8), ('B', 'C', 0.8), ('C', 'D', 0.8), ('A', 'D', 0.3))
        # Two hops cannot get from A to D, so the direct link stands; at three hops it is dominated.
        assert ('A', 'D') in bibliometrics._pfnet_keys(chain, _pf('inf', lmax=2))
        assert ('A', 'D') not in bibliometrics._pfnet_keys(chain, _pf('inf', lmax=3))

    def test_the_keep_fraction_leaves_the_strongest_survivors(self):
        assert bibliometrics._pfnet_keys(self.TRIANGLE, _pf('1', dmax=0.5)) == {('A', 'B'), ('B', 'C')}

    def test_the_bottleneck_case_at_full_depth_is_the_same_graph_as_the_spanning_forest(self):
        """The fast path is not a weaker substitute: PFNET(r=∞, unlimited depth) IS the maximum
        spanning forest, so the two must agree link for link."""
        edges = _edges(
            ('A', 'B', 0.9),
            ('B', 'C', 0.8),
            ('C', 'D', 0.7),
            ('A', 'D', 0.2),
            ('A', 'C', 0.3),
            ('B', 'D', 0.25),
            ('D', 'E', 0.6),
            ('A', 'E', 0.1),
        )
        assert bibliometrics._pfnet_keys(edges, _pf('inf')) == bibliometrics._global_mst_keys(edges)

    def test_a_network_wider_than_the_budget_refuses_and_names_its_numbers(self, monkeypatch):
        monkeypatch.setattr(bibliometrics, '_PFNET_WORK_BUDGET', 10)
        with pytest.raises(ValueError) as exc:
            bibliometrics._pfnet_keys(self.TRIANGLE, _pf('1'))
        text = str(exc.value)
        assert '3' in text and '10' in text, text

    def test_two_and_three_nodes_have_no_indirect_path_to_compare(self):
        assert bibliometrics._pfnet_keys(_edges(('A', 'B', 0.5)), _pf('1')) == {('A', 'B')}


class TestPathfinderInTheRun:
    def test_the_exponent_changes_the_pruned_network(self):
        """A run that prunes identically whatever r says would be a switch that switches nothing."""
        few = bibliometrics.build(_keywords(), _params(pruning='pathfinder', pruning_scope='merged'), 'test')
        many = bibliometrics.build(
            _keywords(), _params(pruning='pathfinder', pruning_scope='merged', pathfinder_r='1'), 'test'
        )
        assert len(many['edges']) >= len(few['edges'])
        assert many['edges'] != few['edges'] or len(many['edges']) > len(few['edges'])

    def test_the_console_names_the_parameters_that_ran(self):
        result = bibliometrics.build(
            _keywords(), _params(pruning='pathfinder', pathfinder_r='2', pathfinder_lmax=3, pathfinder_dmax=0.8), 'test'
        )
        line = next(note for note in result['notes'] if 'Pathfinder' in note)
        assert 'r=2' in line and '3' in line and '0.8' in line

    def test_pruning_a_slice_network_is_not_the_same_job_as_pruning_the_merged_one(self):
        per_slice = bibliometrics.build(_keywords(), _params(pruning='pathfinder', pathfinder_r='1'), 'test')
        merged = bibliometrics.build(
            _keywords(), _params(pruning='pathfinder', pruning_scope='merged', pathfinder_r='1'), 'test'
        )
        assert per_slice['notes'] != merged['notes']


class TestPathfinderParameters:
    def test_the_defaults_are_the_classic_pfnet(self):
        params = normalize_params(_params(), 'test')
        assert (params['pathfinder_r'], params['pathfinder_lmax'], params['pathfinder_dmax']) == ('inf', 0, 1.0)

    def test_normalizing_twice_changes_nothing(self):
        once = normalize_params(_params(pathfinder_r='1', pathfinder_lmax=3, pathfinder_dmax='0.8'), 'test')
        assert normalize_params(once, 'test') == once

    def test_an_exponent_this_build_cannot_compute_is_refused_by_name(self):
        errors = collect_errors(_params(pathfinder_r='3'), 'test')
        assert any('pathfinder_r' in line and '3' in line for line in errors), errors

    @pytest.mark.parametrize(
        ('name', 'value'),
        [('pathfinder_lmax', 51), ('pathfinder_lmax', -1), ('pathfinder_dmax', 0), ('pathfinder_dmax', 1.5)],
    )
    def test_a_number_outside_its_range_is_refused_by_name(self, name, value):
        assert any(name in line for line in collect_errors(_params(**{name: value}), 'test'))

    @pytest.mark.parametrize('name', ['pathfinder_lmax', 'pathfinder_dmax'])
    def test_a_cleared_box_refuses_by_name_rather_than_assuming_the_default(self, name):
        """Same rule as every other numeric box on this node: a value the user erased is not a
        preference for the default, and 0 on the depth would mean "unlimited" while 0 on the
        fraction would mean "keep nothing" — the two readings differ, so the box asks."""
        assert any(name in line for line in collect_errors(_params(**{name: ''}), 'test'))


def _sv_frame():
    """甲 shares its slice with 乙, then with 丙, then with both again."""
    return pd.DataFrame(
        [
            {'题名': 'a', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
            {'题名': 'b', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
            {'题名': 'c', '年份': 2021, '关键词': '甲;丙', '摘要': ''},
            {'题名': 'd', '年份': 2021, '关键词': '甲;丙', '摘要': ''},
            {'题名': 'e', '年份': 2022, '关键词': '甲;乙;丙', '摘要': ''},
        ]
    )


class TestStructuralVariation:
    def _rows(self, frame=None, **overrides):
        base = {'variation': True, 'variation_min': 0.0}
        base.update(overrides)
        params = _params(**base)
        # A DataFrame has no truth value, so the default cannot be `frame or …`.
        result = bibliometrics.build(_sv_frame() if frame is None else frame, params, 'test')
        return result['variation']

    def test_a_completely_different_neighbourhood_is_one_bit(self):
        row = next(r for r in self._rows() if r['节点'] == '甲' and r['起始年'] == 2020)
        assert row['结构变化'] == 1.0
        assert row['新增邻居'] == '丙' and row['消失邻居'] == '乙'

    def test_gaining_one_of_two_partners_is_the_textbook_half_bit_case(self):
        """p = [1] against q = [.5,.5] has JSD = 0.311278… bits; the number is checked against
        the hand computation, not against whatever the code produced."""
        row = next(r for r in self._rows() if r['节点'] == '甲' and r['起始年'] == 2021)
        assert row['结构变化'] == pytest.approx(0.311278, abs=1e-5)
        assert row['消失邻居'] == ''

    def test_only_nodes_present_in_both_slices_are_scored(self):
        """乙/丙 appear in both slices here, but a node with links in ONE slice has no pattern
        to compare — scoring that absence would rank a disappearance above a restructuring."""
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
                {'题名': 'b', '年份': 2021, '关键词': '丙;丁', '摘要': ''},
            ]
        )
        assert self._rows(frame) == []

    def test_the_threshold_decides_what_counts_as_a_change(self):
        everything = self._rows()
        above = self._rows(variation_min=0.5)
        assert len(above) < len(everything)
        assert all(row['结构变化'] >= 0.5 for row in above)

    def test_the_table_is_ranked_by_the_change_not_by_the_node(self):
        scores = [row['结构变化'] for row in self._rows()]
        assert scores == sorted(scores, reverse=True)

    def test_a_year_with_no_records_is_not_compared_across_the_gap(self):
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
                {'题名': 'b', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
                {'题名': 'c', '年份': 2022, '关键词': '甲;丙', '摘要': ''},
                {'题名': 'd', '年份': 2022, '关键词': '甲;丙', '摘要': ''},
            ]
        )
        # 2021 has no records, so slice 0 and slice 2 are not consecutive: comparing them would
        # report a change that is really two years of missing data.
        assert self._rows(frame) == []
        assert self._rows(frame, variation_min=0.5) == []

    def test_the_variation_table_has_its_own_shape_and_reads_back(self):
        params = _params(variation=True, output_shape='variation')
        assert output_columns(params) == list(VARIATION_COLUMNS)
        result = bibliometrics.build(_sv_frame(), params, 'test')
        assert list(result['variation'][0]) == list(VARIATION_COLUMNS)
        assert classify_shape(result['variation'][0]) == 'variation'

    def test_asking_for_the_table_without_the_switch_is_refused_by_name(self):
        with pytest.raises(ValueError) as exc:
            normalize_params(_params(output_shape='variation'), 'test')
        assert 'variation' in str(exc.value)

    def test_one_slice_cannot_show_a_change_and_says_so(self):
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
                {'题名': 'b', '年份': 2020, '关键词': '甲;乙;丙', '摘要': ''},
            ]
        )
        with pytest.raises(ValueError) as exc:
            bibliometrics.build(frame, _params(variation=True), 'test')
        assert '切片' in str(exc.value) or 'slice' in str(exc.value)

    def test_a_coupling_network_refuses_the_switch_rather_than_inventing_slices(self):
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': '甲', '参考文献': 'REF1', '摘要': ''},
                {'题名': 'b', '年份': 2021, '关键词': '乙', '参考文献': 'REF1', '摘要': ''},
            ]
        )
        with pytest.raises(ValueError) as exc:
            bibliometrics.build(
                frame, _params(entity_type='bibliographic_coupling', variation=True, burst=False), 'test'
            )
        assert '耦合' in str(exc.value) or 'coupling' in str(exc.value)

    def test_the_variation_table_is_written_as_an_artifact(self, tmp_path):
        result = bibliometrics.build(_sv_frame(), _params(variation=True), 'test')
        files = bibliometrics.export_result(result, str(tmp_path), 'sv')
        assert 'biblio_variation' in files
        assert '结构变化' in Path(files['biblio_variation']).read_text(encoding='utf-8-sig')


def _counting_frame():
    """Two short documents that pair 甲 with 乙, and one long document that pairs five terms."""
    return pd.DataFrame(
        [
            {'题名': 'a', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
            {'题名': 'b', '年份': 2020, '关键词': '甲;乙;丙;丁;戊', '摘要': ''},
            {'题名': 'c', '年份': 2021, '关键词': '甲;乙', '摘要': ''},
        ]
    )


def _edge(result, left, right):
    key = (left, right) if left < right else (right, left)
    for row in result['edges']:
        if (row['source'], row['target']) == key:
            return row
    return None


class TestFractionalCounting:
    def test_one_document_buys_one_unit_of_credit_whatever_it_carries(self):
        """Cosine on the raw counts gives 甲乙 1.0 (three meetings of two nodes that each occur
        three times). Fractional counting spreads the long document's single unit over its ten
        pairs, so the same edge reads 2.1/3 — the two short documents now outweigh the one long
        one, which is the whole point."""
        full = bibliometrics.build(_counting_frame(), _params(counting='full'), 'test')
        split = bibliometrics.build(_counting_frame(), _params(counting='fractional'), 'test')
        assert _edge(full, '甲', '乙')['weight'] == pytest.approx(1.0)
        assert _edge(split, '甲', '乙')['weight'] == pytest.approx(0.7)

    def test_the_reported_count_is_still_the_number_of_times_they_met(self):
        """Normalization belongs to the strength only. A table whose 次数 quietly became 0.1 is a
        table that no longer answers the question the column asks."""
        split = bibliometrics.build(_counting_frame(), _params(counting='fractional'), 'test')
        assert _edge(split, '甲', '乙')['count'] == 3
        assert _edge(split, '丙', '丁')['count'] == 1

    def test_a_long_list_no_longer_buys_six_strong_links(self):
        full = bibliometrics.build(_counting_frame(), _params(counting='full'), 'test')
        split = bibliometrics.build(_counting_frame(), _params(counting='fractional'), 'test')
        assert _edge(full, '甲', '丙') is not None
        assert _edge(split, '甲', '丙') is None

    def test_the_console_says_the_counting_ran_and_which_documents_were_split(self):
        quiet = bibliometrics.build(_counting_frame(), _params(counting='full'), 'test')
        loud = bibliometrics.build(_counting_frame(), _params(counting='fractional'), 'test')
        assert not any('分数' in note or 'ractional' in note for note in quiet['notes'])
        assert any(('1 篇' in note or '1 document' in note) for note in loud['notes']), loud['notes']

    def test_two_documents_have_nothing_to_split_and_say_so(self):
        """A document carrying one pair already spends its unit on that pair; counting it as
        "renormalized" would claim a change that did not happen."""
        frame = pd.DataFrame(
            [
                {'题名': 'a', '年份': 2020, '关键词': '甲;乙', '摘要': ''},
                {'题名': 'b', '年份': 2021, '关键词': '丙;丁', '摘要': ''},
            ]
        )
        result = bibliometrics.build(frame, _params(counting='fractional'), 'test')
        assert not any('分数' in note or 'ractional' in note for note in result['notes'])

    def test_coupling_has_no_third_document_to_split_and_refuses_by_name(self):
        # Refused at the parameter gate, before any data is read: the rule is about the node
        # type, not about what the corpus happens to contain.
        with pytest.raises(ValueError) as exc:
            normalize_params(_params(entity_type='bibliographic_coupling', counting='fractional', burst=False), 'test')
        text = str(exc.value)
        assert 'fractional' in text and 'bibliographic_coupling' in text, text

    def test_the_default_is_full_counting_so_no_existing_canvas_moves(self):
        assert normalize_params(_params(), 'test')['counting'] == 'full'

    def test_an_unknown_counting_mode_is_refused_by_name(self):
        assert any('counting' in line for line in collect_errors(_params(counting='half'), 'test'))

    def test_normalizing_twice_changes_nothing(self):
        once = normalize_params(_params(counting='fractional'), 'test')
        assert normalize_params(once, 'test') == once
