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
from core.refs import platform_for

# Imported as a module, not as ``t``: this file names a text column 文本, and a bare ``t`` would
# collide with it in exactly the tests that compare console wording.
import i18n
from crawlers.commenting.protocol import BLOCKED, DEAD, OK
from crawlers.commenting.session import CommentSession
from crawlers.engine.wall import looks_blocked, looks_like_login_page
from crawlers.platforms.bilibili.comments import bilibili_reply_js, bilibili_view_js, parse_bilibili_comments
from crawlers.platforms.weibo import comments as weibo_comments
from crawlers.platforms.weibo.comments import parse_weibo_comments, weibo_bid
from crawlers.platforms.xiaohongshu import comments as xhs_comments
from engine.workflow import WorkflowEngine

pytestmark = pytest.mark.unit


class El:
    def __init__(self, text='', attrs=None, kids=None):
        self.text = text
        self._attrs = attrs or {}
        self._kids = kids or {}
        # Declared here so the click below is a write to a known field: tests read it with
        # ``getattr(el, 'clicked', False)``, and an attribute that only exists after a click is
        # how a double silently stops proving that anything was clicked.
        self.clicked = False

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
        # The page-attribute contract the walks stamp (``data-*-tried``) — modelled here so "clicked
        # once, never again" is what the test measures rather than what a fake silently forgets.
        if args and ('hasAttribute' in script or 'setAttribute' in script):
            match = re.search(r"(?:has|set)Attribute\('([^']+)'", script)
            name = match.group(1) if match else ''
            if 'setAttribute' in script:
                args[0]._attrs[name] = '1'
                return None
            return name in args[0]._attrs
        # The pump script also mentions ``.CommentContent`` (it looks for the box that holds them),
        # so the scroll ask is answered first or it would swallow a panel page.
        if 'scrollTop' in script:
            return 120
        if 'CommentContent' in script:
            if not self.panel_pages:
                return []
            # The last page repeats: a panel that stopped changing is what the product's own
            # dedupe and “更多” check have to notice, so the supply must not run out under them.
            return self.panel_pages.pop(0) if len(self.panel_pages) > 1 else self.panel_pages[0]

    def execute_async_script(self, script, *args):
        m = re.search(r'fetch\(\"(.*?)\"', script)
        self.fetched.append(m.group(1) if m else script[:40])
        if self.fetch_queue:
            return self.fetch_queue.pop(0)
        return 'ERR nothing queued'


# ─── pure helpers ───────────────────────────────────────────────────────


