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

import pandas as pd
import pytest

from services.visualizer import CHART_TYPES, ECHARTS_ONLY_TYPES, ChartConfigError
from services.visualizer import VisualizationService as V

pytestmark = pytest.mark.unit

# One usable spec per chart type, so the happy path can be swept in one test.
USABLE = {
    'bar': {'x': '作者', 'y': '点赞'},
    'line': {'x': '作者', 'y': '点赞'},
    'pie': {'x': '作者', 'y': '点赞'},
    'scatter': {'x': '点赞', 'y': '阅读'},
    'histogram': {'x': '点赞'},
    'box': {'x': '作者', 'y': '点赞'},
    'heatmap': {'x': '作者', 'y': '平台'},
    'sankey': {'x': '作者', 'y': '平台'},
    'wordcloud': {'x': '作者'},
    'map': {'x': '作者', 'value_field': '点赞'},
}

# Group keys sort by code point, which is why 丙 precedes 乙 precedes 甲 here.
LABELS = ['丙', '乙', '甲']


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

    @pytest.mark.parametrize('chart_type', CHART_TYPES)
    def test_a_frame_full_of_missing_numbers_still_serialises(self, chart_type):
        frame = pd.DataFrame({'g': ['a', 'b'], 'v': [None, None]})
        option = V.to_echarts_option(frame, chart_type, x='g', y='v', value_field='v')
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
        assert option['color'][0] == '#3B82F9'
        assert option['backgroundColor'] == 'transparent'

    def test_tooltip_trigger_follows_the_chart_kind(self, df):
        assert V.to_echarts_option(df, 'bar', x='作者')['tooltip']['trigger'] == 'axis'
        assert V.to_echarts_option(df, 'pie', x='作者')['tooltip']['trigger'] == 'item'


# ─── aggregation semantics ─────────────────────────────────────────────


class TestAggregation:
    def test_bar_sums_the_value_field_per_category(self, df):
        option = V.to_echarts_option(df, 'bar', x='作者', y='点赞')
        assert option['xAxis']['data'] == LABELS
        assert option['series'][0]['data'] == [40.0, 25.0, 15.0]

    def test_counting_mode_when_no_value_field_is_given(self, df):
        assert V.to_echarts_option(df, 'bar', x='作者')['series'][0]['data'] == [1, 1, 2]

    @pytest.mark.parametrize(
        'agg, expected',
        [
            ('mean', [40.0, 25.0, 7.5]),
            ('max', [40.0, 25.0, 10.0]),
            ('min', [40.0, 25.0, 5.0]),
            ('count', [1.0, 1.0, 2.0]),
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
        assert option['yAxis']['data'] == ['小红书', '微博', '知乎']
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
        url = V.render_image(df, chart_type, x=USABLE[chart_type].get('x'), y=USABLE[chart_type].get('y'))
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
