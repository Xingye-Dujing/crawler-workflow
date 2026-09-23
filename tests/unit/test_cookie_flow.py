"""Cookie flow: which link may open the login browser, and what the panel says."""

import pytest

#: The catalogue itself, for the one assertion that has to read the message table
#: rather than the rendered flow (a key must be *absent*, not merely unwritten).
from crawlers import cookie_hosts
from i18n import _ZH as _ZH_MESSAGES
from services.cookie_flow import crawler_hosts, flow_for, normalize_entry_url, retain_for_platform
from services.cookie_manager import CookieManager

pytestmark = pytest.mark.unit

HOSTS = ('mp.weixin.qq.com',)


class TestEntryUrl:
    """A pasted link is stored in a per-platform cookie file, so a link to
    another site would plant that site's session where a crawler later carries
    it — the allowlist is the guard, not politeness."""

    def test_empty_input_means_use_the_platform_login_page(self):
        assert normalize_entry_url('', HOSTS) == ''
        assert normalize_entry_url('   ', HOSTS) == ''

    def test_exact_host_is_accepted_and_upgraded_to_https(self):
        assert normalize_entry_url('mp.weixin.qq.com/s/abc', HOSTS) == 'https://mp.weixin.qq.com/s/abc'

    def test_a_subdomain_of_an_allowed_host_is_accepted(self):
        assert normalize_entry_url('https://weixin.sogou.com/x', ('sogou.com',)) == 'https://weixin.sogou.com/x'

    def test_a_host_recorded_with_its_www_prefix_also_accepts_the_bare_form(self):
        """Zhihu is crawled at ``www.zhihu.com``; a user pastes whichever spelling
        of the page they were reading."""
        assert normalize_entry_url('https://zhihu.com/question/1', ('www.zhihu.com',)) == 'https://zhihu.com/question/1'
        assert normalize_entry_url('https://www.zhihu.com/question/1', ('www.zhihu.com',))
        assert normalize_entry_url('https://zhihu.com.evil.test/x', ('www.zhihu.com',)) == ''

    def test_a_lookalike_suffix_does_not_pass(self):
        """evil-mp.weixin.qq.com is a subdomain; evilqq.com style lookalikes are not."""
        assert normalize_entry_url('https://evilmp.weixin.qq.com/', HOSTS) == ''
        assert normalize_entry_url('https://mp.weixin.qq.com.evil.test/', HOSTS) == ''

    def test_foreign_host_is_refused(self):
        assert normalize_entry_url('https://example.com/login', HOSTS) == ''

    def test_scheme_injection_is_refused(self):
        for candidate in ('javascript:alert(1)', 'file:///C:/Windows/win.ini', 'data:text/html,x'):
            assert normalize_entry_url(candidate, HOSTS) == ''

    def test_no_allowed_hosts_refuses_everything(self):
        assert normalize_entry_url('https://example.com', ()) == ''

    def test_a_link_that_is_not_parseable_is_refused_rather_than_raising(self):
        assert normalize_entry_url('https://[bad', HOSTS) == ''

    def test_userinfo_cannot_smuggle_the_host(self):
        """``http://evil.test/#mp.weixin.qq.com`` hosts on evil.test; the fragment
        is not the host, so it must be refused."""
        assert normalize_entry_url('https://evil.test/#mp.weixin.qq.com', HOSTS) == ''


class TestFlow:
    def test_steps_arrive_as_ordered_lines(self, monkeypatch):
        monkeypatch.setattr('services.cookie_flow.t', lambda key, **kw: '第一步\n第二步\n')
        flow = flow_for('zhihu', allowed_hosts=HOSTS, login_url='https://www.zhihu.com/')
        assert flow['steps'] == ['第一步', '第二步']

    def test_platform_and_purpose_are_named_for_the_selected_row(self, monkeypatch):
        seen = []

        def fake_t(key, **kw):
            seen.append(key)
            return f'<{key}>'

        monkeypatch.setattr('services.cookie_flow.t', fake_t)
        flow = flow_for('weibo', allowed_hosts=('weibo.com',))
        assert flow['platform'] == 'weibo'
        assert flow['purpose'] == '<cookie.weibo.purpose>'
        assert seen == ['cookie.weibo.purpose', 'cookie.weibo.steps']

    def test_login_url_and_hosts_are_carried_for_the_panel(self, monkeypatch):
        monkeypatch.setattr('services.cookie_flow.t', lambda key, **kw: 'x')
        flow = flow_for('zhihu', allowed_hosts=('www.zhihu.com',), login_url='https://www.zhihu.com/')
        assert flow['login_url'] == 'https://www.zhihu.com/'
        assert flow['allowed_hosts'] == ['www.zhihu.com']
        assert flow['accepts_custom_url'] is True

    def test_a_platform_with_no_hosts_cannot_be_steered_to_a_custom_page(self, monkeypatch):
        monkeypatch.setattr('services.cookie_flow.t', lambda key, **kw: 'x')
        assert flow_for('zhihu', allowed_hosts=())['accepts_custom_url'] is False


