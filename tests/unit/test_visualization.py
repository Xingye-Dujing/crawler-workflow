"""Tests for services/visualizer.py — the chart-spec builder.

Two renderers sit behind one entry point, and the frontend consumes the
ECharts option as raw JSON, so the contracts that matter are:

- the option is *always* JSON-serialisable (a lone ``NaN`` token makes the
  browser reject the whole response),
- a spec that cannot be built fails as ``ChartConfigError`` naming the field,
  rather than as a pandas ``KeyError`` deep in a node,
- the matplotlib renderer refuses chart types it has no equivalent for,
  instead of drawing something misleading.
"""

import base64
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from services.visualizer import ANNOTATED_TYPES, CHART_TYPES, ECHARTS_ONLY_TYPES, ChartConfigError
from services.visualizer import VisualizationService as V

pytestmark = pytest.mark.unit

_WORKFLOW_JS = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js' / 'workflow.js'


def _js_list(text: str, name: str) -> list:
    """The quoted members of ``var NAME = […];`` in the browser's copy of a list."""
    declaration = re.search(rf'var {name} = \[([^\]]*)\];', text)
    assert declaration, f'workflow.js no longer declares {name} as a flat array'
    return re.findall(r"'([^']*)'", declaration.group(1))


# One usable spec per chart type, so the happy path can be swept in one test.
USABLE = {
    'bar': {'x': '作者', 'y': '点赞'},
    'line': {'x': '作者', 'y': '点赞'},
    'dual_line': {'x': '作者', 'y': '点赞', 'y2': '阅读'},
    'stack_pct': {'x': '作者', 'stack_fields': '点赞,阅读'},
    'topic_map': {'x': '点赞', 'y': '阅读'},
    'topic_terms': {'x': '作者', 'y': '点赞', 'y2': '阅读'},
    'pie': {'x': '作者', 'y': '点赞'},
    'scatter': {'x': '点赞', 'y': '阅读'},
    'histogram': {'x': '点赞'},
    'box': {'x': '作者', 'y': '点赞'},
    'heatmap': {'x': '作者', 'y': '平台'},
    'sankey': {'x': '作者', 'y': '平台'},
    'network': {'x': '作者', 'y': '平台'},
    'wordcloud': {'x': '作者'},
    'map': {'x': '作者', 'value_field': '点赞'},
}

# Group keys sort by code point, which is why 丙 precedes 乙 precedes 甲 here.
#: The category axis keeps the TABLE's order — first appearance, not code-point order. This
#: constant used to read ['丙', '乙', '甲'], which was the fixture's rows re-sorted by
#: `_aggregate`'s `sort_index()`. That is the bug 图 3 showed: a phase table arrives sorted by
#: 阶段序号, and a chart that alphabetises the axis puts 一次爆发期 in the first bar while the
#: figure still looks complete.
LABELS = ['甲', '乙', '丙']


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            '作者': ['甲', '乙', '甲', '丙'],
            '平台': ['知乎', '微博', '知乎', '小红书'],
            '点赞': [10.0, 25.0, 5.0, 40.0],
            '阅读': [100, 200, 300, 400],
        }
    )


# ─── catalogue ─────────────────────────────────────────────────────────


class TestChartCatalogue:
    def test_every_advertised_type_can_build_an_option(self, df):
        assert set(USABLE) == set(CHART_TYPES)
        for chart_type, kwargs in USABLE.items():
            assert V.to_echarts_option(df, chart_type, **kwargs)['series'], chart_type

    def test_echarts_only_types_are_a_subset_of_the_catalogue(self):
        assert set(ECHARTS_ONLY_TYPES) < set(CHART_TYPES)

    def test_the_browser_advertises_exactly_the_types_this_builds(self):
        """``workflow.js`` keeps its own copy of both lists, and the two drift apart in the
        one direction no test on the Python side can see: a panel that offers 双轴折线 while
        the service does not know the name hands the user an opaque node failure, and a panel
        that hides a type the service draws is a feature nobody finds."""
        text = _WORKFLOW_JS.read_text(encoding='utf-8')
        assert _js_list(text, 'CHART_TYPES') == list(CHART_TYPES)
        assert _js_list(text, 'ECHARTS_ONLY_CHARTS') == list(ECHARTS_ONLY_TYPES)

    def test_the_browser_offers_event_markers_only_where_they_are_drawn(self):
        # The same drift in the other direction: a box the figure cannot honour is a date the
        # reader of the exported PNG believes is on the curve and never was.
        text = _WORKFLOW_JS.read_text(encoding='utf-8')
        assert _js_list(text, 'CHARTS_WITH_ANNOTATIONS') == list(ANNOTATED_TYPES)


