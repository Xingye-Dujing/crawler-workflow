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


@pytest.mark.parametrize('chart_type', BIBLIO_CHART_TYPES)
def test_each_view_builds_and_is_json_safe(frame, dual_frame, chart_type):
    source = dual_frame if chart_type == 'dual_map' else frame
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
