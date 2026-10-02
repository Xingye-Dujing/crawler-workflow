"""Tests for analyzers/keyword.py — jieba TF-IDF / TextRank / corpus keyphrases.

jieba is deterministic and offline, so what is worth pinning is the shape the
downstream nodes and charts depend on: two output layouts (one aggregate table
vs. one row per hit per source row) and the rule that a text too short to carry
statistics yields nothing rather than noise.

Three later features are pinned here too, each with the same "why": the optional
POS filter, the corpus-scored TF-IDF whose IDF comes from the user's own table
instead of jieba's news corpus, and the domain user dictionary jieba has no way
to know about.
"""

import math

import jieba
import jieba.posseg
import pandas as pd
import pytest

from analyzers.keyword import KeywordExtractor
from config import Config

pytestmark = pytest.mark.unit

LONG_TEXT = (
    '三亚的海非常蓝，适合冬天度假。三亚的潜水体验也很好，珊瑚很多，海龟常见。'
    '海口的美食以海南粉出名，汤底非常鲜美。博鳌论坛小镇非常安静，适合散步。'
)
SHORT_TEXT = '三亚'

#: A phrase whose jieba POS tags the allow_pos tests derive their expectation from, so no
#: assertion below pastes a keyword list jieba could re-tag between versions.
TAGGED_TEXT = '三亚的海非常蓝，很适合冬天度假。潜水体验很好，珊瑚很多，海龟常见。'


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            '正文': ['三亚的海非常蓝，适合冬天度假', '海南粉的汤底非常鲜美，很好吃', '潜水体验很好，珊瑚很多'],
            '标题': ['攻略', '美食', '潜水'],
        }
    )


@pytest.fixture
def extractor():
    return KeywordExtractor()


class TestSingleTextExtraction:
    @pytest.mark.parametrize('method', ['extract_tfidf', 'extract_textrank'])
    def test_hits_are_keyword_weight_records(self, method):
        hits = getattr(KeywordExtractor, method)(LONG_TEXT, topk=5)
        assert hits and len(hits) <= 5
        assert all(sorted(hit) == ['keyword', 'weight'] for hit in hits)

    @pytest.mark.parametrize('method', ['extract_tfidf', 'extract_textrank'])
    def test_weights_are_rounded_and_descending(self, method):
        weights = [hit['weight'] for hit in getattr(KeywordExtractor, method)(LONG_TEXT, topk=8)]
        assert all(round(w, 4) == w for w in weights)
        assert weights == sorted(weights, reverse=True)

    @pytest.mark.parametrize('method', ['extract_tfidf', 'extract_textrank'])
    def test_topk_is_a_hard_cap(self, method):
        assert len(getattr(KeywordExtractor, method)(LONG_TEXT, topk=2)) == 2

    @pytest.mark.parametrize(
        'method, text',
        [
            ('extract_tfidf', SHORT_TEXT),
            ('extract_textrank', SHORT_TEXT),
            ('extract_tfidf', ''),
            ('extract_tfidf', '   '),
            ('extract_tfidf', None),
        ],
    )
    def test_a_text_too_short_to_score_yields_nothing(self, method, text):
        assert getattr(KeywordExtractor, method)(text) == []

    def test_extraction_is_repeatable(self):
        assert KeywordExtractor.extract_tfidf(LONG_TEXT, topk=5) == KeywordExtractor.extract_tfidf(LONG_TEXT, topk=5)


