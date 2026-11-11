"""The 慢速采集 preset's pacing contract — one scale, never the browser's identity.

The preset writes ``crawl_pace_scale`` / ``crawl_wait_scale`` / ``crawl_patience_scale``
as concrete values (see ``runtime.settings_schema.PRESETS``); these tests prove the one
consumer, :mod:`crawlers.engine.pacing`, applies them exactly once and leaves a
default install at the measured baseline. The douyin risk latch lives here for the same
historical reason: the two checks share "what a platform refusing looks like".

Pacing is pure enough to test without a browser: sleep is patched on the module that
owns it.
"""

import pytest

import crawlers.engine.pacing as pacing_module
from crawlers.core.crawler import Crawler
from crawlers.engine.pacing import rounds, throttled_sleep, wait
from crawlers.platforms.douyin.crawler import DouyinCrawler

pytestmark = pytest.mark.unit


@pytest.fixture
def slept(monkeypatch):
    """Capture every sleep this module would take, without actually waiting."""
    calls: list[float] = []
    monkeypatch.setattr(pacing_module.time, 'sleep', calls.append)
    return calls


@pytest.fixture
def no_jitter(monkeypatch):
    """Make the pause deterministic: a zero jitter means the pause is exactly *base*."""
    monkeypatch.setattr(pacing_module.random, 'uniform', lambda _a, _b: 0.0)


def _configure(monkeypatch, *, pace=1.0, wait_scale=1.0, patience=1.0):
    values = {
        'crawl_pace_scale': pace,
        'crawl_wait_scale': wait_scale,
        'crawl_patience_scale': patience,
    }

    def _setting(key):
        return values.get(key)

    monkeypatch.setattr(pacing_module, 'get_setting', _setting)


def test_throttled_sleep_defaults_to_the_requested_pause(monkeypatch, slept):
    _configure(monkeypatch)
    throttled_sleep(2.0)
    assert slept == [2.0], 'a default install is exactly today: the requested pause, unscaled'


def test_throttled_sleep_scales_once(monkeypatch, slept):
    _configure(monkeypatch, pace=4.0)
    throttled_sleep(2.0)
    assert slept == [8.0], 'the slow preset multiplies the pause — speed only'


def test_polite_pause_default_matches_jittered_base(monkeypatch, slept, no_jitter):
    _configure(monkeypatch)
    Crawler._polite_pause(1.0, 0.4)
    assert slept == [1.0]


def test_polite_pause_scales_the_base(monkeypatch, slept, no_jitter):
    _configure(monkeypatch, pace=4.0)
    Crawler._polite_pause(1.0, 0.4)
    assert slept == [4.0]


def test_polite_pause_floor_scales_too(monkeypatch, slept, no_jitter):
    """Even the 0.2 s floor rides the multiplier, so a slow crawl never drops back to
    metronome speed on a fast round — the point is the rhythm, not one long sleep."""
    _configure(monkeypatch, pace=4.0)
    Crawler._polite_pause(0.0, 0.0)
    assert slept == [0.2 * 4.0]


def test_negative_sleep_is_clamped_not_inverted(slept):
    throttled_sleep(-5.0)
    assert slept == [], 'this scales a pause; it must never schedule a negative sleep'


def test_wait_and_rounds_scale_once(monkeypatch):
    _configure(monkeypatch, wait_scale=2.0, patience=2.0)
    assert wait(1.5) == 3.0
    assert rounds(3) == 6


def test_rounds_never_reaches_zero(monkeypatch):
    _configure(monkeypatch, patience=1.0)
    assert rounds(0) == 1


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
