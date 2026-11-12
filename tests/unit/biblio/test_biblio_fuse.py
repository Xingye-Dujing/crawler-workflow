"""The cross-source fusion node: fold tables, keep provenance, refuse what cannot be folded.

The node exists because the engine's fan-in merge is not enough: it concatenates rows and keeps
each table's own column names, so a paper's ``关键词`` and a post's ``话题`` never become one
vocabulary, and no row still knows where it came from. Every case below is one half of that
promise — the fold, the naming, or the refusal.
"""

from pathlib import Path

import pytest

from services.biblio import fuse

pytestmark = pytest.mark.unit

LITERATURE = [
    {'题名': '文1', '年份': 2021, '关键词': '数字治理;算法问责', '作者': '张明', '作者单位': '清华大学'},
    {'题名': '文2', '年份': 2022, '关键词': '数字治理;数据要素', '作者': '周敏', '作者单位': '复旦大学'},
]
POSTS = [
    {
        '用户名': '甲',
        '发布时间': '2022-03-04 11:02',
        '平台': '微博',
        '话题': '数字治理,算法问责',
        '正文': '谈数字治理。',
    },
    {'用户名': '乙', '发布时间': '2023-01-05', '平台': '知乎', '话题': '数据治理', '正文': '谈数据治理。'},
]


def _fuse(upstream, **params):
    return fuse.fuse(upstream, params, 'fuse')


class TestFolding:
    def test_two_sources_with_different_columns_become_one_record_table(self):
        result = _fuse([('node-1', LITERATURE), ('node-2', POSTS)])
        assert result['columns'] == list(fuse.OUTPUT_COLUMNS)
        assert [row['关键词'] for row in result['rows'][:2]] == ['数字治理;算法问责', '数字治理;数据要素']
        # The post table's 话题 lands in 关键词, so a downstream biblio node needs no remapping.
        assert result['rows'][2]['关键词'] == '数字治理;算法问责'

    def test_every_row_knows_its_own_source(self):
        result = _fuse([('node-1', LITERATURE), ('node-2', POSTS)], source_labels='node-1=文献')
        assert [row['来源'] for row in result['rows']] == ['文献', '文献', '微博', '知乎']

    def test_a_role_column_only_later_rows_carry_is_still_found(self):
        """A sharded/merged parent can name 年份 on row 2 and not row 1. Reading only the first
        row's keys dropped the whole column, so every year came back blank."""
        rows = [{'关键词': '数字治理'}, {'关键词': '算法问责', '年份': '2021'}]
        result = _fuse([('node-2', rows)])
        assert [row['年份'] for row in result['rows']] == ['', '2021']

    def test_a_year_is_read_out_of_a_timestamp(self):
        """Social tables stamp 发布时间 as a datetime; the slicing downstream needs a year or
        nothing, never a half-parsed timestamp string."""
        result = _fuse([('node-1', LITERATURE), ('node-2', POSTS)])
        assert [row['年份'] for row in result['rows']] == ['2021', '2022', '2022', '2023']

    def test_undated_rows_can_be_dropped_instead_of_silently_kept(self):
        rows = [{'话题': '数字治理', '发布时间': ''}, {'话题': '数字治理', '发布时间': '2023-05-06'}]
        kept = _fuse([('node-2', rows)])
        assert len(kept['rows']) == 2
        pruned = _fuse([('node-2', rows)], keep_undated=False)
        assert [row['年份'] for row in pruned['rows']] == ['2023']

    def test_a_missing_optional_column_yields_an_empty_cell_not_a_guess(self):
        result = _fuse([('node-2', POSTS)])
        assert result['rows'][0]['作者'] == '甲'
        assert result['rows'][0]['参考文献'] == ''

    def test_the_summary_lists_the_sources_it_found(self):
        result = _fuse([('node-1', LITERATURE), ('node-2', POSTS)], source_labels='node-1=文献')
        assert result['summary']['sources'] == ['微博', '文献', '知乎']
        assert result['summary']['parents'] == 2


class TestNaming:
    def test_a_table_naming_its_platform_per_row_is_not_flattened_to_one_label(self):
        """One parent, several platforms: the node has no single name, so each row keeps its own
        and the parent is filed under its id rather than a label invented for it."""
        result = _fuse([('node-2', POSTS)])
        assert [row['来源'] for row in result['rows']] == ['微博', '知乎']
        assert result['sources'][0]['source'] == 'node-2'

    def test_a_single_platform_table_is_named_by_its_own_column(self):
        weibo = [row for row in POSTS if row['平台'] == '微博']
        result = _fuse([('node-2', weibo)])
        assert result['sources'][0]['source'] == '微博'

    def test_a_parent_that_says_nothing_is_filed_under_its_id_never_as_literature(self):
        """Guessing “文献” for an unlabelled table would put a claim about provenance in the
        graph that nobody made."""
        rows = [{'话题': '数字治理;基层治理', '年份': 2022}, {'话题': '基层治理;风险沟通', '年份': 2023}]
        result = _fuse([('node-7', rows)])
        assert {row['来源'] for row in result['rows']} == {'node-7'}


