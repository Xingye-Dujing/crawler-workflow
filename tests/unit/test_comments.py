"""Comment crawler adapters against fake drivers — every edge case, no browser.

The live tier already proves these work against the real sites; this file is
what pins the *contracts* the live tier cannot express cheaply: pagination
stops, per-article limits, dedupe across scroll rounds, and the three distinct
outcomes (ok / blocked / dead) — because an article that is *genuinely empty*
and an article hidden behind a login wall must never look the same to the user.
"""

import json
import re

import pytest

# Imported as a module, not as ``t``: this file names a text column 文本, and a bare ``t`` would
# collide with it in exactly the tests that compare console wording.
import i18n
from crawlers.comments import (
    BLOCKED,
    DEAD,
    OK,
    CommentSession,
    bilibili_reply_js,
    bilibili_view_js,
    parse_bilibili_comments,
    parse_weibo_comments,
    weibo_bid,
)
from crawlers.engine.wall import looks_blocked, looks_like_login_page
from engine.workflow import WorkflowEngine
from utils.helpers import platform_for

pytestmark = pytest.mark.unit


class El:
    def __init__(self, text='', attrs=None, kids=None):
        self.text = text
        self._attrs = attrs or {}
        self._kids = kids or {}

    def get_attribute(self, name):
        return self._attrs.get(name, '')

    def find_element(self, by, selector):
        found = self.find_elements(by, selector)
        if not found:
            from selenium.common.exceptions import NoSuchElementException

            raise NoSuchElementException(selector)
        return found[0]

    def find_elements(self, by, selector):
        return list(self._kids.get(selector, []))

    def click(self):
        self.clicked = True


class FakeDriver:
    def __init__(self, body='', pages=None, fetch_queue=None, start_url='https://x.test/', panel_pages=None):
        self.body = body
        self.pages = pages or {}
        self.fetch_queue = list(fetch_queue or [])
        self.fetched = []
        self.visited = []
        self.current_url = start_url
        self.scripts = []
        # What the in-page zhihu panel read answers, page by page. The JS itself is a page-side
        # contract (measured by backend/test_zhihu_comment_dom.py); this fake supplies its OUTPUT
        # so the Python half — row building, dedupe, the authorless and cap lines — is what is
        # actually under test here.
        self.panel_pages = list(panel_pages or [])

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def set_script_timeout(self, seconds):
        pass

    def find_element(self, by, selector):
        if selector == 'body':
            return El(self.body)
        return El('')

    def find_elements(self, by, selector):
        return list(self.pages.get(selector, []))

    def execute_script(self, script, *args):
        self.scripts.append(script)
        # The pump script also mentions ``.CommentContent`` (it looks for the box that holds them),
        # so the scroll ask is answered first or it would swallow a panel page.
        if 'scrollTop' in script:
            return 120
        if 'CommentContent' in script:
            if not self.panel_pages:
                return []
            # The last page repeats: a panel that stopped changing is what the product's own
            # dedupe and 「更多」 check have to notice, so the supply must not run out under them.
            return self.panel_pages.pop(0) if len(self.panel_pages) > 1 else self.panel_pages[0]

    def execute_async_script(self, script, *args):
        m = re.search(r'fetch\(\"(.*?)\"', script)
        self.fetched.append(m.group(1) if m else script[:40])
        if self.fetch_queue:
            return self.fetch_queue.pop(0)
        return 'ERR nothing queued'


# ─── pure helpers ───────────────────────────────────────────────────────


