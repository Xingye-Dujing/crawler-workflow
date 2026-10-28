"""Tests for analyzers/ner.py — Chinese entity extraction, in both its modes.

The rules need no model and the LLM path needs one, but the *contract* is the
same and that is what these tests are mostly about: always the five columns
(row/text/label/start/end), one row per entity, and offsets that reproduce the
entity inside its source row. The offset invariant is also the safety net for
the model — an entity it invents cannot survive the check.

The LLM transport is a scripted ``LLMClient`` subclass, exactly like the other
analyzer tests: no sockets, no daemon, and the answers are whatever the script
says, including answers that are wrong on purpose.
"""

import pandas as pd
import pytest

from analyzers.llm_client import ABORT_MARK, LLMClient, LLMError
from analyzers.ner import _LABEL_SEP, _PAIR_SEP, COLUMNS, NamedEntityRecognizer, _explode, answer_pair, wanted_types

pytestmark = pytest.mark.unit

CASES = [
    # The ORG pattern is still greedy — a leading 张先生 sits inside its span —
    # but the surname fix lands the PERSON hit too, so these entries are
    # per-entity presences, not exhaustive result lists.
    ('张先生在北京大学毕业', 'ORG', '张先生在北京大学'),
    ('张先生在北京大学毕业', 'PERSON', '张先生'),
    ('他在北京。北京大学很有名', 'ORG', '北京大学'),
    ('李女士位于上海市', 'LOC', '上海市'),
    ('李女士位于上海市', 'PERSON', '李女士'),
    ('。王小明先生出席了会议', 'PERSON', '王小明先生'),
    ('2024年1月1日开会', 'DATE', '2024年1月1日'),
]


@pytest.fixture
def recognizer():
    return NamedEntityRecognizer()


@pytest.fixture
def df():
    return pd.DataFrame({'正文': ['张先生在北京大学毕业', '李女士位于上海市', '2024年1月1日开会']})


class TestOutputContract:
    def test_the_sample_crawl_texts_are_returned_as_a_table(self, recognizer, df):
        result = recognizer.analyze_dataframe(df)
        assert list(result.columns) == COLUMNS
        assert sorted(result['label'].unique().tolist()) == ['DATE', 'LOC', 'ORG', 'PERSON']

    def test_an_empty_result_still_has_the_five_columns(self, recognizer):
        result = recognizer.analyze_dataframe(pd.DataFrame({'正文': ['今天天气不错', '没有实体']}))
        assert list(result.columns) == COLUMNS
        assert result.empty

    def test_a_missing_text_column_still_answers_with_the_entity_table(self, recognizer, df):
        # Handing back the *input* frame used to look like a run that found
        # nothing, and downstream charts then read a column that is not there.
        # One contract: five columns, whatever happened.
        result = recognizer.analyze_dataframe(df, text_column='不存在')
        assert list(result.columns) == COLUMNS
        assert result.empty

    def test_blank_and_missing_cells_produce_no_rows(self, recognizer):
        frame = pd.DataFrame({'正文': [None, '', '   ', '李女士位于上海市']})
        result = recognizer.analyze_dataframe(frame)
        assert set(result['row']) == {3}


class TestOffsets:
    @pytest.mark.parametrize('text, label, entity', CASES)
    def test_each_label_is_found(self, recognizer, text, label, entity):
        result = recognizer.analyze_dataframe(pd.DataFrame({'正文': [text]}))
        hits = result[(result['label'] == label) & (result['text'] == entity)]
        assert len(hits) == 1

    @pytest.mark.parametrize('text, label, entity', CASES)
    def test_offsets_point_back_into_the_source_text(self, recognizer, text, label, entity):
        result = recognizer.analyze_dataframe(pd.DataFrame({'正文': [text]}))
        row = result[(result['label'] == label) & (result['text'] == entity)].iloc[0]
        assert text[row['start'] : row['end']] == row['text']

    def test_the_row_column_addresses_the_source_frame(self, recognizer, df):
        result = recognizer.analyze_dataframe(df)
        assert set(result['row']) <= set(df.index)
        for _, hit in result.iterrows():
            assert isinstance(hit['row'], int) or hit['row'] in df.index

    def test_a_text_with_two_dates_yields_two_hits(self, recognizer):
        frame = pd.DataFrame({'正文': ['会议于2024年5月举行，3月12日结束']})
        result = recognizer.analyze_dataframe(frame)
        assert result['label'].tolist() == ['DATE', 'DATE']
        assert result['text'].tolist() == ['2024年5月', '3月12日']
        assert result['start'].tolist() == [3, 13]

    def test_labels_come_from_the_documented_set(self, recognizer):
        frame = pd.DataFrame({'正文': [text for text, _, _ in CASES] + ['无关文本', None]})
        result = recognizer.analyze_dataframe(frame)
        assert set(result['label']) <= {'PERSON', 'ORG', 'LOC', 'DATE'}

    def test_a_single_surname_honorific_is_recognised_as_a_person(self, recognizer):
        result = recognizer.analyze_dataframe(pd.DataFrame({'正文': ['张先生在北京大学毕业']}))
        assert 'PERSON' in result['label'].tolist()
        person = result[result['label'] == 'PERSON'].iloc[0]
        assert person['text'] == '张先生'

    def test_hits_are_ordered_by_pattern_family_not_by_position(self, recognizer):
        # PERSON runs before ORG in the source, so a mixed text documents the
        # grouping downstream consumers see (start offsets are still exact).
        result = recognizer.analyze_dataframe(pd.DataFrame({'正文': ['。王小明先生在北京大学演讲']}))
        assert result['label'].tolist() == ['PERSON', 'ORG']


