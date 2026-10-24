"""The bibliometric ECharts views and their named refusals."""

import json

import pandas as pd
import pytest

from services.chart_contracts import BIBLIO_CHART_TYPES
from services.visualizer import ChartConfigError, VisualizationService

pytestmark = pytest.mark.unit


@pytest.fixture
def frame():
    return pd.DataFrame(
        {
            '节点': ['甲', '乙', '丙'],
            'x': [0.0, 10.0, 20.0],
            'y': [0.0, 10.0, 20.0],
            '连接': [
                json.dumps([{'target': '乙', 'value': 1.0, 'count': 2}], ensure_ascii=False),
                json.dumps([{'target': '甲', 'value': 1.0, 'count': 2}], ensure_ascii=False),
                '[]',
            ],
            '频次': [3, 2, 1],
            '聚类': [0, 0, 1],
            '聚类标签': ['甲组', '甲组', '乙组'],
            '突现强度': [2.0, 0.0, 0.0],
            '突现起始': [2020, '', ''],
            '突现结束': [2021, '', ''],
            '首年': [2020, 2020, 2021],
            '末年': [2021, 2021, 2021],
            '年份序列': [
                json.dumps({'2020': 1, '2021': 2}),
                json.dumps({'2020': 2}),
                json.dumps({'2021': 1}),
            ],
        }
    )


@pytest.fixture
def dual_frame():
    return pd.DataFrame(
        {
            'map': ['journal', 'category', 'overlay', 'journal', 'category', 'journal'],
            'source': ['甲刊', '公共管理', '甲刊', '甲刊', '公共管理', '丁刊'],
            'target': ['乙刊', '信息科学', '公共管理', '丙刊', '信息科学', ''],
            'weight': [3.0, 2.0, 5.0, 1.0, 1.0, 4.0],
        }
    )


@pytest.fixture
def variation_frame():
    return pd.DataFrame(
        {
            '节点': ['甲', '甲', '乙', '乙'],
            '起始年': [2020, 2021, 2020, 2021],
            '结束年': [2021, 2022, 2021, 2022],
            '结构变化': [1.0, 0.311278, 0.5, 0.02],
            '前邻居': [1, 1, 2, 3],
            '后邻居': [1, 2, 1, 2],
            '新增邻居': ['丙', '乙', '', '丁'],
            '消失邻居': ['乙', '', '甲', ''],
        }
    )


@pytest.mark.parametrize('chart_type', BIBLIO_CHART_TYPES)
def test_each_view_builds_and_is_json_safe(frame, dual_frame, variation_frame, chart_type):
    source = variation_frame if chart_type == 'variation' else (dual_frame if chart_type == 'dual_map' else frame)
    option = VisualizationService.to_echarts_option(source, chart_type, title='知识图谱')
    assert option['series']
    assert json.dumps(option, allow_nan=False)
    assert option['title']['text'] == '知识图谱'


def test_dual_map_draws_a_node_that_has_only_an_overlay_link(dual_frame):
    """The table lists its nodes with an empty 终点; a journal reached by nothing but one
    overlay line is still a node, and dropping it hides the sparse end of a real dual map."""
    option = VisualizationService.to_echarts_option(dual_frame, 'dual_map')
    names = {node['name'] for node in option['series'][0]['data']}
    assert {'甲刊', '乙刊', '丙刊', '公共管理', '信息科学'} <= names
    assert '丁刊' in names


def test_dual_map_legend_names_the_two_sides_it_draws(dual_frame):
    option = VisualizationService.to_echarts_option(dual_frame, 'dual_map')
    categories = [entry['name'] for entry in option['series'][0]['categories']]
    assert option['legend']['data'] == categories
    assert len(categories) == 2


def test_knowledge_graph_deduplicates_an_undirected_edge(frame):
    option = VisualizationService.to_echarts_option(frame, 'knowledge_graph')
    links = option['series'][0]['links']
    assert len(links) == 1
    assert {links[0]['source'], links[0]['target']} == {'甲', '乙'}


def test_a_missing_fixed_column_is_named(frame):
    broken = frame.drop(columns=['连接'])
    with pytest.raises(ChartConfigError, match='连接'):
        VisualizationService.to_echarts_option(broken, 'knowledge_graph')