class TestWeiboWallIsNotADeadLink:
    """A dead session used to be filed as DEAD for every link, so the node settled DONE over an
    empty table with no cookie verdict and no 继续. The show endpoint answers a wall with HTML."""

    class Session:
        def __init__(self, responses, url='https://weibo.com/'):
            self.responses = list(responses)
            self.driver = type('D', (), {'current_url': url, 'title': ''})()
            self.unproven = []
            self.risk = False
            self.login = False
            self.logs = []

        def fetch_in_page(self, _url, timeout_ms=25000):
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        def nap(self, _seconds):
            pass

        def may_stop(self):
            return False

        def is_walled(self):
            return False

        def mark_risk_blocked(self):
            self.risk = True

        def mark_login_wall(self):
            self.login = True

        def mark_unproven(self, url):
            self.unproven.append(url)

        def log(self, message):
            self.logs.append(message)

    def test_a_passport_answer_is_blocked_not_dead(self):
        session = self.Session(
            ['<html><body>扫码登录 手机号登录</body></html>'],
            url='https://passport.weibo.com/sso/signin?cb=x',
        )
        rows, status = weibo_comments.walk(session, 'https://weibo.com/1763742695/RhYNar0R1', 50)
        assert (rows, status) == ([], BLOCKED)

    def test_a_risk_page_latches_risk_control(self):
        session = self.Session(['<html><body>安全验证 请完成验证</body></html>'])
        rows, status = weibo_comments.walk(session, 'https://weibo.com/1763742695/RhYNar0R1', 50)
        assert (rows, status) == ([], BLOCKED)
        assert session.risk is True, 'a risk page must not send the user to re-save a valid cookie'

    def test_a_page_request_that_dies_mid_thread_pins_the_cursor(self):
        show = json.dumps({'id': '5001', 'comments_count': 3})
        session = self.Session([show, RuntimeError('connection reset')])
        rows, status = weibo_comments.walk(session, 'https://weibo.com/1763742695/RhYNar0R1', 50)
        assert status == OK and rows == []
        assert session.unproven == ['https://weibo.com/1763742695/RhYNar0R1'], (
            'the line promises 可继续, so the cursor must stay on this link'
        )


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

    def test_an_emoji_only_comment_keeps_its_text(self):
        """U40: a comment that is nothing but emoji used to be stored as an empty row.

        The payload's ``text`` for such a row is a run of face images — ``<img alt="[可怜]" src="…png" />`` —
        and the adapter read *only* that field and stripped it, so the row kept its id, author, floor and
        timestamp while 评论内容 came back ``''``. Nothing downstream can see that: the table has the right
        number of rows, the summary agrees, and the analysis node gets a blank to weight. The plain text the
        user actually typed is sitting in the same object as ``text_raw`` (measured 17-of-17 on the saved
        payloads), which is what this platform's post rows have read all along.
        """
        payload = {
            'data': [
                {
                    'id': 1,
                    'floor_number': 4,
                    'rootid': 1,
                    'text': '<img alt="[可怜]" title="[可怜]" src="https://face.t.sinajs.cn/x.png" />'
                    '<img alt="[鼓掌]" title="[鼓掌]" src="https://face.t.sinajs.cn/y.png" />',
                    'text_raw': '[可怜][鼓掌]',
                    'user': {'screen_name': '甲', 'profile_url': '/u/1'},
                },
                {
                    'id': 2,
                    'floor_number': 5,
                    'rootid': 2,
                    'text': '普通一条',
                    'user': {'screen_name': '乙', 'profile_url': '/u/2'},
                },
            ]
        }
        rows = parse_weibo_comments(payload, 'https://weibo.com/1/a')
        assert [row['评论内容'] for row in rows] == ['[可怜][鼓掌]', '普通一条'], rows
        assert all(str(row['评论内容']).strip() for row in rows), rows

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
        rows, status = session.walk('weibo', 'https://weibo.com/1/RhYNar0R1', limit=0)
        assert status == OK and [r['评论内容'] for r in rows] == ['t1', 't2']
        assert any('max_id=99' in url for url in driver.fetched), 'must paginate with returned max_id'

    def test_limit_caps_rows(self):
        big = json.dumps({'data': [{'user': {}, 'text': f'c{i}'} for i in range(30)], 'max_id': 0})
        session, _ = self._session([json.dumps({'id': '555'}), big])
        rows, status = session.walk('weibo', 'https://weibo.com/1/RhYNar0R1', limit=4)
        assert status == OK and len(rows) == 4

    def test_unreadable_post_is_dead(self):
        session, _ = self._session(['ERR network', 'never'])
        rows, status = session.walk('weibo', 'https://weibo.com/1/Deleted01', limit=0)
        assert rows == [] and status == DEAD

    def test_zero_comment_post_is_ok_not_dead(self):
        session, _ = self._session([json.dumps({'id': '555'}), json.dumps({'data': [], 'max_id': 0})])
        rows, status = session.walk('weibo', 'https://weibo.com/1/RhYNar0R1', limit=0)
        assert rows == [] and status == OK, 'an article without comments is success with nothing, not an error'

    def test_bidless_url_is_dead(self):
        session, _ = self._session([])
        rows, status = session.walk('weibo', 'https://weibo.com/', limit=0)
        assert rows == [] and status == DEAD

    def test_the_pages_own_number_names_a_shortfall(self):
        """22 of 30 must not read like a complete thread.

        Measured 2026-09-28 on a live post: the search card, ``statuses/show.comments_count`` and the
        page's ``total_number`` all said 30, the cursor walk returned 22, and the eight missing floors
        were its nested replies. The walk ended on ``max_id=0`` — a clean exhaustion — so only the
        denominator can tell “这些就是全部” from “还差 8 条”, and the user must not have to notice.
        """
        said = []
        page1 = json.dumps({'data': [{'id': f'p1-{i}', 'text': 'x'} for i in range(20)], 'max_id': 99})
        page2 = json.dumps({'data': [{'id': f'p2-{i}', 'text': 'y'} for i in range(2)], 'max_id': 0})
        driver = FakeDriver(
            fetch_queue=[json.dumps({'id': '555', 'comments_count': 30}), page1, page2], start_url='https://weibo.com/'
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, status = session.walk('weibo', 'https://weibo.com/1/RhYNar0R1', limit=0)
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
        rows, status = session.walk('weibo', 'https://weibo.com/1/RhYNar0R1', limit=0)
        assert status == OK and len(rows) == 1, rows
        assert i18n.t('comment.weiboReplay', page=3, rows=1) in said, said
        # The shortfall line is about the SITE, so it stays quiet when our own exit ended the walk.
        assert not [line for line in said if 'weiboShort' in line or '写着' in line], said

    def test_a_limit_crossed_on_the_last_page_does_not_blame_the_thread(self):
        """U41, caught by the live D5 cell: the same page can cross the limit *and* end the cursor.

        评论上限 2 on a thread that reports 3 comments and hands all 3 over on its first (and only) page:
        the loop breaks on ``max_id == 0`` before it ever reaches the limit branch, so ``ended`` stays
        ``'cursor'`` — and the old comparison was made against the **truncated** table, which produced
        “站点写着 3 条，本表只有 2 条 —— 差额是楼中楼”. That sentence is about the site, printed because the
        user typed a smaller number, which is the exact opposite of the branch above it. The measurement is
        against what the walk *received*; if that already equals the thread's number, nothing is missing.
        """
        said = []
        page = json.dumps({'data': [{'id': f'c{i}', 'text': 'x'} for i in range(3)], 'max_id': 0})
        driver = FakeDriver(
            fetch_queue=[json.dumps({'id': '555', 'comments_count': 3}), page], start_url='https://weibo.com/'
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, status = session.walk('weibo', 'https://weibo.com/1/RhYNar0R1', limit=2)
        assert status == OK and len(rows) == 2, rows
        assert said == [], f'the ask was 2 and the site sent all 3 it has: {said}'

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
        rows, status = session.walk('weibo', 'https://weibo.com/1/RhYNar0R1', limit=0)
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
        rows, _ = session.walk('weibo', 'https://weibo.com/1/RhYNar0R1', limit=8)
        assert len(rows) == 8, rows
        assert said == [], f'the user set the number; nothing about the thread is missing: {said}'


# ─── xiaohongshu adapter (DOM) ──────────────────────────────────────────

#: A note link the walk files rows under (the id is what the walk compares against the browser).
XHS_NOTE = 'https://www.xiaohongshu.com/explore/6a9c3d18000000002502e846'


def _xhs_comment(cid, author, body, *, date='09-06', region='四川', likes='赞', replies='1'):
    """One comment as the measured panel read reports it (``PANEL_JS``'s own shape)."""
    return {
        'id': f'comment-{cid}',
        'author': author,
        'href': f'/user/profile/{author}?channel_type=web_note_detail_r10&xsec_token=TOKEN{author}%3D',
        'body': body,
        'date': date,
        'region': region,
        'likes': likes,
        'replies': replies,
    }


class _XhsPanel:
    """The measured 小红书 comment panel as data: parents, their replies, the 展开 openers.

    Measured shape (2026-11-10, logged-in profile): a top-level comment mounts ONE reply by default,
    the rest sit behind a ``.show-more`` reading ``展开 N 条回复``, and **each click pages out one more
    batch** — after it the same control reads ``展开更多回复``. The site's own ``共 N 条评论`` counts
    parents AND replies. All of that is modelled here so the Python half — attribution, floors, the
    paging expander, dedupe and the shortfall — is what the unit tier actually tests.
    """

    def __init__(
        self,
        parents=None,
        *,
        total='',
        pending=None,
        refuse_expand=False,
        batch=1,
        stuck=False,
        ended=False,
        login_gate=False,
    ):
        # each parent: {'own': card, 'subs': [card], 'hidden': [card]}
        self.parents = list(parents or [])
        self.total = total
        self.pending = list(pending or [])
        self.refuse_expand = refuse_expand
        self.batch = batch
        self.stuck = stuck
        #: The site's own end marker at the bottom of the panel (measured: `- THE END -`).
        self.ended = ended
        #: The site's own "登录查看全部评论内容" element (measured for an anonymous session).
        self.login_gate = login_gate
        self.revealed: set = set()
        self.mounted = True

    def opener_text(self, parent) -> str:
        if parent['own']['id'] in self.revealed:
            return '展开更多回复'
        return f'展开 {min(self.batch, len(parent["hidden"]))} 条回复'

    def snapshot(self) -> dict:
        if not self.mounted:
            return {'mounted': False}
        cards = [
            {'own': parent['own'], 'subs': list(parent['subs']), 'has_replies': bool(parent['subs'])}
            for parent in self.parents
        ]
        openers = [
            {'card': parent['own']['id'], 'text': self.opener_text(parent)}
            for parent in self.parents
            if parent.get('hidden')
        ]
        return {
            'mounted': True,
            'total': self.total,
            'login_modal': False,
            'login_gate': self.login_gate,
            'ended': self.ended,
            'cards': cards,
            'openers': openers,
        }

    def key(self) -> str:
        if not self.mounted:
            return ''
        ids = []
        for parent in self.parents:
            ids.append(parent['own']['id'])
            ids.extend(sub['id'] for sub in parent['subs'])
        return '|'.join(ids)

    def expand(self, card_id: str) -> bool:
        for parent in self.parents:
            if parent['own']['id'] != card_id:
                continue
            if self.stuck or not parent.get('hidden'):
                return False
            take = parent['hidden'][: self.batch]
            parent['subs'].extend(take)
            parent['hidden'] = parent['hidden'][len(take) :]
            self.revealed.add(card_id)
            return True
        return False

    def scroll(self) -> None:
        """One screen further down the panel: the next parent mounts (measured: it grows, never recycles)."""
        if self.pending:
            self.parents.append(self.pending.pop(0))


class _XhsOpener:
    """One ``.show-more`` element: its text, and the click the walk performs on it."""

    def __init__(self, driver, parent):
        self._driver = driver
        self._parent = parent
        self.text = driver.panel.opener_text(parent)

    def click(self):
        self._driver.clicks.append(self._parent['own']['id'])
        if self._driver.panel.refuse_expand:
            # Measured: a click the site refuses for lack of a session pops the login dialog and
            # mounts nothing. That is the refusal this walk has to name, not click through.
            self._driver.login_modal = True
            return
        self._driver.panel.expand(self._parent['own']['id'])


class _XhsDriver:
    """Fake driver for the 小红书 walk: the page-side reads answer the panel model."""

    def __init__(self, panel, *, body='正常笔记', url=XHS_NOTE, lands_on='', owner=None):
        self.panel = panel
        self.body = body
        self.current_url = url
        self.title = ''
        self.owner = owner
        self._lands_on = lands_on
        self.scripts = []
        self.clicks = []
        self.gets = []
        self.login_modal = False

    def get(self, url):
        self.gets.append(url)
        self.current_url = self._lands_on or url

    def find_element(self, by, selector):
        return El(self.body)

    def find_elements(self, by, selector):
        if selector == '.comments-container .reply-container .show-more':
            return [_XhsOpener(self, parent) for parent in self.panel.parents if parent.get('hidden')]
        return []

    def execute_script(self, script, *args):
        self.scripts.append(script)
        if script == xhs_comments.PANEL_JS:
            return self.panel.snapshot()
        if script == xhs_comments.PANEL_KEY_JS:
            return self.panel.key()
        if script == xhs_comments.LOGIN_CLOSE_JS:
            self.login_modal = False
        if 'login-modal' in script and 'getBoundingClientRect' in script:
            return self.login_modal
        if 'scrollHeight' in script:
            self.panel.scroll()
        return None


class _FakeActionChains:
    """Stand-in for selenium ActionChains: ``perform`` runs the queued click on the element."""

    def __init__(self, driver):
        self._el = None

    def move_to_element(self, element):
        self._el = element
        return self

    def pause(self, *args):
        return self

    def click(self):
        if self._el is not None:
            self._el.click()
        return self

    def perform(self):
        pass


@pytest.fixture
def xhs_chains(monkeypatch):
    """The walk clicks natively (douyin's measurement); a unit test performs that click itself.

    Pacing sleeps are cancelled here too: the walk pays a page-arrival settle and an expand
    settle, and a unit test must not spend them in real seconds.
    """
    monkeypatch.setattr('crawlers.platforms.xiaohongshu.comments.ActionChains', _FakeActionChains)
    monkeypatch.setattr('crawlers.engine.pacing.time.sleep', lambda _seconds: None)


class _XhsOwner:
    """The browser's owning crawler, as a walk may accuse it.

    The comment engine reads ``login_wall`` / ``risk_blocked`` and ``skipped_targets`` BY
    ATTRIBUTE, so the unit walk needs the same surface a real ``Crawler`` carries.
    """

    def __init__(self, driver):
        self.driver = driver
        self.login_wall = False
        self.risk_blocked = False
        self.skipped_targets: list = []
        self._is_walled = lambda: False


def _xhs_walk(panel, *, limit=0, log=None, abort=None, **kwargs):
    owner = _XhsOwner(None)
    driver = _XhsDriver(panel, owner=owner, **kwargs)
    owner.driver = driver
    session = CommentSession(
        driver, log=log or (lambda message: None), nap=lambda seconds: None, abort=abort, owner=owner
    )
    return session.walk('xiaohongshu', XHS_NOTE, limit), driver


class TestXhsAdapter:
    def test_the_walk_asks_for_the_note_with_the_sites_own_feed_source(self, xhs_chains):
        """A note URL with no ``xsec_source`` is opened as ``?xsec_source=pc_feed``.

        That is the spelling the site's own 复制链接 hands out for a web-feed note; asking
        without it is what leaves the browser on the feed with no note and no panel.
        """
        panel = _XhsPanel([{'own': _xhs_comment('a1', '甲', '评论'), 'subs': [], 'hidden': []}], total='共 1 条评论')
        (rows, status), driver = _xhs_walk(panel)
        assert status == OK and len(rows) == 1
        assert driver.gets == [XHS_NOTE + '?xsec_source=pc_feed'], driver.gets

    def test_a_source_the_link_already_names_is_kept(self, xhs_chains):
        panel = _XhsPanel([{'own': _xhs_comment('a1', '甲', '评论'), 'subs': [], 'hidden': []}], total='共 1 条评论')
        link = XHS_NOTE + '?xsec_token=TOK&xsec_source=pc_search'
        session = CommentSession(
            _XhsDriver(panel, url=link),
            log=lambda message: None,
            nap=lambda seconds: None,
        )
        session.walk('xiaohongshu', link, 0)
        assert session.driver.gets == [link], 'the site issued pc_search for this link; keep it'

    def test_a_reply_is_filed_under_its_parent_with_a_continuous_floor(self, xhs_chains):
        """The measured shape: replies are siblings of their parent's card, one per parent by default.

        A flat ``.comment-item`` read collected them but could not say whose they were — that is what
        ``父楼层`` exists to fix. ``楼层`` numbers TOP-LEVEL comments only (the site's own notion of a
        floor): a reply's own 楼层 stays blank, so no two rows share a number and ``reply_graph``
        gets its parent map from the parents and its edges from the replies.
        """
        panel = _XhsPanel(
            [
                {
                    'own': _xhs_comment('a1', '薄荷', '祝福', date='09-06', region='四川', likes='2'),
                    'subs': [_xhs_comment('a2', '作者', '谢谢！嘿嘿', date='09-07', region='浙江')],
                    'hidden': [],
                },
                {
                    'own': _xhs_comment('b1', '今天吃什么', '是的呀，这才是正确的恋爱观', date='09-06', region='山东'),
                    'subs': [
                        _xhs_comment('b2', '作者', '哈哈哈恋爱嘛 开心就行', date='09-07', region='浙江'),
                        _xhs_comment('b3', '作者', '哈哈哈恋爱嘛 开心就行', date='09-07', region='浙江'),
                    ],
                    'hidden': [],
                },
            ],
            total='共 5 条评论',
        )
        (rows, status), driver = _xhs_walk(panel)
        assert status == OK
        assert [row['楼层'] for row in rows] == [1, '', 2, '', '']
        assert [row['父楼层'] for row in rows] == ['', 1, '', 2, 2]
        assert [row['评论ID'] for row in rows] == ['a1', 'a2', 'b1', 'b2', 'b3']
        assert rows[0]['子回复数'] == 1 and rows[1]['子回复数'] == 0
        assert rows[2]['子回复数'] == 2
        assert rows[0]['评论地区'] == '四川' and rows[1]['评论地区'] == '浙江'
        # The author link's xsec_token changes on every visit: the column keeps the path, not the token.
        assert rows[0]['评论者主页'] == 'https://www.xiaohongshu.com/user/profile/薄荷'
        # Two identical bodies from one author are two comments — the old (author, body) key kept one.
        assert [row['评论内容'] for row in rows[3:]] == ['哈哈哈恋爱嘛 开心就行'] * 2
        # The site's own total matches the table, so nothing is owed and nothing is said.
        assert driver.clicks == []

    def test_the_expander_pages_a_thread_until_the_site_says_no_more(self, xhs_chains):
        """Measured 2026-11-10: one click reveals ONE BATCH (40 new cards over 10 threads), and the
        same control then reads ``展开更多回复`` — 9 of those controls were never clicked by the old walk."""
        panel = _XhsPanel(
            [
                {
                    'own': _xhs_comment('a1', '底单', '上周新课老师说要面对面建群', replies='3'),
                    'subs': [_xhs_comment('a2', '猫猫咪喵喵', '好了现在你是老师了')],
                    'hidden': [_xhs_comment('a3', '甲', '第二条回复'), _xhs_comment('a4', '乙', '第三条回复')],
                }
            ],
            total='共 4 条评论',
            batch=1,
        )
        (rows, status), driver = _xhs_walk(panel)
        assert status == OK
        assert driver.clicks == ['comment-a1', 'comment-a1'], 'one batch per click, until the thread is done'
        assert [row['评论内容'] for row in rows] == [
            '上周新课老师说要面对面建群',
            '好了现在你是老师了',
            '第二条回复',
            '第三条回复',
        ]
        assert [row['父楼层'] for row in rows] == ['', 1, 1, 1]
        assert rows[0]['子回复数'] == 3, '子回复数 is what the table actually holds'
        assert rows[0]['楼层'] == 1 and rows[1]['楼层'] == '', 'a reply is placed by 父楼层, not a floor of its own'

    def test_an_opener_that_only_says_more_is_still_clicked(self, xhs_chains):
        """``展开更多回复`` is the site saying another page exists; ``.reply .count`` may be a rounded
        ``10+``, so the label — not the arithmetic alone — decides that there is more to fetch."""
        panel = _XhsPanel(
            [
                {
                    'own': _xhs_comment('a1', '甲', '主评论', replies='4'),
                    'subs': [_xhs_comment('a2', '乙', '首条')],
                    'hidden': [
                        _xhs_comment('a3', '丙', '第二批一'),
                        _xhs_comment('a4', '丁', '第二批二'),
                        _xhs_comment('a5', '戊', '第三批'),
                    ],
                }
            ],
            total='共 5 条评论',
            batch=2,
        )
        (rows, status), driver = _xhs_walk(panel)
        assert status == OK
        assert len(rows) == 5, f'the whole thread, including the page behind 展开更多回复: {len(rows)}'
        assert driver.clicks == ['comment-a1', 'comment-a1'], 'two batches, two clicks'

    def test_a_thread_whose_opener_never_reveals_anything_is_retired(self, xhs_chains):
        """A deleted/hidden reply thread only keeps its control: tried twice (a batch can land late),
        then retired by the panel's own evidence — never re-clicked in a loop, and the gap is named."""
        said = []
        panel = _XhsPanel(
            [
                {
                    'own': _xhs_comment('a1', '甲', '主评论', replies='2'),
                    'subs': [_xhs_comment('a2', '乙', '首条回复')],
                    'hidden': [_xhs_comment('a3', '丙', '永远展不开的回复')],
                }
            ],
            total='共 3 条评论',
            stuck=True,
        )
        (rows, status), driver = _xhs_walk(panel, log=said.append)
        assert status == OK and len(rows) == 2
        # One attempt while the panel was still feeding, then two after it went quiet — and it STOPS.
        # The contract is "bounded and retired", never a fixed number of attempts: the count is a
        # consequence of the panel's own state.
        assert 2 <= driver.clicks.count('comment-a1') <= 3, driver.clicks
        assert (
            i18n.t(
                'comment.xhsNested',
                url=XHS_NOTE,
                declared=3,
                rows=2,
                nested=1,
                reason=i18n.t('crawl.stopReason.no_new'),
            )
            in said
        ), said

    def test_the_sites_own_end_marker_ends_the_walk(self, xhs_chains):
        """`- THE END -` is the only exit that may be quoted as "this note has no more comments"."""
        said = []
        panel = _XhsPanel(
            [{'own': _xhs_comment('a1', '甲', '最后一条', replies='0'), 'subs': [], 'hidden': []}],
            total='共 1 条评论',
            ended=True,
        )
        (rows, status), _driver = _xhs_walk(panel, log=said.append)
        assert status == OK and len(rows) == 1
        assert said == [], 'one comment, one row, and the site said so — nothing to report'

    def test_a_thread_the_site_already_shows_whole_is_not_clicked(self, xhs_chains):
        """When the mounted replies already meet the site's own count and it is not asking for more,
        the remaining control is not ours to click — that spends the account for nothing."""
        panel = _XhsPanel(
            [
                {
                    'own': _xhs_comment('a1', '甲', '主评论', replies='1'),
                    'subs': [_xhs_comment('a2', '乙', '唯一的回复')],
                    'hidden': [_xhs_comment('a3', '丙', '站点已经数过的那条')],
                }
            ],
            total='共 2 条评论',
        )
        (rows, status), driver = _xhs_walk(panel)
        assert status == OK and len(rows) == 2
        assert driver.clicks == [], 'the site says one reply; one reply is mounted'

    def test_a_refused_expand_is_blocked_and_keeps_every_row_read(self, xhs_chains):
        """Measured: a click without the session the site wants answers with ``.login-modal``.

        That is a refusal, not a slow render and not "this thread has no more replies": the walk
        now ends BLOCKED (rows kept), so the node fails by name, the cursor stays on this link and
        继续 re-walks it after a login instead of stepping over an "ok, 0 new" table.
        """
        said = []
        panel = _XhsPanel(
            [
                {
                    'own': _xhs_comment('a1', '甲', '主评论', replies='2'),
                    'subs': [_xhs_comment('a2', '乙', '首条回复')],
                    'hidden': [_xhs_comment('a3', '丙', '没能展开的回复')],
                }
            ],
            total='共 9 条评论',
            refuse_expand=True,
        )
        (rows, status), driver = _xhs_walk(panel, log=said.append)
        assert status == BLOCKED
        assert driver.clicks == ['comment-a1'], 'tried once, then never again'
        assert rows and rows[0]['评论内容'] == '主评论', 'the parent rows already read must survive'
        assert rows[0]['子回复数'] == 1, 'the reply row is what the table holds, not the site’s count'
        assert i18n.t('comment.xhsLoginGate', url=XHS_NOTE, rows=2) in said, said
        assert driver.owner.login_wall is False
        assert driver.owner.risk_blocked is False, 'a login dialog is not 风控'

    def test_a_login_gated_panel_is_blocked_and_latches_the_wall(self, xhs_chains):
        """The panel's own “登录查看全部评论内容” element is a wall, not a note with no comments."""
        panel = _XhsPanel([], total='共 9 条评论', login_gate=True)
        (rows, status), driver = _xhs_walk(panel)
        assert rows == [] and status == BLOCKED
        assert driver.owner.login_wall is True
        assert driver.owner.skipped_targets == [], 'a wall uses the node’s own verdict, not the cursor pin'

    def test_the_walk_ends_on_the_panels_own_evidence_not_a_round_budget(self, xhs_chains):
        """A fixed round count made 采不满 read as 这条笔记就这么多评论; the panel itself ends the walk."""
        whole = [
            {'own': _xhs_comment(f'c{index}', f'u{index}', f'第 {index} 条'), 'subs': [], 'hidden': []}
            for index in range(20)
        ]
        panel = _XhsPanel(whole[:1], total='共 20 条评论', pending=whole[1:])
        (rows, status), _driver = _xhs_walk(panel)
        assert status == OK
        assert len(rows) == 20, f'a growing panel is walked to its end, not to a screen count: {len(rows)}'
        assert [row['楼层'] for row in rows] == list(range(1, 21)), 'only top-level comments are floors'

    def test_a_short_table_is_named_against_the_sites_own_count(self, xhs_chains):
        said = []
        panel = _XhsPanel(
            [{'own': _xhs_comment('a1', '甲', '唯一的评论'), 'subs': [], 'hidden': []}],
            total='共 20 条评论',
        )
        (rows, status), driver = _xhs_walk(panel, log=said.append)
        assert status == OK and len(rows) == 1
        assert any('comment.xhsShort' in line or '写着 20 条' in line for line in said), said
        assert driver.owner.skipped_targets == [XHS_NOTE], 'a short table without THE END pins the cursor'

    def test_the_sites_end_marker_licenses_a_short_table(self, xhs_chains):
        """Measured on the 357-comment note: 338 rows and the site printed `- THE END -`. That is the
        site's own finish line, so the shortfall is named but the cursor is NOT pinned (failing it
        would make every 继续 red for rows the site refuses to give)."""
        said = []
        panel = _XhsPanel(
            [{'own': _xhs_comment('a1', '甲', '最后一条'), 'subs': [], 'hidden': []}],
            total='共 20 条评论',
            ended=True,
        )
        (rows, status), driver = _xhs_walk(panel, log=said.append)
        assert status == OK and len(rows) == 1
        assert any('comment.xhsShort' in line or '写着 20 条' in line for line in said), said
        assert driver.owner.skipped_targets == [], 'THE END is the site saying it is finished'

    def test_the_users_own_limit_is_not_reported_as_a_shortfall(self, xhs_chains):
        """评论上限 1 on a 20-comment note is the ask, not the thread's absence."""
        said = []
        panel = _XhsPanel(
            [{'own': _xhs_comment('a1', '甲', '第一条'), 'subs': [], 'hidden': []}],
            total='共 20 条评论',
        )
        (rows, _status), _driver = _xhs_walk(panel, limit=1, log=said.append)
        assert len(rows) == 1
        assert said == [], f'the user set the number; nothing about the thread is missing: {said}'

    def test_login_wall_page_is_blocked(self, xhs_chains):
        panel = _XhsPanel([], total='')
        (rows, status), driver = _xhs_walk(panel, body='登录后查看更多内容 扫码登录')
        assert rows == [] and status == BLOCKED
        assert driver.owner.login_wall is True, 'the console must say re-save the cookie, not back off'

    def test_no_panel_is_not_proof_of_an_empty_thread(self, xhs_chains):
        said = []
        panel = _XhsPanel([])
        panel.mounted = False
        (rows, status), driver = _xhs_walk(panel, log=said.append)
        assert rows == [] and status == OK
        assert i18n.t('comment.xhsNoPanel', url=XHS_NOTE) in said, said
        assert driver.owner.skipped_targets == [XHS_NOTE], (
            'a page that never rendered left the cursor on this link for 继续'
        )

    def test_a_link_that_opens_another_note_is_dead_not_the_users_cookie(self, xhs_chains):
        said = []
        panel = _XhsPanel(
            [{'own': _xhs_comment('a1', '甲', '别人的评论'), 'subs': [], 'hidden': []}], total='共 3 条评论'
        )
        (rows, status), _driver = _xhs_walk(
            panel, log=said.append, lands_on='https://www.xiaohongshu.com/explore/6ad2076d000000000a01f058'
        )
        assert rows == [] and status == DEAD
        assert i18n.t('comment.xhsGone', url=XHS_NOTE, shown='6ad2076d000000000a01f058') in said, said

    def test_a_link_sent_back_to_the_feed_is_named_dead_not_walked_as_an_empty_note(self, xhs_chains):
        """The “stuck on the homepage” shape: an aged-out xsec_token lands on /explore.

        The old walk read the missing note id as "no comment panel", returned ok and moved on
        to the next link — the browser never opened a note, and nothing said why. It is a fact
        about THIS link (the site never served the note), so it is DEAD and named.
        """
        said = []
        panel = _XhsPanel([])
        panel.mounted = False
        (rows, status), driver = _xhs_walk(
            panel, log=said.append, lands_on='https://www.xiaohongshu.com/explore?source=web_explore_feed'
        )
        assert rows == [] and status == DEAD
        assert (
            i18n.t(
                'comment.xhsRedirected',
                url=XHS_NOTE,
                landed='https://www.xiaohongshu.com/explore?source=web_explore_feed',
            )
            in said
        ), said
        assert driver.owner.login_wall is False and driver.owner.risk_blocked is False, (
            'a dead link must not accuse the session'
        )
        assert driver.clicks == [], 'nothing is scrolled or expanded on a page that is not the note'

    def test_a_short_link_still_resolving_is_retryable_not_dead(self, xhs_chains):
        """Only a landing ON xiaohongshu.com without a note id convicts the link.

        A share link (``xhslink.com``) or a browser still on its own page has not landed yet;
        the walk leaves the cursor on it so 继续 re-walks it instead of filing it dead.
        """
        said = []
        panel = _XhsPanel([])
        panel.mounted = False
        (rows, status), driver = _xhs_walk(panel, log=said.append, lands_on='https://xhslink.com/aBcDeF')
        assert rows == [] and status == OK
        assert i18n.t('comment.xhsNoPanel', url=XHS_NOTE) in said, said
        assert driver.owner.skipped_targets == [XHS_NOTE]

    def test_a_stop_ends_the_walk_without_claiming_the_thread_ran_out(self, xhs_chains):
        said = []
        whole = [
            {'own': _xhs_comment(f'c{index}', f'u{index}', f'第 {index} 条'), 'subs': [], 'hidden': []}
            for index in range(5)
        ]
        panel = _XhsPanel(whole[:1], total='共 5 条评论', pending=whole[1:])
        (rows, status), driver = _xhs_walk(panel, log=said.append, abort=lambda: True)
        assert status == OK and len(rows) == 1, 'one round read, then 停止'
        # The shortfall sentence may appear, but it must attribute the ending to the user, not the site.
        assert all(
            i18n.t('crawl.stopReason.stopped') in line for line in said if 'xhsShort' in line or '写着' in line
        ), said
        assert driver.owner.skipped_targets == [XHS_NOTE], '停止 is not the site saying the thread ran out'


# ─── zhihu adapter (DOM, panels behind buttons) ─────────────────────────


def _zh_row(author, text, href='https://www.zhihu.com/people/x', when='3 天前', cid=''):
    """One comment as the in-page panel read reports it.

    The fake answers the page-side script with its own output format, so these tests cover the
    Python half — row building, dedupe, the two console lines. The climb itself (stop at the
    ancestor that still holds exactly one ``.CommentContent``) is a page contract, measured by
    ``backend/test_zhihu_comment_dom.py`` and re-measured by the live tier's D group.
    """
    return {'author': author, 'href': href, 'text': text, 'time': when, 'id': cid}


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
        rows, status = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
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
        rows, _ = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
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
        rows, _ = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert len(rows) == 2, 'an anonymous comment is still a comment the user asked for'
        assert rows[0]['评论者'] == ''
        assert i18n.t('comment.zhihuNoAuthor', n=1, total=2) in said

    def test_the_panel_is_pumped_and_the_walk_follows_it(self):
        """The regression the user named: 知乎 has no “更多” button, so button-hunting stops at 12.

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
        rows, _ = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert len(rows) == 12, f'the walk stopped while the panel was still filling: {len(rows)}'
        assert any('scrollTop' in script for script in driver.scripts), 'the container must be scrolled'

    def test_nested_replies_are_opened_and_keep_their_parent(self):
        """A reply does not exist in the DOM until “展开其中 N 条回复” is clicked. Not clicking it
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
        rows, _ = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert getattr(opener, 'clicked', False), 'the reply thread was never opened'
        assert [row['父楼层'] for row in rows] == ['', 1], rows

    def test_a_shortfall_against_the_pages_own_number_is_said(self):
        """The button says 261. If the walk files 3, the console must hold both numbers — “面板就这些”
        and “我们只走到这些” cannot be allowed to look alike in the export."""
        said = []
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('261 条评论')], 'button, a': []},
            panel_pages=[[_zh_row('甲', '唯一一条')]],
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, _ = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert len(rows) == 1
        assert i18n.t('comment.zhihuPanelShort', declared=261, rows=1) in said

    def test_a_panel_that_never_settles_is_walked_until_it_does(self):
        """No round budget: a panel that keeps yielding new rows is drained to its own end.

        The crawler used to stop at ``PANEL_ROUNDS=60`` and name it ``comment.zhihuPanelCapped`` — a
        number WE chose ending a walk the site was still feeding (the douyin walk paid for the same
        lesson at 406 of 3388 rows). The only bounds left are the panel itself, 停止 and 评论上限.
        """
        said = []
        endless = [[_zh_row('甲', f'r{i}', when='')] for i in range(40)]
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('999 条评论')], 'button, a': []},
            panel_pages=endless,
        )
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, _ = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert len(rows) == 40, f'the panel itself ended the walk at {len(rows)} rows'
        assert not any('zhihuPanelCapped' in line or '轮次上限' in line for line in said), said
        assert i18n.t('comment.zhihuPanelShort', declared=999, rows=40) in said, said

    def test_blocked_page_reports_blocked(self):
        driver = FakeDriver(body='您当前请求存在异常，暂时限制本次访问。40362', pages={})
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert rows == [] and status == BLOCKED

    def test_answers_without_comment_buttons_are_ok_empty(self):
        driver = FakeDriver(body='正常', pages={'button': [El('关注')]})
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert rows == [] and status == OK

    def test_the_sites_comment_id_is_the_ledger_identity(self):
        """Two identical “谢谢” from one person are two comments when the site prints two ids.

        The content key (author, body, time) is the fallback for a panel that prints none; when an
        id IS printed, using the content key is what silently merged two real comments.
        """
        from services.runs.store.identity import item_key

        pair = [
            _zh_row('甲', '谢谢', cid='1050000000000000001'),
            _zh_row('甲', '谢谢', cid='1050000000000000002'),
        ]
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('2 条评论')], 'button, a': []},
            panel_pages=[pair],
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, _ = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert [row['评论ID'] for row in rows] == ['1050000000000000001', '1050000000000000002']
        assert item_key(rows[0]) != item_key(rows[1]), 'two site ids collapsed to one ledger key'

    def test_a_comment_without_a_site_id_keeps_a_blank_column_and_the_content_key(self):
        driver = FakeDriver(
            body='正常',
            pages={'button': [El('1 条评论')], 'button, a': []},
            panel_pages=[[_zh_row('甲', '没有 id 的一条')]],
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, _ = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 0)
        assert rows[0]['评论ID'] == '', 'an id the page never printed may not be invented'

    def test_limit_stops_panel_iteration(self):
        btns = [El('5 条评论'), El('6 条评论'), El('7 条评论')]
        driver = FakeDriver(
            body='正常',
            pages={'button': btns, 'button, a': []},
            panel_pages=[[_zh_row('甲', 'a'), _zh_row('乙', 'b')]],
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.walk('zhihu', 'https://www.zhihu.com/question/1/answer/2', 1)
        assert status == OK and len(rows) == 1


# ─── douyin row identity ────────────────────────────────────────────────


class TestDouyinCommentIds:
    """The panel read now carries each item's own id; the row and the ledger key use it."""

    def _fold(self, readings):
        from crawlers.platforms.douyin import comments as dy

        threads, reply_seen, seen = {}, set(), set()
        dy._absorb_threads(readings, threads, reply_seen, seen)
        return dy, threads

    def test_two_identical_bodies_are_two_comments_when_the_site_prints_two_ids(self):
        from services.runs.store.identity import item_key

        body = '甲\n谢谢\n1天前·北京\n0'
        _dy, threads = self._fold(
            [
                {'own': body, 'id': '7300000000000000001', 'replies': []},
                {'own': body, 'id': '7300000000000000002', 'replies': []},
            ]
        )
        assert len(threads) == 2, 'the content key merged two comments the site ids tell apart'
        rows, _ = _dy.parse_douyin_threads(threads, 'https://www.douyin.com/video/7000000000000000001')
        assert [row['评论ID'] for row in rows] == ['7300000000000000001', '7300000000000000002']
        assert item_key(rows[0]) != item_key(rows[1])

    def test_a_reply_takes_its_own_id_from_the_nested_item(self):
        _dy, threads = self._fold(
            [
                {
                    'own': '甲\n顶层\n1天前·北京\n3',
                    'id': '7300000000000000001',
                    'replies': [{'text': '乙\n子回复\n1天前·上海\n1', 'id': '7300000000000000002'}],
                }
            ]
        )
        rows, _ = _dy.parse_douyin_threads(threads, 'https://www.douyin.com/video/7000000000000000001')
        assert [row['评论ID'] for row in rows] == ['7300000000000000001', '7300000000000000002']
        assert rows[1]['父楼层'] == 1

    def test_an_unidentified_reading_keeps_the_content_key(self):
        _dy, threads = self._fold([{'own': '甲\n没有 id\n1天前·北京\n0', 'replies': []}])
        rows, _ = _dy.parse_douyin_threads(threads, 'https://www.douyin.com/video/7000000000000000001')
        assert rows[0]['评论ID'] == ''


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
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
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
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert status == OK and len(rows) == 1
        assert len([u for u in driver.fetched if 'reply/main' in u]) == 2, 'must stop once nothing is new'

    def test_sub_replies_land_under_their_parent_with_continued_floors(self):
        thread = _bili_reply('100', '甲', '主题', rcount=11, subs=[('101', '乙', ' +1'), ('102', '丙', '同问')])
        session, _driver = self._session([_bili_view(), _bili_page([thread], is_end=True)])
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert status == OK
        assert [r['评论者'] for r in rows] == ['甲', '乙', '丙']
        assert [r['楼层'] for r in rows] == [1, 2, 3]
        assert rows[1]['父评论ID'] == '100' and rows[0]['父评论ID'] == ''
        # The unexpanded remainder stays visible: 11 replies exist, 2 were carried.
        assert rows[0]['子回复数'] == 11

    def test_closed_comment_section_is_an_answer_not_a_failure(self):
        session, driver = self._session([_bili_view(reply_total=0)])
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert rows == [] and status == OK
        assert not [u for u in driver.fetched if 'reply/main' in u], 'nothing to page once reply=0'

    def test_a_clean_end_under_the_denominator_is_named_short(self):
        """U54 (live H1, 2026-09-29): a thread that ENDS far under the site's own count must NAME the gap.

        A 2194-comment video whose ``reply/main`` pages stop at 7 with ``is_end`` read back as a clean end —
        the old code returned those 7 with status OK and NO line, so table+summary+completion all agreed on a
        short count the site never actually said (the silent-under-collect). Now the walk compares what it got
        against the ``stat.reply`` denominator it already read and logs ``comment.biliShort``. Two-sided by
        construction: a thread that genuinely holds what it reports (next test) says nothing.
        """
        url = 'https://www.bilibili.com/video/BV1atCRYsE7x/'
        said = []
        seven = [_bili_reply(str(i)) for i in range(7)]
        driver = FakeDriver(fetch_queue=[_bili_view(reply_total=2194), _bili_page(seven, is_end=True)])
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, status = session.walk('bilibili', url, limit=50)
        assert status == OK and len(rows) == 7, (rows, status)
        assert i18n.t('comment.biliShort', url=url, rows=7, declared=2194) in said, (
            f'a 7-of-2194 clean end must name the gap, not complete silently: {said!r}'
        )

    def test_a_thread_that_holds_what_it_reports_says_nothing(self):
        """The other half of the U54 line: rows == denominator is a real end, so NO shortfall is claimed.

        Without the ``len(rows) < declared`` guard this line would fire on every short-but-honest thread and
        blame the user's own small number — the weibo “收到的等于站点报的数就不说” rule.
        """
        url = 'https://www.bilibili.com/video/BV1atCRYsE7x/'
        said = []
        seven = [_bili_reply(str(i)) for i in range(7)]
        driver = FakeDriver(fetch_queue=[_bili_view(reply_total=7), _bili_page(seven, is_end=True)])
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, status = session.walk('bilibili', url, limit=50)
        assert status == OK and len(rows) == 7
        assert i18n.t('comment.biliShort', url=url, rows=7, declared=7) not in said, (
            f'a 7-comment thread that returned all 7 must not be called short: {said!r}'
        )

    def test_a_view_code_is_classified_by_who_it_blames(self):
        """A bad ``view`` code is DEAD (this link); a risk or unrecognised code is BLOCKED (this session).

        §6 U55 (measured 2026-09-29): a nonexistent BV answers ``code=-400``, and the old default sent every
        non-CODE_GONE code to BLOCKED, latching a session-wide cookieExpired beside a video whose comments had
        just crawled — the douyin U47 shape. The matrix, each code at the outcome it earns: video answers
        (gone -404, bad BV -400, hidden 62002) and a transport timeout (no JSON at all, ``None``) are DEAD for
        the link; session answers (intercepted -412, risk -352, need-login -101) and an unrecognised code
        (-799, a measured rate limit outside the video allowlist) are BLOCKED — the latter named by code, so an
        unknown refusal backs off and stays diagnosable rather than being guessed into "this video is fine".
        """
        for code, expected in (
            (-404, DEAD),
            (-400, DEAD),
            (62002, DEAD),
            (None, DEAD),
            (-412, BLOCKED),
            (-352, BLOCKED),
            (-101, BLOCKED),
            (-799, BLOCKED),
        ):
            session, _driver = self._session([_bili_view(code=code)])
            assert session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0) == ([], expected), (
                f'view code {code} must be {expected}'
            )

    def test_a_risk_page_mid_thread_keeps_rows_and_backs_off(self):
        """A throttled thread is NAMED-BLOCKED (back-off + 继续), never a silent OK and never a full.

        U54's license: on a hot account the reply cursor is cut short. The old code ``break``-ed on a failed
        page and returned the partial with status **OK**, so a 9-row read of a 2194-comment video "completed"
        silently. Now a risk page stops the walk but keeps what was read and reports **BLOCKED** — the node
        latches cookieExpired, the run stops (it does not press the next link against a flagged account), and
        the position is recorded so 继续 resumes; the ``biliBadAnswer`` line names the code.
        """
        row = _bili_reply('100', '甲', '留着')
        session, _driver = self._session([_bili_view(), _bili_page([row], next_cursor=2), _bili_page([], code=-352)])
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert status == BLOCKED, 'a risk page mid-thread must back off, not report a finished crawl'
        assert [r['评论内容'] for r in rows] == ['留着'], 'what was collected before the wall is kept'

    def test_a_first_reply_page_timeout_is_dead_not_an_empty_thread(self):
        """A slow FIRST page (never answered as JSON) is DEAD for the link, not a silent 0-comment OK.

        ``stat.reply`` said there are comments; if the first ``reply/main`` request only yields a transport
        failure, reading that back as an empty-but-finished thread is the same silent-under-collect. It must
        be per-link DEAD (which never convicts the session), not OK.
        """
        session, _driver = self._session([_bili_view(reply_total=40), 'not json at all'])
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert rows == [] and status == DEAD, 'an unreadable first page is a dead link, not a closed section'

    def test_a_risk_control_page_never_reaches_the_api(self):
        driver = FakeDriver(body='当前请求存在异常，暂时限制访问', fetch_queue=[])
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert rows == [] and status == BLOCKED and driver.fetched == []

    def test_a_link_without_a_bv_id_is_dead(self):
        session, driver = self._session([_bili_view()])
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/', 0)
        assert rows == [] and status == DEAD and driver.fetched == []

    def test_limit_caps_the_table_not_the_pages(self):
        page1 = [_bili_reply(str(i), '甲', f'第{i}条') for i in range(20)]
        session, _driver = self._session(
            [_bili_view(), _bili_page(page1, next_cursor=2), _bili_page(page1[:19], next_cursor=3, is_end=True)]
        )
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 5)
        assert status == OK and len(rows) == 5

    def test_first_page_refusal_is_blocked_and_keeps_nothing(self):
        session, _driver = self._session([_bili_view(), json.dumps({'code': -509, 'data': None})])
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert rows == [] and status == BLOCKED

    def test_later_page_failure_keeps_the_earlier_rows(self):
        session, _driver = self._session(
            [_bili_view(), _bili_page([_bili_reply('100', '甲', '留着')], next_cursor=2), 'not json at all']
        )
        rows, status = session.walk('bilibili', 'https://www.bilibili.com/video/BV1atCRYsE7x/', 0)
        assert status == OK and len(rows) == 1


