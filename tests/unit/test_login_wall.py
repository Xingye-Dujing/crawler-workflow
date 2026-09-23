"""The shared login-wall detector (``crawlers.base.looks_like_login_page``).

Every platform's "why is this page empty?" answer funnels through this one
function, and its verdict decides two user-visible things: whether a crawl stops
scrolling, and what 验证 Cookie reports about a stored session. A wall it does not
recognise is the worse failure — the panel then answers "Cookie 可用" while the
browser is sitting on a sign-in page, which sends the user off to crawl with a
dead session. So the marker table is pinned here, both for the walls it must catch
and for the pages it must not.
"""

import pytest

from crawlers.base import looks_like_login_page

pytestmark = pytest.mark.unit

#: (url, body text, expected) — a wall the platforms actually park on.
WALLS = [
    ('https://passport.weibo.com/sso/signin?entry=miniblog', '', True),
    ('https://passport.zhihu.com/org', '', True),
    ('https://www.zhihu.com/signin?next=%2F', '', True),
    ('https://x.com/i/flow/login', '', True),
    ('https://x.com/i/flow/login?input_flow_data=%7B', '', True),
    ('https://www.instagram.com/accounts/login/', '', True),
    ('https://accounts.google.com/v3/signin/identifier', '', True),
    # No marker in the URL, but the page itself says it twice — the Chinese walls
    # that render their prompt in the body.
    ('https://www.douyin.com/search/x', '扫描二维码登录 手机号登录', True),
]

#: Pages that are NOT a wall, including the ones a bare substring match would
#: wrongly catch.
OPEN = [
    ('https://x.com/home', 'Home / X', False),
    ('https://x.com/foo/status/123', 'Post 回复 转发', False),
    ('https://www.instagram.com/p/Cg123/', 'Comments', False),
    ('https://www.youtube.com/watch?v=abcdefg', 'Comments', False),
    ('https://www.zhihu.com/question/1/answer/2', '这篇回答提到「请先登录」一次', False),
    # One marker mention in an article body is not a wall: the detector needs two
    # distinct prompts, and only from the top of the page.
    ('https://weibo.com/1/2', '登录后查看全部内容', False),
]


class TestWallDetection:
    @pytest.mark.parametrize(('url', 'body', 'expected'), WALLS + OPEN)
    def test_a_page_is_either_a_wall_or_it_is_not(self, url, body, expected):
        assert looks_like_login_page(url, body) is expected

    def test_a_dead_driver_that_cannot_answer_still_reads_as_no_wall(self):
        """An empty URL comes from a session that cannot answer, and aborting a
        crawl that is otherwise producing rows would be the worse mistake."""
        assert looks_like_login_page('', '') is False

    def test_the_body_markers_need_two_of_a_kind_at_the_top(self):
        head = '请先登录' + ('登录后查看全部内容' * 1)
        assert looks_like_login_page('https://example.com/feed', head) is True
        assert looks_like_login_page('https://example.com/feed', '请先登录') is False

    def test_a_marker_buried_past_the_head_of_the_page_is_ignored(self):
        """An article can quote a login prompt deep in its text; the wall puts its
        prompt at the top, so only the head is examined."""
        body = ('正文' * 500) + '扫描二维码登录 手机号登录'
        assert looks_like_login_page('https://www.douyin.com/video/1', body) is False
