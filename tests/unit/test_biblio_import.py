"""CNKI RefWorks / CSSCI import: the two file shapes the Biblio node can read."""

from pathlib import Path

import pytest

from services.biblio_import import CNKI, CSSCI, detect_format, parse_bytes, parse_text

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).resolve().parents[2] / 'samples'


def _sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


class TestCnki:
    def test_a_refworks_export_becomes_one_normalized_record_row(self):
        parsed = parse_bytes(_sample('biblio_cnki_demo.txt'), 'cnki.txt')
        assert parsed['format'] == CNKI
        assert len(parsed['rows']) == 36
        assert parsed['columns'][:3] == ['记录ID', '题名', '作者']
        first = parsed['rows'][0]
        assert first['题名'] == '数字化转型背景下的公共治理创新研究'
        assert first['作者'] == '张明;李华'
        assert first['年份'] == 2018
        assert first['关键词'].startswith('数字化转型;公共治理')
        assert first['DOI'] == '10.0000/demo.2018.06.002'
        assert first['参考文献'] == ''
        assert first['格式'] == CNKI

    def test_a_continuation_line_stays_in_its_field(self):
        text = 'RT Journal Article\nT1 一篇题名\nAB 第一行摘要\n   第二行摘要\nYR 2020\nER\n'
        parsed = parse_text(text)
        assert parsed['rows'][0]['摘要'] == '第一行摘要 第二行摘要'

    def test_duplicate_records_are_merged_with_a_named_warning(self):
        block = _sample('biblio_cnki_demo.txt').decode('utf-8').split('\n\n')[0]
        parsed = parse_text(block + '\n\n' + block)
        assert len(parsed['rows']) == 1
        assert len(parsed['warnings']) == 1


class TestCssci:
    def test_bracket_records_keep_their_reference_list(self):
        parsed = parse_bytes(_sample('biblio_cssci_demo.txt'), 'cssci.txt')
        assert parsed['format'] == CSSCI
        assert len(parsed['rows']) == 16
        first = parsed['rows'][0]
        assert first['题名'] == '数字治理研究的议题演进与前沿展望'
        assert first['作者'] == '张明;周敏'
        assert first['来源期刊'] == '公共管理学报'
        assert first['年份'] == 2022
        assert first['参考文献'].count('\n') >= 5
        assert '[1]' in first['参考文献']

    def test_a_record_without_a_title_is_skipped(self):
        text = (
            '【作者】张三\n【年份】2020\n\n'
            '【来源篇名】题名一\n【作者】李四\n【年份】2021\n\n'
            '【来源篇名】题名二\n【作者】王五\n【年份】2022\n'
        )
        parsed = parse_text(text)
        assert [row['题名'] for row in parsed['rows']] == ['题名一', '题名二']
        assert len(parsed['warnings']) == 1  # the untitled record is accounted for


class TestDetection:
    def test_plain_text_stays_plain_text(self):
        assert detect_format('三亚的海非常蓝。\n第二行正文\n') is None

    def test_gb18030_is_tried_after_utf8(self):
        record = 'RT Journal Article\nT1 中文题名\nYR 2020\nER\n'
        parsed = parse_bytes(record.encode('gb18030'), 'gb.txt')
        assert parsed['format'] == CNKI
        assert parsed['rows'][0]['题名'] == '中文题名'

    def test_an_empty_export_is_refused_not_treated_as_plain_text(self):
        with pytest.raises(ValueError):
            parse_text('RT Journal Article\nER\n')

    def test_a_bibliographic_looking_text_is_not_parsed_as_a_plain_row(self):
        # The upload route uses None for "ordinary text"; a marker that matches
        # the tag grammar must go through the parser instead.
        parsed = parse_text('RT Journal Article\nT1 题名\nYR 2020\nER\n')
        assert parsed is not None
        assert parsed['rows'][0]['年份'] == 2020
