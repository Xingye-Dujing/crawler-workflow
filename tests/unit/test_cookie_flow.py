"""Cookie flow: which link may open the login browser, and what the panel says."""

import pytest

from services.cookie_flow import flow_for, normalize_entry_url

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
        flow = flow_for('wechat', allowed_hosts=HOSTS, login_url='https://mp.weixin.qq.com/')
        assert flow['login_url'] == 'https://mp.weixin.qq.com/'
        assert flow['allowed_hosts'] == ['mp.weixin.qq.com']
        assert flow['accepts_custom_url'] is True

    def test_a_platform_with_no_hosts_cannot_be_steered_to_a_custom_page(self, monkeypatch):
        monkeypatch.setattr('services.cookie_flow.t', lambda key, **kw: 'x')
        assert flow_for('zhihu', allowed_hosts=())['accepts_custom_url'] is False

    def test_only_wechat_advertises_two_purposes(self, monkeypatch):
        """WeChat is the platform whose cookie file serves two features that need
        two different links; claiming that elsewhere would be a lie to the user."""
        monkeypatch.setattr('services.cookie_flow.t', lambda key, **kw: 'x')
        assert flow_for('wechat')['multi_purpose'] is True
        assert flow_for('xiaohongshu')['multi_purpose'] is False


class TestCatalogue:
    """The panel renders whatever the catalogue says, so the real text is the
    contract — an empty or unwritten entry would silently produce an empty box."""

    @pytest.mark.parametrize('platform', ['zhihu', 'weibo', 'xiaohongshu', 'wechat'])
    def test_every_platform_has_a_real_purpose_and_at_least_one_step(self, platform):
        flow = flow_for(platform)
        assert flow['purpose'] and not flow['purpose'].startswith('cookie.')
        assert len(flow['steps']) >= 1

    def test_wechat_explains_the_admin_login_and_refuses_to_guess(self):
        steps = '\n'.join(flow_for('wechat')['steps'])
        assert 'mp.weixin.qq.com' in steps
        # the measured reason, not a promise that a copied link would help
        assert 'show_comment=0' in steps
        assert '不伪装' in steps

    def test_no_platform_step_promises_a_wechat_comment_route(self):
        """The removed capability must not survive in guidance either."""
        for platform in ('zhihu', 'weibo', 'xiaohongshu', 'wechat'):
            assert 'pass_ticket' not in '\n'.join(flow_for(platform)['steps'])

    @pytest.mark.parametrize('platform', ['zhihu', 'weibo', 'xiaohongshu', 'wechat'])
    def test_the_english_catalogue_answers_too(self, platform):
        from i18n import set_lang

        set_lang('en')
        try:
            flow = flow_for(platform)
            assert flow['purpose'] and len(flow['steps']) >= 1
            assert 'mp.weixin.qq.com' in '\n'.join(flow_for('wechat')['steps'])
        finally:
            set_lang('zh')
