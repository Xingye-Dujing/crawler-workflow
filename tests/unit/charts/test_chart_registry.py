"""One declaration per chart type: the derived tuples and the surfaces that must agree.

Before ``services.charts.registry`` a type was named in five Python sets and three JS arrays, and
adding a chart meant editing them in lockstep. This module pins the shape of that registry:

* every derived tuple is a projection of ``SPECS`` (order included, because the panel walks it);
* a bibliometric view cannot exist without its required columns, and a console type cannot claim
  any (the columns are the refusal contract of the biblio node);
* exactly one type has no paper twin — the agreement matrix, whose point is the colour ramp;
* the front end renders the SERVED chart profile (types, fields, controls) instead of keeping its
  own arrays, and every type has a word in both languages.
"""

import re

import pandas as pd
import pytest
from frontend_catalogue import catalog_keys
from frontend_catalogue import words_missing as _words_missing
from static_assets import js_text

from services.charts import registry
from services.charts.contracts import BIBLIO_CHART_READS, BIBLIO_CHART_TYPES, NO_X_TYPES, ChartConfigError
from services.charts.registry import LATEX_UNBUILDABLE_TYPES
from services.charts.visualizer import CHART_TYPES, ECHARTS_ONLY_TYPES


class TestTheRegistryIsTheOneDeclaration:
    def test_every_derived_tuple_is_a_projection_of_the_specs(self):
        assert tuple(spec.key for spec in registry.SPECS) == CHART_TYPES
        assert tuple(spec.key for spec in registry.SPECS if spec.family == registry.FAMILY_BIBLIO) == BIBLIO_CHART_TYPES
        assert tuple(spec.key for spec in registry.SPECS if spec.echarts_only) == ECHARTS_ONLY_TYPES
        assert tuple(spec.key for spec in registry.SPECS if not spec.latex_buildable) == LATEX_UNBUILDABLE_TYPES
        assert frozenset(spec.key for spec in registry.SPECS if spec.no_x) == NO_X_TYPES
        assert {spec.key: spec.reads for spec in registry.SPECS if spec.reads} == BIBLIO_CHART_READS

    def test_a_bibliometric_view_cannot_forget_its_columns(self):
        for spec in registry.SPECS:
            biblio = spec.family == registry.FAMILY_BIBLIO
            assert bool(spec.reads) == biblio, (
                f'{spec.key}: a {spec.family} type must {"have" if biblio else "not have"} required '
                'columns — the biblio node writes them, a console table does not'
            )

    def test_every_field_role_is_one_of_the_declared_vocabulary(self):
        """A role is what the preflight coerces the named column against (a value must hold
        numbers, a category groups); a typo would silently skip that check."""
        for spec in registry.SPECS:
            for field in spec.fields:
                assert field.role in registry.FIELD_ROLES, f'{spec.key}.{field.name}: {field.role!r}'

    def test_only_annotations_are_declared_where_the_builders_honour_them(self):
        assert registry.ANNOTATED_TYPES == ('bar', 'line', 'dual_line')

    def test_exactly_one_type_has_no_paper_twin(self):
        """The agreement matrix is the only type whose point is the on-screen colour ramp; every
        other chart must print, including the ECharts-only ones (pgfplots draws them)."""
        assert set(LATEX_UNBUILDABLE_TYPES) == {'model_agreement'}
        assert set(LATEX_UNBUILDABLE_TYPES) < set(ECHARTS_ONLY_TYPES)

    def test_an_unknown_type_is_answered_as_unknown(self):
        assert registry.spec_for('nope') is None
        assert registry.spec_for('') is None
        assert registry.is_biblio('nope') is False
        assert registry.is_biblio('burst') is True
        assert registry.is_biblio('bar') is False

    def test_a_spec_carries_its_own_catalogue_key(self):
        assert registry.spec_for('dual_map').label_key == 'chart.dual_map'

    def test_a_blank_field_falls_back_to_the_types_declared_default(self):
        """An untouched topic chart used to refuse at run time, after the crawl was paid for."""
        filled = registry.with_chart_defaults('topic_map', {'x_field': ''})
        assert filled['x_field'] == 'pc1'
        assert filled['y_field'] == 'pc2'
        assert filled['label_field'] == 'topic'
        assert filled['value_field'] == 'prevalence_pct'
        typed = registry.with_chart_defaults('topic_map', {'x_field': '我的横轴'})
        assert typed['x_field'] == '我的横轴', 'a typed value always wins'
        assert registry.with_chart_defaults('bar', {}) == {}
        assert registry.with_chart_defaults('nope', {'x_field': 'x'}) == {'x_field': 'x'}


