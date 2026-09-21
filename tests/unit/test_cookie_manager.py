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
    def test_only_crawlable_platforms_are_supported(self):
        assert CookieManager.PLATFORMS == ('zhihu', 'weibo', 'xiaohongshu', 'wechat')
        assert all(CookieManager.is_supported(p) for p in CookieManager.PLATFORMS)

    @pytest.mark.parametrize('platform', ['ZHIHU', 'zhihu ', '', None, 'douyin', 'zh'])
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
        manager.save('wechat', COOKIES)
        with open(manager._path_for('wechat'), encoding='utf-8') as handle:
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
