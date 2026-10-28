"""One declaration per chart type: the derived tuples and the surfaces that must agree.

Before ``services.charts.registry`` a type was named in five Python sets and three JS arrays, and
adding a chart meant editing them in lockstep. This module pins the shape of that registry:

* every derived tuple is a projection of ``SPECS`` (order included, because the panel walks it);
* a bibliometric view cannot exist without its required columns, and a console type cannot claim
  any (the columns are the refusal contract of the biblio node);
* exactly one type has no paper twin — the agreement matrix, whose point is the colour ramp;
* the front end's three arrays are a pinned mirror of the registry, never a second opinion, and
  every type has a word in both languages.
"""

import re
from pathlib import Path

from frontend_catalogue import words_missing as _words_missing

from services.charts import registry
from services.charts.contracts import BIBLIO_CHART_READS, BIBLIO_CHART_TYPES, NO_X_TYPES
from services.charts.registry import LATEX_UNBUILDABLE_TYPES
from services.charts.visualizer import CHART_TYPES, ECHARTS_ONLY_TYPES

REPO = Path(__file__).resolve().parents[2]
# The three arrays live with the settings panel that draws them (split out of workflow.js).
SETTINGS_JS = REPO / 'backend' / 'static' / 'js' / 'panels' / 'settings.js'


def _js_array(source: str, name: str) -> list[str]:
    match = re.search(rf'var {name} = \[(.*?)\];', source, re.S)
    assert match, f'{name} is declared nowhere in the page'
    return re.findall(r"'([^']+)'", match.group(1))


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


class TestTheFrontEndIsPinnedNotASecondOpinion:
    def test_the_page_offers_exactly_the_registry_types(self):
        source = SETTINGS_JS.read_text(encoding='utf-8')
        assert _js_array(source, 'CHART_TYPES') == list(CHART_TYPES)
        assert _js_array(source, 'BIBLIO_CHARTS') == list(BIBLIO_CHART_TYPES)
        assert set(_js_array(source, 'ECHARTS_ONLY_CHARTS')) == set(ECHARTS_ONLY_TYPES)

    def test_every_type_has_a_word_in_both_languages(self):
        # ``chart.<type>`` is a computed key, so it is asked of both languages of the whole browser
        # dictionary — never counted in one file, which after the domain split holds only a part.
        missing = _words_missing('chart.', CHART_TYPES)
        assert missing == [], f'chart types with no zh+en label: {missing}'
