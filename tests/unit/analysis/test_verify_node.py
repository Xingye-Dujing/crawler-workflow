"""采集校验 (``nodes/executors/verify.py``): the list's promise against the crawl's evidence.

Every case here is about a NUMBER the user will act on: a link reported as missing is a page
they will pay to re-crawl, and a link reported as complete is one they will not. So the tests
pin the coverage rule, the count rule (tolerance / per-item limit), the two "cannot be checked"
answers, and the report columns a downstream node or a re-crawl feed reads.
"""

import pytest
from nodes.executors import verify

pytestmark = pytest.mark.unit


def _node(**params):
    base = {
        'input_key_column': '链接',
        'result_key_column': '文章URL',
        'expected_count_column': '评论数',
        'match_mode': 'url',
        'tolerance': 0,
        'per_link_limit': '',
        'output_mode': 'gaps',
        'swap_tables': False,
        'ignore_case': False,
    }
    base.update(params)
    return {'id': 'v1', 'type': 'verify', 'title': '校验', 'params': base}


LIST = [
    {'标题': '甲', '链接': 'https://ex.com/p/1', '评论数': 3},
    {'标题': '乙', '链接': 'https://ex.com/p/2/', '评论数': 5},
    {'标题': '丙', '链接': 'https://ex.com/p/3', '评论数': 2},
]


def _comments(url, n):
    return [{'文章URL': url, '评论内容': f'c{i}', '评论ID': f'{url}-{i}'} for i in range(n)]


RESULT = _comments('https://ex.com/p/1', 3) + _comments('https://ex.com/p/2', 2)


def _run(node, upstream, monkeypatch):
    lines = []
    monkeypatch.setattr(verify, 'add_log', lambda msg, **kw: lines.append(msg))
    rows = verify.execute_verify_node(node, [], upstream=upstream, label_of={'p1': '清单 #p1', 'p2': '评论 #p2'})
    return rows, lines


def _by_title(rows):
    return {row['标题']: row for row in rows}


