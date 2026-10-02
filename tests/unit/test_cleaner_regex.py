"""``analyzers/cleaner.py`` — the rule-based mode, which spends no model.

The cleaning node was the one operation that ALWAYS called a language model, which on a
Weibo comment table means hours per 10^5 rows on any machine that cannot serve a local
one. The regex mode is the answer to that: it washes the shapes a repost leaves behind
and settles the rows that were nothing else.

What is pinned here is that it stays honest about the two things it cannot do — judge
topic relevance, and invent text — and that it never quietly becomes a model call. The
forward chain gets its own attention because getting it backwards is silent: keep the
tail instead of the head and every repost is judged on whoever was quoted.
"""

import pandas as pd
import pytest

import analyzers.cleaner as cleaner_module
from analyzers.cleaner import ContentCleaner
from i18n import set_lang

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _chinese():
    set_lang('zh')


def frame(*texts) -> pd.DataFrame:
    return pd.DataFrame([{'正文': t} for t in texts])


class TestWashText:
    """One comment in, one washed comment (or nothing) out."""

    def test_a_forward_chain_keeps_the_reposters_own_words_and_drops_the_quote(self):
        """Weibo puts the reposter's reason FIRST: `我也觉得//@A:原文`. The tail is somebody
        else's text, so keeping it would have the sentiment node judge the wrong person."""
        washed = ContentCleaner.wash_text('我也觉得//@张三:说得对//@李四:太离谱了')
        assert washed == '我也觉得'

    def test_a_pure_repost_with_no_words_of_its_own_is_deleted(self):
        # There is no head to keep, so the row is an artifact rather than a comment.
        assert ContentCleaner.wash_text('//@张三:说得对') == ''

    def test_mentions_and_topic_markers_go_but_the_topic_words_stay(self):
        washed = ContentCleaner.wash_text('@小明 你觉得呢 #三亚旅游# 太美了')
        assert '小明' not in washed
        assert '三亚旅游' in washed, 'the topic word is often the best token in the comment'
        assert '#' not in washed

    def test_links_and_placeholders_are_removed(self):
        washed = ContentCleaner.wash_text('看这个 https://t.cn/A6xyz O网页链接 真的绝了 展开c')
        assert 'http' not in washed and '网页链接' not in washed and '展开c' not in washed
        assert '真的绝了' in washed

    @pytest.mark.parametrize(
        'raw, expected',
        [
            ('正文内容收起d', '正文内容'),
            ('正文内容展开d', '正文内容'),
            ('正文内容展开全文', '正文内容'),
            ('正文内容收起全文', '正文内容'),
            ('正文内容展开c', '正文内容'),
            ('正文内容收起c', '正文内容'),
            ('正文内容 展开 更多', '正文内容 更多'),
        ],
    )
    def test_the_expand_control_goes_whole(self, raw, expected):
        """Measured on a real 10k-row weibo export: 23–29% of rows carried the card's own
        展开/收起 control inside 正文, spelled ``收起d``. The old pattern hard-coded the
        letter ``c``, so it matched none of them; and its standalone ``全文`` alternative ate
        only the tail of 「展开全文」, leaving a bare 「展开」 that reads like a word — worse
        than no match at all.
        """
        assert ContentCleaner.wash_text(raw) == expected

    @pytest.mark.parametrize(
        'prose',
        [
            '请大家展开讨论这个问题',
            '请展开说说你的想法',
            '全文如下所述内容较长',
            '这件事情展开了新的调查',
            '他展开双臂拥抱了她',
            '展会开始收起摊位',
        ],
    )
    def test_the_marker_is_never_stripped_out_of_prose(self, prose):
        """The half that protects the text: 展开 is an ordinary verb, so the control only
        goes where a sentence cannot follow it. A pattern that removed the bare word would
        quietly edit what the user wrote — and this is the same distinction ``engine.times``
        makes for relative labels: recognise the shape, never the bare word."""
        assert ContentCleaner.wash_text(prose) == prose

    def test_emoji_codes_are_removed_because_they_tokenise_into_keyword_noise(self):
        washed = ContentCleaner.wash_text('[泪][泪]太感动了[赞]')
        assert '[' not in washed and ']' not in washed
        assert '太感动了' in washed

    def test_a_row_that_was_only_emoji_and_punctuation_is_deleted(self):
        # Nothing survives the artifact strip, so there is no opinion here to analyse.
        assert ContentCleaner.wash_text('[泪][泪][泪]') == ''
        assert ContentCleaner.wash_text('。。。！！！') == ''

    def test_a_run_of_identical_characters_collapses(self):
        assert ContentCleaner.wash_text('哈哈哈哈哈哈哈哈') == '哈哈'

    def test_zero_width_characters_are_stripped(self):
        assert '\u200b' not in ContentCleaner.wash_text('好\u200b的\u200b吧')

    def test_reply_prefixes_and_contact_details_are_removed(self):
        washed = ContentCleaner.wash_text('回复@小红:加微信 abc12345 了解一下')
        assert '小红' not in washed
        assert 'abc12345' not in washed

    def test_text_survives_instruction_like_content_untouched(self):
        # A rule set must not paraphrase: what it cannot classify, it leaves exactly as
        # written, because only the model mode is allowed to rewrite a comment.
        assert ContentCleaner.wash_text('这服务太差了，再也不来了') == '这服务太差了，再也不来了'


