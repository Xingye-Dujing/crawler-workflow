"""The shared interception detector (``crawlers.engine.wall``).

Every platform's "why is this page empty?" answer funnels through this module,
and its verdict decides two user-visible things: whether a crawl stops scrolling,
and what 验证 Cookie reports about a stored session. A wall it does not recognise
is the worse failure — the panel then answers "Cookie 可用" while the browser is
sitting on a sign-in page, which sends the user off to crawl with a dead session.

Login and risk control are pinned *apart*, because the user's next action
differs: re-save the cookie, or wait. The shapes below are all measured, not
imagined — including Instagram's, where the router answers a profile request at
the site root with no URL clue at all.
"""

import pytest

from crawlers.engine.wall import bounced_to_root, classify, looks_blocked, looks_like_login_page

pytestmark = pytest.mark.unit

#: (url, body text, expected) — a wall the platforms actually park on.
WALLS = [
    ('https://passport.weibo.com/sso/signin?entry=miniblog', '', True),
    ('https://passport.zhihu.com/org', '', True),
    ('https://www.zhihu.com/signin?next=%2F', '', True),
    ('https://x.com/i/flow/login', '', True),
    ('https://x.com/i/flow/login?input_flow_data=%7B', '', True),
    # X's re-verification interstitial: still on x.com, so only the route tells.
    ('https://x.com/i/jf/onboarding/web?mode=login', '', True),
    ('https://www.instagram.com/accounts/login/', '', True),
    ('https://accounts.google.com/v3/signin/identifier', '', True),
    # No marker in the URL, but the page itself says it twice — the Chinese walls
    # that render their prompt in the body.
    ('https://www.douyin.com/search/x', '扫描二维码登录 手机号登录', True),
    # Instagram's login form uses none of the Chinese wording; its own pair of
    # footer links is what identifies it. Seen served at ``https://www.instagram.com/#``.
    ('https://www.instagram.com/#', '手机号、账号或邮箱 密码 登录 忘记密码了？ 创建新账户', True),
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

    def test_a_marker_beyond_the_head_of_the_page_is_ignored(self):
        """An article can quote a login prompt deep in its text; the wall puts its
        prompt at the top, so only the head is examined."""
        body = ('正文' * 500) + '扫描二维码登录 手机号登录'
        assert looks_like_login_page('https://www.douyin.com/video/1', body) is False


class TestRiskControlIsNotALoginProblem:
    @pytest.mark.parametrize(
        'body',
        [
            '检测到您的账号存在异常，请配合完成验证',
            '哎呀，出了一点问题 暂时限制本次访问',
            '40362',
        ],
    )
    def test_a_refusal_from_the_risk_engine_is_detected(self, body):
        assert looks_blocked(body) is True

    def test_douyin_announces_its_captcha_in_the_tab_title(self):
        """Measured: no URL pattern and no body marker — the title is the signal."""
        assert looks_blocked('', title='验证码中间页-抖音') is True

    def test_ordinary_content_is_not_a_block(self):
        assert looks_blocked('三亚旅游攻略 五天四晚 人均两千') is False

    def test_a_login_wall_wins_over_the_block_wording(self):
        """The fix differs, and a cookie is the cheaper thing to ask for first."""
        assert classify('https://passport.zhihu.com', '暂时限制 登录后查看') == 'login'

    def test_the_three_verdicts_are_the_three_user_actions(self):
        assert classify('https://www.zhihu.com/question/1', '正常内容') == 'ok'
        assert classify('https://x.com/i/flow/login', '') == 'login'
        assert classify('https://www.douyin.com/search/x', '滑动验证') == 'blocked'


class TestTheRootBounce:
    """Instagram's challenge answer to a profile request: the site root, no clue."""

    ROOT = 'https://www.instagram.com/'

    def test_a_profile_request_dropped_at_the_root_is_a_bounce(self):
        assert bounced_to_root('https://www.instagram.com/nasa/', 'https://www.instagram.com/#', self.ROOT) is True

    def test_asking_for_the_root_and_getting_it_is_not(self):
        assert bounced_to_root('https://www.instagram.com/', 'https://www.instagram.com/', self.ROOT) is False

    def test_a_redirect_to_another_real_page_is_not(self):
        landed = 'https://www.instagram.com/accounts/login/'
        assert bounced_to_root('https://www.instagram.com/nasa/', landed, self.ROOT) is False

    def test_a_foreign_request_is_not_judged_against_this_site(self):
        assert bounced_to_root('https://example.com/x', 'https://www.instagram.com/', self.ROOT) is False

    def test_the_fragment_and_trailing_slash_do_not_matter(self):
        assert bounced_to_root('https://www.instagram.com/nasa', 'https://www.instagram.com', self.ROOT) is True