class TestRefusals:
    def test_no_input_is_refused(self):
        with pytest.raises(ValueError, match='fuse'):
            _fuse([])

    def test_an_empty_parent_is_refused_by_id(self):
        with pytest.raises(ValueError, match='node-3'):
            _fuse([('node-1', LITERATURE), ('node-3', [])])

    def test_a_parent_without_an_entity_column_names_the_candidates_tried(self):
        with pytest.raises(ValueError, match='关键词'):
            _fuse([('node-9', [{'题名': '只有题名', '年份': 2020}])])

    def test_a_parent_whose_entity_column_holds_nothing_is_refused(self):
        with pytest.raises(ValueError, match='node-9'):
            _fuse([('node-9', [{'话题': '  '}])])

    def test_an_entity_role_with_no_candidates_is_refused_before_running(self):
        errors = fuse.collect_errors({'entity_columns': '  '}, 'fuse')
        assert errors and 'fuse' in errors[0]


class TestContract:
    def test_a_row_keeps_its_identity_when_the_parents_are_reordered(self):
        """``记录ID`` is a CONTENT identity here, like every other record table in this project.

        It used to be ``{origin}#{parent index}-{row index}``: inserting or removing a parent shifted
        every id, so the same paper was drawn under a different name in the next run's figure —
        ``metrics.records`` falls back to ``记录ID`` as a document NAME when a record has no title,
        and disambiguates two same-titled works with ``[:6]``.
        """
        first = _fuse([('node-1', LITERATURE), ('node-2', POSTS)])
        second = _fuse([('node-2', POSTS), ('node-1', LITERATURE)])

        def by_title(result):
            return {row['题名']: row['记录ID'] for row in result['rows']}

        assert by_title(first) == by_title(second), 'reordering the parents renumbered the records'

    def test_two_same_titled_records_get_different_ids(self):
        """A hash over title alone would collide; the source and the year are part of the identity."""
        result = _fuse([('node-1', LITERATURE), ('node-2', POSTS)])
        ids = [row['记录ID'] for row in result['rows']]
        assert len(set(ids)) == len(ids), ids

    def test_repeated_identical_rows_in_one_source_stay_distinct_records(self):
        """The fusion keeps every row a parent produced; two identical rows are still two records.

        A content hash over title|author|year|source alone collapsed them into one identity, so a
        downstream reader that names documents by ``记录ID`` could not tell them apart. The ordinal
        is per source and follows row order, so reordering PARENTS does not change it.
        """
        row = {'题名': '同一篇', '年份': 2021, '关键词': '数字治理', '作者': '张明'}
        result = _fuse([('node-1', [dict(row), dict(row)])])
        ids = [entry['记录ID'] for entry in result['rows']]
        assert len(set(ids)) == 2, ids

    def test_the_output_columns_are_a_fixed_contract(self):
        """A fusion node's output is canonical by design: whatever the sources called their
        columns, the downstream node reads 题名/关键词/年份/来源 with its default mapping."""
        result = _fuse([('node-2', POSTS)])
        assert set(result['columns']) >= {'题名', '作者', '年份', '关键词', '来源'}
        assert all(set(row) == set(result['columns']) for row in result['rows'])

    def test_an_exported_title_cannot_start_a_spreadsheet_formula(self, tmp_path):
        """The fused CSV is handed to colleagues and opened in Excel. A record whose title
        begins with ``=`` is DATA; it must not execute when the file opens."""
        rows = [{'记录ID': '1', '题名': '=HYPERLINK("http://example.invalid")', '作者': '@SUM(1)'}]
        path = Path(fuse.export_records(rows, str(tmp_path), 'fuse'))
        text = path.read_text(encoding='utf-8-sig')
        assert "'=HYPERLINK" in text
        assert "'@SUM" in text

    def test_the_role_parameters_are_the_ones_the_panel_edits(self):
        """``nodes/schema.py`` reports a fusion node's column dependencies from this list, so a
        parameter renamed on one side is a stale diagnostic on the other."""
        assert fuse.ROLE_PARAMS == (
            'entity_columns',
            'year_columns',
            'title_columns',
            'author_columns',
            'affiliation_columns',
            'text_columns',
            'reference_columns',
            'source_columns',
        )