class TestEventMarkers:
    """Dated vertical lines — the reading the study hangs on its events.

    4 月 23 日的遗体打捞 and 5 月 19 日的通报 are what make a sentiment curve mean anything,
    and ECharts draws one as a ``markLine`` positioned by a CATEGORY. That single dependency
    is the whole risk: a date written differently from the axis label matches nothing and
    silently draws nothing, so the tests here pin the refusal as hard as the placement.
    """

    def test_each_marker_is_a_line_at_the_label_it_names(self, df):
        option = V.to_echarts_option(df, 'line', x='作者', y='点赞', annotations='甲=起点; 丙=终点')
        markers = option['series'][0]['markLine']
        assert [item['xAxis'] for item in markers['data']] == ['甲', '丙']
        assert [item['label']['formatter'] for item in markers['data']] == ['起点', '终点']
        assert markers['silent'] is True, 'a hovered point must not fight the event line'

    def test_a_marker_can_sit_on_the_left_axis_of_a_two_scale_figure(self, df):
        # The line belongs to the shared category axis, so it rides the first series; putting
        # it on the right one would scale a vertical line against the wrong axis.
        option = V.to_echarts_option(df, 'dual_line', x='作者', y='点赞', y2='阅读', annotations='乙=通报')
        assert 'markLine' not in option['series'][1]
        assert option['series'][0]['markLine']['data'][0]['xAxis'] == '乙'

    def test_a_date_that_is_not_on_the_axis_lists_the_labels_that_are(self, df):
        with pytest.raises(ChartConfigError) as excinfo:
            V.to_echarts_option(df, 'line', x='作者', y='点赞', annotations='2024-04-23=遗体打捞')
        message = str(excinfo.value)
        assert 'is not a value of the x axis "作者"' in message
        for label in ('甲', '乙', '丙'):
            assert label in message, 'the refusal has to hand back the labels that would work'

    @pytest.mark.parametrize('text', ['甲', '甲|乙'])
    def test_a_chunk_with_no_separator_is_refused(self, df, text):
        with pytest.raises(ChartConfigError, match='not a "date=label" pair'):
            V.to_echarts_option(df, 'line', x='作者', y='点赞', annotations=text)

    def test_a_marker_with_no_label_of_its_own_is_named_by_its_date(self, df):
        markers = V.to_echarts_option(df, 'bar', x='作者', annotations='甲=')['series'][0]['markLine']
        assert markers['data'][0]['label']['formatter'] == '甲'

    def test_a_chart_without_a_category_axis_refuses_the_box(self, df):
        for chart_type in ('pie', 'scatter', 'heatmap'):
            with pytest.raises(ChartConfigError, match='cannot carry event markers'):
                V.to_echarts_option(df, chart_type, x='作者', y='点赞', annotations='甲=起点')

    def test_the_image_engine_refuses_markers_by_name(self, df):
        # Not a PNG with the dates missing: the renderer has no marker layer at all.
        with pytest.raises(ChartConfigError, match='engine=echarts'):
            V.render_image(df, 'bar', x='作者', y='点赞', annotations='甲=起点')

    def test_no_markers_means_no_marker_layer(self, df):
        option = V.to_echarts_option(df, 'line', x='作者', y='点赞')
        assert 'markLine' not in option['series'][0]
        assert 'markLine' not in V.to_echarts_option(df, 'line', x='作者', y='点赞', annotations='  ')


class TestRelationshipNetwork:
    """The co-occurrence and flow graphs: edges are the data, so no edges is a refusal."""

    def test_links_are_aggregated_and_nodes_carry_their_own_incident_weight(self, df):
        option = V.to_echarts_option(df, 'network', x='作者', y='平台', value_field='点赞')
        series = option['series'][0]
        assert series['type'] == 'graph' and series['layout'] == 'force'
        # 甲 appears twice, both against 知乎, so ONE edge carries the summed weight.
        assert {(link['source'], link['target']): link['value'] for link in series['links']} == {
            ('甲', '知乎'): 15.0,
            ('乙', '微博'): 25.0,
            ('丙', '小红书'): 40.0,
        }
        values = {node['name']: node['value'] for node in series['data']}
        assert values['甲'] == 15.0 and values['小红书'] == 40.0

    def test_size_and_width_follow_the_weight_rather_than_the_raw_number(self, df):
        # Radius proportional to value would make the busiest node look four times what it is;
        # the square root puts the eye back on the area, which is the same rule the topic map uses.
        option = V.to_echarts_option(df, 'network', x='作者', y='平台', value_field='点赞')
        series = option['series'][0]
        sizes = {node['name']: node['symbolSize'] for node in series['data']}
        assert sizes['甲'] < sizes['丙']
        assert (sizes['丙'] - 14.0) / (sizes['甲'] - 14.0) == pytest.approx((40.0 / 15.0) ** 0.5, abs=0.02)
        widths = {(link['source'], link['target']): link['lineStyle']['width'] for link in series['links']}
        assert widths[('丙', '小红书')] > widths[('甲', '知乎')]

    def test_the_layout_starts_circular_so_two_runs_of_one_table_agree(self, df):
        force = V.to_echarts_option(df, 'network', x='作者', y='平台')['series'][0]['force']
        assert force['initLayout'] == 'circular'

    def test_a_graph_with_no_edge_is_refused_not_drawn_empty(self):
        frame = pd.DataFrame({'s': ['a', 'b'], 't': ['x', 'y'], 'v': [None, None]})
        with pytest.raises(ChartConfigError, match='no edges'):
            V.to_echarts_option(frame, 'network', x='s', y='t', value_field='v')

    def test_nested_edge_styles_are_json_safe(self, df):
        option = V.to_echarts_option(df, 'network', x='作者', y='平台', value_field='点赞')
        assert json.dumps(option, allow_nan=False)
        assert all(isinstance(link['lineStyle']['width'], float) for link in option['series'][0]['links'])

    def test_both_field_names_are_required_and_addressable(self, df):
        with pytest.raises(ChartConfigError, match='requires a source field'):
            V.to_echarts_option(df, 'network', x='作者')
        with pytest.raises(ChartConfigError, match='Field not found in the data'):
            V.to_echarts_option(df, 'network', x='作者', y='不存在的列')


