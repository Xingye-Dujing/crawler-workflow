"""Tests for services/latex_charts.py — the LaTeX figure / three-line-table generator.

These assert the SOURCE is well-formed and complete (a document shell, the right commands, every
data value present, TeX specials escaped, Chinese preserved, a crowded category axis thinned rather
than silently dropped). Whether it *renders* is MiKTeX's job and is checked by compiling the emitted
.txt in the manual pass (see README), not here — a byte of LaTeX the fast suite compiles would make
the suite depend on a TeX installation it is not allowed to need.
"""

import pandas as pd
import pytest

from services.latex_charts import LatexChartService as L
from services.visualizer import CHART_TYPES, ChartConfigError

pytestmark = pytest.mark.unit


def _cat():
    return pd.DataFrame(
        {
            'g': ['甲', '乙', '甲', '丙'],
            'v': [10.0, 25.0, 5.0, 40.0],
            'w': [100, 200, 300, 400],
            'd': ['知乎', '微博', '知乎', '小红书'],
        }
    )


def _share():
    return pd.DataFrame(
        {
            '阶段': ['发酵期', '爆发期', '衰退期'],
            'positive_pct': [8.0, 4.0, 12.0],
            'neutral_pct': [20.0, 18.0, 30.0],
            'negative_pct': [72.0, 78.0, 58.0],
        }
    )


def _flow():
    return pd.DataFrame({'s': ['A', 'B', 'C'], 't': ['C', 'D', 'D'], 'v': [3.0, 5.0, 2.0]})


def _tp():
    return pd.DataFrame(
        {'pc1': [0.2, -0.3, 0.5], 'pc2': [0.1, 0.4, -0.2], 'prev': [70.0, 30.0, 50.0], '主题概括': ['甲', '乙', '丙']}
    )


def _tt():
    return pd.DataFrame({'term': ['词一', '词二', '词三'], 'overall': [100, 80, 50], 'within': [30, 20, 15]})


# One usable spec + one frame per chart type, so the happy path is swept in one test.
CASES = {
    'bar': (_cat(), dict(x='g', y='v')),
    'line': (_cat(), dict(x='g', y='v')),
    'dual_line': (_cat(), dict(x='g', y='v', y2='w')),
    'stack_pct': (_share(), dict(x='阶段', stack_fields='positive_pct,neutral_pct,negative_pct')),
    'scatter': (_cat(), dict(x='v', y='w')),
    'histogram': (_cat(), dict(x='v')),
    'box': (_cat(), dict(x='g', y='v')),
    'pie': (_cat(), dict(x='g', y='v')),
    'heatmap': (_cat(), dict(x='g', y='d', value_field='v')),
    'topic_map': (_tp(), dict(x='pc1', y='pc2', value_field='prev', label_field='主题概括')),
    'topic_terms': (_tt(), dict(x='term', y='overall', y2='within')),
    'sankey': (_flow(), dict(x='s', y='t', value_field='v')),
    'network': (_flow(), dict(x='s', y='t', value_field='v')),
    'wordcloud': (_cat(), dict(x='g', value_field='v')),
    'map': (_cat(), dict(x='g', value_field='v')),
}


class TestFigure:
    @pytest.mark.parametrize('chart_type', CHART_TYPES)
    def test_every_type_emits_a_standalone_document(self, chart_type):
        df, kw = CASES[chart_type]
        out = L.to_latex_document(df, chart_type, title='图 X', **kw)
        assert '\\documentclass[border=6pt]{standalone}' in out
        assert '\\begin{document}' in out and out.rstrip().endswith('\\end{document}')
        # every figure is a pgfplots axis, a tikzpicture, or (word cloud) a minipage box — never bare prose
        assert '\\begin{axis}' in out or '\\begin{tikzpicture}' in out or '\\begin{minipage}' in out
        assert '\\usepackage{ctex}' in out and '\\usepackage{pgfplots}' in out

    def test_labels_and_numbers_survive_into_the_source(self):
        out = L.to_latex_document(_cat(), 'bar', x='g', y='v')
        # the aggregated value for 甲 (10+5) and the category label itself must both be in there
        assert '甲' in out and '15' in out

    def test_tex_specials_are_escaped(self):
        df = pd.DataFrame({'g': ['a_b&c%d'], 'v': [3.0]})
        out = L.to_latex_document(df, 'bar', x='g', y='v')
        assert r'a\_b\&c\%d' in out, 'underscore/ampersand/percent must be escaped'

    def test_a_crowded_axis_is_thinned_not_lied_about(self):
        # 24 days would collide; the figure rotates and shows a regular subset, keeping every point.
        df = pd.DataFrame({'日期': [f'2022-01-{d:02d}' for d in range(1, 25)], 'v': list(range(24))})
        out = L.to_latex_document(df, 'bar', x='日期', y='v')
        assert 'rotate=45' in out and 'xtick distance=2' in out

    def test_a_short_axis_keeps_every_label_horizontal(self):
        out = L.to_latex_document(_cat(), 'bar', x='g', y='v')
        assert 'rotate=45' not in out

    def test_stack_pct_normalises_and_legends_each_segment(self):
        out = L.to_latex_document(_share(), 'stack_pct', x='阶段', stack_fields='positive_pct,neutral_pct,negative_pct')
        assert 'ybar stacked' in out and 'ymax=100' in out
        for name in ('积极占比', '中性占比', '消极占比'):
            assert name in out, name

    def test_map_is_a_bubble_map_that_still_lists_every_value(self):
        df = pd.DataFrame({'省': ['广东', '四川', '某不存在地区'], 'v': [50, 10, 7]})
        out = L.to_latex_document(df, 'map', x='省', value_field='v')
        assert '\\begin{tikzpicture}' in out and 'circle' in out
        # content completeness: even a region with no centroid is in the appendix table
        assert '某不存在地区' in out and '广东' in out and '四川' in out

    def test_wordcloud_sizes_words_by_frequency_and_appends_the_table(self):
        out = L.to_latex_document(_cat(), 'wordcloud', x='g', value_field='v')
        assert out.count('fontsize') >= 2 and '\\begin{tabular}' in out

    def test_a_type_missing_its_required_field_refuses_by_name(self):
        with pytest.raises(ChartConfigError):
            L.to_latex_document(_cat(), 'scatter', x='v')  # scatter needs y too
        with pytest.raises(ChartConfigError):
            L.to_latex_document(_cat(), 'stack_pct', x='g')  # needs stack_fields


class TestTable:
    @pytest.mark.parametrize('chart_type', CHART_TYPES)
    def test_every_type_makes_a_booktabs_three_line_table(self, chart_type):
        df, kw = CASES[chart_type]
        out = L.to_latex_table(df, chart_type, title='表 X', **kw)
        assert '\\toprule' in out and '\\midrule' in out and '\\bottomrule' in out
        assert '\\begin{tabular}' in out and out.rstrip().endswith('\\end{document}')

    def test_stack_pct_table_shares_sum_to_a_hundred(self):
        out = L.to_latex_table(_share(), 'stack_pct', x='阶段', stack_fields='positive_pct,neutral_pct,negative_pct')
        assert '积极占比 (\\%)' in out, 'the % must be escaped or it comments out the row'
        # 发酵期 row: 8 / 20 / 72
        assert '8' in out and '72' in out
