"""Tests for utils/helpers.py — the small shared helpers.

These four functions are used by the crawler parsers and by every download /
export path, so their edges are the interesting parts: a scraped title becomes
a file name, and a scraped counter arrives as '1,234' or '3.5万' of text.
"""

import io

import pandas as pd
import pytest

from utils.helpers import MAX_FILENAME_LENGTH, df_to_csv_string, extract_number, merge_results, sanitize_filename

pytestmark = pytest.mark.unit


class TestSanitizeFilename:
    @pytest.mark.parametrize('char', list('\\/*?:"<>|'))
    def test_reserved_characters_become_underscores(self, char):
        assert sanitize_filename(f'名字{char}后缀') == '名字_后缀'

    @pytest.mark.parametrize('code', [0x00, 0x0A, 0x1F])
    def test_control_characters_are_neutralised(self, code):
        assert sanitize_filename(f'a{chr(code)}b') == 'a_b'

    @pytest.mark.parametrize(
        'raw, expected',
        [
            ('..name..', 'name'),
            ('  spaced  ', 'spaced'),
            ('.', ''),
            ('...', ''),
            ('', ''),
            (None, ''),
            ('正常中文名', '正常中文名'),
        ],
    )
    def test_edge_shapes(self, raw, expected):
        assert sanitize_filename(raw) == expected

    def test_separators_cannot_escape_a_directory(self):
        clean = sanitize_filename('../../etc/passwd')
        assert '/' not in clean and '\\' not in clean

    def test_the_length_is_capped(self):
        assert len(sanitize_filename('长' * 300)) == MAX_FILENAME_LENGTH

    def test_a_long_name_keeps_its_extension(self):
        name = sanitize_filename('数据' * 80 + '.csv')
        assert len(name) == MAX_FILENAME_LENGTH
        assert name.endswith('.csv')

    def test_a_short_name_is_untouched(self):
        assert sanitize_filename('export.csv') == 'export.csv'

    def test_numbers_are_stringified(self):
        assert sanitize_filename(2024) == '2024'


class TestExtractNumber:
    @pytest.mark.parametrize(
        'text, expected',
        [
            ('1234', 1234),
            ('1,234', 1234),
            ('1,234,567', 1234567),
            ('点赞 42 次', 42),
            ('0', 0),
            ('无数字', 0),
            ('', 0),
            (None, 0),
        ],
    )
    def test_the_first_integer_wins(self, text, expected):
        assert extract_number(text) == expected

    def test_only_the_first_number_of_a_range_is_taken(self):
        assert extract_number('10-20') == 10

    def test_the_separator_is_ignored_across_the_whole_string(self):
        # '1 234' is not a thousands group, so the leading run stops at '1'.
        assert extract_number('1 234') == 1

    def test_floats_lose_the_fraction(self):
        assert extract_number('3.75') == 3


class TestDataframeCsv:
    def test_header_and_rows_are_present(self):
        frame = pd.DataFrame({'a': [1, 2], 'b': ['x', 'y']})
        text = df_to_csv_string(frame)
        assert text.splitlines()[0] == 'a,b'
        assert 'x' in text

    def test_an_in_memory_string_carries_no_bom(self):
        # ``encoding='utf-8-sig'`` only matters when a file is opened; writing
        # into a StringIO yields plain text, which is what the preview pane eats.
        text = df_to_csv_string(pd.DataFrame({'a': [1], 'b': ['x']}))
        assert not text.startswith('\ufeff')
        assert text.splitlines()[0] == 'a,b'

    def test_the_string_reparses_into_the_same_table(self):
        frame = pd.DataFrame({'a': [1, 2], 'b': [3.5, 4.5]})
        reparsed = pd.read_csv(io.StringIO(df_to_csv_string(frame).lstrip('\ufeff')))
        pd.testing.assert_frame_equal(reparsed, frame)

    def test_no_index_column_is_written(self):
        assert df_to_csv_string(pd.DataFrame({'a': [1]})).splitlines()[1].startswith('1')


class TestMergeResults:
    def test_lists_are_extended_and_dicts_appended(self):
        merged = merge_results([{'a': 1}, [{'a': 2}, {'a': 3}]])
        assert merged['a'].tolist() == [1, 2, 3]

    def test_other_members_are_ignored_not_crashed_on(self):
        merged = merge_results([[{'a': 1}], 'junk', None, 42, {'b': 2}, [{'c': 3}]])
        assert merged.shape[0] == 3
        assert list(merged.columns) == ['a', 'b', 'c']

    def test_columns_are_the_union_of_the_keys(self):
        merged = merge_results([[{'a': 1}], {'b': 2}])
        assert list(merged.columns) == ['a', 'b']
        assert merged.shape == (2, 2)

    def test_nothing_at_all_is_an_empty_frame(self):
        assert merge_results([]).empty
        assert merge_results([[], {}, None]).empty

    def test_the_key_argument_is_ignored(self):
        assert merge_results([[{'a': 1}]], 'platform')['a'].tolist() == [1]
