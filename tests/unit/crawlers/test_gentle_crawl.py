"""The 慢速采集 preset's pacing contract — one knob per interval, never the browser's identity.

The preset writes ``crawl_pace_scale`` / ``crawl_scroll_scale`` / ``crawl_expand_scale`` /
``crawl_click_scale`` / ``crawl_wait_scale`` / ``crawl_arrival_scale`` /
``crawl_patience_scale`` as concrete values (see ``runtime.settings_schema.PRESETS``);
these tests prove the one consumer, :mod:`crawlers.engine.pacing`, applies each of them
exactly once, to its own dimension, and leaves a default install at the measured
baseline. The douyin risk latch lives here for the same historical reason: the two
checks share "what a platform refusing looks like".

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


def _configure(
    monkeypatch,
    *,
    pace=1.0,
    scroll=1.0,
    expand=1.0,
    click=1.0,
    wait_scale=1.0,
    arrival=1.0,
    page=1.0,
    jitter=0.0,
    patience=1.0,
):
    values = {
        'crawl_pace_scale': pace,
        'crawl_scroll_scale': scroll,
        'crawl_expand_scale': expand,
        'crawl_click_scale': click,
        'crawl_wait_scale': wait_scale,
        'crawl_arrival_scale': arrival,
        'crawl_page_scale': page,
        'crawl_jitter': jitter,
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


class TestEachDimensionIsItsOwnKnob:
    """Splitting the three scales into seven: a scroll no longer moves an expand, etc.

    Each pause sleeps through the module's own clock so the assertion is the number of
    seconds a platform would really pay, not a reader's arithmetic.
    """

    def test_each_nap_reads_its_own_dimension(self, monkeypatch, slept):
        _configure(monkeypatch, pace=2.0, scroll=3.0, expand=4.0, click=5.0, arrival=6.0)
        pacing_module.nap(1.0)
        pacing_module.scroll_nap(1.0)
        pacing_module.expand_nap(1.0)
        pacing_module.click_nap(1.0)
        pacing_module.arrival_nap(1.0)
        assert slept == [2.0, 3.0, 4.0, 5.0, 6.0], 'one dimension may not borrow another multiplier'

    def test_a_dimension_left_at_baseline_is_untouched(self, monkeypatch, slept):
        _configure(monkeypatch, scroll=3.0)
        pacing_module.expand_nap(2.0)
        pacing_module.scroll_nap(2.0)
        assert slept == [2.0, 6.0]

    def test_waits_follow_the_dimension_they_belong_to(self, monkeypatch):
        _configure(monkeypatch, scroll=2.0, expand=3.0, click=4.0, wait_scale=5.0, arrival=6.0)
        assert pacing_module.wait(1.0) == 5.0
        assert pacing_module.scroll_wait(1.0) == 2.0
        assert pacing_module.expand_wait(1.0) == 3.0
        assert pacing_module.click_wait(1.0) == 4.0
        assert pacing_module.arrival(1.0) == 6.0

    def test_wait_nap_rides_the_element_wait_dimension(self, monkeypatch, slept):
        _configure(monkeypatch, wait_scale=2.0, scroll=9.0)
        pacing_module.wait_nap(1.0)
        assert slept == [2.0]

    def test_the_page_interval_is_its_own_knob_and_keeps_the_jitter(self, monkeypatch, slept):
        """Between two pages a human is not a metronome: base ± spread, then the multiplier."""
        _configure(monkeypatch, page=3.0)
        pacing_module.page_nap(1.0)
        assert slept == [3.0], 'the page interval must ride its own multiplier, not the polite one'

        slept.clear()
        pacing_module.between_pages()  # the real draw: 1.0..2.2 s × 3
        assert len(slept) == 1 and 3.0 <= slept[0] <= 6.6, slept

        slept.clear()
        monkeypatch.setattr(pacing_module.random, 'uniform', lambda _a, _b: 0.0)
        pacing_module.between_pages()
        assert slept == [1.6 * 3.0]

    def test_a_poll_tick_is_never_stretched(self, monkeypatch, slept):
        _configure(monkeypatch, scroll=3.0)
        pacing_module.poll_tick(1.0)
        assert slept == [1.0], 'a poll tick inside a fixed budget is never stretched'

    def test_a_negative_dimension_is_clamped(self, monkeypatch, slept):
        _configure(monkeypatch, scroll=-4.0)
        pacing_module.scroll_nap(3.0)
        assert slept == []

    def test_jitter_spreads_the_beat_and_never_a_budget(self, monkeypatch, slept):
        """30% means 0.7–1.3×, on the beats only: a wait budget is a promise, not a rhythm."""
        _configure(monkeypatch, scroll=1.0, wait_scale=1.0, jitter=30.0)
        draws = iter([0.0, 0.999])
        # ``uniform(a, b)`` is called with (0.7, 1.3) for a 30% jitter; answer the ends.
        monkeypatch.setattr(pacing_module.random, 'uniform', lambda a, b: a if next(draws) < 0.5 else b)
        pacing_module.scroll_nap(2.0)
        pacing_module.expand_nap(2.0)
        assert [round(value, 2) for value in slept] == [1.4, 2.6], slept
        slept.clear()
        pacing_module.wait(2.0)  # returns, never sleeps: a budget is not a beat
        assert slept == []


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