class TestHelpers:
    def test_platform_dispatch(self):
        assert platform_for('https://www.zhihu.com/question/1/answer/2') == 'zhihu'
        assert platform_for('https://www.xiaohongshu.com/explore/abc') == 'xiaohongshu'
        assert platform_for('https://weibo.com/123/AbCdEf') == 'weibo'
        assert platform_for('https://m.weibo.cn/detail/123') == 'weibo'
        assert platform_for('https://example.com/x') == ''
        assert platform_for('') == ''

    def test_weibo_bid_forms(self):
        assert weibo_bid('https://weibo.com/1763742695/RhYNar0R1') == 'RhYNar0R1'
        assert weibo_bid('https://m.weibo.cn/detail/5342852646438143') == '5342852646438143'
        assert weibo_bid('nonsense') == ''

    def test_block_detection(self):
        # Risk control and a login wall are different answers now (the user's fix
        # differs: wait, or re-save the cookie), so the two detectors are asserted
        # apart rather than through one helper that accepted either.
        assert looks_blocked('…暂时限制本次访问…')
        assert looks_like_login_page('', '扫码登录 手机号登录')
        assert not looks_blocked('正常内容 三亚攻略')

    def test_weibo_parser_strips_tags_and_counts(self):
        payload = {
            'data': [
                {'user': {'screen_name': '甲'}, 'text': '好<b>棒</b>', 'created_at': '9月14日', 'like_count': 3},
                {'user': None, 'text': None},
            ]
        }
        rows = parse_weibo_comments(payload, 'https://weibo.com/1/a')
        assert rows[0]['评论内容'] == '好棒' and rows[0]['点赞数'] == 3 and rows[0]['楼层'] == 1
        assert rows[1]['评论者'] == '' and rows[1]['点赞数'] == 0
        # A row the payload gives no id for is still a row: 评论ID exists to de-duplicate pages, and an
        # empty one may not delete a comment the site showed.
        assert rows[1]['评论ID'] == ''
        # Identity-safe columns: none of the dedupe-ledger URL/author/body names. 父楼层 joins the set
        # because weibo hands back one nested reply per parent row, and 评论ID because the walker needs
        # an id to keep the pages apart (docs/crawler_notes.md 微博第 0 步).
        assert set(rows[0]) == {
            '平台',
            '文章URL',
            '评论者',
            '评论者主页',
            '评论内容',
            '评论时间',
            '点赞数',
            '楼层',
            '父楼层',
            '评论ID',
        }

    def test_weibo_parser_reads_the_sites_own_floor_likes_and_home(self):
        """The four columns this adapter used to guess, pinned against the measured payload.

        Measured 2026-09-28 (``scratchpad/weibo_structure.json``): the desktop row carries
        ``like_counts`` (the old code read ``like_count``, so every comment stored 0 likes),
        ``floor_number`` numbered across the whole thread (the old per-page ``enumerate`` restarted at
        1 on page 2), ``created_at`` as ``'Sun Jul 26 09:49:46 +0800 2026'`` (stored raw beside the
        search path's ``09月26日 21:00``), and BOTH ``profile_url`` and ``profile_image_url`` — the
        column is 评论者主页, so the avatar was the wrong answer, not a worse-format one.
        """
        rows = parse_weibo_comments(
            {
                'data': [
                    {
                        'id': 5324866577500964,
                        'floor_number': 28,
                        'like_counts': 4,
                        'created_at': 'Sun Jul 26 09:49:46 +0800 2026',
                        'rootid': 5324866577500964,
                        'text': '主楼',
                        'user': {
                            'screen_name': '甲',
                            'profile_url': '/u/5893846418',
                            'profile_image_url': 'https://tvax.sinaimg.cn/avatar.jpg',
                        },
                    }
                ]
            },
            'https://weibo.com/1/a',
        )
        assert rows[0]['楼层'] == 28, rows
        assert rows[0]['点赞数'] == 4, 'the desktop key is like_counts, not like_count'
        assert rows[0]['评论时间'] == '2026-07-26 09:49', rows
        assert rows[0]['评论者主页'] == 'https://weibo.com/u/5893846418'
        assert rows[0]['父楼层'] == '', 'rootid equal to its own id means a top-level comment'

    def test_weibo_parser_keeps_the_parent_preview_reply(self):
        """One nested reply per parent row is in the payload already, and used to be thrown away."""
        payload = {
            'data': [
                {
                    'id': 1,
                    'floor_number': 254,
                    'rootid': 1,
                    'text': '父',
                    'user': {'screen_name': '甲', 'profile_url': '/u/1'},
                    'total_number': 6,
                    'comments': [
                        {
                            'id': 2,
                            'floor_number': 0,
                            'rootid': 1,
                            'text': '子',
                            'like_counts': 9,
                            'user': {'screen_name': '乙', 'profile_url': '/u/2'},
                        }
                    ],
                }
            ]
        }
        rows = parse_weibo_comments(payload, 'https://weibo.com/1/a')
        assert [r['评论内容'] for r in rows] == ['父', '子'], rows
        assert [r['父楼层'] for r in rows] == ['', 254], rows
        # A reply has NO floor of its own — the measured payload says ``floor_number: 0`` on a child, which
        # is the site saying "the whole-thread numbering does not apply to me". Substituting its position
        # inside its parent's preview would put two numbering systems in one column and re-create the
        # six-rows-called-1 defect the test above pins.
        assert rows[1]['楼层'] == '', rows
        assert rows[1]['点赞数'] == 9


