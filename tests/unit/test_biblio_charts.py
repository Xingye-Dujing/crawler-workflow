"""The bibliometric ECharts views and their named refusals."""

import json
import math

import pandas as pd
import pytest

from services.charts.contracts import BIBLIO_CHART_TYPES
from services.charts.visualizer import ChartConfigError, VisualizationService

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


@pytest.fixture
def geo_frame():
    """A ``country`` graph's node table: real region names, and one the basemap cannot place.

    The spellings are deliberately mixed (``China`` beside ``Peoples R China``, ``England`` on its
    own) because that is what a WoS export actually contains, and the map has to fold them into
    one region while SAYING it did.
    """
    return pd.DataFrame(
        {
            '节点': ['China', 'Peoples R China', 'United States', 'England', 'Atlantis'],
            'x': [0.0, 10.0, 20.0, 30.0, 40.0],
            'y': [0.0, 10.0, 20.0, 30.0, 40.0],
            '连接': ['[]'] * 5,
            '频次': [30, 5, 22, 9, 3],
        }
    )


@pytest.fixture
def overlay_frame():
    """A node table with both overlay columns, plus one node carrying no label at all.

    甲的 documents split 6/3/1 across positive/neutral/negative; 丁 was mentioned only by
    documents the upstream step never labelled, so it must be left off the figures and named.
    """
    return pd.DataFrame(
        {
            '节点': ['甲', '乙', '丙', '丁'],
            '频次': [10, 8, 6, 3],
            '情感倾向': ['positive', 'negative', 'neutral', ''],
            '情感分布': [
                json.dumps({'positive': 6, 'neutral': 3, 'negative': 1}),
                json.dumps({'negative': 5, 'neutral': 2, 'positive': 1}),
                json.dumps({'neutral': 4, 'positive': 1}),
                '{}',
            ],
            '主导话题': ['T1', 'T2', 'T1', ''],
            '话题分布': [
                json.dumps({'T1': 7, 'T2': 3}),
                json.dumps({'T2': 6, 'T1': 1}),
                json.dumps({'T1': 5}),
                '{}',
            ],
        }
    )


@pytest.mark.parametrize('chart_type', BIBLIO_CHART_TYPES)
def test_each_view_builds_and_is_json_safe(frame, dual_frame, variation_frame, geo_frame, overlay_frame, chart_type):
    by_shape = {
        'variation': variation_frame,
        'dual_map': dual_frame,
        'geo_map': geo_frame,
        'sentiment_overlay': overlay_frame,
        'topic_overlay': overlay_frame,
    }
    source = by_shape.get(chart_type, frame)
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
        from services.charts.contracts import VARIATION_ROW_LIMIT

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


class TestTheReplayData:
    """The browser replays the network slice by slice, and the only honest source for that is the
    node table's own ``年份序列``. Shipping it inside the option means one request, one artifact,
    and a frame that cannot disagree with the figure it was cut from."""

    @staticmethod
    def _by_name(option):
        return {node['name']: node for node in option['series'][0]['data']}

    def test_a_graph_node_carries_its_year_counts_oldest_first(self, frame):
        option = VisualizationService.to_echarts_option(frame, 'knowledge_graph')
        assert self._by_name(option)['甲']['yearSeries'] == [[2020, 1.0], [2021, 2.0]]
        assert self._by_name(option)['乙']['yearSeries'] == [[2020, 2.0]]

    def test_a_table_without_the_series_column_still_draws_and_ships_nothing_to_replay(self, frame):
        """``年份序列`` is not one of this view's required columns, so a hand-made table stays
        drawable — and the play bar has to be able to tell "no series" from "series of zeroes"."""
        option = VisualizationService.to_echarts_option(frame.drop(columns=['年份序列']), 'knowledge_graph')
        assert all('yearSeries' not in node for node in self._by_name(option).values())

    def test_a_node_that_was_never_counted_in_any_year_ships_no_frame(self, frame):
        empty = frame.assign(年份序列=['{}', '{}', '{}'])
        option = VisualizationService.to_echarts_option(empty, 'knowledge_graph')
        assert all('yearSeries' not in node for node in self._by_name(option).values())

    def test_a_malformed_series_is_refused_by_name_rather_than_played_as_absent(self, frame):
        broken = frame.assign(年份序列=['{not json', '{}', '{}'])
        with pytest.raises(ChartConfigError) as err:
            VisualizationService.to_echarts_option(broken, 'knowledge_graph')
        assert '年份序列' in str(err.value)

    def test_the_circular_view_replays_from_the_same_field(self, frame):
        """Both graph layouts share the node builder, so a frame cut from either one is the same
        network — a second copy of the series would be a second answer to the same question."""
        option = VisualizationService.to_echarts_option(frame, 'circular')
        assert self._by_name(option)['丙']['yearSeries'] == [[2021, 1.0]]


