"""Tests for services/cookie_manager.py — persisted browser logins.

A cookie file is a path built from a client-supplied string, so the security
edge matters more than the happy path: the platform name is whitelisted, and
every other read failure has to degrade to "no cookies" (a crawl then runs
logged out) rather than raising inside the crawler.
"""

import json
import os

import pytest

from services.cookie_manager import CookieManager

pytestmark = pytest.mark.unit

COOKIES = [{'name': 'dopuel', 'value': 'x', 'domain': '.zhihu.com', 'path': '/'}]


@pytest.fixture
def manager(tmp_path):
    return CookieManager(str(tmp_path / 'cookies'))


class TestPlatformWhitelist:
    def test_the_cookie_whitelist_is_the_platform_list(self):
        """Eight platforms hold a cookie file. WeChat is deliberately not one of
        them: its article bodies are served to anyone, and the keyword search that
        did need a login was removed — a cookie row would be advice to log in for
        nothing."""
        assert CookieManager.PLATFORMS == (
            'zhihu',
            'weibo',
            'xiaohongshu',
            'bilibili',
            'douyin',
            'twitter',
            'instagram',
            'youtube',
        )
        assert all(CookieManager.is_supported(p) for p in CookieManager.PLATFORMS)
        assert CookieManager.is_supported('wechat') is False

    def test_cookie_support_and_crawl_support_are_different_things(self):
        """The distinction that keeps a half-built platform out of the canvas: a
        platform may be loggable in while still refusing to be a data source —
        and, as WeChat shows, the other way round too.

        Pinned on the *mechanism*, not on which platform happens to be
        unimplemented today — that roster changes every time a crawl lands, and a
        test that names a platform as the exception breaks for the wrong reason.
        So the rule a capture-only platform must satisfy is spelled out: it says
        where to log in, which hosts its cookie is valid on, and it RAISES instead
        of returning an empty table (an empty table reads as "this keyword found
        nothing", which is a lie with plausible manners).
        """
        from crawlers import CRAWLERS, is_crawlable

        # Every loggable platform has a class that knows its own hosts; the
        # converse need not hold, and not every such class crawls yet.
        assert set(CookieManager.PLATFORMS) < set(CRAWLERS)
        assert is_crawlable('kuaishou') is False  # nobody logs into it, nobody crawls it
        for platform, cls in CRAWLERS.items():
            if is_crawlable(platform):
                continue
            assert getattr(cls, 'login_url', ''), f'{platform} is loggable but has no login page to open'
            assert getattr(cls, 'domain', ''), f'{platform} has no host its cookie belongs to'
            crawler = cls.__new__(cls)  # no browser: the refusal must not need one
            with pytest.raises(RuntimeError, match='Cookie'):
                crawler.search('any keyword')
            with pytest.raises(RuntimeError, match='Cookie'):
                crawler.get_detail('https://example.com/1')

        class _CookieOnly:
            supports_crawl = False

        original = CRAWLERS.get('douyin')
        CRAWLERS['douyin'] = _CookieOnly
        try:
            assert is_crawlable('douyin') is False
        finally:
            CRAWLERS['douyin'] = original
        assert is_crawlable('douyin') is True, 'the registry is back to what it was'

    @pytest.mark.parametrize('platform', ['ZHIHU', 'zhihu ', '', None, 'kuaishou', 'zh'])
    def test_anything_else_is_unsupported(self, platform):
        assert CookieManager.is_supported(platform) is False

    @pytest.mark.parametrize('platform', ['../../evil', 'zhihu/../../x', '', 'Weibo'])
    def test_path_for_refuses_unknown_platforms(self, manager, platform):
        with pytest.raises(ValueError, match='Unsupported platform'):
            manager._path_for(platform)

    def test_file_name_follows_the_platform(self, manager):
        assert manager._path_for('weibo') == os.path.join(manager.cookie_dir, 'weibo_cookies.json')


