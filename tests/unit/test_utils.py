"""Tests for utils/helpers.py — the small shared helpers.

These are the functions the crawler parsers and every download / export path
reach for, so their edges are the interesting parts: a scraped title becomes a
file name, a scraped counter arrives as '1,234' or '3.5万' of text, and a switch
stored by the panel arrives as the text 'false' while the same switch in an
exported workflow file arrives as the boolean ``False``.
"""

import io

import pandas as pd
import pytest

from utils.helpers import (
    MAX_FILENAME_LENGTH,
    as_bool,
    df_to_csv_string,
    export_stamp,
    extract_number,
    merge_results,
    sanitize_filename,
    window_tag,
)

pytestmark = pytest.mark.unit


class TestAsBool:
    """A switch read from a stored parameter, in every grammar that stores one.

    ``== 'true'`` and ``bool(raw)`` are the two wrong readings this helper replaced,
    and each was wrong for a different caller: comparing against the text answered the
    real boolean ``True`` with False (so 升序 sorted descending), and ``bool()``
    answered the text ``'false'`` with True (so an unticked 重新采集 re-crawled
    everything the node had already paid for). The grid below is the two grammars ×
    case × whitespace × language × the default direction, because every one of those
    dimensions is a way a file on disk differs from what the panel wrote.
    """

    @pytest.mark.parametrize(
        ('stored, expected'),
        [
            # The grammar the settings panel used to write.
            ('true', True),
            ('false', False),
            # The grammar a JSON document, an exported workflow and a Python caller write.
            (True, True),
            (False, False),
            # Case and padding are not meaning: the same word in another spelling.
            ('True', True),
            ('TRUE', True),
            ('  true  ', True),
            (' False', False),
            # The words a person types into a draft, in both interface languages.
            ('yes', True),
            ('on', True),
            ('1', True),
            ('no', False),
            ('off', False),
            ('0', False),
            ('是', True),
            ('否', False),
            ('不', False),
            ('假', False),
            # Numbers: pandas' own reading of a truthy cell.
            (1, True),
            (0, False),
            (2, True),
            (-1, True),
        ],
    )
    def test_every_spelling_of_on_and_off(self, stored, expected):
        assert as_bool(stored, default=False) is expected, stored

    @pytest.mark.parametrize('absent', [None, '', '   ', '\n'])
    @pytest.mark.parametrize('default', [True, False])
    def test_a_field_that_states_nothing_answers_the_default(self, absent, default):
        """Blank is not "off". The panel's own default for 升序 and 合并统计 is
        *checked*, so a cleared or never-opened box must keep that direction — which
        is the half ``bool()`` and ``== 'true'`` each got wrong from opposite sides.
        """
        assert as_bool(absent, default=default) is default

    @pytest.mark.parametrize('unintelligible', ['abc', 'maybe', 'tru', '升序', ['true'], {'k': 1}, 'trueish'])
    @pytest.mark.parametrize('default', [True, False])
    def test_a_word_none_of_the_three_grammars_uses_answers_the_default(self, unintelligible, default):
        """A switch has no third position, so a value that is neither list's answer is
        "not stated" rather than a guess. Refusing it would be the matrix's rule; these
        parameters are not selects, and the declared default is the figure the panel
        showed.
        """
        assert as_bool(unintelligible, default=default) is default

    def test_a_missing_field_never_becomes_the_other_answer(self):
        """The comparison this helper replaced, kept as a case rather than a comment:
        ``True == 'true'`` is False, so reading one spelling silently inverted the
        behaviour of every caller that used the other.
        """
        assert as_bool(True) is True
        assert as_bool(True, default=False) is True
        assert as_bool('false', default=True) is False
        assert ('true' == True) is False, 'the reason the old comparison was wrong'

    def test_a_nan_states_nothing(self):
        """``bool(nan)`` is True and ``0 != 0`` is False, so a numeric field that came
        back from pandas as a missing value has to be read as absent.
        """
        assert as_bool(float('nan'), default=False) is False
        assert as_bool(float('nan'), default=True) is True

    def test_the_default_is_false_when_not_given(self):
        assert as_bool(None) is False
        assert as_bool('') is False


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