class TestRegexMode:
    def test_the_column_contract_is_the_one_the_model_path_writes(self):
        out = ContentCleaner().clean_dataframe(frame('太差劲了//@张三:原文'), mode='regex')
        assert {'action', 'cleaned_text'} <= set(out.columns)
        assert out.at[0, 'action'] == '保留'
        assert out.at[0, 'cleaned_text'] == '太差劲了'

    def test_the_source_column_is_kept_so_nothing_is_destroyed(self):
        out = ContentCleaner().clean_dataframe(frame('[泪]好难过'), mode='regex')
        assert out.at[0, '正文'] == '[泪]好难过', 'the raw comment must still be readable downstream'
        assert out.at[0, 'cleaned_text'] == '好难过'

    def test_a_row_that_washing_emptied_is_marked_deleted_not_left_undecided(self):
        out = ContentCleaner().clean_dataframe(frame('//@张三:原文', '真的很好'), mode='regex')
        assert out.at[0, 'action'] == '删除' and out.at[0, 'cleaned_text'] is None
        assert out.at[1, 'action'] == '保留'

    def test_a_blank_row_stays_blank_rather_than_being_called_deleted(self):
        """「没有内容可判」 and 「判定为删除」 are different statements, and the model path
        draws the same line."""
        out = ContentCleaner().clean_dataframe(frame('', None), mode='regex')
        assert list(out['action']) == ['', '']
        assert list(out['cleaned_text']) == [None, None]

    def test_the_regex_mode_never_reaches_a_model(self, monkeypatch):
        def boom(*args, **kwargs):
            raise AssertionError('the regex mode must not call the row runner')

        monkeypatch.setattr(cleaner_module, 'run_llm_dataframe', boom)
        out = ContentCleaner().clean_dataframe(frame('真的很好'), mode='regex')
        assert out.at[0, 'cleaned_text'] == '真的很好'

    def test_a_missing_column_is_reported_not_a_crash(self):
        out = ContentCleaner().clean_dataframe(pd.DataFrame([{'别的': 'x'}]), '正文', mode='regex')
        assert list(out.columns) == ['别的', 'action', 'cleaned_text']

    @pytest.mark.parametrize('stored', ['Regex', 'REGEX', 'rules', 'clean'])
    def test_an_unknown_mode_is_refused_by_name(self, stored):
        # The analyzer is reachable directly (/api/analysis/run), so the second door holds
        # the same rule as the node: a name it does not know is never another algorithm.
        with pytest.raises(ValueError, match=stored) as err:
            ContentCleaner().clean_dataframe(frame('好'), mode=stored)
        assert 'regex' in str(err.value), 'the refusal must name what IS available'


class TestDeclaredMode:
    """The node's select-shaped parameter, refused by name like every other one."""

    @pytest.fixture
    def exec_(self):
        import app

        return app

    def test_the_two_modes_are_what_the_matrix_declares(self, exec_):
        default, allowed = exec_.PROCESS_ENUMS['clean']['mode']
        assert allowed == ('regex', 'llm')
        # A workflow saved before this selector existed was doing llm work; a blank must
        # not silently change what a stored canvas produces.
        assert default == 'llm'

    def test_a_blank_mode_is_the_declared_default(self, exec_):
        assert exec_.enum_param('clean', {}, 'mode') == 'llm'
        assert exec_.enum_param('clean', {'mode': '  '}, 'mode') == 'llm'

    def test_the_regex_mode_is_what_asks_for_no_model(self, exec_):
        """The whole point of the mode: a regex clean node must not block a run behind an
        API key, and a blank one must still behave as it always did."""
        assert exec_._op_needs_llm('clean', {'mode': 'regex'}) is False
        assert exec_._op_needs_llm('clean', {'mode': 'llm'}) is True
        assert exec_._op_needs_llm('clean', {}) is True
