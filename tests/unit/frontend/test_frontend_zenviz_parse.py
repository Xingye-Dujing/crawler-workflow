"""The studio's paste parser: `tests/frontend/harness_zenviz_parse.mjs` runs the shipped file.

The parser used to live inside the studio page's 14k-line IIFE, where no test could execute it, and
it split rows on the delimiter with `String.split`. A quoted field containing that delimiter was
therefore cut in half — `"Beijing, China"` became two cells — and every column AFTER it shifted by
one: the pasted table loaded with each value under its neighbour's header, silently, because the
grid still looked plausible. It is now `js/zenviz-parse.js`, and these cases measure it.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

HARNESS = Path(__file__).resolve().parents[2] / 'frontend' / 'harness_zenviz_parse.mjs'
JS_DIR = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js'

pytestmark = [pytestmark, pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')]


@pytest.fixture(scope='module')
def parsed():
    result = subprocess.run(
        ['node', str(HARNESS), str(JS_DIR)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


class TestAQuotedFieldIsOneCell:
    """The measured bug: a comma inside quotes moved every later column one place to the right."""

    def test_the_delimiter_inside_quotes_does_not_split_the_cell(self, parsed):
        case = parsed['quotedDelimiter']
        assert case['headers'] == ['城市', '备注', '数量']
        assert case['rows'][0] == ['北京, 中国', '他说 "你好"', '3']

    def test_the_column_count_stays_rectangular(self, parsed):
        """A shifted row is one cell longer than the header, which is what put values under the
        wrong header; the parser must answer one width for every row."""
        case = parsed['quotedDelimiter']
        width = len(case['headers'])
        assert all(len(row) == width for row in case['rows']), case['rows']

    def test_a_doubled_quote_is_one_literal_quote(self, parsed):
        assert parsed['quotedDelimiter']['rows'][0][1] == '他说 "你好"'

    def test_an_empty_quoted_field_stays_empty_not_quoted(self, parsed):
        """`上海,,4` — the blank between the delimiters is a missing value, never `""`."""
        assert parsed['quotedDelimiter']['rows'][1] == ['上海', '', '4']


class TestTheDelimiterIsChosenFromTheHeader:
    @pytest.mark.parametrize('case', ['tabSeparated', 'semicolonSeparated', 'spaceSeparated'])
    def test_each_shape_reads_two_columns(self, parsed, case):
        assert parsed[case]['headers'] == ['城市', '数量']
        assert parsed[case]['rows'] == [['北京', '3']]

    def test_one_column_pasted_data_is_not_an_error(self, parsed):
        assert parsed['singleColumn'] == {'headers': ['名称'], 'rows': [['甲'], ['乙']]}


class TestTheGridIsAlwaysRectangular:
    def test_a_short_row_is_padded_to_the_header_width(self, parsed):
        assert parsed['raggedRows']['rows'][0] == ['1', '', '']

    def test_a_long_row_widens_the_header(self, parsed):
        """`4,5` in a three-column paste: the missing header is named rather than left undefined —
        a contenteditable cell bound to `rows[r][2]` needs the column to exist."""
        assert parsed['raggedRows']['headers'] == ['a', 'b', 'c']
        assert parsed['raggedRows']['rows'][1] == ['4', '5', '']

    def test_a_blank_header_cell_stays_blank(self, parsed):
        """`a,,c` is a column with no name, not a shifted one: padding must not reorder cells."""
        assert parsed['blankHeader']['headers'] == ['a', '', 'c']
        assert parsed['blankHeader']['rows'] == [['1', '2', '3']]


class TestNothingPastedIsAnEmptyTable:
    def test_whitespace_only_answers_no_columns(self, parsed):
        assert parsed['empty'] == {'headers': [], 'rows': []}