class TestWindowTag:
    """A crawl's declared time window, as a filename component.

    The window is the only thing that tells a table collected for January apart from the
    one collected for March, and it used to exist nowhere but the node's own form — the
    second file silently replaced the first and nobody could tell afterwards which month
    they were reading. Anything that is not a complete, parseable pair answers the empty
    string, because the crawler refuses those inputs itself and half a name would claim a
    range this table does not describe.
    """

    def test_a_complete_pair_is_compacted_into_the_component(self):
        assert window_tag('2026-01-01', '2026-03-15') == '_20260101_to_20260315'

    def test_padding_and_a_longer_timestamp_still_read_as_the_date(self):
        assert window_tag('  2026-01-01 ', '2026-03-15 08:30:00') == '_20260101_to_20260315'

    @pytest.mark.parametrize(
        'start,end',
        [
            (None, None),
            ('', ''),
            ('2026-01-01', ''),
            ('', '2026-03-15'),
            ('2026-13-01', '2026-03-15'),
            ('January', '2026-03-15'),
            ('2026/01/01', '2026-03-15'),
        ],
    )
    def test_an_incomplete_or_unparseable_pair_names_nothing(self, start, end):
        assert window_tag(start, end) == ''

    def test_an_unpadded_date_is_read_because_the_crawler_reads_it(self):
        # ``crawlers/weibo.py:_parse_date`` accepts this through the same strptime, so a
        # filename that refused it would disagree with the crawl that really ran.
        assert window_tag('2026-1-1', '2026-3-5') == '_20260101_to_20260305'

    def test_a_one_sided_window_is_not_half_a_name(self):
        # ``crawlers/weibo.py:_build_urls`` raises on exactly this input; a filename is
        # not where that answer belongs, and printing one date would read as a range.
        assert window_tag('2026-01-01', None) == ''

    def test_the_separator_is_not_a_tilde(self):
        # NTFS reads '~' as an 8.3 short-name marker and ``sanitize_filename`` would keep
        # it, so the character is a decision, not a taste.
        assert '~' not in window_tag('2026-01-01', '2026-03-15')

    def test_the_tag_survives_the_filename_sanitizer_unchanged(self):
        tag = window_tag('2026-01-01', '2026-03-15')
        assert sanitize_filename(tag) == tag, 'the sanitizer would be eating this out of every name'


class TestExportStamp:
    """Which record wrote this file, in its name — and stable across that record's attempts.

    ``PartWriter`` adopts the shards an interrupted attempt already flushed by matching
    its stem as a prefix, so a stamp that moved between attempts would leave those parts
    orphaned beside a numbering that restarted at 001. The record's ``started_at`` is
    precisely the field 继续 never refreshes; the run id is the fallback, because it keeps
    the one property that matters — one value per record, a different one between records.
    """

    def test_the_iso_timestamp_the_store_writes_becomes_the_component(self):
        assert export_stamp('2026-10-02T14:35:07') == '_20261002-1435'

    def test_a_space_separated_date_is_read_as_well(self):
        assert export_stamp('2026-10-02 14:35:07') == '_20261002-1435'

    def test_the_record_id_rides_along_because_minutes_collide(self):
        # A parallel canvas opens several records inside one second, so no date
        # resolution short of the record itself keeps two of them off one filename.
        assert export_stamp('2026-10-02T14:35:07', 'a1b2c3d4') == '_20261002-1435-a1b2c3d4'
        assert export_stamp('2026-10-02T14:35:07', 'zzzz9999') != export_stamp('2026-10-02T14:35:07', 'a1b2c3d4')

    def test_the_two_pieces_each_stand_alone(self):
        assert export_stamp('2026-10-02T14:35:07', '') == '_20261002-1435'
        assert export_stamp('', 'a1b2c3d4') == '_a1b2c3d4'

    @pytest.mark.parametrize('stored', ['', None, 'not a date', '2026-10-02'])
    def test_an_unreadable_date_falls_back_to_the_run_id(self, stored):
        assert export_stamp(stored, 'abcdef123456') == '_abcdef12'

    def test_the_fallback_cannot_carry_path_shape(self):
        assert export_stamp('', '../evil') == '_evil'

    def test_nothing_to_name_answers_nothing(self):
        assert export_stamp('', '') == ''
        assert export_stamp(None, None) == ''

    def test_two_attempts_of_one_record_answer_the_same_string(self):
        # The whole reason this is read off the record instead of ``time.strftime``: a
        # resumed crawl must find the shards its previous attempt left, by name.
        first = export_stamp('2026-10-02T14:35:07', 'run1')
        assert first == export_stamp('2026-10-02T14:35:07', 'run1')


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
