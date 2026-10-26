"""The cross-source fusion node: fold tables, keep provenance, refuse what cannot be folded.

The node exists because the engine's fan-in merge is not enough: it concatenates rows and keeps
each table's own column names, so a paper's ``关键词`` and a post's ``话题`` never become one
vocabulary, and no row still knows where it came from. Every case below is one half of that
promise — the fold, the naming, or the refusal.
"""

import pytest

from services import biblio_fuse

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
    return biblio_fuse.fuse(upstream, params, 'fuse')


class TestFolding:
    def test_two_sources_with_different_columns_become_one_record_table(self):
        result = _fuse([('node-1', LITERATURE), ('node-2', POSTS)])
        assert result['columns'] == list(biblio_fuse.OUTPUT_COLUMNS)
        assert [row['关键词'] for row in result['rows'][:2]] == ['数字治理;算法问责', '数字治理;数据要素']
        # The post table's 话题 lands in 关键词, so a downstream biblio node needs no remapping.
        assert result['rows'][2]['关键词'] == '数字治理;算法问责'

    def test_every_row_knows_its_own_source(self):
        result = _fuse([('node-1', LITERATURE), ('node-2', POSTS)], source_labels='node-1=文献')
        assert [row['来源'] for row in result['rows']] == ['文献', '文献', '微博', '知乎']

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
        """Guessing 「文献」 for an unlabelled table would put a claim about provenance in the
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
        errors = biblio_fuse.collect_errors({'entity_columns': '  '}, 'fuse')
        assert errors and 'fuse' in errors[0]


class TestContract:
    def test_the_output_columns_are_a_fixed_contract(self):
        """A fusion node's output is canonical by design: whatever the sources called their
        columns, the downstream node reads 题名/关键词/年份/来源 with its default mapping."""
        result = _fuse([('node-2', POSTS)])
        assert set(result['columns']) >= {'题名', '作者', '年份', '关键词', '来源'}
        assert all(set(row) == set(result['columns']) for row in result['rows'])

    def test_the_role_parameters_are_the_ones_the_panel_edits(self):
        """``nodes/schema.py`` reports a fusion node's column dependencies from this list, so a
        parameter renamed on one side is a stale diagnostic on the other."""
        assert biblio_fuse.ROLE_PARAMS == (
            'entity_columns',
            'year_columns',
            'title_columns',
            'author_columns',
            'affiliation_columns',
            'text_columns',
            'reference_columns',
            'source_columns',
        )