class TestBilibiliParser:
    def test_endpoint_urls_carry_the_measured_shape(self):
        assert bilibili_view_js('BV1x') == 'https://api.bilibili.com/x/web-interface/view?bvid=BV1x'
        assert bilibili_reply_js(99, 2) == 'https://api.bilibili.com/x/v2/reply/main?type=1&oid=99&mode=3&next=2&ps=20'

    def test_column_names_stay_outside_the_dedupe_identity_fields(self):
        """'文章URL'/'评论者'/'评论内容' are deliberate near-misses of the ledger's
        field lists; a comment that borrowed '链接' would hash every row of one
        video to the same key and drop all but the first."""
        from services.runs.store.identity import _AUTHOR_FIELDS, _BODY_FIELDS, _URL_FIELDS

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
    def test_engine_requires_urls(self, seeded_logins):
        # The login is not what this case is about, but a comment crawl IS a logged-in
        # one, and validation now refuses the ones this machine cannot serve (#28).
        wf = {'nodes': [{'id': 'node-1', 'type': 'comment', 'params': {'urls': '   '}}], 'connections': []}
        errors = WorkflowEngine(wf).validate()
        assert any('node-1' in e for e in errors)
        wf['nodes'][0]['params']['urls'] = 'https://weibo.com/1/abc'
        assert WorkflowEngine(wf).validate() == []

    def test_comment_rows_keep_distinct_ledger_identity(self):
        # Rows of ONE article must not collapse onto one item_key — that would
        # silently drop every comment after the first into the dedupe ledger.
        from services.runs.store import item_key

        rows = parse_weibo_comments(
            {'data': [{'user': {'screen_name': '甲'}, 'text': 'a'}, {'user': {'screen_name': '乙'}, 'text': 'b'}]},
            'https://weibo.com/1/abc',
        )
        assert item_key(rows[0]) != item_key(rows[1])


