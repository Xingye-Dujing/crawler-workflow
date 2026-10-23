"""Bibliographic import: Chinese exports and the international format registry."""

import json
from pathlib import Path

import pandas as pd
import pytest

from services.biblio_import import CNKI, CSSCI, detect_format, parse_bytes, parse_frame, parse_text

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


class TestInternationalFormats:
    @pytest.mark.parametrize(
        ('name', 'fmt', 'rows'),
        [
            ('biblio_wos_demo.txt', 'WoS', 3),
            ('biblio_scopus_demo.csv', 'Scopus', 3),
            ('biblio_dimensions_demo.csv', 'Dimensions', 2),
            ('biblio_lens_demo.csv', 'Lens', 2),
            ('biblio_pubmed_demo.xml', 'PubMed', 2),
            ('biblio_ris_demo.ris', 'RIS', 2),
            ('biblio_bibtex_demo.bib', 'BibTeX', 2),
            ('biblio_endnote_demo.enw', 'EndNote', 2),
        ],
    )
    def test_every_registered_format_normalizes_to_the_same_columns(self, name, fmt, rows):
        parsed = parse_bytes(_sample(name), name)
        assert parsed['format'] == fmt
        assert len(parsed['rows']) == rows
        assert parsed['columns'][:3] == ['记录ID', '题名', '作者']
        first = parsed['rows'][0]
        assert 'Digital governance' in first['题名']
        assert first['年份'] == 2021
        assert first['格式'] == fmt
        assert first['作者']
        assert first['引文']
        assert json.loads(first['引文'])[0]['title']

    def test_wos_keeps_author_commas_and_each_cited_reference_separate(self):
        parsed = parse_bytes(_sample('biblio_wos_demo.txt'), 'wos.txt')
        first = parsed['rows'][0]
        assert first['作者'] == 'ZHANG, Y;LI, X'
        assert first['参考文献'].splitlines() == [
            'SMITH J, 2018, PUBLIC ADMIN REV, V78, P1',
            'DOE J, 2019, GOVERNANCE, V32, P2',
            'ROE P, 2020, POLICY STUD J, V48, P3',
        ]
        assert first['引用次数'] == 12
        assert first['使用次数'] == 30
        assert first['使用次数2013'] == 41
        assert "People's Republic of China" in first['国家']
        assert first['学科'] == 'Public Administration'
        assert first['文献类型'] == 'Article'

    def test_pubmed_xml_keeps_structured_references_and_affiliation_countries(self):
        parsed = parse_bytes(_sample('biblio_pubmed_demo.xml'), 'pubmed.xml')
        first = parsed['rows'][0]
        assert first['作者'] == 'Yan Zhang;Xin Li'
        assert first['DOI'] == '10.0000/demo.pubmed.2021.001'
        assert first['关键词'] == 'digital governance;public participation'
        assert 'China' in first['国家']
        assert 'National Natural Science Foundation' in first['基金']
        references = json.loads(first['引文'])
        assert references[0]['journal'] == 'Public Administration Review'
        assert references[0]['doi'] == '10.0000/demo.ref.2018.1'

    def test_scopus_csv_is_also_read_from_a_frame(self):
        frame = pd.read_csv(SAMPLES / 'biblio_scopus_demo.csv', dtype=str, keep_default_na=False)
        parsed = parse_frame(frame)
        assert parsed['format'] == 'Scopus'
        assert len(parsed['rows']) == 3
        assert parsed['rows'][0]['来源期刊'] == 'Public Management Review'
        assert parsed['rows'][0]['引用次数'] == 12

    def test_a_plain_csv_is_not_claimed_by_the_registry(self):
        assert detect_format('name,age\n张三,20\n') is None
        assert parse_text('name,age\n张三,20\n') is None

    def test_a_plain_sentence_with_at_signs_stays_text(self):
        assert detect_format('我的邮箱是 someone@example.com，不是一条 BibTeX 记录。') is None

    def test_pubmed_refuses_an_xml_entity_declaration(self):
        with pytest.raises(ValueError, match='ENTITY|实体'):
            parse_text(
                '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY y "z">]><PubmedArticleSet><x>&y;</x></PubmedArticleSet>',
                'PubMed',
            )

    def test_an_unknown_registered_extension_is_refused_not_stored_as_text(self):
        with pytest.raises(ValueError):
            # A .ris file that is not RIS must not quietly become one text row;
            # the upload route reports this refusal as a 400.
            parse_text('not a ris file at all', 'RIS')
