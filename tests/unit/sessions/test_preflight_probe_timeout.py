"""The pre-run probe is the one browser a slow-mode run opens before it starts.

Measured shape (2026-11-14, user's packaged build): 慢速采集 turns 自动验证 on, a visible
Chrome lands on the platform's home page, and it is still there four minutes later. The
probe's *endpoint* budget answered “无法核对” and the run started, but the browser thread
was left in ``WaitForPendingNavigations`` holding the window and the profile. This pins the
fix: the probe bounds its own page load and closes the browser when it does not answer.
"""

import threading
import time

import pytest
from runtime import paths
from sessions import preflight

pytestmark = pytest.mark.unit


class _Scope:
    cookie_dir = '/tmp/nowhere'


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, 'active', lambda: _Scope())
    preflight.reset()
    yield
    preflight.reset()


def test_a_probe_that_never_answers_is_closed_at_its_budget(monkeypatch):
    closed = []

    class _Crawler:
        risk_blocked = False

        def diagnose(self, url=''):
            threading.Event().wait(5)

        def close(self):
            closed.append(True)

    monkeypatch.setattr('crawlers.get_crawler', lambda *a, **k: _Crawler())
    monkeypatch.setattr(preflight, '_probe_budget', lambda: 0.2)
    started = time.monotonic()
    facts = preflight._probe_live('xiaohongshu')
    elapsed = time.monotonic() - started
    assert 'error' in facts, facts
    assert closed == [True], 'a wedged probe left its window and profile behind'
    assert elapsed < 2.0, f'the probe outlived its own budget: {elapsed:.1f}s'


def test_a_probe_that_answers_reports_its_facts(monkeypatch):
    closed = []

    class _Crawler:
        risk_blocked = True

        def diagnose(self, url=''):
            return {'login_wall': False, 'unreachable': False}

        def close(self):
            closed.append(True)

    monkeypatch.setattr('crawlers.get_crawler', lambda *a, **k: _Crawler())
    facts = preflight._probe_live('xiaohongshu')
    assert facts == {'login_wall': False, 'risk_blocked': True, 'unreachable': False}
    assert closed == [True]