class TestTheBrowserReadsTheRegistry:
    """The settings panel renders the served chart profiles — it keeps no second table.

    It used to keep eight arrays (which chart shows y, which takes source/target, which accepts
    annotations…) beside the Python registry. The page now asks ``NodeTypes.charts()``; this test
    pins that the panel really reads it and that a new chart type needs no JavaScript edit.
    """

    def test_the_panel_asks_the_catalogue_for_its_charts_and_fields(self):
        source = js_text('panels/node-chart.js')
        assert 'NodeTypes.charts()' in source
        assert 'NodeTypes.chart(' in source
        for stale in ('var CHART_TYPES', 'var BIBLIO_CHARTS', 'CHARTS_NO_Y', 'CHARTS_WITH_Y2', 'CHART_X_LABEL_KEY'):
            assert stale not in source, f'{stale} is a second opinion about the chart registry'

    def test_every_declared_control_has_exactly_one_registered_widget(self):
        """A chart names a control and a widget id; a name with no renderer would silently draw no
        box, so the two declarations are held equal (``reusable``/settings renderers, same rule)."""
        source = js_text('panels/node-chart.js')
        registered = set(re.findall(r"registerChartControl\('([a-z0-9_]+)'", source))
        declared = set()
        for spec in registry.SPECS:
            declared.update(spec.controls)
            declared.update(field.control for field in spec.fields if field.control)
        assert declared == registered, f'declared={sorted(declared)} registered={sorted(registered)}'

    def test_every_profile_carries_its_fields_and_display_defaults(self):
        profiles = registry.chart_profiles()
        assert [profile['key'] for profile in profiles] == list(CHART_TYPES)
        for profile in profiles:
            spec = registry.spec_for(profile['key'])
            assert [field['name'] for field in profile['fields']] == [field.name for field in spec.fields]
            assert profile['defaults'] == dict(spec.defaults)
            assert profile['echartsOnly'] is spec.echarts_only

    def test_every_field_label_and_hint_has_a_word_in_both_languages(self):
        keys = set()
        for profile in registry.chart_profiles():
            if profile['hintKey']:
                keys.add(profile['hintKey'])
            for field in profile['fields']:
                keys.update(key for key in (field['labelKey'], field['placeholderKey'], field['hintKey']) if key)
        tables = catalog_keys()
        missing = [
            f'{key} missing from {lang}' for key in sorted(keys) for lang in ('en', 'zh') if key not in tables[lang]
        ]
        assert missing == []

    def test_every_type_has_a_word_in_both_languages(self):
        # ``chart.<type>`` is a computed key, so it is asked of both languages of the whole browser
        # dictionary — never counted in one file, which after the domain split holds only a part.
        missing = _words_missing('chart.', CHART_TYPES)
        assert missing == [], f'chart types with no zh+en label: {missing}'


class TestTheAiCatalogueUsesTheSameDeclaration:
    """The AI's chart tool answers in the same vocabulary the form and validation use."""

    def test_the_ai_catalogue_carries_the_same_fields(self):
        from ai.vocabulary import chart_catalog

        rows = {row['chart_type']: row for row in chart_catalog()}
        assert [field['name'] for field in rows['scatter']['fields']] == ['x_field', 'y_field']
        assert [field['required'] for field in rows['scatter']['fields']] == [True, True]
        assert rows['knowledge_graph']['fields'] == []