class TestDualAxisLine:
    """热度 and 强度 on one figure — the paper's inverse relationship, as a spec.

    The one thing a single-axis chart cannot say is that the taller bar and the colder
    sentiment belong to different phases, so the two series must be scaled independently
    while sharing one category axis. ECharts reads that as ``yAxis`` being a LIST plus a
    ``yAxisIndex`` on every series, which is what is pinned here rather than how it looks.
    """

    def test_each_series_is_scaled_by_its_own_axis(self, df):
        option = V.to_echarts_option(df, 'dual_line', x='作者', y='点赞', y2='阅读')
        assert [axis['name'] for axis in option['yAxis']] == ['点赞', '阅读']
        assert [series['yAxisIndex'] for series in option['series']] == [0, 1]
        assert option['legend']['data'] == ['点赞', '阅读']
        # Both series land on the same categories, in the order the rows first showed them.
        assert [series['data'] for series in option['series']] == [[15.0, 25.0, 40.0], [400, 200, 400]]

    def test_the_right_axis_draws_no_second_graph_paper(self, df):
        # Two sets of dashed grid lines at different scales is unreadable, and the left axis
        # is the one the eye measures against.
        option = V.to_echarts_option(df, 'dual_line', x='作者', y='点赞', y2='阅读')
        assert option['yAxis'][1]['position'] == 'right'
        assert option['yAxis'][1]['splitLine'] == {'show': False}
        assert 'lineStyle' in option['yAxis'][0]['splitLine'], 'the left axis keeps its grid'

    def test_an_empty_left_field_counts_rows_rather_than_defaulting_to_zero(self, df):
        # 舆情热度 is exactly "how many rows this period has", which is why 左轴 may be left
        # blank — and the legend has to say what it then drew. The display name is localised
        # for the run's language; under zh the fallback reads 数量（作者） not count(作者).
        option = V.to_echarts_option(df, 'dual_line', x='作者', y2='阅读')
        assert option['series'][0]['name'] == '数量（作者）'
        assert option['series'][0]['data'] == [2, 1, 1]

    def test_the_image_engine_refuses_the_type_by_name(self, df):
        # Matplotlib could draw a twinx, but the shared tooltip, the legend and the second
        # scale are the readable half of this figure; two engines drawing one spec
        # differently is how a chart starts meaning something else in a report.
        with pytest.raises(ChartConfigError, match='engine=echarts'):
            V.render_image(df, 'dual_line', x='作者', y='点赞')


class TestTopicFigureCharts:
    """The two panels of the pyLDAvis figure, drawn from the tables the analysis steps write.

    These types read the column names their steps emit, so the pair is a contract: a renamed
    column must refuse by name rather than draw an empty figure, and the geometry that carries
    the meaning (bubble AREA, rank-1-on-top) is exactly what a generic scatter or bar would get
    wrong.
    """

    MAP = pd.DataFrame(
        {
            'topic': ['Topic-1', 'Topic-2', 'Topic-3'],
            'pc1': [-0.4, 0.35, 0.05],
            'pc2': [0.2, -0.3, 0.42],
            'prevalence_pct': [12.5, 62.5, 25.0],
        }
    )

    TERMS = pd.DataFrame(
        {
            'topic': ['Topic-1'] * 3,
            'rank': [1, 2, 3],
            'term': ['通报', '警方', '人肉'],
            'overall_freq': [40, 8, 6],
            'within_freq': [14.2, 7.5, 0.4],
        }
    )

    def test_bubbles_are_placed_labelled_and_sized_by_area(self):
        option = V.to_echarts_option(
            self.MAP, 'topic_map', x='pc1', y='pc2', label_field='topic', value_field='prevalence_pct'
        )
        series = option['series'][0]
        assert [point['value'] for point in series['data']] == [[-0.4, 0.2], [0.35, -0.3], [0.05, 0.42]]
        assert [point['name'] for point in series['data']] == ['主题-1', '主题-2', '主题-3'], (
            'Topic-N (the model numbering) is displayed as 主题N under zh; the raw value is unchanged'
        )
        assert series['label']['show'] is True and series['label']['formatter'] == '{b}'
        sizes = [point['symbolSize'] for point in series['data']]
        assert sizes[0] < sizes[2] < sizes[1], 'the bubble order follows the share, monotonically'
        # Area, not radius: the 62.5% bubble is 2.5× the 25% one in AREA, so its radius grows
        # by the square root — a linear scale would read as 2.5× the width, i.e. 6× the area.
        assert (sizes[1] / sizes[2]) ** 2 == pytest.approx(62.5 / 25.0, rel=0.02)

    def test_the_map_draws_the_reference_lines_the_reader_measures_against(self):
        option = V.to_echarts_option(self.MAP, 'topic_map', x='pc1', y='pc2', label_field='topic')
        marks = option['series'][0]['markLine']['data']
        assert {'xAxis': 0} in marks and {'yAxis': 0} in marks
        assert option['xAxis']['name'] == '第一主坐标' and option['yAxis']['name'] == '第二主坐标'

    def test_a_map_without_label_or_size_columns_is_still_a_map(self):
        # Both extras degrade to "uniform bubbles", because a map whose bubbles are all the
        # same size still answers WHERE the topics are; only the coordinates are required.
        option = V.to_echarts_option(self.MAP, 'topic_map', x='pc1', y='pc2', label_field='', value_field='')
        series = option['series'][0]
        assert len(series['data']) == 3
        assert series['label']['show'] is False, 'no label column, no invented labels'
        assert {point['symbolSize'] for point in series['data']} == {10.0}

    def test_the_terms_panel_bars_both_counts_on_one_shared_scale(self):
        option = V.to_echarts_option(self.TERMS, 'topic_terms', x='term', y='overall_freq', y2='within_freq')
        assert option['yAxis']['type'] == 'category'
        assert option['yAxis']['data'] == ['通报', '警方', '人肉']
        assert option['yAxis']['inverse'] is True, 'rank 1 reads at the top'
        assert option['xAxis']['type'] == 'value', 'both series share one count axis'
        assert [series['name'] for series in option['series']] == ['总体词频', '主题内词频']
        assert option['series'][0]['data'] == [40, 8, 6]
        assert option['series'][1]['data'] == [14.2, 7.5, 0.4]

    def test_a_renamed_column_refuses_instead_of_drawing_nothing(self):
        with pytest.raises(ChartConfigError, match='Field not found in the data: 词'):
            V.to_echarts_option(self.TERMS, 'topic_terms', x='词', y='overall_freq', y2='within_freq')

    def test_both_types_are_refused_by_the_image_engine(self):
        # The refusal happens before any column is read, so the same frame answers both.
        for chart_type in ('topic_map', 'topic_terms'):
            with pytest.raises(ChartConfigError, match='engine=echarts'):
                V.render_image(self.MAP, chart_type, x='pc1', y='pc2')