class TestEntityTypeFilter:
    """The panel's 实体类型 field, applied to the rules."""

    @pytest.fixture
    def frame(self):
        return pd.DataFrame({'正文': ['张先生在北京大学毕业', '李女士位于上海市', '2024年1月1日开会']})

    def test_only_the_requested_labels_come_back(self, recognizer, frame):
        result = recognizer.analyze_dataframe(frame, entity_types='person')
        assert set(result['label']) == {'PERSON'}
        assert result['text'].tolist() == ['张先生', '李女士']

    def test_the_other_patterns_are_not_even_run(self, recognizer, frame):
        # A date-only filter must not leak an ORG hit from the same text, which
        # is what a post-hoc row filter would have done instead.
        result = recognizer.analyze_dataframe(frame, entity_types='DATE')
        assert result['label'].tolist() == ['DATE']
        assert result['text'].tolist() == ['2024年1月1日']

    def test_the_filter_accepts_a_list_as_well_as_a_string(self, recognizer, frame):
        by_list = recognizer.analyze_dataframe(frame, entity_types=['person', 'loc'])
        by_string = recognizer.analyze_dataframe(frame, entity_types='person,loc')
        assert by_list.equals(by_string)

    def test_spaces_and_a_chinese_comma_do_not_change_the_answer(self, recognizer, frame):
        tidy = recognizer.analyze_dataframe(frame, entity_types='PERSON,DATE')
        messy = recognizer.analyze_dataframe(frame, entity_types=' person ， date ')
        assert tidy.equals(messy)

    def test_a_typo_asks_for_everything_rather_than_failing_the_run(self, recognizer, frame):
        # Thousands of rows may already have been crawled; a mistyped category
        # in an optional field is not a reason to throw them away.
        result = recognizer.analyze_dataframe(frame, entity_types='peaple')
        assert set(result['label']) == {'PERSON', 'ORG', 'LOC', 'DATE'}

    def test_an_empty_field_means_no_filter(self, recognizer, frame):
        for blank in (None, '', '   ', [], {}):
            assert set(recognizer.analyze_dataframe(frame, entity_types=blank)['label']) == {
                'PERSON',
                'ORG',
                'LOC',
                'DATE',
            }

    def test_wanted_types_is_the_single_reader_of_the_field(self):
        assert wanted_types('org') == {'ORG'}
        assert wanted_types('ORG,NOPE') == {'ORG'}
        assert wanted_types(42) == {'PERSON', 'ORG', 'LOC', 'DATE'}


class ScriptedClient(LLMClient):
    """A real client (so truncation and host semantics stay production ones) whose
    transport is a script: replies are chosen by which text the prompt carries."""

    def __init__(self, reply='NONE', replies=None, exc=None):
        super().__init__(provider='ollama', model='scripted', host='')
        self.reply = reply
        self.replies = dict(replies or {})
        self.exc = exc
        self.prompts = []

    def chat(self, prompt, max_retries=2):
        self.prompts.append(prompt)
        if self.exc is not None:
            raise self.exc
        for needle, answer in self.replies.items():
            if needle in prompt:
                return answer
        return self.reply


def llm_ctx(client, publish=None):
    """The minimum context app.py's ``_llm_run_ctx`` produces, without a store:
    no checkpoint directory means nothing is persisted, so tests stay isolated."""
    return {
        'client': client,
        'node_id': 'n1',
        'batch_size': 10,
        'workers': 1,
        'publish': publish or (lambda frame: None),
        'cancel_event': None,
        'checkpoint_dir': '',
    }