class TestDataframeMode:
    def test_merged_mode_returns_one_aggregate_table(self, extractor, df):
        result = extractor.analyze_dataframe(df, method='tfidf', topk=6)
        assert list(result.columns) == ['method', 'keyword', 'weight']
        assert len(result) <= 6
        assert set(result['method']) == {'tfidf'}
        assert all(isinstance(v, str) for v in result['keyword'])

    def test_per_row_mode_keeps_the_source_index(self, extractor, df):
        result = extractor.analyze_dataframe(df, method='textrank', topk=3, merge=False)
        assert list(result.columns) == ['keyword', 'weight', 'row', 'method']
        assert set(result['method']) == {'textrank'}
        assert set(result['row']) <= set(df.index)
        assert all(math.isfinite(w) for w in result['weight'])

    def test_empty_cells_never_appear_as_hits(self, extractor):
        frame = pd.DataFrame({'正文': ['三亚的海非常蓝，适合冬天度假', None, '   ', '海口的海南粉很鲜美']})
        result = extractor.analyze_dataframe(frame, merge=False, topk=4)
        assert set(result['row']) == {0, 3}

    def test_a_missing_column_returns_the_frame_untouched(self, extractor, df):
        assert extractor.analyze_dataframe(df, text_column='不存在') is df

    def test_an_unknown_method_is_refused_by_name(self, extractor, df):
        """Not TextRank with the requested name stamped into the output.

        The table's own ``method`` column used to say ``'yake'`` for rows jieba's
        co-occurrence graph had produced, so the file itself lied about how it was
        made and a filter on that column matched them.
        """
        with pytest.raises(ValueError, match='yake') as err:
            extractor.analyze_dataframe(df, method='yake', topk=4, merge=False)
        # The refusal must name what WAS available, or the user cannot fix the typo — and the
        # corpus method has to be in that list, since it is a real method of this node.
        assert 'tfidf_corpus' in str(err.value)

    def test_a_custom_text_column_is_honoured(self, extractor):
        frame = pd.DataFrame({'内容': ['海口骑楼老街很有味道', '三亚湾的日落非常漂亮', '博鳌小镇安静适合散步']})
        assert set(extractor.analyze_dataframe(frame, text_column='内容')['method']) == {'tfidf'}

    def test_the_input_frame_is_not_mutated(self, extractor, df):
        before = df.copy()
        extractor.analyze_dataframe(df, merge=False)
        pd.testing.assert_frame_equal(df, before)


# ─── allow_pos ───


def _tag_map(*texts: str) -> dict[str, str]:
    """word → jieba's POS tag for that word, taken from the same posseg pass the code uses."""
    tags = {}
    for text in texts:
        tags.update({word.word: word.flag for word in jieba.posseg.cut(text)})
    return tags


class TestAllowPos:
    """The stored POS filter: one comma/、-separated string, blank meaning "do not filter"."""

    @pytest.mark.parametrize('method', ['extract_tfidf', 'extract_textrank'])
    def test_only_the_named_categories_survive(self, method):
        tags = _tag_map(TAGGED_TEXT)
        assert tags['度假'] == 'v', 'the fixture no longer carries the verb this test filters on'
        hits = getattr(KeywordExtractor, method)(TAGGED_TEXT, topk=20, allow_pos='v')
        assert hits, 'nothing scored, so the tag filter was never exercised'
        assert all(tags[hit['keyword']] == 'v' for hit in hits)

    @pytest.mark.parametrize('method', ['extract_tfidf', 'extract_textrank'])
    def test_a_category_the_text_does_not_carry_yields_nothing(self, method):
        assert getattr(KeywordExtractor, method)(TAGGED_TEXT, topk=5, allow_pos='eng') == []

    def test_the_stored_string_the_comma_and_the_list_forms_agree(self):
        """The panel sends ``'n、v'``, a saved workflow may hold a list: one filter, one answer."""
        list_form = KeywordExtractor.extract_tfidf(TAGGED_TEXT, topk=20, allow_pos=['n', 'v'])
        assert list_form
        assert KeywordExtractor.extract_tfidf(TAGGED_TEXT, topk=20, allow_pos='n、v') == list_form
        assert KeywordExtractor.extract_tfidf(TAGGED_TEXT, topk=20, allow_pos='n,v') == list_form

    @pytest.mark.parametrize('method', ['extract_tfidf', 'extract_textrank'])
    def test_blank_allow_pos_leaves_todays_output_alone(self, method):
        """Blank is the default and jieba's own default must survive it.

        TextRank is the reason this is not vacuous: its default ``allowPOS`` is
        ``('ns', 'n', 'vn', 'v')``, and passing the empty tuple a literal reading of "no
        filtering" suggests would empty its POS filter and return no keyword at all.
        """
        fn = getattr(KeywordExtractor, method)
        baseline = fn(TAGGED_TEXT, topk=8)
        assert baseline, 'the fixture must score something, or this comparison proves nothing'
        assert fn(TAGGED_TEXT, topk=8, allow_pos='') == baseline
        assert fn(TAGGED_TEXT, topk=8, allow_pos='   ') == baseline
        assert fn(TAGGED_TEXT, topk=8, allow_pos=[]) == baseline

    @pytest.mark.parametrize('method', ['tfidf', 'textrank'])
    def test_analyze_dataframe_passes_the_filter_to_both_methods(self, extractor, df, method):
        tags = _tag_map(*df['正文'])
        hits = extractor.analyze_dataframe(df, method=method, topk=10, merge=False, allow_pos='n')
        assert not hits.empty, 'no noun hit at all, so the dataframe path never applied the filter'
        assert all(tags[keyword] == 'n' for keyword in hits['keyword'])

    def test_analyze_dataframe_merged_mode_filters_too(self, extractor, df):
        tags = _tag_map(' '.join(df['正文']))
        hits = extractor.analyze_dataframe(df, method='tfidf', topk=10, merge=True, allow_pos='v')
        assert not hits.empty
        assert all(tags[keyword] == 'v' for keyword in hits['keyword'])