class TestChartDisplayLocalisation:
    """Charts render in the run's language; the stored column names and label values never change.

    A humanities paper reads its own figures in Chinese, so a Chinese run must not print
    Total / positive / PC1 — but the DataFrame keeps English columns and English analyzer labels
    (the input contract every node depends on), and an English run must still read English.
    :func:`_localize_label` is the single place a controlled token becomes display text; everything
    else passes through, because category values are unbounded and guessing at one is worse than
    leaving it.
    """

    def _map(self):
        return pd.DataFrame(
            {
                'topic': ['Topic-1', 'Topic-2'],
                'pc1': [-0.4, 0.35],
                'pc2': [0.2, -0.3],
                'prevalence_pct': [12.5, 62.5],
            }
        )

    def test_controlled_tokens_follow_the_run_language(self):
        from i18n import set_lang
        from services.visualizer import _localize_label as localize

        set_lang('zh')
        assert localize('total') == '发帖量'
        assert localize('positive') == '正面'
        assert localize('Topic-1') == '主题-1'
        assert localize('TopicⅠ-3') == '主题Ⅰ-3', 'the model numbering survives, the word does not'
        set_lang('en')
        assert localize('total') == 'Total'
        assert localize('positive') == 'Positive'
        assert localize('Topic-1') == 'Topic-1', 'an English run keeps the model numbering intact'

    def test_emotion_and_tendency_tokens_localize(self):
        """The emotion/tendency nodes write English categories (Anger, Praise/Affirmation) into
        stored columns; a chart of them must show the reader's own words in zh and the exact
        analyzer spelling in en — the same display-only contract as sentiment."""
        from i18n import set_lang
        from services.visualizer import _localize_label as localize

        set_lang('zh')
        assert localize('emotion') == '情绪'
        assert localize('tendency') == '倾向'
        assert localize('Anger') == '愤怒'
        assert localize('Surprise') == '惊讶'
        assert localize('Praise/Affirmation') == '赞扬/肯定'
        assert localize('Objective Statement') == '客观陈述'
        set_lang('en')
        assert localize('emotion') == 'Emotion'
        assert localize('Anger') == 'Anger', 'an English run keeps the analyzer label itself'
        assert localize('Praise/Affirmation') == 'Praise/Affirmation'

    def test_unknown_and_non_text_values_pass_through_untouched(self):
        from i18n import set_lang
        from services.visualizer import _localize_label as localize

        set_lang('zh')
        assert localize('2022-01-24') == '2022-01-24', 'a date is not a label to translate'
        assert localize('发酵期') == '发酵期', 'an already-Chinese phase is not re-translated'
        assert localize('') == ''
        assert localize('author') == 'author', 'a column the tool does not know is left alone'

    def test_topic_map_series_and_axes_are_chinese_in_a_zh_run(self):
        from i18n import set_lang

        set_lang('zh')
        option = V.to_echarts_option(
            self._map(), 'topic_map', x='pc1', y='pc2', label_field='topic', value_field='prevalence_pct'
        )
        assert option['series'][0]['name'] == '主题'
        assert option['xAxis']['name'] == '第一主坐标'
        assert option['yAxis']['name'] == '第二主坐标'

    def test_sankey_node_names_and_link_endpoints_localise_together(self):
        # A sankey joins a node list to links BY NAME; if one side localises and the other does
        # not, ECharts silently drops every link. Both go through the same map, so they agree.
        from i18n import set_lang

        set_lang('zh')
        df = pd.DataFrame({'emotion': ['positive', 'negative', 'positive'], 'stage': ['发酵期', '发酵期', '爆发期']})
        nodes, links = V._sankey_links(df, 'emotion', 'stage')
        assert {'正面', '负面', '发酵期', '爆发期'} == set(nodes)
        assert all(link['source'] in nodes and link['target'] in nodes for link in links), 'link names match node names'


# ─── option shape / JSON safety ────────────────────────────────────────