# ─── weibo adapter (in-page ajax) ───────────────────────────────────────


class TestWeiboAdapter:
    def _session(self, queue, start='https://weibo.com/'):
        driver = FakeDriver(fetch_queue=queue, start_url=start)
        return CommentSession(driver, nap=lambda s: None), driver

    def test_two_pages_follow_max_id(self):
        page1 = json.dumps({'data': [{'user': {'screen_name': 'a'}, 'text': 't1'}], 'max_id': 99})
        page2 = json.dumps({'data': [{'user': {'screen_name': 'b'}, 'text': 't2'}], 'max_id': 0})
        session, driver = self._session([json.dumps({'id': '555'}), page1, page2])
        rows, status = session.crawl_weibo('https://weibo.com/1/RhYNar0R1', limit=0)
        assert status == OK and [r['评论内容'] for r in rows] == ['t1', 't2']
        assert any('max_id=99' in url for url in driver.fetched), 'must paginate with returned max_id'

    def test_limit_caps_rows(self):
        big = json.dumps({'data': [{'user': {}, 'text': f'c{i}'} for i in range(30)], 'max_id': 0})
        session, _ = self._session([json.dumps({'id': '555'}), big])
        rows, status = session.crawl_weibo('https://weibo.com/1/RhYNar0R1', limit=4)
        assert status == OK and len(rows) == 4

    def test_unreadable_post_is_dead(self):
        session, _ = self._session(['ERR network', 'never'])
        rows, status = session.crawl_weibo('https://weibo.com/1/Deleted01', limit=0)
        assert rows == [] and status == DEAD

    def test_zero_comment_post_is_ok_not_dead(self):
        session, _ = self._session([json.dumps({'id': '555'}), json.dumps({'data': [], 'max_id': 0})])
        rows, status = session.crawl_weibo('https://weibo.com/1/RhYNar0R1', limit=0)
        assert rows == [] and status == OK, 'an article without comments is success with nothing, not an error'

    def test_bidless_url_is_dead(self):
        session, _ = self._session([])
        rows, status = session.crawl_weibo('https://weibo.com/', limit=0)
        assert rows == [] and status == DEAD

    def test_the_pages_own_number_names_a_shortfall(self):
        """22 of 30 must not read like a complete thread.

        Measured 2026-09-28 on a live post: the search card, ``statuses/show.comments_count`` and the
        page's ``total_number`` all said 30, the cursor walk returned 22, and the eight missing floors
        were its nested replies. The walk ended on ``max_id=0`` — a clean exhaustion — so only the
        denominator can tell 「这些就是全部」 from 「还差 8 条」, and the user must not have to notice.
        """
        said = []
        page1 = json.dumps({'data': [{'id': f'p1-{i}', 'text': 'x'} for i in range(20)], 'max_id': 99})
        page2 = json.dumps({'data': [{'id': f'p2-{i}', 'text': 'y'} for i in range(2)], 'max_id': 0})
        driver = FakeDriver(
            fetch_queue=[json.dumps({'id': '555', 'comments_count': 30}), page1, page2], start_url='https://weibo.com/'
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, status = session.crawl_weibo('https://weibo.com/1/RhYNar0R1', limit=0)
        assert status == OK and len(rows) == 22, rows
        assert i18n.t('comment.weiboShort', declared=30, rows=22, gap=8) in said, said

    def test_a_replayed_page_ends_the_walk_and_says_so(self):
        """U19's weibo cell, fixed without a page budget.

        A constant number of pages was the old exit: a bare ``break`` that made a capped crawl
        indistinguishable from one the site finished, so the user read the shorter number as the thread's
        size. The repo has no page budgets any more, and this thread really does run past 600 rows
        (measured: ~19-22 per page, 749 declared, cursor still live at page 6) — so what ends the walk is
        the cursor dying or the site replaying, and the replay is *named*.
        """
        said = []
        replay = json.dumps({'data': [{'id': 'p1-0', 'text': 'x'}], 'max_id': 99})
        driver = FakeDriver(
            fetch_queue=[json.dumps({'id': '555', 'comments_count': 900}), replay, replay, replay],
            start_url='https://weibo.com/',
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, status = session.crawl_weibo('https://weibo.com/1/RhYNar0R1', limit=0)
        assert status == OK and len(rows) == 1, rows
        assert i18n.t('comment.weiboReplay', page=3, rows=1) in said, said
        # The shortfall line is about the SITE, so it stays quiet when our own exit ended the walk.
        assert not [line for line in said if 'weiboShort' in line or '写着' in line], said

    def test_a_failed_comment_page_names_itself_instead_of_looking_finished(self):
        """The one exit of this walk that used to print nothing at all.

        A thread that walked to page 2 and had the request die there handed back its page-1 rows and left
        the console empty: ``comment.weiboShort`` stayed silent *by design*, because that line speaks for
        the cursor running out and the cursor had not — a transport failure had. So the short table read
        exactly like a thread that had no more comments, which is the shape this campaign exists to catch.
        Naming the failure is also what makes 继续 the right advice: the walk's cursor is on the page that
        died, not past it.
        """
        said = []
        page1 = json.dumps({'data': [{'id': f'c{i}', 'text': 'x'} for i in range(20)], 'max_id': 99})
        driver = FakeDriver(
            fetch_queue=[json.dumps({'id': '555', 'comments_count': 60}), page1], start_url='https://weibo.com/'
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, status = session.crawl_weibo('https://weibo.com/1/RhYNar0R1', limit=0)
        assert status == OK and len(rows) == 20, rows
        assert i18n.t('comment.weiboFetchDied', page=1, rows=20, declared=60, gap=40) in said, said
        # One line, not two: the cursor never ran out, so the site-blaming sentence must not also print.
        assert not [line for line in said if '写着' in line], said

    def test_the_ask_is_not_reported_as_a_shortfall(self):
        """评论上限 20 on a 749-comment post is the user's number, not the thread's absence.

        Attributing that gap to 楼中楼 would blame the site for the ask — and this is exactly the shape the
        live tier drives (``test_live_comments.py`` asks for 5), so the wrong line would be printed on
        every run of that matrix.
        """
        said = []
        big = json.dumps({'data': [{'id': f'c{i}', 'text': 'x'} for i in range(20)], 'max_id': 99})
        driver = FakeDriver(
            fetch_queue=[json.dumps({'id': '555', 'comments_count': 749}), big], start_url='https://weibo.com/'
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, _ = session.crawl_weibo('https://weibo.com/1/RhYNar0R1', limit=8)
        assert len(rows) == 8, rows
        assert said == [], f'the user set the number; nothing about the thread is missing: {said}'


# ─── xiaohongshu adapter (DOM) ──────────────────────────────────────────


def _xhs_card(author, text, date='09-10', likes='赞'):
    return El(
        kids={
            '.author-wrapper .name, .name': [El(author)],
            '.content': [El(text)],
            '.date': [El(date)],
            '.like .count, .like-wrapper .count': [El(likes)],
        }
    )


class TestXhsAdapter:
    def test_collects_and_dedupes_across_rounds(self):
        cards = [_xhs_card('甲', '很全的攻略'), _xhs_card('乙', '图一在哪')]
        driver = FakeDriver(pages={'.comment-item': cards})
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_xiaohongshu('https://www.xiaohongshu.com/explore/x', 0)
        assert status == OK and len(rows) == 2
        assert rows[0]['评论者'] == '甲' and rows[1]['评论内容'] == '图一在哪'
        assert 'scrollBy' in ''.join(driver.scripts), 'must scroll to load more comments'
        # second round returns the SAME elements → seen-set stops the loop

    def test_login_wall_page_is_blocked(self):
        driver = FakeDriver(body='登录后查看更多内容 扫码登录', pages={'.comment-item': []})
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_xiaohongshu('https://www.xiaohongshu.com/explore/x', 0)
        assert rows == [] and status == BLOCKED

    def test_no_comments_is_ok(self):
        driver = FakeDriver(body='正常笔记', pages={})
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_xiaohongshu('https://www.xiaohongshu.com/explore/x', 0)
        assert rows == [] and status == OK


# ─── zhihu adapter (DOM, panels behind buttons) ─────────────────────────


def _zh_row(author, text, href='https://www.zhihu.com/people/x', when='3 天前'):
    """One comment as the in-page panel read reports it.

    The fake answers the page-side script with its own output format, so these tests cover the
    Python half — row building, dedupe, the two console lines. The climb itself (stop at the
    ancestor that still holds exactly one ``.CommentContent``) is a page contract, measured by
    ``backend/test_zhihu_comment_dom.py`` and re-measured by the live tier's D group.
    """
    return {'author': author, 'href': href, 'text': text, 'time': when}


class TestZhihuAdapter:
    def test_opens_panels_and_collects(self):
        btn = El('17 条评论')
        driver = FakeDriver(
            body='正常回答',
            pages={
                'button': [btn, El('举报')],
                'button, a': [El('举报')],  # no 更多 → single round
            },
            panel_pages=[[_zh_row('陈博涵', '三亚最南所以火'), _zh_row('路人', '秦皇岛外打鱼船')]],
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert status == OK and len(rows) == 2
        assert getattr(btn, 'clicked', False), 'comment panel must be opened'
        assert rows[0]['评论者'] == '陈博涵' and rows[0]['评论者主页'].endswith('/people/x')

    def test_the_time_is_the_pages_and_the_like_column_is_not_invented(self):
        """Both columns used to be written without asking: 评论时间 as ``''`` and 点赞数 as ``0``.

        A zero in a count column is a fact the user reads ("nobody liked this") and acts on in a
        chart; the panel was measured (22 items over 2 answers) to expose no like count at all, so
        the honest value is the one that says nothing was read.
        """
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('5 条评论')], 'button, a': []},
            panel_pages=[[_zh_row('甲', 'a', when='2019-08-15')]],
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, _ = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert rows[0]['评论时间'] == '2019-08-15', 'the page names the moment; the row must carry it'
        assert rows[0]['点赞数'] == '', 'a column this crawler never reads may not publish a zero'

    def test_an_authorless_comment_is_kept_and_counted_out_loud(self):
        """An empty 评论者 is either the site's answer (anonymous) or a dead read, and the only
        thing that tells them apart later is a line with a number in it."""
        said = []
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('5 条评论')], 'button, a': []},
            panel_pages=[[_zh_row('', '匿名的一条'), _zh_row('乙', '两条')]],
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, _ = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert len(rows) == 2, 'an anonymous comment is still a comment the user asked for'
        assert rows[0]['评论者'] == ''
        assert i18n.t('comment.zhihuNoAuthor', n=1, total=2) in said

    def test_the_panel_is_pumped_and_the_walk_follows_it(self):
        """The regression the user named: 知乎 has no 「更多」 button, so button-hunting stops at 12.

        Measured (``backend/test_zhihu_comment_structure.py``): one answer declares 261 comments and
        the panel holds 12 until its OWN box is scrolled (then 36, and 41 after the reply threads).
        The walk therefore pumps the container each round and re-reads, and it must keep going while
        the page keeps answering with new comments.
        """
        pages = [[_zh_row('甲', f'{r}-{i}') for i in range(4)] for r in range(3)]
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('261 条评论')], 'button, a': []},
            panel_pages=pages,
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, _ = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert len(rows) == 12, f'the walk stopped while the panel was still filling: {len(rows)}'
        assert any('scrollTop' in script for script in driver.scripts), 'the container must be scrolled'

    def test_nested_replies_are_opened_and_keep_their_parent(self):
        """A reply does not exist in the DOM until 「展开其中 N 条回复」 is clicked. Not clicking it
        is 漏采 by construction, and losing which comment it belongs to makes the thread unreadable
        even when the text was taken."""
        opener = El('展开其中 2 条回复')
        pages = [
            [
                _zh_row('甲', '顶层一条'),
                _zh_row('乙', '子回复', when=''),  # parent index 0 → 父楼层 1
            ]
        ]
        pages[0][1]['parent'] = 0
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('44 条评论')], 'button, a': [opener]},
            panel_pages=pages,
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, _ = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert getattr(opener, 'clicked', False), 'the reply thread was never opened'
        assert [row['父楼层'] for row in rows] == ['', 1], rows

    def test_a_shortfall_against_the_pages_own_number_is_said(self):
        """The button says 261. If the walk files 3, the console must hold both numbers — 「面板就这些」
        and 「我们只走到这些」 cannot be allowed to look alike in the export."""
        said = []
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('261 条评论')], 'button, a': []},
            panel_pages=[[_zh_row('甲', '唯一一条')]],
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, _ = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert len(rows) == 1
        assert i18n.t('comment.zhihuPanelShort', declared=261, rows=1) in said

    def test_the_round_budget_is_named_when_a_panel_never_settles(self):
        """A budget the crawler imposes has to announce itself, or "we stopped" reads as "it ended"."""
        said = []
        endless = [[_zh_row('甲', f'r{i}', when='')] for i in range(40)]
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('999 条评论')], 'button, a': []},
            panel_pages=endless,
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        previous = CommentSession.ZHIHU_PANEL_ROUNDS
        try:
            CommentSession.ZHIHU_PANEL_ROUNDS = 4
            rows, _ = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        finally:
            CommentSession.ZHIHU_PANEL_ROUNDS = previous
        assert len(rows) == 4
        assert i18n.t('comment.zhihuPanelCapped', n=4, rows=4) in said

    def test_blocked_page_reports_blocked(self):
        driver = FakeDriver(body='您当前请求存在异常，暂时限制本次访问。40362', pages={})
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert rows == [] and status == BLOCKED

    def test_answers_without_comment_buttons_are_ok_empty(self):
        driver = FakeDriver(body='正常', pages={'button': [El('关注')]})
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert rows == [] and status == OK

    def test_limit_stops_panel_iteration(self):
        btns = [El('5 条评论'), El('6 条评论'), El('7 条评论')]
        driver = FakeDriver(
            body='正常',
            pages={'button': btns, 'button, a': []},
            panel_pages=[[_zh_row('甲', 'a'), _zh_row('乙', 'b')]],
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 1)
        assert status == OK and len(rows) == 1