# ─── tfidf_corpus ───


class TestTfidfCorpus:
    """The method whose IDF is the user's table, not jieba's news corpus."""

    def test_it_is_an_accepted_method_with_its_own_name_in_the_table(self, extractor, df):
        merged = extractor.analyze_dataframe(df, method='tfidf_corpus', topk=4)
        assert set(merged['method']) == {'tfidf_corpus'}
        per_row = extractor.analyze_dataframe(df, method='tfidf_corpus', topk=2, merge=False)
        assert set(per_row['method']) == {'tfidf_corpus'}
        assert set(per_row['row']) <= set(df.index)

    @pytest.mark.parametrize('merge', [True, False])
    def test_it_returns_the_same_columns_as_the_other_methods(self, extractor, df, merge):
        corpus = extractor.analyze_dataframe(df, method='tfidf_corpus', topk=4, merge=merge)
        assert not corpus.empty
        for other in ('tfidf', 'textrank'):
            reference = extractor.analyze_dataframe(df, method=other, topk=4, merge=merge)
            assert list(corpus.columns) == list(reference.columns)

    def test_topk_is_a_hard_cap_in_both_modes(self, extractor, df):
        assert len(extractor.tfidf_corpus(df, topk=3, merge=True)) <= 3
        per_row = extractor.tfidf_corpus(df, topk=1, merge=False)
        assert not per_row.empty
        assert per_row.groupby('row').size().max() == 1

    def test_a_term_every_row_uses_scores_below_a_term_one_row_owns(self):
        """The IDF is the table's: 三亚 is in all three rows, the unique term only in one.

        Both terms occur once in the row that owns both, so the row's shared L2 norm cancels
        and the comparison is the IDF alone — the opposite of what a news corpus would say
        about 潜水, and the reason this method exists.
        """
        frame = pd.DataFrame({'正文': ['三亚的潜水体验很好', '三亚的美食很多', '三亚的酒店很安静']})
        per_row = KeywordExtractor().tfidf_corpus(frame, topk=10, merge=False)
        first = per_row[per_row['row'] == 0]
        weights = dict(zip(first['keyword'], first['weight'], strict=True))
        assert {'三亚', '潜水'} <= set(weights), weights
        assert weights['三亚'] < weights['潜水']

    def test_merged_weights_are_the_per_row_weights_summed(self, extractor, df):
        per_row = extractor.tfidf_corpus(df, topk=100, merge=False)
        merged = extractor.tfidf_corpus(df, topk=100, merge=True)
        totals = per_row.groupby('keyword')['weight'].sum()
        assert set(merged['keyword']) == set(totals.index)
        for keyword, weight in zip(merged['keyword'], merged['weight'], strict=True):
            # A 1e-3 tolerance: the per-row column is rounded before this sum is taken.
            assert weight == pytest.approx(totals[keyword], abs=1e-3), keyword

    def test_allow_pos_filters_the_corpus_tokens_too(self, extractor, df):
        tags = _tag_map(*df['正文'])
        hits = extractor.tfidf_corpus(df, topk=5, merge=True, allow_pos='n')
        assert not hits.empty
        assert all(tags[keyword] == 'n' for keyword in hits['keyword'])

    def test_a_filter_no_token_carries_is_an_empty_table_not_a_crash(self, extractor, df):
        empty = extractor.tfidf_corpus(df, topk=5, allow_pos='eng')
        assert empty.empty
        assert list(empty.columns) == ['method', 'keyword', 'weight']

    def test_a_table_with_no_usable_text_returns_the_empty_table(self, extractor):
        frame = pd.DataFrame({'正文': ['', None, '   ']})
        merged = extractor.tfidf_corpus(frame, topk=5, merge=True)
        assert merged.empty and list(merged.columns) == ['method', 'keyword', 'weight']
        per_row = extractor.tfidf_corpus(frame, topk=5, merge=False)
        assert per_row.empty and list(per_row.columns) == ['keyword', 'weight', 'row', 'method']

    def test_a_missing_column_returns_the_frame_untouched(self, extractor, df):
        assert extractor.tfidf_corpus(df, text_column='不存在') is df

    def test_two_runs_on_one_table_agree(self, extractor, df):
        assert extractor.tfidf_corpus(df, topk=4).equals(extractor.tfidf_corpus(df, topk=4))