class TestOptionJsonSafety:
    @pytest.mark.parametrize('chart_type', CHART_TYPES)
    def test_options_are_json_serialisable(self, df, chart_type):
        option = V.to_echarts_option(df, chart_type, title='标题', **USABLE[chart_type])
        assert json.dumps(option, allow_nan=False)
        assert option['title']['text'] == '标题'

    def test_a_group_with_no_values_becomes_null_not_nan(self):
        frame = pd.DataFrame({'g': ['a', 'a', 'b'], 'v': [None, None, 3.0]})
        values = V.to_echarts_option(frame, 'bar', x='g', y='v', agg='mean')['series'][0]['data']
        assert values[0] is None
        assert json.dumps(values, allow_nan=False)

    @pytest.mark.parametrize('chart_type', [c for c in CHART_TYPES if c != 'network'])
    def test_a_frame_full_of_missing_numbers_still_serialises(self, chart_type):
        # ``network`` is out of this sweep for a reason, not by oversight: on a frame with no
        # usable numbers it has no edge to draw, and an edge-less graph is a refusal
        # (TestRelationshipNetwork) rather than a serialisable empty figure.
        frame = pd.DataFrame({'g': ['a', 'b'], 'v': [None, None]})
        # 双轴折线 and 显著词图 need their second field like any other type needs x: without
        # one they are a refused spec (pinned in TestConfigErrors), not a chart with a blank
        # second series.
        extra = {'y2': 'v'} if chart_type in ('dual_line', 'topic_terms') else {}
        if chart_type == 'stack_pct':
            extra = {'stack_fields': 'v'}
        option = V.to_echarts_option(frame, chart_type, x='g', y='v', value_field='v', **extra)
        assert json.dumps(option, allow_nan=False)

    def test_numpy_scalars_are_folded_into_python_numbers(self, df):
        option = V.to_echarts_option(df, 'heatmap', x='作者', y='平台')
        assert all(isinstance(cell[2], int) for cell in option['series'][0]['data'])

    def test_scatter_pairs_survive_json_as_lists(self, df):
        data = V.to_echarts_option(df, 'scatter', x='点赞', y='阅读')['series'][0]['data']
        assert data[0] == [10.0, 100]
        assert json.loads(json.dumps(data))[0] == [10.0, 100]

    def test_colours_come_from_the_shared_palette(self, df):
        option = V.to_echarts_option(df, 'bar', x='作者', y='点赞')
        # The print palette, not the old UI accent: a figure in a paper is read in ink, so the
        # first colour is a deep slate rather than dashboard blue.
        assert option['color'][0] == '#2C4E6B'
        assert option['backgroundColor'] == 'transparent'
        assert 'SimSun' in option['title']['textStyle']['fontFamily']

    def test_a_dense_category_axis_keeps_every_tick_and_makes_room_for_it(self, df):
        """The complaint was half a date, not an ugly colour.

        ECharts drops category labels to avoid crowding, and the default margins clipped what
        survived — so 图 2 showed every other day of an event whose whole point is the daily curve.
        """
        many = pd.DataFrame({'日期': [f'2022-01-{day:02d}' for day in range(1, 25)], '总数': range(24)})
        option = V.to_echarts_option(many, 'line', x='日期', y='总数')
        assert option['xAxis']['axisLabel']['interval'] == 0
        assert option['xAxis']['axisLabel']['rotate'] == 45
        assert option['xAxis']['axisLabel']['hideOverlap'] is False
        assert option['grid']['containLabel'] is True
        assert option['grid']['bottom'] >= 96

    def test_a_short_category_axis_is_not_forced_to_the_dense_rule(self, df):
        """The rotate/interval rule fires on crowding, not on every axis.

        A bar chart rotates its category labels by design (they are often long names); what the
        finalize pass adds is the *dense* case — a 24-day axis keeps every tick. So a short axis
        must not be told to show `interval: 0`, which is ECharts' own "drop labels" setting.
        """
        option = V.to_echarts_option(df, 'line', x='作者', y='点赞')
        assert option['xAxis']['axisLabel'].get('interval') != 0

    def test_a_line_is_drawn_as_measured_points_not_a_smoothed_shaded_hill(self, df):
        option = V.to_echarts_option(df, 'line', x='作者', y='点赞')
        series = option['series'][0]
        assert series['smooth'] is False, 'a spline invents the days between two measurements'
        assert 'areaStyle' not in series, 'the gradient under the line reads as a quantity that is not one'

    def test_a_force_graph_is_laid_out_before_it_is_shown(self, df):
        """图 16 used to drift for tens of seconds: ECharts iterates the solver on screen."""
        option = V.to_echarts_option(
            pd.DataFrame({'source': ['甲', '乙'], 'target': ['乙', '丙'], 'value': [3, 5]}),
            'network',
            x='source',
            y='target',
            value_field='value',
        )
        series = option['series'][0]
        assert series['force']['animate'] is False
        assert series['layoutAnimation'] is False
        assert series['force']['initLayout'] == 'circular'

    def test_a_category_axis_keeps_the_tables_own_order(self, df):
        """The 图 3 bug: 表 2 arrives in lifecycle order and the chart alphabetised it away."""
        phases = pd.DataFrame(
            {'阶段': ['二次爆发期', '发酵期', '波动期', '爆发期', '衰退期'], '发帖量': [4526, 3778, 4993, 4366, 623]}
        )
        option = V.to_echarts_option(phases, 'bar', x='阶段', y='发帖量')
        assert option['xAxis']['data'] == ['二次爆发期', '发酵期', '波动期', '爆发期', '衰退期']
        assert option['series'][0]['data'] == [4526, 3778, 4993, 4366, 623]

    def test_tooltip_trigger_follows_the_chart_kind(self, df):
        assert V.to_echarts_option(df, 'bar', x='作者')['tooltip']['trigger'] == 'axis'
        assert V.to_echarts_option(df, 'pie', x='作者')['tooltip']['trigger'] == 'item'