# ─── bilibili adapter (in-page ajax, server-owned cursor) ───────────────


def _bili_view(aid=113332711333508, reply_total=40, code=0):
    data = {
        'aid': aid,
        'bvid': 'BV1atCRYsE7x',
        'title': '90分钟！清华博士带你一口气搞懂人工智能',
        'stat': {
            'view': 1405449,
            'like': 85667,
            'coin': 79485,
            'favorite': 130552,
            'share': 24794,
            'reply': reply_total,
        },
    }
    return json.dumps({'code': code, 'message': 'OK', 'data': data})


def _bili_reply(rpid, uname='甲', msg='讲得很透彻', like=1001, ctime=1729339402, subs=(), rcount=0):
    item = {
        'rpid': rpid,
        'ctime': ctime,
        'like': like,
        'rcount': rcount,
        'count': rcount,
        'member': {'mid': '343586650', 'uname': uname, 'level_info': {'current_level': 5}},
        'content': {'message': msg},
        'card_label': [],
    }
    if subs:
        item['replies'] = [
            {
                'rpid': sub_rpid,
                'ctime': ctime + 10,
                'like': 3,
                'member': {'mid': '7', 'uname': sub_name, 'level_info': {'current_level': 2}},
                'content': {'message': sub_msg},
                'root': rpid,
            }
            for sub_rpid, sub_name, sub_msg in subs
        ]
    return item


