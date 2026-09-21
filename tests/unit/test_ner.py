"""Tests for analyzers/ner.py — the rule-based Chinese entity extractor.

There is no model here, only four regexes, so the value of these tests is in
the *output contract* the visualize/download nodes assume: always the same five
columns (even when nothing was found), one row per hit, and offsets that point
back into the source text exactly. The offset invariant catches a whole class
of group-index mistakes in the regexes.
"""
import pandas as pd
import pytest

from analyzers.ner import NamedEntityRecognizer

pytestmark = pytest.mark.unit

COLUMNS = ['row', 'text', 'label', 'start', 'end']

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

    def test_a_missing_text_column_returns_the_frame(self, recognizer, df):
        assert recognizer.analyze_dataframe(df, text_column='不存在') is df

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