# ─── 100% stacked share (stack_pct) ───────────────────────────────────


class TestStackPct:
    """Every category is normalised to 100%, so the figure reads as shares of one whole.

    The chart is the one place a 情感演化 table (positive_pct / neutral_pct / negative_pct) becomes
    a picture, and the whole point is the CONTRAST between periods — so a period that does not add
    up to 100, an axis that alphabetises the phases, or a segment that keeps its English column
    name each breaks the reading, not just the looks.
    """

    @staticmethod
    def _periods():
        return pd.DataFrame(
            {
                '阶段': ['发酵期', '爆发期', '衰退期'],
                '积极': [10, 30, 20],
                '中性': [20, 40, 30],
                '消极': [70, 30, 50],
            }
        )

    def test_each_period_normalises_to_a_hundred_percent(self):
        option = V.to_echarts_option(self._periods(), 'stack_pct', x='阶段', stack_fields='积极,中性,消极')
        # Three series, one per stacked column, all on the same stack.
        assert len(option['series']) == 3
        assert all(s['stack'] == 'total' for s in option['series'])
        for i in range(3):
            shares = [s['data'][i] for s in option['series']]
            assert round(sum(shares), 1) == 100.0, f'{i} period does not add up: {shares}'

    def test_raw_counts_are_shown_as_shares_not_heights(self):
        # 1 of 4, 2 of 4, 3 of 4 — the column is a raw count, the figure must be a percentage.
        frame = pd.DataFrame({'g': ['a', 'b', 'c'], 'pos': [1, 2, 3], 'neg': [3, 2, 1]})
        option = V.to_echarts_option(frame, 'stack_pct', x='g', stack_fields='pos,neg')
        assert option['series'][0]['data'] == [25.0, 50.0, 75.0]

    def test_the_phases_keep_the_tables_own_order(self):
        # A phase table arrives in lifecycle order; alphabetising the axis would reorder the story.
        option = V.to_echarts_option(self._periods(), 'stack_pct', x='阶段', stack_fields='积极,中性,消极')
        assert option['xAxis']['data'] == ['发酵期', '爆发期', '衰退期']

    def test_the_y_axis_is_a_capped_share_scale(self):
        option = V.to_echarts_option(self._periods(), 'stack_pct', x='阶段', stack_fields='积极,中性,消极')
        assert option['yAxis']['max'] == 100
        assert option['yAxis']['name']

    def test_a_period_with_nothing_to_show_is_zero_not_a_crash(self):
        frame = pd.DataFrame({'g': ['a', 'b'], 'pos': [0, 2], 'neg': [0, 2]})
        option = V.to_echarts_option(frame, 'stack_pct', x='g', stack_fields='pos,neg')
        # Period 'a' sums to zero: shares become 0.0 rather than a division by zero / NaN token.
        assert option['series'][0]['data'][0] == 0.0
        assert json.dumps(option, allow_nan=False)

    def test_a_fullwidth_comma_in_the_field_box_is_understood(self):
        # Users paste Chinese separators; the box must split on ， as well as ,.
        option = V.to_echarts_option(self._periods(), 'stack_pct', x='阶段', stack_fields='积极，中性，消极')
        assert len(option['series']) == 3

    def test_the_segment_name_is_the_localised_column(self):
        from i18n import set_lang

        set_lang('zh')
        frame = pd.DataFrame(
            {'阶段': ['a', 'b'], 'positive_pct': [1, 2], 'neutral_pct': [2, 1], 'negative_pct': [3, 3]}
        )
        option = V.to_echarts_option(frame, 'stack_pct', x='阶段', stack_fields='positive_pct,neutral_pct,negative_pct')
        assert [s['name'] for s in option['series']] == ['积极占比', '中性占比', '消极占比']

    def test_the_axis_or_field_that_is_not_given_is_refused_by_name(self):
        with pytest.raises(ChartConfigError, match='requires a category field'):
            V.to_echarts_option(self._periods(), 'stack_pct', stack_fields='积极')
        with pytest.raises(ChartConfigError, match='requires stacked fields'):
            V.to_echarts_option(self._periods(), 'stack_pct', x='阶段')

    def test_a_stacked_column_that_is_not_in_the_data_is_reported(self):
        with pytest.raises(ChartConfigError, match='Field not found in the data'):
            V.to_echarts_option(self._periods(), 'stack_pct', x='阶段', stack_fields='积极,不存在')

    def test_the_matplotlib_renderer_draws_the_same_share(self):
        url = V.render_image(self._periods(), 'stack_pct', x='阶段', stack_fields='积极,中性,消极')
        assert url.startswith('data:image/png;base64,')
        assert base64.b64decode(url.split(',', 1)[1])[:8] == b'\x89PNG\r\n\x1a\n'

    def test_it_carries_the_paper_style_like_every_other_figure(self):
        # The 文科论文 pass (_print_style) runs over all options; a share chart is no exception —
        # no graph paper behind the bars, and the two axes that stay are drawn in ink.
        option = V.to_echarts_option(self._periods(), 'stack_pct', x='阶段', stack_fields='积极,中性,消极')
        for axis_key in ('xAxis', 'yAxis'):
            axis = option[axis_key]
            assert axis['splitLine']['show'] is False
            assert axis['axisLine']['show'] is True
            assert axis['axisLine']['lineStyle']['color'] == '#666'


# ─── aggregation semantics ─────────────────────────────────────────────


