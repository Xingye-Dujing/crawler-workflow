"""#2: the 慢速采集 (``gentle_crawl``) switch — pacing only, never the browser's identity.

Two contracts, both pure enough to test without a browser:

* :func:`throttled_sleep` and :meth:`Crawler._polite_pause` stretch every inter-action pause by
  :data:`GENTLE_PAUSE_FACTOR` when the switch is on, and behave exactly as before when it is off
  (the default — so landing this changes nothing on any current crawl).
* :meth:`DouyinCrawler._latch_risk_if_walled` turns a 验证码中间页 into ``risk_blocked`` (back-off)
  and refuses to latch a login wall there, because the two carry opposite advice.
"""

import pytest

import crawlers.base as base_module
from crawlers.base import GENTLE_PAUSE_FACTOR, Crawler, throttled_sleep
from crawlers.douyin import DouyinCrawler

pytestmark = pytest.mark.unit


@pytest.fixture
def slept(monkeypatch):
    """Capture every sleep this module would take, without actually waiting."""
    calls: list[float] = []
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: calls.append(s))
    return calls


@pytest.fixture
def no_jitter(monkeypatch):
    """Make :meth:`_polite_pause` deterministic: a zero jitter means the pause is exactly *base*."""
    monkeypatch.setattr(base_module.random, 'uniform', lambda _a, _b: 0.0)


def _set_gentle(monkeypatch, value: bool):
    monkeypatch.setattr(base_module, 'get_setting', lambda key: value if key == 'gentle_crawl' else None)


def test_throttled_sleep_is_untouched_when_off(monkeypatch, slept):
    _set_gentle(monkeypatch, False)
    throttled_sleep(2.0)
    assert slept == [2.0], 'off is today: the requested pause, unscaled'


def test_throttled_sleep_scales_when_gentle(monkeypatch, slept):
    _set_gentle(monkeypatch, True)
    throttled_sleep(2.0)
    assert slept == [2.0 * GENTLE_PAUSE_FACTOR], 'gentle multiplies the wait — speed only'


def test_polite_pause_off_matches_jittered_base(monkeypatch, slept, no_jitter):
    _set_gentle(monkeypatch, False)
    Crawler._polite_pause(1.0, 0.4)
    assert slept == [1.0]


def test_polite_pause_gentle_stretches_the_base(monkeypatch, slept, no_jitter):
    _set_gentle(monkeypatch, True)
    Crawler._polite_pause(1.0, 0.4)
    assert slept == [1.0 * GENTLE_PAUSE_FACTOR]


def test_polite_pause_floor_scales_too(monkeypatch, slept, no_jitter):
    """Even the 0.2 s floor rides the multiplier, so a gentle crawl never drops back to metronome
    speed on a fast round — the whole point is the rhythm, not one long sleep."""
    _set_gentle(monkeypatch, True)
    Crawler._polite_pause(0.0, 0.0)  # jitter-free, base below the floor
    assert slept == [0.2 * GENTLE_PAUSE_FACTOR]


def test_negative_sleep_is_clamped_not_inverted(slept):
    throttled_sleep(-5.0)
    assert slept == [0.0], 'this scales a pause; it must never schedule a negative or invert it'


class _WalledProbe:
    """A receiver with just enough surface for the unbound :meth:`_latch_risk_if_walled`."""

    def __init__(self, walled: bool, login_wall: bool = False):
        self._walled = walled
        self.login_wall = login_wall
        self.risk_blocked = False

    def _is_walled(self) -> bool:
        return self._walled


def test_a_captcha_latches_risk_not_a_cookie():
    probe = _WalledProbe(walled=True)
    DouyinCrawler._latch_risk_if_walled(probe)
    assert probe.risk_blocked is True, 'a 验证码中间页 is 风控: latch it so the executor backs off'


def test_a_login_wall_is_left_to_the_cookie_path():
    """A login wall already sets ``login_wall`` and is owned by the cookie verdict; latching risk
    too would blur the two refusals this repo keeps deliberately apart."""
    probe = _WalledProbe(walled=True, login_wall=True)
    DouyinCrawler._latch_risk_if_walled(probe)
    assert probe.risk_blocked is False, 'a login wall must not also read as risk control'


def test_an_unwalled_page_latches_nothing():
    probe = _WalledProbe(walled=False)
    DouyinCrawler._latch_risk_if_walled(probe)
    assert probe.risk_blocked is False
