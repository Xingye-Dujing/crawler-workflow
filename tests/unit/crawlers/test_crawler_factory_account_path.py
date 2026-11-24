"""One account, ONE spelling of where its session lives.

The default login has two spellings — its NAME (``default``, which is what the candidate list
and a new node's preselection hand out) and the historical BLANK every old canvas carries — and
:``CookieManager.path_segment`` is the single place that folds them onto the same unsuffixed
file. The factory built its own ``<platform>@<account>`` name instead, so a default-account
crawl read ``weibo@default_cookies.json``: a file ``path_for`` never writes and
``account_files`` refuses even to list. ``file_stamp`` of a path that cannot exist is ``''``,
which blanked the profile's cookie stamp and permanently disarmed the deferred re-plant, and a
“本次不用 Profile” crawl then loaded no session at all and said nothing.

No browser is bought here: the class lookup is stubbed and the factory's decisions are read off
the object it was handed.
"""

import pytest
from sessions import naming, profiles
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
    produces, which read as "no cookie" and silently crawled anonymous."""
    made = crawlers.get_crawler('weibo', cookie_dir='C:/jar', account=account)
    assert made.cookie_path.replace('\\', '/') == 'C:/jar/weibo_cookies.json', made.cookie_path


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
    The fold must not turn "no session" into an exception."""
    made = crawlers.get_crawler('wechat', cookie_dir='C:/jar', account='default')
    assert made.cookie_path.replace('\\', '/') == 'C:/jar/wechat_cookies.json'


@pytest.mark.parametrize('account', ['', 'default', 'DEFAULT', 'work'])
def test_the_same_session_free_platform_asks_one_namer_for_the_name(stub_factory, account):
    """The factory used to splice ``<platform>@<account>_cookies.json`` by hand for a platform
    outside the manager — a second copy of the naming rule (W4 follow-up). Blank, the NAME
    ``default`` and a real label all go through ``sessions.naming.cookie_filename`` now, so the
    two spellings of one login cannot drift apart."""
    made = crawlers.get_crawler('wechat', cookie_dir='C:/jar', account=account)
    expected = naming.cookie_filename('wechat', account)
    assert made.cookie_path.replace('\\', '/') == f'C:/jar/{expected}', made.cookie_path


@pytest.mark.parametrize('account', ['work.home', 'x/../../y', 'has space', '桌号'])
def test_a_malformed_account_label_is_refused_by_name(stub_factory, account):
    """The factory spliced its own filename, so a bad label either walked out of the cookie dir
    or read a path no writer produces (anonymous crawl, no line saying the login was never used)."""
    with pytest.raises(ValueError) as caught:
        crawlers.get_crawler('weibo', cookie_dir='C:/jar', account=account)
    assert account in str(caught.value), str(caught.value)


def test_a_cookie_that_was_never_saved_is_not_recorded_as_imported(monkeypatch, tmp_path):
    """``mark_used`` must not claim a profile was given a session it never received.

    The flag tested the PATH, not the file: with a cookie dir configured and nothing saved yet,
    ``imported=True`` recorded ``cookie_stamp=''``, so the panel said 已导入 for an empty profile —
    and ``needs_refresh`` (which needs a non-empty stamp) answered "no" from then on, so a user who
    saved a Cookie afterwards was never offered the re-plant that would put it into that profile.
    """
    recorded = {}

    monkeypatch.setattr(crawlers, 'crawler_class', lambda platform: _StubCrawler)
    monkeypatch.setattr(profiles, 'profile_dir_for', lambda platform, enabled=None, account='': str(tmp_path / 'p'))
    monkeypatch.setattr(profiles, 'needs_refresh', lambda platform, path, account='': False)
    monkeypatch.setattr(profiles, 'is_used', lambda platform, account='': False)
    monkeypatch.setattr(profiles, 'file_stamp', lambda path: 'stamp' if path else '')
    monkeypatch.setattr(profiles, 'mark_used', lambda *a, **k: recorded.update(k))

    crawlers.get_crawler('weibo', cookie_dir=str(tmp_path / 'jar'), account='default')

    assert recorded.get('imported') is False, 'a missing cookie file was recorded as imported'


def test_a_cookie_that_is_there_is_still_imported(monkeypatch, tmp_path):
    """Positive control: the plant still happens for a file that exists."""
    recorded = {}
    jar = tmp_path / 'jar'
    jar.mkdir()
    (jar / 'weibo_cookies.json').write_text('[{"name": "SUB"}]', encoding='utf-8')

    monkeypatch.setattr(crawlers, 'crawler_class', lambda platform: _StubCrawler)
    monkeypatch.setattr(profiles, 'profile_dir_for', lambda platform, enabled=None, account='': str(tmp_path / 'p'))
    monkeypatch.setattr(profiles, 'needs_refresh', lambda platform, path, account='': False)
    monkeypatch.setattr(profiles, 'is_used', lambda platform, account='': False)
    monkeypatch.setattr(profiles, 'file_stamp', lambda path: 'stamp' if path else '')
    monkeypatch.setattr(profiles, 'mark_used', lambda *a, **k: recorded.update(k))

    crawlers.get_crawler('weibo', cookie_dir=str(jar), account='default')

    assert recorded.get('imported') is True


def test_a_jar_that_planted_nothing_is_not_recorded_as_imported(monkeypatch, tmp_path):
    """The file existing is not the same fact as its cookies reaching the browser."""
    recorded = {}
    jar = tmp_path / 'jar'
    jar.mkdir()
    (jar / 'weibo_cookies.json').write_text('[{"name": "SUB", "expiry": 1}]', encoding='utf-8')

    class _AppliedNothing(_StubCrawler):
        cookies_loaded = 0

    monkeypatch.setattr(crawlers, 'crawler_class', lambda platform: _AppliedNothing)
    monkeypatch.setattr(profiles, 'profile_dir_for', lambda platform, enabled=None, account='': str(tmp_path / 'p'))
    monkeypatch.setattr(profiles, 'needs_refresh', lambda platform, path, account='': False)
    monkeypatch.setattr(profiles, 'is_used', lambda platform, account='': False)
    monkeypatch.setattr(profiles, 'file_stamp', lambda path: 'stamp' if path else '')
    monkeypatch.setattr(profiles, 'mark_used', lambda *a, **k: recorded.update(k))

    crawlers.get_crawler('weibo', cookie_dir=str(jar), account='default')

    assert recorded.get('imported') is False, 'an expired jar was recorded as a planted session'
    assert recorded.get('cookie_stamp') == '', 'a stamp recorded for a jar that went in nowhere'