class TestEveryConsoleTypeHasOneBuilder:
    """The option builder is a registry, not an ``if`` chain: one type, one plugin entry.

    The old ``_build_option`` was a 700-line chain of ``if chart_type == …`` blocks. A type that
    existed in ``CHART_TYPES`` but was never reached by the chain fell through to the generic
    bar/line axes — a figure that looked complete and was not what the user asked for.
    """

    def test_the_registry_covers_exactly_the_console_types(self):
        from services.charts.options import BUILDERS

        assert set(BUILDERS) == set(CHART_TYPES) - set(BIBLIO_CHART_TYPES), (
            'every console type must have exactly one builder; the bibliometric family is built by '
            'services.biblio.charts from the node-written frame'
        )

    def test_a_second_claim_on_one_type_is_refused(self):
        from services.charts.options import builder

        with pytest.raises(ValueError, match='already has a builder'):
            builder('bar')(lambda *_args: None)

    def test_a_type_whose_builder_vanished_is_refused_by_name(self, monkeypatch):
        from services.charts import options
        from services.charts.visualizer import VisualizationService as V

        monkeypatch.delitem(options.BUILDERS, 'bar')
        with pytest.raises(ChartConfigError, match='Unsupported chart type: bar'):
            V._build_option(pd.DataFrame({'作者': ['甲'], '点赞': [1.0]}), 'bar', x='作者', y='点赞')

    def test_every_builder_sits_in_a_family_module(self):
        """A builder defined in ``base`` would make the registry a second monolith."""
        from services.charts.options import BUILDERS

        homes = {fn.__module__.rsplit('.', 1)[-1] for fn in BUILDERS.values()}
        assert homes == {'series', 'distributions', 'relations', 'topics'}, homes