class TestCoverageAndCounts:
    def test_the_three_verdicts_and_the_report_they_produce(self, monkeypatch):
        rows, _lines = _run(_node(), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        # gaps mode: 甲 is complete, 乙 is short by 3, 丙 was never collected.
        assert [row['标题'] for row in rows] == ['乙', '丙']
        report = _by_title(rows)
        assert report['乙']['采集状态'] == verify.STATUS_SHORT
        assert report['乙']['缺失条数'] == 3
        assert report['乙']['实际条数'] == 2
        assert report['丙']['采集状态'] == verify.STATUS_MISSING
        assert report['丙']['缺失条数'] == 2
        # The list's own columns survive: that is what makes the 链接 column feedable.
        assert report['丙']['链接'] == 'https://ex.com/p/3'

    def test_all_mode_keeps_every_row_with_its_status(self, monkeypatch):
        rows, _lines = _run(_node(output_mode='all'), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        status = {row['标题']: row['采集状态'] for row in rows}
        assert status == {'甲': verify.STATUS_COMPLETE, '乙': verify.STATUS_SHORT, '丙': verify.STATUS_MISSING}
        assert rows[0]['完成度'] == '100.0%'

    def test_the_console_total_names_the_numbers_it_measured(self, monkeypatch):
        _rows, lines = _run(_node(output_mode='all'), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        done = [line for line in lines if '清单' in line and '覆盖' in line]
        assert done, lines
        assert '2/3' in done[0], 'two of the three links were collected'
        assert any('清单 #p1' in line and '评论 #p2' in line for line in lines), 'roles must be named'
        assert any('重爬' in line for line in lines), 'the gap table must tell the user how to re-crawl'

    def test_no_gap_is_said_out_loud(self, monkeypatch):
        result = (
            _comments('https://ex.com/p/1', 3) + _comments('https://ex.com/p/2', 5) + _comments('https://ex.com/p/3', 2)
        )
        _rows, lines = _run(_node(), [('p1', LIST), ('p2', result)], monkeypatch)
        assert any('全部已覆盖' in line for line in lines), lines


class TestTheCountingRules:
    def test_tolerance_absorbs_a_small_shortfall(self, monkeypatch):
        rows, _lines = _run(_node(tolerance=3, output_mode='all'), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        assert _by_title(rows)['乙']['采集状态'] == verify.STATUS_COMPLETE

    def test_the_crawls_per_item_limit_bounds_the_expectation(self, monkeypatch):
        """A crawl told to keep only 2 comments per item cannot be judged against 5."""
        rows, _lines = _run(_node(per_link_limit=2, output_mode='all'), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        second = _by_title(rows)['乙']
        assert second['期望条数'] == 2 and second['采集状态'] == verify.STATUS_COMPLETE

    def test_a_blank_count_is_unverifiable_not_zero(self, monkeypatch):
        listing = [{'标题': '甲', '链接': 'https://ex.com/p/1', '评论数': ''}]
        rows, lines = _run(_node(output_mode='all'), [('p1', listing), ('p2', RESULT)], monkeypatch)
        assert rows[0]['采集状态'] == verify.STATUS_UNCHECKED
        assert rows[0]['缺失条数'] == ''
        assert any('无法识别' in line for line in lines), lines
        assert not any('重爬' in line for line in lines), 'an unreadable count is not a re-crawl gap'

    def test_more_rows_than_promised_is_reported_as_over_not_missing(self, monkeypatch):
        listing = [{'标题': '甲', '链接': 'https://ex.com/p/1', '评论数': 1}]
        rows, _lines = _run(_node(output_mode='all'), [('p1', listing), ('p2', RESULT)], monkeypatch)
        assert rows[0]['采集状态'] == verify.STATUS_OVER
        assert rows[0]['缺失条数'] == 0

    def test_a_thousands_separator_or_a_rounded_label_still_parses(self, monkeypatch):
        listing = [{'标题': '甲', '链接': 'https://ex.com/p/1', '评论数': '3'}]
        rows, _lines = _run(_node(output_mode='all'), [('p1', listing), ('p2', RESULT)], monkeypatch)
        assert rows[0]['期望条数'] == 3

    def test_the_box_can_be_blank_for_coverage_only(self, monkeypatch):
        rows, _lines = _run(
            _node(expected_count_column='', output_mode='all'),
            [('p1', LIST), ('p2', RESULT)],
            monkeypatch,
        )
        status = {row['标题']: row['采集状态'] for row in rows}
        assert status == {'甲': verify.STATUS_UNCHECKED, '乙': verify.STATUS_UNCHECKED, '丙': verify.STATUS_MISSING}


class TestTheMatchingRule:
    def test_a_share_link_and_a_trailing_slash_are_the_same_page(self, monkeypatch):
        listing = [{'标题': '甲', '链接': 'https://ex.com/p/1?utm_source=share', '评论数': 1}]
        rows, _lines = _run(_node(), [('p1', listing), ('p2', _comments('https://ex.com/p/1', 1))], monkeypatch)
        assert rows == [], 'the share form of a collected page is that page'

    def test_similar_matching_is_refused_because_it_cannot_count(self, monkeypatch):
        with pytest.raises(ValueError) as excinfo:
            _run(_node(match_mode='similar'), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        assert 'similar' in str(excinfo.value)

    def test_an_unknown_output_mode_is_refused(self, monkeypatch):
        with pytest.raises(ValueError):
            _run(_node(output_mode='moon'), [('p1', LIST), ('p2', RESULT)], monkeypatch)


class TestTheEdgeCases:
    def test_a_link_repeated_in_the_list_is_checked_once_and_each_row_reports_it(self, monkeypatch):
        listing = LIST + [{'标题': '甲-重复', '链接': 'https://ex.com/p/1', '评论数': 3}]
        rows, lines = _run(_node(output_mode='all'), [('p1', listing), ('p2', RESULT)], monkeypatch)
        assert len(rows) == 4
        assert _by_title(rows)['甲-重复']['采集状态'] == verify.STATUS_COMPLETE
        assert any('重复的链接' in line for line in lines), lines

    def test_an_uncovered_result_page_is_reported_as_an_orphan(self, monkeypatch):
        result = RESULT + _comments('https://elsewhere.com/x', 1)
        _rows, lines = _run(_node(output_mode='all'), [('p1', LIST), ('p2', result)], monkeypatch)
        assert any('不在清单中' in line for line in lines), lines

    def test_a_blank_link_row_is_not_reported_as_a_gap(self, monkeypatch):
        listing = [{'标题': '空', '链接': '', '评论数': 3}]
        rows, lines = _run(_node(), [('p1', listing), ('p2', RESULT)], monkeypatch)
        assert rows == [], 'there is no link to re-crawl, so it is not a gap'
        assert any('链接为空' in line for line in lines), lines

    def test_an_empty_list_is_answered_not_crashed(self, monkeypatch):
        rows, lines = _run(_node(), [('p1', []), ('p2', RESULT)], monkeypatch)
        assert rows == []
        assert any('没有可校验的链接' in line for line in lines), lines

    def test_swapping_exchanges_the_promised_and_the_collected(self, monkeypatch):
        """The comment table becomes the LIST and the post table the RESULT — the same two
        tables, the opposite question. With the roles named the other way round (and no count
        column, which the comment rows do not carry) every comment page is covered but
        unverifiable, which is exactly what that question can answer."""
        rows, _lines = _run(
            _node(
                swap_tables=True,
                input_key_column='文章URL',
                result_key_column='链接',
                expected_count_column='',
                output_mode='all',
            ),
            [('p1', LIST), ('p2', RESULT)],
            monkeypatch,
        )
        assert len(rows) == len(RESULT)
        assert {row['采集状态'] for row in rows} == {verify.STATUS_UNCHECKED}


class TestTheRefusals:
    def test_exactly_two_upstreams_are_required(self, monkeypatch):
        for upstream in ([('p1', LIST)], [('p1', LIST), ('p2', RESULT), ('p3', RESULT)]):
            with pytest.raises(ValueError) as excinfo:
                _run(_node(), upstream, monkeypatch)
            assert '两条' in str(excinfo.value) or 'two' in str(excinfo.value).lower()

    def test_a_non_table_upstream_is_named(self, monkeypatch):
        with pytest.raises(ValueError) as excinfo:
            _run(_node(), [('p1', LIST), ('p2', {'chart': 'spec'})], monkeypatch)
        assert '表格' in str(excinfo.value)

    def test_a_missing_list_or_result_column_names_the_table(self, monkeypatch):
        with pytest.raises(ValueError) as list_col:
            _run(_node(input_key_column='网址'), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        assert '网址' in str(list_col.value) and '清单 #p1' in str(list_col.value)
        with pytest.raises(ValueError) as result_col:
            _run(_node(result_key_column='网址'), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        assert '网址' in str(result_col.value) and '评论 #p2' in str(result_col.value)

    def test_a_named_count_column_that_does_not_exist_says_how_to_clear_it(self, monkeypatch):
        with pytest.raises(ValueError) as excinfo:
            _run(_node(expected_count_column='点赞数'), [('p1', LIST), ('p2', RESULT)], monkeypatch)
        assert '点赞数' in str(excinfo.value) and '留空' in str(excinfo.value)

    def test_empty_key_boxes_are_refused(self, monkeypatch):
        for params in ({'input_key_column': ''}, {'result_key_column': ''}):
            with pytest.raises(ValueError):
                _run(_node(**params), [('p1', LIST), ('p2', RESULT)], monkeypatch)


class TestTheColumnContract:
    def test_the_report_columns_are_one_place_and_are_appended(self):
        assert verify.REPORT_COLUMNS == ('采集状态', '期望条数', '实际条数', '缺失条数', '完成度')

    def test_the_lineage_says_which_columns_the_audit_reads(self):
        node = _node()
        assert verify.read_columns(node) == ['链接', '文章URL', '评论数']
        assert verify.read_columns(_node(expected_count_column='')) == ['链接', '文章URL']