class TestTheGeoMap:
    """The choropleth's promises are about names, not pixels: what it merges, what it refuses to
    place, and where it says so."""

    def test_several_spellings_of_one_region_are_one_value(self, geo_frame):
        option = VisualizationService.to_echarts_option(geo_frame, 'geo_map')
        data = {item['name']: item['value'] for item in option['series'][0]['data']}
        assert data['中华人民共和国'] == 35.0, 'China + Peoples R China are one region, not two'
        assert 'Peoples R China' not in ' '.join(data)
        assert len(data) == 3, f'Atlantis is not a region, so it is not a row either: {data}'

    def test_what_the_basemap_cannot_place_is_named_on_the_figure(self, geo_frame):
        """A region missing from a choropleth reads as "that country published nothing" — the one
        mistake a map must not make quietly."""
        option = VisualizationService.to_echarts_option(geo_frame, 'geo_map')
        subtext = option['title']['subtext']
        assert 'Atlantis' in subtext
        assert 'England→英国' in subtext, 'a fold into a bigger region is said too'

    def test_only_the_leading_regions_are_labelled(self, geo_frame):
        option = VisualizationService.to_echarts_option(geo_frame, 'geo_map')
        assert all(item['label']['show'] for item in option['series'][0]['data']), 'a small set still labels'

    def test_the_run_language_picks_both_the_keying_and_the_labels(self, geo_frame):
        from i18n import set_lang

        try:
            set_lang('en')
            option = VisualizationService.to_echarts_option(geo_frame, 'geo_map')
        finally:
            set_lang('zh')
        series = option['series'][0]
        assert series['map'] == 'world' and series['nameProperty'] == 'name'
        assert {item['name'] for item in series['data']} == {'China', 'United States of America', 'United Kingdom'}

    def test_a_table_of_things_that_are_not_countries_refuses_and_shows_what_it_read(self):
        frame = pd.DataFrame({'节点': ['甲', '乙'], '频次': [3, 2]})
        with pytest.raises(ChartConfigError) as err:
            VisualizationService.to_echarts_option(frame, 'geo_map')
        assert '甲' in str(err.value), 'the refusal quotes the names it could not place'

    def test_the_colour_scale_spans_the_largest_region(self, geo_frame):
        option = VisualizationService.to_echarts_option(geo_frame, 'geo_map')
        assert option['visualMap']['min'] == 0
        assert option['visualMap']['max'] == 35.0


class TestOverlayViews:
    """Sentiment and topic overlays: the two views that read columns only an overlay writes."""

    def test_sentiment_bars_split_each_node_into_one_hundred_percent(self, overlay_frame):
        option = VisualizationService.to_echarts_option(overlay_frame, 'sentiment_overlay')
        series = option['series']
        assert [s['type'] for s in series] == ['bar', 'bar', 'bar']
        assert all(s['stack'] == 'overlay' for s in series)
        by_name = {
            name: [series[i]['data'][index]['value'] for i in (0, 1, 2)]
            for index, name in enumerate(option['yAxis']['data'])
        }
        assert by_name['甲'] == [10.0, 30.0, 60.0], 'negative → neutral → positive, not frequency order'
        for shares in by_name.values():
            assert round(sum(shares), 2) == 100.0

    def test_polarity_is_ordered_by_meaning_not_frequency(self, overlay_frame):
        from i18n import t

        option = VisualizationService.to_echarts_option(overlay_frame, 'sentiment_overlay')
        assert [s['name'] for s in option['series']] == [
            t('chart.value.negative'),
            t('chart.value.neutral'),
            t('chart.value.positive'),
        ]
        # 甲 has more positive documents than negative ones, and it is still drawn on top
        # because the figure ranks by positive SHARE (60 %), not by count or alphabet.
        assert option['yAxis']['data'][0] == '甲'

    def test_a_node_without_any_label_is_dropped_and_counted(self, overlay_frame):
        option = VisualizationService.to_echarts_option(overlay_frame, 'sentiment_overlay')
        assert '丁' not in option['yAxis']['data'], 'a row of zeros would read as "measured, and zero"'
        assert '1' in option['title']['subtext']

    def test_a_label_set_that_is_not_polarity_keeps_frequency_order(self):
        from i18n import t

        frame = pd.DataFrame(
            {
                '节点': ['甲', '乙'],
                '情感分布': [
                    json.dumps({'Joy': 1, 'Anger': 4}),
                    json.dumps({'Sadness': 2, 'Anger': 1}),
                ],
            }
        )
        option = VisualizationService.to_echarts_option(frame, 'sentiment_overlay')
        assert [s['name'] for s in option['series']] == [
            t('chart.value.anger'),
            t('chart.value.sadness'),
            t('chart.value.joy'),
        ]

    def test_topic_cells_are_the_share_of_that_nodes_labelled_documents(self, overlay_frame):
        option = VisualizationService.to_echarts_option(overlay_frame, 'topic_overlay')
        series = option['series'][0]
        names = option['yAxis']['data']
        topics = option['xAxis']['data']
        cells = {(names[int(v[1])], topics[int(v[0])]): v[2] for v in (item['value'] for item in series['data'])}
        assert cells[('甲', 'T1')] == 70.0
        assert cells[('乙', 'T2')] == 85.71
        assert option['visualMap']['max'] == 100

    def test_both_axes_are_capped_and_the_note_says_so(self):
        from services.charts.contracts import OVERLAY_ROW_LIMIT, OVERLAY_TOPIC_LIMIT

        rows = []
        for index in range(OVERLAY_ROW_LIMIT + 4):
            rows.append(
                {
                    '节点': f'词{index}',
                    '话题分布': json.dumps({f'T{topic}': index + topic for topic in range(OVERLAY_TOPIC_LIMIT + 3)}),
                }
            )
        option = VisualizationService.to_echarts_option(pd.DataFrame(rows), 'topic_overlay')
        assert len(option['yAxis']['data']) == OVERLAY_ROW_LIMIT
        assert len(option['xAxis']['data']) == OVERLAY_TOPIC_LIMIT
        assert '话题' in option['title']['subtext'] and '节点' in option['title']['subtext']

    def test_a_missing_overlay_column_is_refused_by_name(self, overlay_frame):
        with pytest.raises(ChartConfigError, match='情感分布'):
            VisualizationService.to_echarts_option(overlay_frame.drop(columns=['情感分布']), 'sentiment_overlay')
        with pytest.raises(ChartConfigError, match='话题分布'):
            VisualizationService.to_echarts_option(overlay_frame.drop(columns=['话题分布']), 'topic_overlay')

    def test_a_table_where_every_node_lacks_a_label_is_refused(self):
        frame = pd.DataFrame({'节点': ['甲', '乙'], '情感分布': ['{}', '{}']})
        with pytest.raises(ChartConfigError):
            VisualizationService.to_echarts_option(frame, 'sentiment_overlay')

    def test_a_malformed_distribution_is_refused_rather_than_read_as_absent(self, overlay_frame):
        broken = overlay_frame.assign(情感分布=['not json'] * len(overlay_frame))
        with pytest.raises(ChartConfigError, match='情感分布'):
            VisualizationService.to_echarts_option(broken, 'sentiment_overlay')