# ─── domain user dictionary ───

#: A word no news corpus contains, so the tests prove the FILE was read rather than that jieba
#: guessed the same segmentation.
USERDICT_WORD = '荧惑星野度假星球'


@pytest.fixture
def domain_dict(tmp_path, monkeypatch):
    """A domain dictionary reachable only through ``Config.DATA_DIR``.

    The directory is created inside the test's own tmp root on purpose: if the module read the
    path from its own file location, or froze it at import time, this file would never be found
    and the test below would fail instead of silently passing on the repository's ``data/``.
    """
    (tmp_path / 'jieba').mkdir()
    (tmp_path / 'jieba' / 'userdict.txt').write_text(f'{USERDICT_WORD} 4242 nz\n', encoding='utf-8')
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    yield tmp_path
    # jieba's dictionary is process-wide, so the entry is taken out again: left behind it would
    # change what every later keyword test segments.
    jieba.del_word(USERDICT_WORD)


class TestDomainUserDictionary:
    def test_the_file_is_read_and_the_word_is_cut_whole(self, domain_dict):
        text = f'{USERDICT_WORD}的日落非常漂亮'
        KeywordExtractor.extract_tfidf(text, topk=5)
        assert jieba.dt.FREQ.get(USERDICT_WORD) == 4242, 'the dictionary file was never read'
        assert USERDICT_WORD in jieba.lcut(text), 'the word was read but did not change segmentation'

    def test_it_is_read_once_and_not_once_per_row(self, tmp_path, monkeypatch):
        reads = []
        (tmp_path / 'jieba').mkdir()
        (tmp_path / 'jieba' / 'userdict.txt').write_text(f'{USERDICT_WORD} 4242 nz\n', encoding='utf-8')
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
        monkeypatch.setattr(jieba, 'load_userdict', reads.append)
        frame = pd.DataFrame({'正文': [f'{USERDICT_WORD}的度假体验很好' for _ in range(4)]})
        KeywordExtractor().analyze_dataframe(frame, merge=False, topk=2)
        assert len(reads) == 1, f'a per-row loop re-read the dictionary {len(reads)} times'

    def test_the_node_works_with_no_dictionary_at_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))  # no jieba/ inside, as on a fresh install
        assert KeywordExtractor.extract_tfidf(LONG_TEXT, topk=5)
        merged = KeywordExtractor().tfidf_corpus(pd.DataFrame({'正文': ['三亚的海很蓝，适合度假', '潜水很好']}), topk=3)
        assert not merged.empty