class TestLlmMode:
    """Mode ``llm``: the model replaces the regexes, the output does not change."""

    def test_a_text_the_rules_cannot_read_still_yields_entities(self):
        # No honorific after 张伟, no 在/到/位于 before 上海 — the rules find
        # nothing here, which is exactly the gap the model is for.
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        client = ScriptedClient(reply='张伟|PERSON\n上海|LOC')
        result = NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, ctx=llm_ctx(client))
        assert list(result.columns) == COLUMNS
        assert result[['text', 'label']].values.tolist() == [['张伟', 'PERSON'], ['上海', 'LOC']]

    def test_the_model_offsets_still_point_back_into_the_source(self):
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        result = NamedEntityRecognizer(mode='llm').analyze_dataframe(
            frame, ctx=llm_ctx(ScriptedClient(reply='张伟|PERSON\n上海|LOC'))
        )
        text = frame['正文'].iloc[0]
        for _, hit in result.iterrows():
            assert text[int(hit['start']) : int(hit['end'])] == hit['text']
        assert result['row'].tolist() == [0, 0]

    def test_an_entity_the_text_does_not_contain_is_dropped(self):
        # The plausible-data defence: a model that answers 李四 for a text about
        # 张伟 must not put 李四 in the table.
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        result = NamedEntityRecognizer(mode='llm').analyze_dataframe(
            frame, ctx=llm_ctx(ScriptedClient(reply='李四|PERSON\n上海|LOC'))
        )
        assert result['text'].tolist() == ['上海']

    def test_a_spelling_wider_than_the_text_is_dropped(self):
        # The model writes 上海市 where the text says 上海. The entity table feeds
        # charts and exports, so it reports what the corpus says, not what the
        # model knows about it.
        frame = pd.DataFrame({'正文': ['张伟在上海开会']})
        result = NamedEntityRecognizer(mode='llm').analyze_dataframe(
            frame, ctx=llm_ctx(ScriptedClient(reply='上海市|LOC\n上海|LOC'))
        )
        assert result['text'].tolist() == ['上海']

    def test_an_unknown_category_is_dropped_rather_than_guessed(self):
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        result = NamedEntityRecognizer(mode='llm').analyze_dataframe(
            frame, ctx=llm_ctx(ScriptedClient(reply='张伟|WEBSITE\n峰会|EVENT\n上海|LOC'))
        )
        assert result[['text', 'label']].values.tolist() == [['上海', 'LOC']]

    def test_none_is_an_answer_and_not_a_failure(self):
        frame = pd.DataFrame({'正文': ['今天天气不错']})
        result = NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, ctx=llm_ctx(ScriptedClient(reply='NONE')))
        assert list(result.columns) == COLUMNS
        assert result.empty

    def test_a_repeated_line_lands_once(self):
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        client = ScriptedClient(reply='上海|LOC\n上海|LOC\n上海|LOC')
        result = NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, ctx=llm_ctx(client))
        assert len(result) == 1

    def test_the_prompt_offers_only_the_requested_categories(self):
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        client = ScriptedClient(reply='张伟|PERSON')
        NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, entity_types='person', ctx=llm_ctx(client))
        prompt = client.prompts[0]
        assert 'only: PERSON.' in prompt
        assert 'ORG:' not in prompt
        assert 'LOC:' not in prompt

    def test_the_category_filter_is_part_of_the_answer_cache_scope(self, monkeypatch):
        # A cached PERSON-only answer must never be replayed for a run that
        # asked for every type, and the prompt digest cannot see the filter.
        import analyzers.ner as ner_module

        seen = []

        def spy(df, text_column, **kwargs):
            seen.append(kwargs['extra_key'])
            return df

        monkeypatch.setattr(ner_module, 'run_llm_dataframe', spy)
        recognizer = NamedEntityRecognizer(mode='llm')
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        recognizer.analyze_dataframe(frame, entity_types='person,date', ctx=llm_ctx(ScriptedClient()))
        recognizer.analyze_dataframe(frame, ctx=llm_ctx(ScriptedClient()))
        assert seen[0] == 'PERSON,DATE'
        assert seen[1] == 'PERSON,ORG,LOC,DATE'
        assert seen[0] != seen[1]

    def test_a_row_published_mid_run_is_already_an_entity_table(self):
        published = []
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        ctx = llm_ctx(ScriptedClient(reply='上海|LOC'), publish=published.append)
        NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, ctx=ctx)
        assert published, 'the runner never published'
        for table in published:
            assert list(table.columns) == COLUMNS

    def test_a_dead_transport_stops_the_node_rather_than_passing_a_blank_table(self):
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        client = ScriptedClient(exc=LLMError('daemon down', 'network'))
        with pytest.raises(LLMError):
            NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, ctx=llm_ctx(client))

    def test_a_missing_text_column_raises_in_llm_mode(self):
        # The rule path answers with an empty table; the model path shares the
        # loss-containment rules of every other LLM analyzer, which fail loudly
        # so a misconfigured node cannot report a successful empty run.
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        with pytest.raises(LLMError):
            NamedEntityRecognizer(mode='llm').analyze_dataframe(
                frame, text_column='不存在', ctx=llm_ctx(ScriptedClient())
            )

    def test_the_rules_are_the_default_and_never_ask_a_model(self):
        client = ScriptedClient(exc=AssertionError('the model was called'))
        frame = pd.DataFrame({'正文': ['张先生在北京大学毕业']})
        result = NamedEntityRecognizer().analyze_dataframe(frame, ctx=llm_ctx(client))
        assert 'ORG' in result['label'].tolist()
        assert client.prompts == []

    @pytest.mark.parametrize('mode', ['regex', 'llm'])
    def test_both_modes_answer_in_the_same_five_columns(self, mode):
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会']})
        result = NamedEntityRecognizer(mode=mode).analyze_dataframe(
            frame, ctx=llm_ctx(ScriptedClient(reply='上海|LOC'))
        )
        assert list(result.columns) == COLUMNS

    def test_a_mode_the_panel_could_not_have_sent_stays_on_the_rules(self):
        for blank in (None, '', 'ML', 'sklearn'):
            assert NamedEntityRecognizer(mode=blank).mode == 'regex'
        for asked in ('llm', 'LLM', ' Llm '):
            assert NamedEntityRecognizer(mode=asked).mode == 'llm'


