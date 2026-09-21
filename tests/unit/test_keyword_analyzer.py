"""Tests for analyzers/keyword.py — jieba TF-IDF / TextRank keyphrases.

jieba is deterministic and offline, so what is worth pinning is the shape the
downstream nodes and charts depend on: two output layouts (one aggregate table
vs. one row per hit per source row) and the rule that a text too short to carry
statistics yields nothing rather than noise.
"""
import math

import pandas as pd
import pytest

from analyzers.keyword import KeywordExtractor

pytestmark = pytest.mark.unit

LONG_TEXT = (
    '三亚的海非常蓝，适合冬天度假。三亚的潜水体验也很好，珊瑚很多，海龟常见。'
    '海口的美食以海南粉出名，汤底非常鲜美。博鳌论坛小镇非常安静，适合散步。'
)
SHORT_TEXT = '三亚'


@pytest.fixture
def df():
    return pd.DataFrame({
        '正文': ['三亚的海非常蓝，适合冬天度假', '海南粉的汤底非常鲜美，很好吃', '潜水体验很好，珊瑚很多'],
        '标题': ['攻略', '美食', '潜水'],
    })


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

    @pytest.mark.parametrize('method, text', [
        ('extract_tfidf', SHORT_TEXT),
        ('extract_textrank', SHORT_TEXT),
        ('extract_tfidf', ''),
        ('extract_tfidf', '   '),
        ('extract_tfidf', None),
    ])
    def test_a_text_too_short_to_score_yields_nothing(self, method, text):
        assert getattr(KeywordExtractor, method)(text) == []

    def test_extraction_is_repeatable(self):
        assert KeywordExtractor.extract_tfidf(LONG_TEXT, topk=5) == KeywordExtractor.extract_tfidf(
            LONG_TEXT, topk=5)


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

    def test_an_unknown_method_falls_back_to_textrank(self, extractor, df):
        result = extractor.analyze_dataframe(df, method='yake', topk=4, merge=False)
        assert set(result['method']) == {'yake'}
        assert len(result) <= 4 * len(df)

    def test_a_custom_text_column_is_honoured(self, extractor):
        frame = pd.DataFrame({'内容': ['海口骑楼老街很有味道', '三亚湾的日落非常漂亮', '博鳌小镇安静适合散步']})
        assert set(extractor.analyze_dataframe(frame, text_column='内容')['method']) == {'tfidf'}

    def test_the_input_frame_is_not_mutated(self, extractor, df):
        before = df.copy()
        extractor.analyze_dataframe(df, merge=False)
        pd.testing.assert_frame_equal(df, before)