class TestTheConcentricRings:
    """Rings by first-appearance year, oldest at the centre, frequency running clockwise."""

    @staticmethod
    def _radii(option):
        return {item['name']: round(math.hypot(item['x'], item['y']), 6) for item in option['series'][0]['data']}

    def test_rings_are_cut_by_first_year_inside_out(self, frame):
        option = VisualizationService.to_echarts_option(frame, 'concentric')
        radii = self._radii(option)
        assert radii['甲'] == pytest.approx(1.0) and radii['乙'] == pytest.approx(1.0)
        assert radii['丙'] == pytest.approx(2.0), 'the 2021 node belongs on the second ring out'
        assert option['series'][0]['categories'] == [{'name': '2020'}, {'name': '2021'}]

    def test_the_subtext_names_the_ring_rule(self, frame):
        option = VisualizationService.to_echarts_option(frame, 'concentric')
        assert option['title']['subtext']
        assert '2' in option['title']['subtext']

    def test_within_a_ring_the_most_frequent_node_starts_at_angle_zero(self, frame):
        option = VisualizationService.to_echarts_option(frame, 'concentric')
        item = next(entry for entry in option['series'][0]['data'] if entry['name'] == '甲')
        assert item['x'] == pytest.approx(1.0)
        assert abs(item['y']) < 1e-6

    def test_a_node_without_any_year_gets_its_own_outer_ring(self):
        from i18n import t

        frame = pd.DataFrame(
            {
                '节点': ['甲', '丙'],
                '连接': [
                    json.dumps([{'target': '丙', 'value': 1.0}], ensure_ascii=False),
                    json.dumps([{'target': '甲', 'value': 1.0}], ensure_ascii=False),
                ],
                '频次': [3, 1],
                '年份序列': [json.dumps({'2020': 3}), '{}'],
            }
        )
        option = VisualizationService.to_echarts_option(frame, 'concentric')
        labels = [category['name'] for category in option['series'][0]['categories']]
        assert labels == ['2020', t('chart.biblio_ring_unknown')]
        assert self._radii(option)['丙'] == pytest.approx(2.0), 'the yearless node sits on the outer ring'

    def test_a_table_without_year_data_refuses_by_name(self):
        frame = pd.DataFrame(
            {
                '节点': ['甲', '丙'],
                '连接': [
                    json.dumps([{'target': '丙', 'value': 1.0}], ensure_ascii=False),
                    json.dumps([{'target': '甲', 'value': 1.0}], ensure_ascii=False),
                ],
                '频次': [3, 1],
                '年份序列': ['{}', '{}'],
            }
        )
        with pytest.raises(ChartConfigError, match='年份'):
            VisualizationService.to_echarts_option(frame, 'concentric')