class TestRequiredFieldsReachValidation:
    """The chart matrix: every type's required boxes are named before a run.

    One declaration (``ChartSpec.fields``) answers both halves — which boxes the form shows and
    which of them a run cannot start without. The matrix walks every type, so a chart added
    tomorrow is covered the day it lands.
    """

    @staticmethod
    def _satisfying(spec) -> dict:
        params: dict = {'chart_type': spec.key}
        for field in spec.fields:
            if field.role == 'list':
                params[field.name] = '甲,乙'
            else:
                params[field.name] = 'c'
        return params

    def test_every_type_accepts_its_own_filled_contract(self):
        for spec in registry.SPECS:
            assert registry.chart_problems(spec.key, self._satisfying(spec)) == [], spec.key

    def test_every_required_field_without_a_default_is_named_when_blank(self):
        for spec in registry.SPECS:
            defaults = dict(spec.defaults)
            for field in spec.fields:
                if not field.required or str(defaults.get(field.name) or '').strip():
                    continue
                params = self._satisfying(spec)
                params[field.name] = ''
                found = registry.chart_problems(spec.key, params)
                assert [p['param'] for p in found] == [field.name], (spec.key, field.name, found)
                assert found[0]['code'] == 'engine.chart_field_missing'

    def test_a_declared_default_is_not_reported_when_the_box_is_blank(self):
        for spec in registry.SPECS:
            defaults = dict(spec.defaults)
            if not defaults:
                continue
            params = self._satisfying(spec)
            for name in defaults:
                params[name] = ''
            assert registry.chart_problems(spec.key, params) == [], spec.key

    def test_stack_pct_declares_stack_fields_on_its_spec(self):
        from services.charts.registry import spec_for

        spec = spec_for('stack_pct')
        assert spec is not None
        assert [field.name for field in spec.fields if field.required] == ['x_field', 'stack_fields']

    def test_a_box_plot_with_neither_axis_is_named(self):
        found = registry.chart_problems('box', {'chart_type': 'box'})
        assert [p['code'] for p in found] == ['engine.chart_field_group_missing']
        assert found[0]['param'] == 'x_field'

    def test_a_box_plot_with_one_numeric_column_is_clean(self):
        assert registry.chart_problems('box', {'chart_type': 'box', 'x_field': '评分'}) == []

    def test_a_box_plot_grouped_by_y_requires_the_category_x(self):
        """The builder refuses a y-only box at run time; naming the category is the contract."""
        found = registry.chart_problems('box', {'chart_type': 'box', 'y_field': '评分'})
        assert [(p['code'], p['param']) for p in found] == [('engine.chart_field_missing', 'x_field')]

    def test_an_unknown_chart_type_is_named_and_offers_the_default_as_fix(self):
        found = registry.chart_problems('moonbase', {'chart_type': 'moonbase'})
        assert [p['code'] for p in found] == ['engine.chart_unknown']
        assert found[0]['fix'] == {'set': {'chart_type': registry.DEFAULT_CHART}}

    def test_a_blank_chart_type_is_the_declared_default_not_an_error(self):
        """A blank ``chart_type`` draws the manifest's default (``bar``); refusing it was a false
        alarm — the executor never read it as “no chart”."""
        assert registry.effective_chart_key('') == registry.DEFAULT_CHART
        codes = [problem['code'] for problem in registry.chart_problems('', {'x_field': '词'})]
        assert codes == []

    def test_validation_names_stack_fields_before_the_run(self):
        """The builder used to be the only place that noticed; the user paid for the upstream
        crawl first. The engine now reads the spec's field table."""
        from engine.workflow import WorkflowEngine

        workflow = {
            'nodes': [
                {
                    'id': 'chart-1',
                    'type': 'visualize',
                    'params': {'chart_type': 'stack_pct', 'x_field': '平台'},
                }
            ],
            'connections': [],
        }
        entries = WorkflowEngine(workflow).validate_detailed()
        named = [entry for entry in entries if entry['code'] == 'engine.chart_field_missing']
        assert named, 'validate did not name the missing stack_fields before a run'
        assert 'stack_fields' in named[0]['message']
        assert named[0]['id'] == 'chart-1'
        assert named[0]['param'] == 'stack_fields'

    def test_a_filled_stack_fields_is_not_reported(self):
        from engine.workflow import WorkflowEngine

        workflow = {
            'nodes': [
                {
                    'id': 'chart-1',
                    'type': 'visualize',
                    'params': {
                        'chart_type': 'stack_pct',
                        'x_field': '平台',
                        'stack_fields': '正面,中性,负面',
                    },
                }
            ],
            'connections': [],
        }
        codes = [entry['code'] for entry in WorkflowEngine(workflow).validate_detailed()]
        assert 'engine.chart_field_missing' not in codes

    def test_the_engine_names_the_parameter_behind_the_problem(self):
        """The console and the panel share one sentence: it names the chart and the PARAMETER the
        entry also carries, so the panel can mark that box (``entry['param']``) without re-wording
        anything. Labels live in the browser catalogue, which the backend console cannot read."""
        from engine.workflow import WorkflowEngine
        from i18n import get_lang, set_lang

        previous = get_lang()
        set_lang('en')
        try:
            workflow = {
                'nodes': [{'id': 'chart-1', 'type': 'visualize', 'params': {'chart_type': 'heatmap'}}],
                'connections': [],
            }
            entries = [
                entry
                for entry in WorkflowEngine(workflow).validate_detailed()
                if entry['code'] == 'engine.chart_field_missing'
            ]
        finally:
            set_lang(previous)
        assert [entry['param'] for entry in entries] == ['x_field', 'y_field']
        assert all('heatmap' in entry['message'] and entry['param'] in entry['message'] for entry in entries)
