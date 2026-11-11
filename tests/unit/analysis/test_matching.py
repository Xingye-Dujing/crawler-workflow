"""The one definition of "the same content" (``services/analysis/matching.py``).

Two features compare two tables — the 内容去重 step and the 采集校验 node — and this module is
their shared answer. What it must never do is decide two empty cells are "the same content", or
fold two different pages into one key: both failures are silent, and both cost the user either a
row that vanished or a hole the audit never reported.
"""

import pytest

from services.analysis.kernels import UnknownOperationError
from services.analysis.matching import (
    COUNT_MODES,
    MATCH_MODES,
    canonical_url,
    cell_text,
    key_counts,
    match_mask,
    row_key,
    value_key,
)

pytestmark = pytest.mark.unit


class TestTheKeySpelling:
    def test_a_number_and_its_text_form_are_one_key(self):
        """A CSV answers ``12345``; a JSON export answers ``12345`` as an int; pandas can answer
        ``12345.0``. A key that changes spelling between two files makes every row unmatched."""
        assert cell_text(12345) == cell_text('12345') == cell_text(12345.0) == '12345'
        assert cell_text(float('nan')) == ''
        assert cell_text(None) == ''

    def test_trim_folds_padding_and_full_width_spaces(self):
        assert value_key('  张三 ', 'trim') == '张三'
        assert value_key('张\u3000三', 'trim') == '张 三'

    def test_exact_is_exact(self):
        assert value_key(' A ', 'exact') != value_key('A', 'exact')

    def test_case_folding_is_opt_in_and_never_touches_a_url_path(self):
        assert value_key('ABC', 'trim') != value_key('abc', 'trim')
        assert value_key('ABC', 'trim', ignore_case=True) == 'abc'
        # A host is folded by the URL rule itself; a path is case-sensitive on real sites.
        assert value_key('https://EX.com/a/B', 'url') == 'https://ex.com/a/B'

    def test_a_blank_cell_has_no_identity(self):
        assert value_key('', 'trim') == ''
        assert value_key('   ', 'trim') == ''
        assert value_key(None, 'url') == ''

    def test_an_unknown_mode_is_refused_by_name(self):
        with pytest.raises(UnknownOperationError) as excinfo:
            value_key('x', 'moon')
        assert 'moon' in str(excinfo.value)

    def test_similar_is_not_a_key_mode(self):
        """Near matching groups transitively, so it can say hit/miss but never "which key"."""
        assert 'similar' in MATCH_MODES and 'similar' not in COUNT_MODES
        with pytest.raises(UnknownOperationError):
            value_key('x', 'similar')


class TestTheUrlRule:
    def test_the_forms_one_site_serves_for_one_page_fold_together(self):
        plain = canonical_url('https://www.weibo.com/detail/42')
        assert canonical_url('HTTPS://WWW.WEIBO.COM/detail/42/') == plain
        assert canonical_url('https://weibo.com/detail/42#comment') == plain
        assert canonical_url('https://weibo.com/detail/42?utm_source=share&spm=a1z.1') == plain
        assert canonical_url('//weibo.com/detail/42') == plain

    def test_a_meaningful_query_is_kept_and_sorted(self):
        assert canonical_url('https://ex.com/p?b=2&a=1') == 'https://ex.com/p?a=1&b=2'

    def test_a_non_address_is_not_an_address(self):
        assert canonical_url('张三') == ''
        assert canonical_url('') == ''

    def test_url_mode_falls_back_to_the_trimmed_cell(self):
        """A list of names is compared by its text; only an address takes the URL rule."""
        assert value_key(' 某人 ', 'url') == '某人'


class TestCompositeKeys:
    def test_two_columns_are_one_identity(self):
        left = {'平台': 'weibo', '链接': 'https://a/1'}
        right = {'平台': 'weibo', '链接': 'https://a/1'}
        assert row_key(left, ['平台', '链接'], 'trim') == row_key(right, ['平台', '链接'], 'trim')

    def test_a_partially_blank_tuple_never_matches(self):
        """``('公众号A', '')`` must not match every blank link of that account."""
        assert row_key({'a': 'x', 'b': ''}, ['a', 'b'], 'trim') == ''
        assert row_key({'a': '', 'b': 'y'}, ['a', 'b'], 'trim') == ''


class TestMatchMask:
    def test_equality_modes_answer_membership_and_count_the_blanks(self):
        mask, stats = match_mask(['a', 'b', ' ', ''], ['a', 'a', ''], mode='trim')
        assert mask == [True, False, False, False]
        assert stats == {'left_blank': 2, 'right_blank': 1, 'right_keys': 1}

    def test_an_empty_right_side_matches_nothing(self):
        mask, stats = match_mask(['a'], [], mode='trim')
        assert mask == [False] and stats['right_keys'] == 0

    def test_similar_finds_a_near_rewrite_and_ignores_the_unrelated(self):
        """Measured on this pair: a one-character addition sits 14 bits away, an unrelated
        sentence 36 — so the search is asked for a distance that can actually separate them."""
        left = ['今天的三亚湾日落真的很美', '完全无关的另一句话']
        right = ['今天的三亚湾日落真的很美啊']
        mask, _stats = match_mask(left, right, mode='similar', max_distance=15)
        assert mask == [True, False], mask

    def test_a_distance_the_banded_search_cannot_prove_is_refused(self):
        with pytest.raises(UnknownOperationError) as excinfo:
            match_mask(['a'], ['a'], mode='similar', max_distance=99)
        assert '99' in str(excinfo.value)

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(UnknownOperationError):
            match_mask(['a'], ['a'], mode='moon')


class TestKeyCounts:
    def test_it_counts_rows_per_key_and_reports_the_blanks(self):
        counts, blanks = key_counts(['https://a/1', 'https://a/1/', ' ', 'https://b/2'], mode='url')
        assert counts == {'https://a/1': 2, 'https://b/2': 1}
        assert blanks == 1