class TestAggregation:
    def test_bar_sums_the_value_field_per_category(self, df):
        option = V.to_echarts_option(df, 'bar', x='作者', y='点赞')
        assert option['xAxis']['data'] == LABELS
        assert option['series'][0]['data'] == [15.0, 25.0, 40.0]

    def test_counting_mode_when_no_value_field_is_given(self, df):
        assert V.to_echarts_option(df, 'bar', x='作者')['series'][0]['data'] == [2, 1, 1]

    @pytest.mark.parametrize(
        'agg, expected',
        [
            # One value per category, in the order the rows appear: 甲 (two rows), 乙, 丙.
            ('mean', [7.5, 25.0, 40.0]),
            ('max', [10.0, 25.0, 40.0]),
            ('min', [5.0, 25.0, 40.0]),
            ('count', [2.0, 1.0, 1.0]),
        ],
    )
    def test_alternative_aggregations(self, df, agg, expected):
        assert V.to_echarts_option(df, 'line', x='作者', y='点赞', agg=agg)['series'][0]['data'] == expected

    def test_pie_carries_named_slices_and_a_percentage_tooltip(self, df):
        option = V.to_echarts_option(df, 'pie', x='作者', y='点赞')
        assert {'name': '甲', 'value': 15.0} in option['series'][0]['data']
        assert '%' in option['tooltip']['formatter']
        assert option['legend']['data'] == LABELS

    def test_histogram_bins_count_the_observations(self, df):
        option = V.to_echarts_option(df, 'histogram', x='点赞')
        counts = option['series'][0]['data']
        assert sum(counts) == 4
        assert len(option['xAxis']['data']) == len(counts)

    def test_box_plot_emits_five_number_summaries_plus_the_points(self, df):
        option = V.to_echarts_option(df, 'box', x='作者', y='点赞')
        assert [series['type'] for series in option['series']] == ['boxplot', 'scatter']
        assert all(len(row) == 5 for row in option['series'][0]['data'])
        assert option['series'][1]['data'] == [[0, 40.0], [1, 25.0], [2, 10.0], [2, 5.0]]

    def test_box_plot_from_a_single_numeric_column(self, df):
        option = V.to_echarts_option(df, 'box', x='点赞')
        assert option['xAxis']['data'] == ['点赞']
        assert option['series'][0]['data'] == [[5.0, 8.75, 17.5, 28.75, 40.0]]

    def test_heatmap_cells_are_indexed_by_category_position(self, df):
        option = V.to_echarts_option(df, 'heatmap', x='作者', y='平台')
        assert option['xAxis']['data'] == LABELS
        assert option['yAxis']['data'] == ['知乎', '微博', '小红书']
        assert len(option['series'][0]['data']) == 9
        assert option['visualMap']['min'] <= option['visualMap']['max']

    def test_sankey_links_are_weighted_by_rows(self, df):
        links = V.to_echarts_option(df, 'sankey', x='作者', y='平台')['series'][0]['links']
        assert {'source': '甲', 'target': '知乎', 'value': 2.0} in links
        assert all(link['value'] > 0 for link in links)

    def test_sankey_drops_links_without_a_positive_weight(self):
        frame = pd.DataFrame({'s': ['a', 'b'], 't': ['x', 'y'], 'v': [0.0, None]})
        links = V.to_echarts_option(frame, 'sankey', x='s', y='t', value_field='v', agg='sum')['series'][0]['links']
        assert links == []

    def test_wordcloud_repeats_categories_with_counts(self, df):
        data = V.to_echarts_option(df, 'wordcloud', x='作者')['series'][0]['data']
        assert [item for item in data if item['name'] == '甲'][0]['value'] == 2

    def test_map_bounds_ignore_missing_values(self):
        frame = pd.DataFrame({'r': ['海南', '广东'], 'v': [None, 7.0]})
        option = V.to_echarts_option(frame, 'map', x='r', value_field='v', agg='mean')
        # The colour scale must not be poisoned by the group that has no data.
        assert option['visualMap']['max'] == 7.0
        values = {item['name']: item['value'] for item in option['series'][0]['data']}
        assert values == {'广东': 7.0, '海南': None}

    def test_unknown_wordcloud_style_falls_back_to_the_default(self, df):
        default = V.to_echarts_option(df, 'wordcloud', x='作者')['series'][0]['textStyle']
        weird = V.to_echarts_option(df, 'wordcloud', x='作者', wordcloud_style='nope')['series'][0]['textStyle']
        assert default == weird
        assert default['fontWeight'] == 'bold'


# ─── tokenizing ────────────────────────────────────────────────────────


class TestTokenizeFrequency:
    def test_chinese_text_becomes_word_counts(self):
        frame = pd.DataFrame({'正文': ['三亚的海非常蓝，适合冬天度假', '三亚非常漂亮，冬天适合度假']})
        labels, values = V.tokenize_frequency(frame, '正文', top_n=5)
        assert '三亚' in labels and '度假' in labels
        assert len(labels) == len(values)
        assert values == sorted(values, reverse=True)

    def test_stopwords_are_dropped(self):
        frame = pd.DataFrame({'正文': ['是的了的和', '好的是我的']})
        labels, _ = V.tokenize_frequency(frame, '正文')
        assert '的' not in labels and '是' not in labels

    def test_top_n_truncates_the_result(self):
        frame = pd.DataFrame({'正文': ['三亚海蓝色冬天度假漂亮', '海口美食推荐潜水体验很好']})
        assert len(V.tokenize_frequency(frame, '正文', top_n=2)[0]) <= 2

    def test_missing_column_is_a_configuration_error(self, df):
        with pytest.raises(ChartConfigError, match='Field not found in the data: nope'):
            V.tokenize_frequency(df, 'nope')

    def test_tokenizing_wordcloud_consumes_the_text_column(self):
        frame = pd.DataFrame({'正文': ['海口美食推荐', '海口潜水体验']})
        data = V.to_echarts_option(frame, 'wordcloud', x='正文', tokenize=True)['series'][0]['data']
        assert any(item['name'] == '海口' for item in data)