class TestRoundTrip:
    def test_save_then_load_returns_the_same_cookies(self, manager):
        manager.save('zhihu', COOKIES)
        assert manager.load('zhihu') == COOKIES

    def test_save_writes_readable_json(self, manager):
        manager.save('bilibili', COOKIES)
        with open(manager._path_for('bilibili'), encoding='utf-8') as handle:
            assert json.load(handle) == COOKIES

    @pytest.mark.parametrize('platform', CookieManager.PLATFORMS)
    def test_each_platform_gets_its_own_file(self, manager, platform):
        manager.save(platform, [{'name': platform, 'value': 'v'}])
        assert manager.load(platform) == [{'name': platform, 'value': 'v'}]
        assert manager.load('zhihu' if platform != 'zhihu' else 'weibo') == []

    def test_saving_twice_replaces_the_login(self, manager):
        manager.save('zhihu', COOKIES)
        manager.save('zhihu', [])
        assert manager.load('zhihu') == []

    def test_the_directory_is_created_on_construction(self, tmp_path):
        target = tmp_path / 'deep' / 'cookies'
        CookieManager(str(target))
        assert target.is_dir()

    def test_unicode_cookie_values_survive(self, manager):
        manager.save('xiaohongshu', [{'name': '昵称', 'value': '旅人甲'}])
        assert manager.load('xiaohongshu')[0]['value'] == '旅人甲'


class TestExistsAndDelete:
    def test_exists_tracks_the_file(self, manager):
        assert manager.exists('zhihu') is False
        manager.save('zhihu', COOKIES)
        assert manager.exists('zhihu') is True

    def test_exists_is_quiet_about_unknown_platforms(self, manager):
        assert manager.exists('../../etc/passwd') is False

    def test_delete_removes_the_file(self, manager):
        manager.save('weibo', COOKIES)
        manager.delete('weibo')
        assert manager.exists('weibo') is False
        assert manager.load('weibo') == []

    def test_deleting_a_missing_login_is_not_an_error(self, manager):
        manager.delete('zhihu')

    def test_delete_refuses_an_unknown_platform(self, manager):
        with pytest.raises(ValueError, match='Unsupported platform'):
            manager.delete('nope')


class TestDamagedFiles:
    @pytest.mark.parametrize('content', ['{not json', '', '[1,2,'])
    def test_corrupt_json_reads_as_no_cookies(self, manager, content):
        manager.save('zhihu', COOKIES)
        with open(manager._path_for('zhihu'), 'w', encoding='utf-8') as handle:
            handle.write(content)
        assert manager.load('zhihu') == []

    @pytest.mark.parametrize('payload', [{'a': 1}, ['x'], 'text', 3])
    def test_a_json_document_is_not_a_cookie_list(self, manager, payload):
        manager.save('zhihu', COOKIES)
        with open(manager._path_for('zhihu'), 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(payload))
        expected = ['x'] if payload == ['x'] else []
        assert manager.load('zhihu') == expected

    def test_a_platform_with_no_file_reads_as_no_cookies(self, manager):
        assert manager.load('wechat') == []


class TestSessionOnlyCount:
    """How many saved entries will NOT outlive the window that imports them.

    Measured against a real Chrome (``tests/integration/test_profile_cookie_plant.py``):
    a cookie planted without an expiry is written to memory, not to the profile store, so
    the 「更新进 Profile」 answer has to count them — a transfer that partly evaporates is
    not a transfer.
    """

    def test_a_persistent_entry_is_not_counted(self, manager):
        manager.save('zhihu', [{'name': 'sid', 'value': 'v', 'domain': '.zhihu.com', 'expiry': 4e9}])
        assert manager.session_only_count('zhihu') == 0

    def test_an_entry_with_no_expiry_at_all_is_counted(self, manager):
        manager.save('zhihu', [{'name': 'sid', 'value': 'v', 'domain': '.zhihu.com'}])
        assert manager.session_only_count('zhihu') == 1

    @pytest.mark.parametrize('field', ['expiry', 'expirationDate'])
    def test_either_spelling_of_an_expiry_is_honoured(self, manager, field):
        """The driver reports one shape and a browser's own export another; reading only
        one would tell the user a persistent cookie is about to be lost."""
        manager.save('zhihu', [{'name': 'sid', 'value': 'v', 'domain': '.zhihu.com', field: 4e9}])
        assert manager.session_only_count('zhihu') == 0

    def test_a_zero_expiry_is_no_expiry(self, manager):
        manager.save('weibo', [{'name': 'sid', 'value': 'v', 'domain': '.weibo.com', 'expiry': 0}])
        assert manager.session_only_count('weibo') == 1

    def test_the_two_shapes_are_counted_separately(self, manager):
        manager.save(
            'bilibili',
            [
                {'name': 'a', 'value': '1', 'domain': '.bilibili.com', 'expiry': 4e9},
                {'name': 'b', 'value': '2', 'domain': '.bilibili.com'},
                {'name': 'c', 'value': '3', 'domain': '.bilibili.com'},
            ],
        )
        assert manager.session_only_count('bilibili') == 2

    def test_a_missing_file_counts_nothing_rather_than_raising(self, manager):
        assert manager.session_only_count('youtube') == 0

    def test_an_unsupported_platform_counts_nothing(self, manager):
        assert manager.session_only_count('../../etc/passwd') == 0

    def test_a_non_dictionary_entry_is_not_counted_as_a_cookie(self, manager):
        """``load`` returns whatever list was stored; a row that is not an object plants
        nothing anywhere, so it must not be reported as a cookie about to be lost."""
        manager.save('zhihu', ['not-a-cookie'])
        assert manager.session_only_count('zhihu') == 0