class TestCatalogue:
    """The panel renders whatever the catalogue says, so the real text is the
    contract — an empty or unwritten entry would silently produce an empty box."""

    @pytest.mark.parametrize('platform', list(CookieManager.PLATFORMS))
    def test_every_platform_has_a_real_purpose_and_at_least_one_step(self, platform):
        flow = flow_for(platform)
        assert flow['purpose'] and not flow['purpose'].startswith('cookie.')
        assert len(flow['steps']) >= 1

    def test_no_platform_advertises_a_wechat_cookie(self):
        """WeChat article bodies need no login, and the keyword-search route that
        did was removed — a cookie row for it would be guidance to log in for
        nothing. The platform list, not the prose, is what proves it."""
        assert 'wechat' not in CookieManager.PLATFORMS
        assert 'cookie.wechat.purpose' not in _ZH_MESSAGES

    def test_no_platform_step_promises_a_wechat_comment_route(self):
        """The removed capability must not survive in guidance either."""
        for platform in CookieManager.PLATFORMS:
            assert 'pass_ticket' not in '\n'.join(flow_for(platform)['steps'])

    @pytest.mark.parametrize('platform', list(CookieManager.PLATFORMS))
    def test_the_english_catalogue_answers_too(self, platform):
        from i18n import set_lang

        set_lang('en')
        try:
            flow = flow_for(platform)
            assert flow['purpose'] and len(flow['steps']) >= 1
            assert not flow['purpose'].startswith('cookie.'), f'{platform} has no English text'
        finally:
            set_lang('zh')


class TestCookieOwnership:
    """Which cookies belong in one platform's file.

    The capture reads only the page the browser is on, and a login walks through
    an identity provider to get there — YouTube behind a Google sign-in, Instagram
    behind Facebook. Keeping ``.google.com`` out of ``youtube_cookies.json`` is not
    tidiness: those rows open Gmail and Drive, and a file full of them would also
    hide the fact that the session the crawl needs was never captured.
    """

    def test_the_platform_host_and_its_extra_planting_hosts_are_the_allowlist(self):
        class _Crawler:
            domain = 'www.youtube.com'
            cookie_domains = ('youtube.com', 'm.youtube.com')

        assert crawler_hosts(_Crawler()) == ('www.youtube.com', 'youtube.com', 'm.youtube.com')

    def test_a_class_that_lists_no_extra_hosts_still_answers_with_its_own(self):
        class _Crawler:
            domain = 'x.com'

        assert crawler_hosts(_Crawler()) == ('x.com',)

    def test_an_empty_domain_is_not_turned_into_an_empty_string_entry(self):
        class _Crawler:
            domain = ''
            cookie_domains = ('', 'twitter.com')

        assert crawler_hosts(_Crawler()) == ('twitter.com',)

    def test_the_saved_session_of_the_platform_itself_is_kept(self):
        cookies = [
            {'name': 'SID', 'domain': '.youtube.com'},
            {'name': '__Secure-1PSID', 'domain': 'www.youtube.com'},
        ]
        kept, dropped = retain_for_platform(cookies, ('www.youtube.com',))
        assert [c['name'] for c in kept] == ['SID', '__Secure-1PSID']
        assert dropped == 0

    def test_the_identity_provider_session_goes_back_to_the_provider(self):
        cookies = [{'name': 'SID', 'domain': '.google.com'}, {'name': 'auth_token', 'domain': '.x.com'}]
        kept, dropped = retain_for_platform(cookies, ('x.com', 'twitter.com'))
        assert [c['name'] for c in kept] == ['auth_token']
        assert dropped == 1

    def test_a_lookalike_suffix_is_not_the_platform(self):
        """``evilyoutube.com`` ends in the platform's name and in nothing else —
        the same confusion the entry-link allowlist already refuses."""
        kept, dropped = retain_for_platform([{'name': 'SID', 'domain': '.evilyoutube.com'}], ('www.youtube.com',))
        assert kept == [] and dropped == 1

    def test_a_paste_with_no_domain_to_judge_is_kept(self):
        """Extensions and hand-written JSON routinely omit the domain. Refusing
        those would block the panel's own 粘贴 Cookies JSON path, so an entry that
        cannot be judged is accepted rather than guessed away."""
        kept, dropped = retain_for_platform([{'name': 'SUB', 'value': 'x'}, {'name': 'A', 'domain': '  '}, 'junk'], ())
        assert len(kept) == 3 and dropped == 0

    def test_the_count_returned_is_the_count_dropped_not_the_count_kept(self):
        cookies = [{'name': 'a', 'domain': '.example.com'}, {'name': 'b', 'domain': '.other.test'}]
        kept, dropped = retain_for_platform(cookies, ('example.com',))
        assert (len(kept), dropped) == (1, 1)

    def test_nothing_at_all_is_an_answer_with_nothing_dropped(self):
        assert retain_for_platform([], ('example.com',)) == ([], 0)
        assert retain_for_platform(None, ('example.com',)) == ([], 0)

    def test_a_cookie_host_that_the_platform_itself_lists_always_passes(self):
        """The overseas platforms are the reason this filter exists, so their own
        hosts must clear it — a false refusal here would empty a fresh login."""
        for platform, hosts in (('twitter', ('x.com', 'twitter.com')), ('youtube', ('www.youtube.com',))):
            cookies = [{'name': 'session', 'domain': f'.{host}'} for host in hosts]
            kept, dropped = retain_for_platform(cookies, cookie_hosts(platform))
            assert dropped == 0, f'{platform} rejected its own host'
            assert len(kept) == len(hosts)
