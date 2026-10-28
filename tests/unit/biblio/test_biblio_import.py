"""Bibliographic import: Chinese exports and the international format registry."""

import json
from pathlib import Path

import pandas as pd
import pytest

from services.biblio.formats import FORMAT_SPECS
from services.biblio.importer import CNKI, CSSCI, detect_format, parse_bytes, parse_frame, parse_text

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).resolve().parents[3] / 'samples' / 'biblio'

#: One entry per fixture: (file, format id, record count, carries a reference list).
#: The counts and dialects come from the real exports in ``samples/`` (see
#: ``docs/analysis.md``); several formats genuinely have no reference list — CNKI, Dimensions,
#: EndNote-as-CNKI-exports, PubMed and Lens among them (Lens writes Lens record ids there, not
#: citation text) — so `has_refs` is asserted per case instead of being demanded of every one,
#: which would push a fixture to invent a field its vendor omits.
FORMAT_CASES = [
    ('biblio_wos_demo.txt', 'WoS', 3, True),
    ('biblio_wos_table_demo.csv', 'WoS', 3, True),
    ('biblio_scopus_demo.csv', 'Scopus', 3, True),
    ('biblio_dimensions_demo.csv', 'Dimensions', 2, False),
    ('biblio_pubmed_demo.txt', 'PubMed', 2, False),
    ('biblio_pubmed_csv_demo.csv', 'PubMed', 3, False),
    ('biblio_ris_demo.ris', 'RIS', 2, True),
    ('biblio_bibtex_demo.bib', 'BibTeX', 2, True),
    ('biblio_endnote_demo.enw', 'EndNote', 2, False),
    ('biblio_noteexpress_demo.net', 'NoteExpress', 2, False),
    ('biblio_lens_demo.csv', 'Lens', 4, False),
]


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
        # CSSCI numbers its reference list ``1.`` — not ``[1]`` — and the exporter writes the
        # whole list into 【参考文献】 with each work on its own line.
        assert first['参考文献'].startswith('1.')

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
    @pytest.mark.parametrize(('name', 'fmt', 'rows', 'has_refs'), FORMAT_CASES)
    def test_every_registered_format_normalizes_to_the_same_columns(self, name, fmt, rows, has_refs):
        parsed = parse_bytes(_sample(name), name)
        assert parsed['format'] == fmt
        assert len(parsed['rows']) == rows
        assert parsed['columns'][:3] == ['记录ID', '题名', '作者']
        first = parsed['rows'][0]
        assert first['题名'].strip()
        assert isinstance(first['年份'], int) and first['年份'] >= 2015
        assert first['格式'] == fmt
        assert first['作者']
        assert bool(str(first['参考文献']).strip()) is has_refs
        if has_refs:
            assert json.loads(first['引文'])[0]['title']

    def test_the_case_list_and_the_registry_name_the_same_formats(self):
        """A format registered without a sample parses nowhere and is tested nowhere — and a
        fixture nobody claims is a dialect the code does not actually read."""
        registered = {spec.id for spec in FORMAT_SPECS}
        assert {fmt for _name, fmt, _rows, _refs in FORMAT_CASES} == registered
        for name, _fmt, _rows, _refs in FORMAT_CASES:
            assert (SAMPLES / name).is_file(), f'{name} is missing'
        claimed = {name for name, _fmt, _rows, _refs in FORMAT_CASES}
        for path in sorted(SAMPLES.glob('biblio_*_demo.*')):
            # CNKI and CSSCI are read by services.biblio.importer, not by the registry, so their
            # fixtures are exempt from the registry side but not from being claimed below.
            if path.name in claimed or path.name in ('biblio_cnki_demo.txt', 'biblio_cssci_demo.txt'):
                continue
            # The dual-map basemap is not an export at all: it is a two-column table the user
            # supplies themselves, and tests/api/test_biblio_api.py reads it under that name.
            if path.name == 'biblio_basemap_demo.csv':
                continue
            # The Lens patent file has no reader on purpose — its fixture exists to be refused.
            if path.name == 'biblio_lens_patent_demo.csv':
                continue
            raise AssertionError(f'{path.name} is a fixture no reader owns')

    def test_a_lens_patent_export_is_refused_by_name(self):
        """The real file we were given is the patent collection; drawing it as authors is worse."""
        with pytest.raises(ValueError) as exc:
            parse_bytes(_sample('biblio_lens_patent_demo.csv'), 'lens-export.csv')
        message = str(exc.value)
        assert '专利' in message or 'PATENT' in message.upper(), message
        assert 'Jurisdiction' in message, f'the refusal must name the evidence: {message}'

    def test_a_lens_export_lands_what_its_own_columns_carry_and_nothing_more(self):
        """The scholarly Lens download is read for its fields, and its two absences are the point."""
        first = parse_bytes(_sample('biblio_lens_demo.csv'), 'lens-export.csv')['rows'][0]
        assert first['题名'].startswith('Digital governance')
        assert first['作者'] == 'Zhang, Yan;Li, Xin'
        assert first['来源期刊'] == 'Government Information Quarterly'
        assert first['年份'] == 2021
        assert first['卷'] == '38' and first['期'] == '3'
        assert first['页码'] == '101-119'
        assert '数字' not in first['关键词']
        assert first['关键词'].startswith('digital governance;city service portals')
        assert 'Government Information Systems' in first['关键词']
        assert first['引用次数'] == 17
        assert 'National Science Foundation' in first['基金']
        assert first['学科'].startswith('Public administration')
        assert first['文献类型'] == 'journal article'
        # References are Lens ids, and Source Country is the journal's, not the authors':
        # both columns are absent rather than filled with something that means otherwise.
        assert first['参考文献'] == ''
        assert '国家' not in first

    def test_scopus_column_names_move_between_versions_and_all_are_read(self):
        """Measured: the same download has shipped as Citation count/Cited by and Article
        number/Art. No. — a reader that remembered only one spelling loses the count."""
        rows = parse_bytes(_sample('biblio_scopus_demo.csv'), 'scopus.csv')['rows']
        assert [row['引用次数'] for row in rows] == [12, 7, 21]
        assert rows[0]['页码'] == '100-120'
        # An article-number row has no page range: the number is its 页码.
        assert rows[1]['页码'] == '101500'
        assert 'European Research Council' in rows[1]['基金']
        assert 'Tsinghua University' in rows[0]['作者单位']
        assert 'China' in rows[0]['国家']

    def test_a_wos_excel_shape_without_cited_references_still_imports(self):
        """Measured on the re-exported Excel: keywords/categories/funding/usage are filled, but
        ``Cited References`` stays empty and only ``Cited Reference Count`` (a number) is written.

        Detection must not depend on CR being present — refusing the file would throw away the
        four networks it *can* answer — and the capability map has to say ``refs: false`` so the
        biblio node refuses citation analyses by name instead of drawing an empty graph.
        """
        text = (
            'Article Title,Source Title,Publication Year,Author Keywords,WoS Categories,'
            'Cited References,Cited Reference Count,UT (Unique WOS ID)\n'
            'A synthetic title,Journal A,2021,kw one; kw two,Public Administration,,"7",WOS:1\n'
        )
        parsed = parse_text(text)
        assert parsed['format'] == 'WoS'
        assert parsed['rows'][0]['关键词'] == 'kw one;kw two'
        assert parsed['rows'][0]['学科'] == 'Public Administration'
        assert parsed['rows'][0]['参考文献'] == ''
        assert parsed['capabilities']['keywords'] is True
        assert parsed['capabilities']['refs'] is False

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

    def test_medline_text_keeps_wrapped_abstracts_and_affiliation_countries(self):
        parsed = parse_bytes(_sample('biblio_pubmed_demo.txt'), 'pubmed.txt')
        first = parsed['rows'][0]
        assert parsed['format'] == 'PubMed'
        assert first['作者'] == 'Zhang, Ming;Zhou, Min'
        assert first['DOI'] == '10.5555/demo.1'
        assert 'digital governance' in first['关键词'].lower()
        assert 'China' in first['国家']
        # The abstract wraps without a tag on the second line; joining is the whole point.
        assert 'the tag column is four characters wide' in first['摘要']
        assert not any(row['参考文献'].strip() for row in parsed['rows']), 'this export carries no list'

    def test_pubmed_csv_summary_reads_volume_and_pages_out_of_the_citation(self):
        parsed = parse_bytes(_sample('biblio_pubmed_csv_demo.csv'), 'pubmed.csv')
        first = parsed['rows'][0]
        assert parsed['format'] == 'PubMed'
        assert first['来源期刊'] == 'Public Administration Review'
        assert (first['卷'], first['期']) == ('20', '1'), 'only the free citation string carries them'
        assert first['页码'] == '100-112'
        assert first['作者'] == 'Zhang M;Zhou L;Chen H'

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

    def test_an_unknown_registered_extension_is_refused_not_stored_as_text(self):
        with pytest.raises(ValueError):
            # A .ris file that is not RIS must not quietly become one text row;
            # the upload route reports this refusal as a 400.
            parse_text('not a ris file at all', 'RIS')
