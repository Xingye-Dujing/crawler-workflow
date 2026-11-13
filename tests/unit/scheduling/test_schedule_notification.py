"""A scheduled fire with nobody at the desk is the one start worth a system notification.

The tray itself is tested in ``tests/unit/desktop/test_desktop_shell.py``; this pins the decision:
an automatic fire notifies, a manual "run now" from the panel does not (the person who pressed it
is already looking at the answer).
"""

from __future__ import annotations

import pytest

from engine import run_schedule
from i18n import t
from services import desktop

pytestmark = pytest.mark.unit


@pytest.fixture()
def fired(monkeypatch):
    sent = []
    monkeypatch.setattr(run_schedule, 'scheduled_canvas', lambda name: {'workflow': {}, 'error': ''})
    monkeypatch.setattr(run_schedule, '_scheduled_session_gate', lambda workflow: '')
    monkeypatch.setattr(desktop, 'notify', lambda title, message='': sent.append((title, message)) and True)

    import engine.run as run_engine

    monkeypatch.setattr(
        run_engine,
        'begin_run',
        lambda data, lang: {'status': 200, 'body': {'ok': True, 'queued': False, 'run_id': 'r1'}},
    )
    return sent


def test_an_automatic_fire_notifies(fired):
    answer = run_schedule.start_scheduled_run({'name': '早报', 'workflow': 'w'}, manual=False)
    assert answer['ok'] is True
    assert fired == [(t('desktop.schedStartTitle'), t('desktop.schedStartBody', name='早报'))]


def test_a_queued_fire_waits_for_its_own_start(fired, monkeypatch):
    import engine.run as run_engine

    monkeypatch.setattr(
        run_engine,
        'begin_run',
        lambda data, lang: {'status': 200, 'body': {'ok': True, 'queued': True, 'run_id': 'r1'}},
    )
    run_schedule.start_scheduled_run({'name': '早报', 'workflow': 'w'}, manual=False)
    assert fired == [], 'a parked fire has not started; the run itself will announce the finish'


def test_a_manual_trigger_does_not_notify(fired):
    run_schedule.start_scheduled_run({'name': '早报', 'workflow': 'w'}, manual=True)
    assert fired == []
