"""红果短剧 comment parser — the harvested-JSON contract, no process involved.

The fixtures below are condensed from a real mitmproxy capture of the desktop
player's ``comment/list`` (2026-10-19): a danmaku-guide row, an anonymous row with
no name block, and logged-in rows whose ``base_info`` carries ``user_name``. The
shapes are what the parser is pinned against — the harvester that feeds it lives in
the device tier.
"""

import pytest

from crawlers.comments_hongguo import hg_comment_rows, hg_page_title, hg_series_id

pytestmark = pytest.mark.unit

ARTICLE = 'https://hongguoduanju.com/detail?series_id=7696074722013875224'


def _entry(cid, text, ts, *, group='7696074722013875224', user=None, digg=0, replies=0, danmaku=False):
    common = {
        'comment_type': 0,
        'content': {'text': text},
        'create_timestamp': ts,
        'group_id': group,
        'service_id': 20,
        'status': 1,
        'user_info': user if user is not None else {},
    }
    expand = {'book_id': '7696063528179878937'}
    if danmaku:
        expand['danmaku_activity_info'] = {'activity_id': '7687486352526508094', 'activity_name': '弹幕活动'}
        common['service_id'] = 0
        common['status'] = 0
    return {
        'comment': {
            'comment_id': cid,
            'common': common,
            'expand': expand,
            'stat': {'digg_count': digg, 'reply_count': replies},
        },
        'data_type': 4,
    }


def _envelope(entries, total=3, has_more=False, cursor='{"start_offset_time":0,"end_offset_time":30000}'):
    return {
        'BaseResp': {'StatusCode': 0, 'StatusMessage': 'success'},
        'code': 0,
        'data': {
            'common_list_info': {'cursor': cursor, 'has_more': has_more, 'total': total},
            'data_list': entries,
        },
    }


class TestRows:
    def test_a_real_comment_becomes_the_standard_columns(self):
        payload = _envelope([_entry('7697905336342594366', '女主好飒', 1792313924, digg=1, replies=2)])
        rows, dropped, total, has_more = hg_comment_rows(payload, ARTICLE, drama_title='测试剧', episode_index=3)
        assert dropped == 0 and total == 3 and has_more is False
        row = rows[0]
        assert row['平台'] == 'hongguo'
        assert row['文章URL'] == ARTICLE
        assert row['评论内容'] == '女主好飒'
        assert row['评论ID'] == '7697905336342594366'
        assert row['点赞数'] == 1 and row['子回复数'] == 2 and row['楼层'] == 1
        assert row['分集ID'] == '7696074722013875224'
        # A 短剧 comment is about an EPISODE of a NAMED drama, and neither fact is in the
        # payload: the walker hands both down, or the table is a list of unreadable ids.
        assert row['剧名'] == '测试剧'
        assert row['集序号'] == 3
        # A bare epoch second must leave as a Beijing wall-clock stamp, not the number.
        assert row['评论时间'].startswith('20') and ':' in row['评论时间']
        # The payload offers no profile URL for a commenter: blank, never invented.
        assert row['评论者主页'] == ''

    def test_the_column_set_is_the_shared_key_plus_the_dramas_own_words(self):
        # Pinned whole because a column added on one side is a chart or an analysis
        # looking for it on the other: 文章URL stays the cross-platform join key (every
        # platform's comment table carries it) and the drama shape lives beside it.
        payload = _envelope([_entry('7001', '甲', 1792313924)])
        rows, _dropped, _total, _more = hg_comment_rows(payload, ARTICLE)
        assert set(rows[0]) == {
            '平台',
            '文章URL',
            '剧名',
            '集序号',
            '评论者',
            '评论者主页',
            '评论内容',
            '评论时间',
            '点赞数',
            '楼层',
            '父楼层',
            '评论ID',
            '分集ID',
            '子回复数',
        }
        # No walker facts, no invention: called bare, the drama columns stay empty/blank.
        assert rows[0]['剧名'] == '' and rows[0]['集序号'] == ''

    def test_the_danmaku_guide_row_is_dropped_and_counted(self):
        payload = _envelope(
            [
                _entry('11114', '输入弹幕活动名TA的名字', 0, danmaku=True),
                _entry('7698176206572831550', '追完了', 1792380851),
            ],
            total=2,
        )
        rows, dropped, _total, _more = hg_comment_rows(payload, ARTICLE)
        assert dropped == 1
        assert [r['评论ID'] for r in rows] == ['7698176206572831550']

    def test_a_zero_timestamp_row_dies_even_without_the_activity_block(self):
        payload = _envelope([_entry('11115', '系统提示', 0)])
        rows, dropped, _t, _m = hg_comment_rows(payload, ARTICLE)
        assert (rows, dropped) == ([], 1)

    def test_an_empty_body_dies_and_does_not_steal_a_floor(self):
        payload = _envelope(
            [
                _entry('1', '第一', 1792313924),
                _entry('2', '   ', 1792313925),
                _entry('3', '第三', 1792313926),
            ]
        )
        rows, dropped, _t, _m = hg_comment_rows(payload, ARTICLE)
        assert dropped == 1
        assert [(r['评论ID'], r['楼层']) for r in rows] == [('1', 1), ('3', 2)]

    def test_floors_continue_across_pages_via_first_floor(self):
        page2 = _envelope(
            [_entry('91', '续', 1792313924)], cursor='{"start_offset_time":30000,"end_offset_time":60000}'
        )
        rows, _d, _t, _m = hg_comment_rows(page2, ARTICLE, first_floor=91)
        assert rows[0]['楼层'] == 91

    def test_reply_rows_link_to_their_parent_floor(self):
        payload = _envelope([_entry('2001', '回复内容', 1792313924)])
        rows, _d, _t, _m = hg_comment_rows(payload, ARTICLE, first_floor=1, parent_floor=7)
        assert rows[0]['父楼层'] == 7

    def test_a_top_level_row_reports_no_parent(self):
        payload = _envelope([_entry('2002', '主楼', 1792313924)])
        rows, _d, _t, _m = hg_comment_rows(payload, ARTICLE)
        assert rows[0]['父楼层'] == ''