# ─── configuration errors ──────────────────────────────────────────────


class TestConfigErrors:
    def test_unknown_chart_type_is_refused(self, df):
        with pytest.raises(ChartConfigError, match='Unsupported chart type: donut'):
            V.to_echarts_option(df, 'donut', x='作者')

    @pytest.mark.parametrize(
        'chart_type, kwargs, needle',
        [
            ('bar', {}, 'bar chart requires a category field'),
            ('line', {}, 'line chart requires a category field'),
            ('pie', {}, 'Pie chart requires a category field'),
            ('scatter', {'x': '点赞'}, 'Scatter chart requires both x and y fields'),
            ('histogram', {}, 'Histogram requires a numeric field'),
            ('heatmap', {'x': '作者'}, 'Heatmap requires two category fields'),
            ('sankey', {'x': '作者'}, 'Sankey diagram requires a source field'),
            ('wordcloud', {}, 'Word cloud requires a text/category field'),
            ('map', {}, 'Map chart requires a region-name field'),
            ('box', {}, 'Box plot requires a category field'),
            ('box', {'y': '点赞'}, 'Box plot requires a category field'),
            ('dual_line', {'x': '作者', 'y': '点赞'}, 'requires a second value field'),
            ('dual_line', {'y2': '阅读'}, 'requires a category field'),
            ('topic_map', {'x': '点赞'}, 'needs both coordinate fields'),
            ('topic_terms', {}, 'requires a term field'),
            ('topic_terms', {'x': '作者', 'y': '点赞'}, 'needs BOTH frequency fields'),
        ],
    )
    def test_specs_missing_required_fields_name_the_gap(self, df, chart_type, kwargs, needle):
        with pytest.raises(ChartConfigError) as excinfo:
            V.to_echarts_option(df, chart_type, **kwargs)
        assert needle in str(excinfo.value)

    @pytest.mark.parametrize('chart_type', [c for c in CHART_TYPES if c != 'box'])
    def test_a_field_that_is_not_in_the_data_is_reported(self, df, chart_type):
        kwargs = {key: '不存在的列' for key in USABLE[chart_type]}
        with pytest.raises(ChartConfigError, match='Field not found in the data'):
            V.to_echarts_option(df, chart_type, **kwargs)

    def test_a_missing_y_field_is_not_silently_counted(self, df):
        with pytest.raises(ChartConfigError, match='Field not found in the data: nope'):
            V.to_echarts_option(df, 'bar', x='作者', y='nope')

    def test_chart_config_error_is_a_value_error(self):
        assert issubclass(ChartConfigError, ValueError)


# ─── matplotlib renderer ───────────────────────────────────────────────


class TestRenderImage:
    @pytest.mark.parametrize('chart_type', [c for c in CHART_TYPES if c not in ECHARTS_ONLY_TYPES])
    def test_png_data_url_is_produced(self, df, chart_type):
        url = V.render_image(
            df,
            chart_type,
            x=USABLE[chart_type].get('x'),
            y=USABLE[chart_type].get('y'),
            stack_fields=USABLE[chart_type].get('stack_fields'),
        )
        assert url.startswith('data:image/png;base64,')
        payload = base64.b64decode(url.split(',', 1)[1])
        assert payload[:8] == b'\x89PNG\r\n\x1a\n'  # a real PNG; pixels are not compared
        assert len(payload) > 100

    def test_title_is_optional_decoration(self, df):
        assert V.render_image(df, 'bar', x='作者', y='点赞', title='点赞分布').startswith('data:image/png')

    def test_echarts_only_types_explain_the_engine_hint(self, df):
        for chart_type in ECHARTS_ONLY_TYPES:
            with pytest.raises(ChartConfigError) as excinfo:
                V.render_image(df, chart_type, x='作者')
            assert 'engine=echarts' in str(excinfo.value)

    def test_unknown_chart_type_is_refused_before_drawing(self, df):
        with pytest.raises(ChartConfigError, match='Unsupported chart type'):
            V.render_image(df, 'donut', x='作者')

    @pytest.mark.parametrize(
        'chart_type, kwargs, needle',
        [
            ('bar', {}, 'requires a field (x)'),
            ('scatter', {'x': '点赞'}, 'requires both x and y fields'),
            ('heatmap', {'y': '平台'}, 'requires both x and y fields'),
        ],
    )
    def test_missing_fields_use_the_same_message_shape(self, df, chart_type, kwargs, needle):
        with pytest.raises(ChartConfigError) as excinfo:
            V.render_image(df, chart_type, **kwargs)
        assert needle in str(excinfo.value)

    def test_unknown_column_is_reported(self, df):
        with pytest.raises(ChartConfigError, match='Field not found in the data'):
            V.render_image(df, 'bar', x='nope')

    def test_missing_values_do_not_break_a_server_side_render(self, df):
        assert V.render_image(df, 'bar', x='作者', y='阅读', agg='mean').count('base64') == 1
