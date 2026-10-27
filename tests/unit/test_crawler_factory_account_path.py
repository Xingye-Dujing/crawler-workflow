"""One account, ONE spelling of where its session lives.

The default login has two spellings — its NAME (``default``, which is what the candidate list
and a new node's preselection hand out) and the historical BLANK every old canvas carries — and
:``CookieManager.path_segment`` is the single place that folds them onto the same unsuffixed
file. The factory built its own ``<platform>@<account>`` name instead, so a default-account
crawl read ``weibo@default_cookies.json``: a file ``path_for`` never writes and
``account_files`` refuses even to list. ``file_stamp`` of a path that cannot exist is ``''``,
which blanked the profile's cookie stamp and permanently disarmed the deferred re-plant, and a
「本次不用 Profile」 crawl then loaded no session at all and said nothing.

No browser is bought here: the class lookup is stubbed and the factory's decisions are read off
the object it was handed.
"""

import pytest
from sessions import profiles
from sessions.cookies import CookieManager

import crawlers

pytestmark = [pytest.mark.unit]


class _StubCrawler:
    """Records what the factory decided, so nothing has to launch Chrome to be tested."""

    def __init__(self, headless=True, cookie_path=None, for_login=False, profile_dir=None, abort=None):
        self.headless = headless
        self.cookie_path = cookie_path
        self.for_login = for_login
        self.profile_dir = profile_dir
        self.abort = abort


@pytest.fixture
def stub_factory(monkeypatch):
    """Answer every platform with the stub, and keep the profile questions off the disk."""
    monkeypatch.setattr(crawlers, 'crawler_class', lambda platform: _StubCrawler)
    monkeypatch.setattr(profiles, 'profile_dir_for', lambda platform, enabled=None, account='': None)
    monkeypatch.setattr(profiles, 'needs_refresh', lambda platform, path, account='': False)
    monkeypatch.setattr(profiles, 'is_used', lambda platform, account='': True)
    monkeypatch.setattr(profiles, 'file_stamp', lambda path: 'stamp' if path else '')
    monkeypatch.setattr(profiles, 'mark_used', lambda *a, **k: None)


@pytest.mark.parametrize('account', ['', '   ', 'default', 'DEFAULT'])
def test_the_default_login_is_one_file_under_either_spelling(stub_factory, account):
    """``default`` and blank are the same session, so they must be the same FILE. The factory
    used to splice ``weibo@default_cookies.json`` for the named spelling — a path no writer
    produces, which read as 「no cookie」 and silently crawled anonymous."""
    made = crawlers.get_crawler('weibo', cookie_dir='C:/jar', account=account)
    assert made.cookie_path == 'C:/jar/weibo_cookies.json', made.cookie_path


def test_a_named_account_keeps_its_own_file_and_the_factory_agrees_with_the_manager(stub_factory):
    """The other half of the rule: a real second login DOES have its own file, and the path the
    factory builds is exactly the one CookieManager writes — not a second spelling of it."""
    expected = CookieManager('C:/jar').path_for('weibo', 'work')
    made = crawlers.get_crawler('weibo', cookie_dir='C:/jar', account='work')
    assert made.cookie_path.replace('\\', '/') == expected.replace('\\', '/'), made.cookie_path
    assert 'weibo@work_cookies.json' in made.cookie_path


def test_the_platform_that_holds_no_session_still_builds_no_cookie_file(stub_factory):
    """WeChat is not in CookieManager.PLATFORMS (its bodies need no login), so folding through
    the manager's validating path builder would refuse a crawl that has never wanted a cookie.
    The fold must not turn 「no session」 into an exception."""
    made = crawlers.get_crawler('wechat', cookie_dir='C:/jar', account='default')
    assert made.cookie_path == 'C:/jar/wechat_cookies.json'