class TestNames:
    def test_logged_in_payload_reads_the_user_name_field(self):
        user = {'base_info': {'user_id': '1383644647135260', 'user_name': '咪咪猫'}, 'user_id': '1383644647135260'}
        payload = _envelope([_entry('3001', '有名字', 1792313924, user=user)])
        rows, *_ = hg_comment_rows(payload, ARTICLE)
        assert rows[0]['评论者'] == '咪咪猫'

    def test_anonymous_payload_leaves_the_name_blank_not_the_id(self):
        user = {'base_info': {}, 'expand_extra': {}, 'user_id': '3850914299130251'}
        payload = _envelope([_entry('3002', '匿名', 1792313924, user=user)])
        rows, *_ = hg_comment_rows(payload, ARTICLE)
        assert rows[0]['评论者'] == ''


class TestEnvelopeTolerance:
    def test_a_missing_data_block_answers_empty_not_crash(self):
        rows, dropped, total, has_more = hg_comment_rows({'code': 71012}, ARTICLE)
        assert (rows, dropped, total, has_more) == ([], 0, 0, False)

    def test_entries_that_are_not_dicts_are_dropped(self):
        payload = _envelope([None, 'x', _entry('4001', 'ok', 1792313924)])
        rows, dropped, *_ = hg_comment_rows(payload, ARTICLE)
        assert len(rows) == 1 and dropped == 2


class TestLinkHelpers:
    def test_the_detail_link_names_the_series(self):
        assert hg_series_id(ARTICLE) == '7696074722013875224'

    def test_a_bare_id_is_accepted(self):
        assert hg_series_id('7696074722013875224') == '7696074722013875224'

    def test_an_unrelated_link_names_nothing(self):
        assert hg_series_id('https://www.douyin.com/video/123') == ''
        assert hg_series_id('') == ''

    def test_the_detail_title_is_the_drama_name_before_the_first_underscore(self):
        html = '<title>瓜宝奇缘之我家老公是BOSS的十倍价_红果短剧免费短剧大全在线观看_红果短剧</title>'
        assert hg_page_title(html) == '瓜宝奇缘之我家老公是BOSS的十倍价'

    def test_a_page_without_a_title_gives_no_name(self):
        assert hg_page_title('<html></html>') == ''
        assert hg_page_title('') == ''


def _reply_element(rid, text, ts, *, group, parent, digg=0, book='7615465407347952664', stamp_zero=False):
    """One ``data.reply_list[]`` element in the shape a REAL child page prints.

    Measured 2026-10-20 from a kept capture: the body key is a CAPITALISED ``Common``, the
    child's own id is ``reply_id``, its parent is ``reply_to_comment_id``, and there is no
    ``comment``/``data_list`` wrapper at all — which is why reading only ``data_list`` made
    every expansion click answer zero rows for a day.
    """
    return {
        'Common': {
            'comment_type': 0,
            'content': {'text': text},
            'create_timestamp': 0 if stamp_zero else ts,
            'group_id': group,
            'service_id': 4,
            'status': 1,
            'user_info': {'base_info': {'user_name': f'用户{rid[-3:]}'}, 'user_id': '605154498058220'},
        },
        'expand': {'book_id': book},
        'reply_id': rid,
        'reply_to_comment_id': parent,
        'reply_to_reply_id': '',
        'stat': {'digg_count': digg, 'reply_count': 0},
        'sub_reply': [],
    }