class TestAccounts:
    """Several saved logins for one platform — the storage half of multi-account.

    The naming rule is the whole contract: the blank account keeps the historical
    ``<platform>_cookies.json`` byte-for-byte (nobody's existing login moves because
    the code learned a parameter), and a named account adds exactly one ``@`` segment.
    The account label enters a filename from a text box, so anything that is not a
    plain lowercase word is refused the same way an unknown platform is — the
    whitelist is about the path, not about taste.
    """

    def test_the_blank_account_is_the_historical_filename(self, manager):
        assert manager._path_for('zhihu') == manager._path_for('zhihu', '')
        assert manager._path_for('zhihu').endswith('zhihu_cookies.json')

    def test_a_named_account_inserts_one_segment(self, manager):
        assert manager._path_for('zhihu', 'work').endswith('zhihu@work_cookies.json')

    @pytest.mark.parametrize('bad', ['../x', 'a/b', 'A', 'has space', 'x' * 25, '@', 'q"uote'])
    def test_an_account_that_is_not_a_plain_word_is_refused(self, manager, bad):
        with pytest.raises(ValueError):
            manager._path_for('zhihu', bad)

    def test_is_account_answers_usability_without_raising(self):
        assert CookieManager.is_account('') is True
        assert CookieManager.is_account('work_2') is True
        assert CookieManager.is_account('Work') is False
        assert CookieManager.is_account('../x') is False

    def test_two_accounts_hold_two_sessions(self, manager):
        manager.save('weibo', COOKIES, 'a')
        manager.save('weibo', [], 'b')
        assert manager.load('weibo', 'a') == COOKIES
        assert manager.load('weibo', 'b') == []
        assert manager.load('weibo') == [], 'the default account is neither of them'

    def test_delete_removes_one_account_only(self, manager):
        manager.save('weibo', COOKIES, 'a')
        manager.save('weibo', COOKIES, 'b')
        manager.delete('weibo', 'a')
        assert manager.exists('weibo', 'a') is False
        assert manager.exists('weibo', 'b') is True

    def test_the_account_list_reads_filenames_not_sessions(self, manager):
        """The panel and the matrix options ask "which accounts exist"; the answer
        comes from the file listing, and no cookie value is opened for it."""
        manager.save('zhihu', COOKIES)
        manager.save('zhihu', COOKIES, 'work')
        manager.save('zhihu', COOKIES, 'alt')
        assert manager.account_files('zhihu') == ['alt', 'work']

    def test_names_that_are_not_account_files_are_ignored(self, manager):
        os.makedirs(manager.cookie_dir, exist_ok=True)
        with open(os.path.join(manager.cookie_dir, 'zhihu_cookies.json'), 'w') as f:
            f.write('[]')
        with open(os.path.join(manager.cookie_dir, 'zhihu@_cookies.json'), 'w') as f:
            f.write('[]')
        with open(os.path.join(manager.cookie_dir, 'zhihu@Bad-Name_cookies.json'), 'w') as f:
            f.write('[]')
        assert manager.account_files('zhihu') == [], 'only well-formed named files count'
