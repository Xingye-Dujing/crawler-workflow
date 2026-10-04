"""The shared stop-word rule — one list, every step that counts words.

Before this module the steps disagreed: the LDA sites in ``services.data_analysis`` filtered only
"has a letter or digit", ``analyzers.keyword`` dropped one-character tokens, and the word cloud
carried its own small set. The result was measured on the 刘学州 export — a phase's top feature
words included 自己 / 一直 / 成为 / 一个 / 这个, and 共词网络's strongest edges joined those. A topic
table led by grammar is not a noisy measurement of the event; it is a measurement of the language.

What is pinned here is the boundary the list has to hold: the shape rules (two characters, some
letter or digit, not a bare number) and the two directions of the judgement — function words out,
domain words in. The second direction matters more than the first: in a cyberbullying corpus even a
word a generic list calls filler (网友, 微博, 私信, 问题) is a subject the paper is about, so those
are asserted to SURVIVE. A list that quietly ate 网暴 would raise the coherence of every topic while
answering nothing.
"""

import pandas as pd
import pytest

from analyzers.stopwords import STOPWORDS, cut, filter_tokens, is_meaningful
from services.data_analysis import DataAnalysisService as D
from services.visualizer import VisualizationService as V

#: Words the study is about. A stop-word list that removes any of these is wrong, not aggressive.
DOMAIN_TERMS = [
    '网暴',
    '暴力',
    '警方',
    '通报',
    '律师',
    '判决',
    '寻亲',
    '生父',
    '校园',
    '霸凌',
    '造谣',
    '私信',
    '微博',
    '网友',
    '粉丝',
    '问题',
    '声音',
]

FUNCTION_TERMS = [
    '自己',
    '一个',
    '这个',
    '那个',
    '一直',
    '成为',
    '我们',
    '他们',
    '就是',
    '不是',
    '因为',
    '但是',
    '什么',
    '怎么',
    '为什么',
    '真的',
    '确实',
    '现在',
    '时候',
    '已经',
    '应该',
    '可以',
    '大家',
    '别人',
    '这样',
    '那样',
]


class TestTheRule:
    @pytest.mark.parametrize('term', FUNCTION_TERMS)
    def test_a_function_word_is_not_a_term(self, term):
        assert term in STOPWORDS
        assert is_meaningful(term) is False

    @pytest.mark.parametrize('term', DOMAIN_TERMS)
    def test_a_word_the_study_is_about_survives(self, term):
        assert is_meaningful(term) is True, f'{term} must never be filtered out'

    @pytest.mark.parametrize(
        ('token', 'expected'),
        [
            ('的', False),
            ('。', False),
            ('，', False),
            ('a', False),
            ('2022', False),
            ('3.5', False),
            ('刘学州', True),
            ('二审', True),
            ('9b', True),
            ('  ', False),
            (None, False),
            ('', False),
        ],
    )
    def test_the_shape_rules(self, token, expected):
        assert is_meaningful(token) is expected

    def test_the_cut_is_the_same_rule_for_every_caller(self):
        tokens = cut('因为网暴，这个孩子已经失去了自己')
        assert '网暴' in tokens
        assert not set(tokens) & {'因为', '这个', '已经', '自己'}

    def test_filter_tokens_keeps_the_order(self):
        assert filter_tokens(['警方', '的', '通报', '了']) == ['警方', '通报']


class TestTheStepsAgree:
    """Every text-derived output must have passed the same filter — one disagreement is two corpora."""

    @classmethod
    def _corpus(cls):
        rows = []
        for index in range(12):
            rows.append(
                {
                    'stage': '发酵期',
                    '正文': f'警方通报 调查 依法 处置 网络暴力 因为 这个 自己 一直 {index}',
                }
            )
            rows.append({'stage': '发酵期', '正文': f'律师 起诉 隐私 曝光 个人信息 就是 什么 大家 别人 {index}'})
        return pd.DataFrame(rows)

    def test_topic_feature_words_carry_no_function_words(self):
        out = D.topic_model(self._corpus(), '正文', n_topics=2, topn=8)
        words = {token for value in out['keyword'] for token in str(value).replace('、', ' ').split()}
        assert words, 'the model produced no words at all'
        assert not words & STOPWORDS, f'特征词 still contains {sorted(words & STOPWORDS)}'

    def test_the_cooccurrence_graph_is_not_built_from_grammar(self):
        out = D.cooccur(self._corpus(), '正文', topn=20, min_count=2)
        assert not out.empty
        names = set(out['source']) | set(out['target'])
        assert not names & STOPWORDS, f'共词网络 still edges through {sorted(names & STOPWORDS)}'
        assert '暴力' in names, 'the content word the corpus repeats must reach the graph'

    def test_the_salient_term_list_uses_the_same_vocabulary(self):
        out = D.topic_salience(self._corpus(), '正文', n_topics=2, topn=6)
        assert not set(out['term']) & STOPWORDS

    def test_the_keyword_node_shares_the_list(self):
        from analyzers.keyword import KeywordExtractor

        tokens = KeywordExtractor._tokenize('因为网暴，这个孩子已经失去了自己', None)
        assert '网暴' in tokens
        assert not set(tokens) & {'因为', '这个', '已经', '自己'}

    def test_the_word_cloud_shares_the_list(self):
        frame = pd.DataFrame({'正文': ['因为网暴，这个孩子已经失去了自己', '网暴 警方 通报 一个 自己']})
        labels, _counts = V.tokenize_frequency(frame, '正文')
        assert '网暴' in labels
        assert not set(labels) & {'因为', '这个', '一个', '自己'}