def _reply_parent(cid='7620733881692750616', *, group='7615470196337151038', replies=4):
    """``data.comment`` — the parent comment, in the ``comment/list`` element shape."""
    return _entry(cid, '父评论', 1774343143, group=group, replies=replies)['comment']


def _reply_envelope(elements, total, parent=None, has_more=False):
    return {
        'BaseResp': {'StatusCode': 0, 'StatusMessage': 'success'},
        'code': 0,
        'data': {
            'comment': parent if parent is not None else _reply_parent(),
            'comment_list_info': {'cursor': '50', 'has_more': has_more, 'total': total},
            'extra': {},
            'reply_list': elements,
        },
    }


class TestReplyShape:
    """``reply/list`` is a DIFFERENT envelope, and the parser has to know that."""

    def test_a_real_child_page_yields_child_rows_not_an_empty_table(self):
        payload = _reply_envelope(
            [
                _reply_element(
                    '7697252120426136345',
                    '修仙小妖怪',
                    1792160661,
                    group='7615470196337151038',
                    parent='7620733881692750616',
                ),
                _reply_element(
                    '7697252120426136346',
                    '好看',
                    1792160700,
                    group='7615470196337151038',
                    parent='7620733881692750616',
                    digg=3,
                ),
            ],
            total=4,
        )
        rows, dropped, total, has_more = hg_comment_rows(
            payload, ARTICLE, first_floor=9, parent_floor=2, drama_title='某剧', episode_index=1
        )
        assert dropped == 0, 'a real child row is not a danmaku prompt'
        assert [r['评论ID'] for r in rows] == ['7697252120426136345', '7697252120426136346'], 'reply_id is the id'
        assert all(r['父楼层'] == 2 for r in rows), 'a child links back to its parent floor'
        assert [r['楼层'] for r in rows] == [9, 10], 'floors continue from the walker, newest-first inside a page'
        assert rows[0]['分集ID'] == '7615470196337151038', 'the episode group is read out of the body'
        assert rows[0]['剧名'] == '某剧' and rows[0]['评论者'] == '用户345'
        assert rows[1]['点赞数'] == 3

    def test_the_child_pages_total_comes_from_its_own_pagination_block(self):
        # comment/list paginates in ``common_list_info``, reply/list in ``comment_list_info``.
        # The walker grades 展开 N 条回复 against this number, so reading the wrong block made
        # every thread look complete at zero.
        payload = _reply_envelope(
            [_reply_element('1', '甲', 1792160661, group='g', parent='p')],
            total=200,
        )
        rows, _dropped, total, has_more = hg_comment_rows(payload, ARTICLE)
        assert len(rows) == 1 and total == 200 and has_more is False

    def test_a_child_row_without_a_body_is_counted_as_dropped(self):
        payload = _reply_envelope(
            [
                _reply_element('1', '甲', 1792160661, group='g', parent='p'),
                _reply_element('2', '乙', 0, group='g', parent='p'),  # create_timestamp 0 → prompt
            ],
            total=2,
        )
        rows, dropped, _total, _more = hg_comment_rows(payload, ARTICLE)
        assert len(rows) == 1 and dropped == 1

    def test_an_element_that_names_no_body_is_refused_rather_than_blanked(self):
        # A payload shape change (the capitalised key renamed) must not become a table of
        # empty rows: it is refused here, loudly, and the walker's shortfall then names it.
        payload = _reply_envelope([{'comment': {'comment_id': '1'}}], total=1)
        rows, dropped, _total, _more = hg_comment_rows(payload, ARTICLE)
        assert rows == [] and dropped == 1

    def test_the_comment_list_shape_still_reads_as_the_other_envelope(self):
        # The branch is chosen by where the list lives, so an ordinary page must not be
        # re-read as a child page just because the reply keys exist somewhere else.
        payload = _envelope([_entry('7697905336342594366', '女主好飒', 1792313924)])
        rows, dropped, total, _more = hg_comment_rows(payload, ARTICLE)
        assert len(rows) == 1 and dropped == 0 and total == 3
