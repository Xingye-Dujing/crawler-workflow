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

A third thing is pinned apart from both: a navigation the *browser* refused. That
page is not the site's answer at all, so it is neither a dead cookie nor a risk
refusal — and it is only visible in the document's own address, because the
address bar keeps showing what was asked for.
"""

import pytest

from crawlers.engine.wall import (
    VERDICTS,
    bounced_to_root,
    classify,
    error_token,
    looks_blocked,
    looks_like_login_page,
    never_arrived,
    unreachable_page,
)

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

    def test_the_four_verdicts_are_the_four_user_actions(self):
        assert classify('https://www.zhihu.com/question/1', '正常内容') == 'ok'
        assert classify('https://x.com/i/flow/login', '') == 'login'
        assert classify('https://www.douyin.com/search/x', '滑动验证') == 'blocked'
        assert classify('https://www.douyin.com/search/x', '', document_uri='chrome-error://chromewebdata/') == (
            'unreachable'
        )

    def test_the_vocabulary_is_closed_because_a_consumer_tests_one_word(self):
        """``== 'blocked'`` is how half the crawler reads this answer, so a fifth word
        added without noticing would be silently filed as "not risk control". Listing
        the words here is what makes adding one a deliberate edit."""
        assert VERDICTS == ('ok', 'login', 'blocked', 'unreachable')
        seen = {
            classify(url, body, title, uri)
            for url, body, title, uri in (
                ('https://www.zhihu.com/question/1', '正常内容', '', ''),
                ('https://x.com/i/flow/login', '', '', ''),
                ('https://www.douyin.com/search/x', '滑动验证', '', ''),
                ('https://www.douyin.com/search/x', '无法访问此网站', '', 'chrome-error://chromewebdata/'),
                ('chrome://new-tab-page/', '新标签页', '', ''),
                ('', '', '', ''),
            )
        }
        assert seen <= set(VERDICTS), f'classify answered a word outside its own vocabulary: {seen - set(VERDICTS)}'

    def test_a_browser_still_on_its_own_page_never_arrived(self):
        """Measured 2026-09-25 on xiaohongshu: a throttled VISIBLE window stayed on
        ``chrome://new-tab-page`` (body 「新标签页 / 自定义 Chrome」, no wall wording),
        the classifier read 'ok', and the search filed an empty grid as if the keyword
        had no notes. No site can redirect into these schemes — being here IS the
        navigation failure, and a failure must be named, never tabled as a result.
        """
        assert never_arrived('chrome://new-tab-page/') is True
        assert never_arrived('about:blank') is True
        assert never_arrived('https://www.xiaohongshu.com/search_result?keyword=%E4%B8%89%E4%BA%9A') is False
        assert classify('chrome://new-tab-page/', '新标签页 应用商店 自定义 Chrome') == 'blocked'
        # A driver that cannot answer at all ('') is NOT an internal page — it stays
        # the 'ok' the dead-session rule promises, so a crawl producing rows is not
        # aborted by a peek that failed.
        assert classify('', '') == 'ok'


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


#: The three measured shapes of a navigation the browser refused, and the document each
#: one leaves behind. Taken with Chrome 148 by ``backend/test_arrival_evidence.py``; the
#: body text is the real Chinese error page, abbreviations aside.
REFUSALS = [
    (
        'http://no-host-xyz-invalid.example/',
        'chrome-error://chromewebdata/',
        '无法访问此网站\n\n找不到 no-host-xyz-invalid.example 的服务器 IP 地址\n\nERR_NAME_NOT_RESOLVED',
        'ERR_NAME_NOT_RESOLVED',
    ),
    (
        'http://127.0.0.1:1/nope',
        'chrome-error://chromewebdata/',
        '无法访问此网站\n\n无效的网址\n\nERR_UNSAFE_PORT',
        'ERR_UNSAFE_PORT',
    ),
    (
        'http://10.255.255.1/',
        'chrome-error://chromewebdata/',
        '无法访问此网站\n\n10.255.255.1 响应时间过长\n\nERR_CONNECTION_TIMED_OUT',
        'ERR_CONNECTION_TIMED_OUT',
    ),
]


class TestTheBrowserRefusedTheNavigation:
    """:class:`Crawler` reads the address it asked for; only the document knows it lost.

    This is the distinction the whole word exists for. Measured 2026-09-25: after a
    refused navigation ``driver.current_url`` still reports the URL that was asked for,
    while the committed document calls itself ``chrome-error://chromewebdata`` and prints
    a ``net::ERR_…`` token. A classifier that reads only the first of those two files a
    dead DNS entry as "the site answered with nothing", which is the same lie in a
    different costume as calling a login page an empty account.
    """

    @pytest.mark.parametrize(('asked', 'uri', 'body', 'token'), REFUSALS)
    def test_a_page_the_browser_wrote_names_itself(self, asked, uri, body, token):
        assert classify(asked, body, document_uri=uri) == 'unreachable'
        assert error_token(body) == token

    @pytest.mark.parametrize(('asked', 'uri', 'body', 'token'), REFUSALS)
    def test_the_asked_for_address_alone_does_not_give_it_away(self, asked, uri, body, token):
        """The bug this regression-pins: judging the address bar says the page is fine."""
        assert classify(asked, body) == 'ok', 'the asked-for URL is a real http address, and reads as arrived'

    def test_a_refusal_that_printed_no_token_is_still_a_refusal(self):
        """The token is a name, not the evidence: the document's own address is."""
        assert unreachable_page('https://www.douyin.com/hot', 'chrome-error://chromewebdata/') is True
        assert error_token('无法访问此网站') == ''

    def test_an_article_about_the_token_is_not_a_refusal(self):
        """The reverse case, and the expensive one: a development post that quotes
        ``net::ERR_CONNECTION_RESET`` in its body is content. Reading the body for the
        token without the browser-owned document would throw away a page that arrived.
        """
        body = '排查 net::ERR_CONNECTION_RESET 的三种原因：代理、防火墙、服务端主动关闭。'
        url = 'https://blog.example.com/2026/09/reset'
        assert classify(url, body, document_uri=url) == 'ok'
        assert error_token(body) == 'ERR_CONNECTION_RESET', 'the reader works; the *decision* is what is guarded'

    def test_an_address_that_merely_mentions_the_error_scheme_is_not_one(self):
        """The test is on what the document *is*, not on a substring of the request."""
        assert unreachable_page('https://example.com/?next=chrome-error://x', '') is False

    def test_no_reading_at_all_is_still_no_evidence(self):
        """A driver that cannot answer ``documentURI`` (a test double, a session tearing
        down) must not hand out a refusal — the same rule ``current_url`` follows."""
        assert classify('https://www.douyin.com/search/x', '', document_uri='') == 'ok'
        assert unreachable_page('', '') is False

    def test_a_refusal_is_not_the_same_page_as_a_window_on_its_own_new_tab(self):
        """``chrome://new-tab-page`` means the navigation never happened; ``chrome-error``
        means it happened and was refused. One is a flash to wait out, the other names
        its own cause, and they reach the user as different sentences.
        """
        assert never_arrived('chrome-error://chromewebdata/') is False
        assert classify('chrome-error://chromewebdata/', '无法访问此网站') == 'unreachable'
