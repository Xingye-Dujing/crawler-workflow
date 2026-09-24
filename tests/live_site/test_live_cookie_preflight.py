"""The pre-run Cookie gate against a real platform, in a real browser.

The fast tier swaps the one function that buys a browser, which is right for every
decision around it but blind to the call itself: whether ``diagnose`` still answers
what the gate reads off it, whether the browser is really closed, and whether the
cached verdict spares the user a second Chrome. Those are only true of the real
object, so they are measured here — against a site, with the session the user
actually saved.

Deliberately ``live_site`` and not ``live_quick``: the daily gate has no business
opening a window on the developer's desktop, and what this checks cannot regress
without the whole crawl breaking first (which the quick tier would catch).

The verdict itself is not asserted as valid or expired. Which of the two a machine
answers on a given afternoon is the site's choice — a cookie can genuinely be dead
here, and the tier's job is to prove the check *works*, not to vouch for the session.
"""

from pathlib import Path

import cookie_preflight
import pytest

from config import Config

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

REPO_ROOT = Path(__file__).resolve().parents[2]
COOKIE_DIR = REPO_ROOT / 'data' / 'cookies'

#: A platform whose saved session is the ordinary case on this machine, and whose
#: login page is a plain page load: bilibili answers a logged-out visitor with
#: content, so the interesting thing measured is the browser path, not the wall.
PLATFORM = 'bilibili'
DECIDED = {
    cookie_preflight.VALID,
    cookie_preflight.EXPIRED,
    cookie_preflight.UNKNOWN,
    cookie_preflight.NO_COOKIE,
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    """No verdict inherited from a previous probe."""
    cookie_preflight.reset()
    yield
    cookie_preflight.reset()


@pytest.fixture
def real_jar(monkeypatch):
    """Point the gate at the sessions the user actually saved, and skip when this
    platform has none — the tier's standing contract, not a way of avoiding a
    failure: without a session there is no browser path to measure.

    ``tests/conftest`` redirects ``Config.COOKIE_DIR`` into a throwaway directory,
    which is right for the fast tiers and would mean "nobody has a cookie" here.
    """
    if not (COOKIE_DIR / f'{PLATFORM}_cookies.json').exists():
        pytest.skip(f'no saved cookies for {PLATFORM}')
    monkeypatch.setattr(Config, 'COOKIE_DIR', str(COOKIE_DIR))
    return str(COOKIE_DIR)


class TestRealProbe:
    def test_the_probe_runs_end_to_end_and_closes_its_browser(self, real_jar):
        """Whatever the site answers, the gate must come back with a *decided* verdict
        and no leaked Chrome. A probe that hung, or that closed the browser only on
        the happy path, is a window left on the user's desktop holding their profile
        — which then parks the run that follows on ``PROFILE_LOCK_TIMEOUT``.
        """
        import browser_profiles

        profile = browser_profiles.profile_dir_for(PLATFORM)
        assert browser_profiles.is_busy(profile) is False, 'a probe may not queue behind a live crawl'
        verdict = cookie_preflight.probe(PLATFORM)
        assert verdict['state'] in DECIDED, verdict
        assert verdict['probed'] is True, f'a saved session was never looked at: {verdict}'
        assert verdict['blocking'] is (verdict['state'] in cookie_preflight.BLOCKING), verdict
        assert browser_profiles.is_busy(profile) is False, 'the probe left its browser holding the profile'

    def test_the_second_ask_within_the_ttl_buys_no_second_browser(self, monkeypatch, real_jar):
        """The cache is the whole reason a parallel canvas can afford this check at
        all, so it has to be measured against a real probe rather than a stub."""
        real = cookie_preflight._probe_live
        calls = []

        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        monkeypatch.setattr(cookie_preflight, '_probe_live', counting)
        cookie_preflight.probe(PLATFORM)
        second = cookie_preflight.probe(PLATFORM)
        assert len(calls) == 1, f'a cached verdict still opened {len(calls)} browsers'
        assert second['cached'] is True and second['probed'] is False

    def test_a_rendered_sentence_comes_back_for_the_platform(self):
        """The gate shows server-rendered wording rather than a key the browser would
        have to translate twice; an unresolved key would print as gibberish."""
        verdict = cookie_preflight.probe(PLATFORM)
        text = cookie_preflight.describe(verdict)
        assert text and 'cookie.pre.' not in text, text
        assert PLATFORM in text or '平台' in text, text