class TestTheCountsWrittenIntoTheRow:
    """Numbers a reader trusts without checking: 楼层 and 点赞数.

    Both were silently wrong in ways no shape check could see — a repeated floor is still
    an int, and ``1.2万`` read as 1 is still plausible — so they are pinned here.
    """

    def test_xhs_floor_runs_across_parents_and_their_replies(self):
        """楼层 counts top-level comments only; a reply's position is the 父楼层 it names."""
        threads = {
            'id:a1': {
                'own': _xhs_comment('a1', '甲', '父评论', replies='2'),
                'subs': [_xhs_comment('a2', '乙', '子一'), _xhs_comment('a3', '丙', '子二')],
                'declared': 2,
            },
            'id:b1': {'own': _xhs_comment('b1', '丁', '下一个父评论'), 'subs': [], 'declared': 0},
        }
        rows = xhs_comments.parse_xhs_threads(threads, XHS_NOTE)
        assert [row['楼层'] for row in rows] == [1, '', '', 2]
        assert [row['父楼层'] for row in rows] == ['', 1, 1, '']
        assert [row['子回复数'] for row in rows] == [2, 0, 0, 0]

    def test_xhs_like_count_honours_the_units(self):
        """``1千+`` / ``3,204`` / a bare ``赞``: the panel writes all three, and the count is read, not guessed."""
        threads = {
            'id:a1': {'own': _xhs_comment('a1', '甲', '好', likes='1千+'), 'subs': [], 'declared': 0},
            'id:b1': {'own': _xhs_comment('b1', '乙', '好', likes='3,204'), 'subs': [], 'declared': 0},
            'id:c1': {'own': _xhs_comment('c1', '丙', '好', likes='赞'), 'subs': [], 'declared': 0},
        }
        rows = xhs_comments.parse_xhs_threads(threads, XHS_NOTE)
        assert [row['点赞数'] for row in rows] == [1000, 3204, 0]

    def test_a_millisecond_stamp_is_blank_not_a_crash(self):
        """13-digit stamps answer ``OSError``, which the old ``except ValueError`` missed."""
        from crawlers.commenting.protocol import _stamp

        assert _stamp(1700000000000) == ''
        assert _stamp(-1) == ''
        assert _stamp(10**20) == ''
        assert _stamp(1700000000) == '2023-11-15 06:13:20'