class TestAnswerLineParsing:
    """The shapes a model actually produces, before the source-text check."""

    @pytest.mark.parametrize(
        'line, expected',
        [
            ('张伟|PERSON', ('张伟', 'PERSON')),
            ('- 上海 | LOC', ('上海', 'LOC')),
            ('* 北京大学|ORG', ('北京大学', 'ORG')),
            ('1. 2024年5月|DATE', ('2024年5月', 'DATE')),
            ('张伟（人名）', ('张伟', 'PERSON')),
            ('新华社: ORG', ('新华社', 'ORG')),
            ('李女士→PERSON', ('李女士', 'PERSON')),
            ('`张伟`|`PERSON`', ('张伟', 'PERSON')),
            ('location|LOC', ('location', 'LOC')),
        ],
    )
    def test_an_answer_line_becomes_a_pair(self, line, expected):
        assert answer_pair(line) == expected

    @pytest.mark.parametrize('line', ['', 'NONE', '无', '没有实体。', '张伟前往上海参加峰会', '张伟'])
    def test_a_line_that_is_not_an_entity_is_not_one(self, line):
        assert answer_pair(line) is None

    @pytest.mark.parametrize(
        'line, entity',
        [('张伟|个人', '张伟'), ('张伟|WEBSITE', '张伟'), ('峰会|EVENT', '峰会'), ('上海|地点啊', '上海')],
    )
    def test_a_category_outside_the_vocabulary_is_left_blank_for_the_table_to_drop(self, line, entity):
        # Guessing which of the four this was meant to be is how false data is
        # born, so the parse reports "no category" and no row lands.
        assert answer_pair(line) == (entity, '')


class TestExplodeCounting:
    """A row the run never reached must not be reported as a wrong answer."""

    def test_the_abort_marker_is_skipped_and_not_counted(self):
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会'], 'entities': [ABORT_MARK]})
        table, rejected = _explode(frame, '正文', {'PERSON', 'ORG', 'LOC', 'DATE'})
        assert table.empty
        assert rejected == 0

    def test_an_answer_without_the_source_text_counts_as_rejected(self):
        cell = _PAIR_SEP.join([f'李四{_LABEL_SEP}PERSON', f'上海{_LABEL_SEP}LOC'])
        frame = pd.DataFrame({'正文': ['张伟前往上海参加峰会'], 'entities': [cell]})
        table, rejected = _explode(frame, '正文', {'PERSON', 'ORG', 'LOC', 'DATE'})
        assert table['text'].tolist() == ['上海']
        assert rejected == 1