def _bili_page(rows, next_cursor=None, is_end=False, code=0):
    cursor = {
        'all_count': len(rows),
        'is_end': is_end,
        'next': rows and next_cursor if next_cursor is not None else 0,
    }
    return json.dumps({'code': code, 'data': {'replies': rows, 'cursor': cursor}})


class TestBilibiliAdapter:
    def _session(self, queue):
        driver = FakeDriver(fetch_queue=queue)
        return CommentSession(driver, nap=lambda s: None), driver

    def test_the_walk_follows_the_servers_cursor_not_a_counter(self):
        """Measured: ``next=0`` answers and reports ``cursor.next=2``, and asking
        for ``next=1`` replays page 0 byte for byte. Incrementing would store the
        same 19 comments forever, so the request URL is the assertion here."""
        first = _bili_reply('100', '甲', '第一条')
        second = _bili_reply('200', '乙', '第二条')
        session, driver = self._session(
            [
                _bili_view(),
                _bili_page([first], next_cursor=2),
                _bili_page([second], next_cursor=3),
                _bili_page([_bili_reply('300', '丙', '第三条')], is_end=True),
            ]
        )
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert status == OK and [r['评论内容'] for r in rows] == ['第一条', '第二条', '第三条']
        comment_calls = [u for u in driver.fetched if 'reply/main' in u]
        assert [u.split('next=')[1].split('&')[0] for u in comment_calls] == ['0', '2', '3']
        assert 'oid=113332711333508' in comment_calls[0] and 'mode=3' in comment_calls[0]

    def test_a_replaying_page_ends_the_walk_instead_of_looping(self):
        row = _bili_reply('100', '甲', '只有一条')
        session, driver = self._session(
            [
                _bili_view(),
                _bili_page([row], next_cursor=2),
                _bili_page([row], next_cursor=3),
                _bili_page([row], next_cursor=4),
            ]
        )
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert status == OK and len(rows) == 1
        assert len([u for u in driver.fetched if 'reply/main' in u]) == 2, 'must stop once nothing is new'

    def test_sub_replies_land_under_their_parent_with_continued_floors(self):
        thread = _bili_reply('100', '甲', '主题', rcount=11, subs=[('101', '乙', ' +1'), ('102', '丙', '同问')])
        session, _driver = self._session([_bili_view(), _bili_page([thread], is_end=True)])
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert status == OK
        assert [r['评论者'] for r in rows] == ['甲', '乙', '丙']
        assert [r['楼层'] for r in rows] == [1, 2, 3]
        assert rows[1]['父评论ID'] == '100' and rows[0]['父评论ID'] == ''
        # The unexpanded remainder stays visible: 11 replies exist, 2 were carried.
        assert rows[0]['子回复数'] == 11

    def test_closed_comment_section_is_an_answer_not_a_failure(self):
        session, driver = self._session([_bili_view(reply_total=0)])
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert rows == [] and status == OK
        assert not [u for u in driver.fetched if 'reply/main' in u], 'nothing to page once reply=0'

    def test_a_withdrawn_video_is_dead_and_a_refusal_is_blocked(self):
        session, _driver = self._session([_bili_view(code=-404)])
        assert session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0) == ([], DEAD)
        session, _driver = self._session([_bili_view(code=-412)])
        assert session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0) == ([], BLOCKED)

    def test_a_risk_control_page_never_reaches_the_api(self):
        driver = FakeDriver(body='当前请求存在异常，暂时限制访问', fetch_queue=[])
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert rows == [] and status == BLOCKED and driver.fetched == []

    def test_a_link_without_a_bv_id_is_dead(self):
        session, driver = self._session([_bili_view()])
        rows, status = session.crawl_bilibili('https://www.bilibili.com/', 0)
        assert rows == [] and status == DEAD and driver.fetched == []

    def test_limit_caps_the_table_not_the_pages(self):
        page1 = [_bili_reply(str(i), '甲', f'第{i}条') for i in range(20)]
        session, _driver = self._session(
            [_bili_view(), _bili_page(page1, next_cursor=2), _bili_page(page1[:19], next_cursor=3, is_end=True)]
        )
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 5)
        assert status == OK and len(rows) == 5

    def test_first_page_refusal_is_blocked_and_keeps_nothing(self):
        session, _driver = self._session([_bili_view(), json.dumps({'code': -509, 'data': None})])
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert rows == [] and status == BLOCKED

    def test_later_page_failure_keeps_the_earlier_rows(self):
        session, _driver = self._session(
            [_bili_view(), _bili_page([_bili_reply('100', '甲', '留着')], next_cursor=2), 'not json at all']
        )
        rows, status = session.crawl_bilibili('https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert status == OK and len(rows) == 1


class TestBilibiliParser:
    def test_endpoint_urls_carry_the_measured_shape(self):
        assert bilibili_view_js('BV1x') == 'https://api.bilibili.com/x/web-interface/view?bvid=BV1x'
        assert bilibili_reply_js(99, 2) == 'https://api.bilibili.com/x/v2/reply/main?type=1&oid=99&mode=3&next=2&ps=20'

    def test_column_names_stay_outside_the_dedupe_identity_fields(self):
        """'文章URL'/'评论者'/'评论内容' are deliberate near-misses of the ledger's
        field lists; a comment that borrowed '链接' would hash every row of one
        video to the same key and drop all but the first."""
        from services.run_store import _AUTHOR_FIELDS, _BODY_FIELDS, _URL_FIELDS

        rows = parse_bilibili_comments([_bili_reply('100', '甲', '好')], 'https://www.bilibili.com/video/BV1x/')
        for name in rows[0]:
            assert name not in _URL_FIELDS + _AUTHOR_FIELDS + _BODY_FIELDS, name

    def test_up_liked_badge_is_read_from_the_card_label(self):
        item = _bili_reply('100', '甲', '好')
        item['card_label'] = [{'text_content': 'UP主觉得很赞'}]
        assert parse_bilibili_comments([item], 'u')[0]['UP主态'] == '点赞'
        assert parse_bilibili_comments([_bili_reply('101', '乙', '一般')], 'u')[0]['UP主态'] == ''

    def test_malformed_items_are_skipped_not_raised(self):
        rows = parse_bilibili_comments(['not-a-dict', None, _bili_reply('100', '甲', '好')], 'u')
        assert [r['评论者'] for r in rows] == ['甲']

    def test_bilibili_links_route_to_the_bilibili_adapter(self):
        assert platform_for('https://www.bilibili.com/video/BV1atCRYsE7x/') == 'bilibili'
        assert platform_for('https://m.bilibili.com/video/BV1atCRYsE7x') == 'bilibili'


# ─── engine validation + row identity ───────────────────────────────────


class TestEngineAndIdentity:
    def test_engine_requires_urls(self):
        wf = {'nodes': [{'id': 'node-1', 'type': 'comment', 'params': {'urls': '   '}}], 'connections': []}
        errors = WorkflowEngine(wf).validate()
        assert any('node-1' in e for e in errors)
        wf['nodes'][0]['params']['urls'] = 'https://weibo.com/1/abc'
        assert WorkflowEngine(wf).validate() == []

    def test_comment_rows_keep_distinct_ledger_identity(self):
        # Rows of ONE article must not collapse onto one item_key — that would
        # silently drop every comment after the first into the dedupe ledger.
        from services.run_store import item_key

        rows = parse_weibo_comments(
            {'data': [{'user': {'screen_name': '甲'}, 'text': 'a'}, {'user': {'screen_name': '乙'}, 'text': 'b'}]},
            'https://weibo.com/1/abc',
        )
        assert item_key(rows[0]) != item_key(rows[1])
