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

from crawlers.comments import (
    BLOCKED,
    DEAD,
    OK,
    CommentSession,
    page_is_blocked,
    parse_weibo_comments,
    weibo_bid,
)
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
    def __init__(self, body='', pages=None, fetch_queue=None, start_url='https://x.test/'):
        self.body = body
        self.pages = pages or {}
        self.fetch_queue = list(fetch_queue or [])
        self.fetched = []
        self.visited = []
        self.current_url = start_url
        self.scripts = []

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
        assert page_is_blocked('…暂时限制本次访问…')
        assert page_is_blocked('扫码登录 手机号登录')
        assert not page_is_blocked('正常内容 三亚攻略')

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
        # Identity-safe columns: none of the dedupe-ledger URL/author/body names.
        assert set(rows[0]) == {'平台', '文章URL', '评论者', '评论者主页', '评论内容', '评论时间', '点赞数', '楼层'}


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


def _zh_content(author, text, href='https://www.zhihu.com/people/x'):
    parent = El(kids={'a[href*="/people/"]': [El(author, attrs={'href': href})]})
    content = El(text)
    # _comment_author walks ./ancestor::div[3] — fake it via find_element on the xpath.
    content._ancestors = {0: parent}

    def finder(by, selector):
        if selector.startswith('./ancestor'):
            return parent
        from selenium.common.exceptions import NoSuchElementException

        raise NoSuchElementException(selector)

    content.find_element = finder
    return content


class TestZhihuAdapter:
    def test_opens_panels_and_collects(self):
        btn = El('17 条评论')
        driver = FakeDriver(
            body='正常回答',
            pages={
                'button': [btn, El('举报')],
                '.CommentContent': [_zh_content('陈博涵', '三亚最南所以火'), _zh_content('路人', '秦皇岛外打鱼船')],
                'button, a': [El('举报')],  # no 更多 → single round
            },
        )
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 0)
        assert status == OK and len(rows) == 2
        assert getattr(btn, 'clicked', False), 'comment panel must be opened'
        assert rows[0]['评论者'] == '陈博涵' and rows[0]['评论者主页'].endswith('/people/x')

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
        contents = [_zh_content('甲', 'a'), _zh_content('乙', 'b')]
        driver = FakeDriver(body='正常', pages={'button': btns, '.CommentContent': contents, 'button, a': []})
        session = CommentSession(driver, nap=lambda s: None)
        rows, status = session.crawl_zhihu('https://www.zhihu.com/question/1/answer/2', 1)
        assert status == OK and len(rows) == 1


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
