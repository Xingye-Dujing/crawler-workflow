"""The chart preflight: what a SAMPLE of the upstream rows proves before a run is paid for.

The static contract (``chart_problems``) proves the boxes are filled; this half proves the columns
those boxes name actually hold what the builder needs. It is deliberately narrow — only conclusive
facts are refused, because a preflight that guesses would refuse runs that would have succeeded:

* a named column that is not in the sample (the sample comes from a run of the same node
  fingerprint, so it is the table this node would receive);
* a value/coordinate/stack column with at least one real cell and no number in any of them (the
  builders' own ``chart.y_not_numeric`` refusal, mirrored exactly — an all-blank column draws an
  empty chart rather than refusing, and so does this).

A share's negativity and a matrix's final cardinality cannot be proved from 200 rows, so those
refusals stay with the builder at run time.
"""

import pytest

from services.charts import registry
from services.charts.registry import CHART_TYPES, chart_preflight

pytestmark = pytest.mark.unit

#: The column each parameter names in the fixtures; ``stack_fields`` names two.
_COLUMNS = {
    'x_field': 'X',
    'y_field': 'Y',
    'y2_field': 'Y2',
    'value_field': 'V',
    'label_field': 'L',
    'model_field': 'M',
    'agreement_label_field': 'AL',
    'id_field': 'ID',
    'stack_fields': 'A,B',
}
_NUMERIC_ROLES = set(registry.NUMERIC_ROLES)


def _params(spec) -> dict:
    params = {'chart_type': spec.key}
    for field in spec.fields:
        params[field.name] = _COLUMNS[field.name]
    return params


def _sample(spec, rows: int = 3) -> list[dict]:
    """A table that satisfies every field the chart declares."""
    out = []
    for index in range(rows):
        row = {}
        for field in spec.fields:
            if field.role == 'list':
                row['A'], row['B'] = index + 1, index + 2
            elif field.role in _NUMERIC_ROLES:
                row[_COLUMNS[field.name]] = index + 1
            else:
                row[_COLUMNS[field.name]] = f'类{index}'
        out.append(row)
    return out


class TestEveryChartTypeHasAPreflightContract:
    def test_a_sample_that_fits_is_clean(self):
        for spec in registry.SPECS:
            found = chart_preflight(spec.key, _params(spec), _sample(spec))
            assert found == [], (spec.key, found)

    def test_a_chart_type_with_no_declared_fields_is_not_preflighted(self):
        # The bibliometric views read fixed columns the biblio node writes; there is no user box
        # to check against a sample here (their own node contract names the reads).
        for spec in registry.SPECS:
            if spec.fields:
                continue
            assert chart_preflight(spec.key, _params(spec), _sample(spec)) == []


class TestWhatASampleProves:
    def test_every_numeric_field_is_named_when_its_sample_holds_only_text(self):
        """The matrix that keeps role and check together: for every chart and every numeric
        field, a text-only column must be named as THAT box — and nothing else."""
        for spec in registry.SPECS:
            for field in spec.fields:
                if field.role not in _NUMERIC_ROLES:
                    continue
                sample = _sample(spec)
                for row in sample:
                    if field.role == 'list':
                        row['A'] = row['B'] = '文本'
                    else:
                        row[_COLUMNS[field.name]] = '文本'
                found = chart_preflight(spec.key, _params(spec), sample)
                assert found, (spec.key, field.name)
                assert {(problem['code'], problem['param']) for problem in found} == {
                    ('engine.chart_column_not_numeric', field.name)
                }, (spec.key, field.name, found)

    def test_a_renamed_column_is_named_before_the_run(self):
        found = chart_preflight('bar', {'chart_type': 'bar', 'x_field': '词'}, [{'X': '甲', 'Y': 1}])
        assert [p['code'] for p in found] == ['engine.chart_column_missing']
        assert found[0]['param'] == 'x_field'
        assert found[0]['context']['column'] == '词'

    def test_a_text_value_column_is_named(self):
        sample = [{'X': '甲', 'Y': '很高'}, {'X': '乙', 'Y': '一般'}]
        found = chart_preflight('bar', {'chart_type': 'bar', 'x_field': 'X', 'y_field': 'Y'}, sample)
        assert [p['code'] for p in found] == ['engine.chart_column_not_numeric']
        assert found[0]['param'] == 'y_field'
        assert found[0]['context']['column'] == 'Y'

    def test_a_category_column_may_hold_text(self):
        sample = [{'X': '甲', 'Y': 1}, {'X': '乙', 'Y': 2}]
        assert chart_preflight('bar', {'chart_type': 'bar', 'x_field': 'X', 'y_field': 'Y'}, sample) == []

    def test_an_all_blank_value_column_is_not_reported(self):
        """The builders draw an all-missing column as an empty chart, not a refusal — the
        preflight mirrors that instead of inventing a stricter rule."""
        sample = [{'X': '甲', 'Y': None}, {'X': '乙', 'Y': ''}]
        assert chart_preflight('bar', {'chart_type': 'bar', 'x_field': 'X', 'y_field': 'Y'}, sample) == []

    def test_one_number_anywhere_keeps_a_column_plotable(self):
        sample = [{'X': '甲', 'Y': '未填'}, {'X': '乙', 'Y': 3}]
        assert chart_preflight('bar', {'chart_type': 'bar', 'x_field': 'X', 'y_field': 'Y'}, sample) == []

    def test_every_numeric_role_is_checked(self):
        sample = [{'X': '甲', 'Y': 'a', 'V': 'b', 'A': 1, 'B': 2}]
        params = {
            'chart_type': 'scatter',
            'x_field': 'X',
            'y_field': 'Y',
        }
        assert [p['param'] for p in chart_preflight('scatter', params, sample)] == ['x_field', 'y_field']
        dual = chart_preflight('dual_line', {'chart_type': 'dual_line', 'x_field': 'X', 'y2_field': 'V'}, sample)
        assert [p['param'] for p in dual] == ['y2_field']
        stack = chart_preflight(
            'stack_pct',
            {'chart_type': 'stack_pct', 'x_field': 'X', 'stack_fields': 'A,B'},
            [{'X': '甲', 'A': 1, 'B': '很多'}],
        )
        assert [p['param'] for p in stack] == ['stack_fields']

    def test_an_empty_sample_is_not_a_verdict(self):
        assert chart_preflight('bar', {'chart_type': 'bar', 'x_field': 'X'}, []) == []

    def test_an_unknown_chart_type_is_left_to_the_static_contract(self):
        assert chart_preflight('moonbase', {'chart_type': 'moonbase'}, [{'X': 1}]) == []

    def test_a_declared_default_column_is_checked_too(self):
        """An untouched 主题距离图 reads pc1/pc2 by contract; a sample without them is still a
        rename the builder would refuse."""
        found = chart_preflight('topic_map', {'chart_type': 'topic_map'}, [{'term': '甲', 'overall_freq': 2}])
        assert [p['param'] for p in found] == ['x_field', 'y_field', 'label_field', 'value_field']
        assert CHART_TYPES, 'the registry must enumerate chart types'