def test_a_graph_without_links_is_not_drawn(frame):
    broken = frame.assign(连接='[]')
    with pytest.raises(ChartConfigError):
        VisualizationService.to_echarts_option(broken, 'knowledge_graph')


def test_timeline_needs_cluster_columns(frame):
    broken = frame.drop(columns=['聚类', '聚类标签'])
    with pytest.raises(ChartConfigError):
        VisualizationService.to_echarts_option(broken, 'cluster_timeline')


def test_dual_map_names_a_missing_basemap_column(frame):
    with pytest.raises(ChartConfigError, match='map'):
        VisualizationService.to_echarts_option(frame, 'dual_map')


def test_burst_without_any_burst_is_refused(frame):
    broken = frame.assign(突现强度=0.0)
    with pytest.raises(ChartConfigError):
        VisualizationService.to_echarts_option(broken, 'burst')


class TestVariationView:
    def test_the_marker_carries_the_score_and_the_pair(self, variation_frame):
        option = VisualizationService.to_echarts_option(variation_frame, 'variation')
        series = option['series'][0]
        assert series['type'] == 'scatter'
        # value = [pair index, node index, score, node, gained, lost]
        assert {tuple(item['value'])[:1] for item in series['data']}
        assert option['visualMap']['min'] == 0
        assert option['visualMap']['max'] == 1.0

    def test_a_bigger_change_draws_a_bigger_marker(self, variation_frame):
        option = VisualizationService.to_echarts_option(variation_frame, 'variation')
        by_score = sorted(option['series'][0]['data'], key=lambda item: item['value'][2])
        sizes = [item['symbolSize'] for item in by_score]
        assert sizes == sorted(sizes), f'marker size must follow the score: {sizes}'

    def test_a_node_that_only_moved_once_still_gets_its_row(self):
        """A node that moved in one pair and not in the other is still a mover; keeping only
        nodes that moved repeatedly would quietly turn the figure into a story about the
        persistent nodes."""
        import pandas as pd

        frame = pd.DataFrame(
            {
                '节点': ['甲', '甲', '丙'],
                '起始年': [2020, 2021, 2021],
                '结束年': [2021, 2022, 2022],
                '结构变化': [1.0, 0.3, 0.7],
                '前邻居': [1, 1, 2],
                '后邻居': [1, 2, 1],
                '新增邻居': ['丙', '乙', ''],
                '消失邻居': ['乙', '', '甲'],
            }
        )
        option = VisualizationService.to_echarts_option(frame, 'variation')
        assert '丙' in option['yAxis']['data']
        assert '丙' not in option['xAxis']['data']

    def test_the_column_is_capped_and_the_cap_names_itself(self):
        import pandas as pd

        from services.chart_contracts import VARIATION_ROW_LIMIT

        rows = [
            {
                '节点': f'词{i}',
                '起始年': 2020,
                '结束年': 2021,
                '结构变化': 0.9 - i * 0.001,
                '前邻居': 1,
                '后邻居': 2,
                '新增邻居': '乙',
                '消失邻居': '甲',
            }
            for i in range(VARIATION_ROW_LIMIT + 12)
        ]
        option = VisualizationService.to_echarts_option(pd.DataFrame(rows), 'variation')
        assert len(option['yAxis']['data']) == VARIATION_ROW_LIMIT
        # The strongest movers are the ones kept, not the first rows of the table.
        assert option['yAxis']['data'][0] == '词0'

    def test_a_table_with_no_scored_move_refuses_by_name(self):
        import pandas as pd

        empty = pd.DataFrame(
            {
                '节点': ['甲'],
                '起始年': [2020],
                '结束年': [2021],
                '结构变化': [0.0],
                '前邻居': [1],
                '后邻居': [1],
                '新增邻居': [''],
                '消失邻居': [''],
            }
        )
        with pytest.raises(ChartConfigError) as exc:
            VisualizationService.to_echarts_option(empty, 'variation')
        assert 'variation_min' in str(exc.value) or 'variation' in str(exc.value)

    def test_a_frame_without_the_variation_columns_refuses_naming_the_column(self, frame):
        with pytest.raises(ChartConfigError) as exc:
            VisualizationService.to_echarts_option(frame, 'variation')
        assert '结构变化' in str(exc.value)
