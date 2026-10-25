"""``scheduler`` — the clock, its two seams, and the one start path it is allowed to use.

The clock owns no way to start a run: ``app.py`` injects a starter, so a scheduled fire goes
through the same ``_begin_run`` a manual 执行 does. What is pinned here is therefore the
scheduler's own behaviour: which tasks a tick fires and which it leaves alone, what each outcome is
written down as (started / queued / refused / error), that a refused or crashed task does not fire
in a loop, that a manual 立即执行 keeps a cron slot on its wall clock, that the language of a fire
comes from the TASK rather than from whatever request ran last, and that a moment which passed
while nobody was ticking is counted once at boot instead of replayed.

No thread is left running: the module-level thread is stopped by the fixture, because a daemon
still ticking would fire a later test's tasks.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
import scheduler as scheduler_module

from config import Config
from i18n import get_lang, set_lang, t
from services import cron
from services import schedule_store as store

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Its own store file, no injected seams, and no thread left behind."""
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(scheduler_module, '_starter', None)
    monkeypatch.setattr(scheduler_module, '_canvas_source', None)
    yield
    scheduler_module.stop()


def _save(now=NOW, **over):
    raw = {
        'name': '每天早八',
        'workflow': '红果短剧',
        'trigger': {'kind': 'daily', 'at': '08:00'},
        'timezone': 'Asia/Shanghai',
    }
    raw.update(over)
    task, error = store.save_task(raw, now)
    assert error == '', error
    return task


def _starter_recording(answers):
    """A starter that answers in turn and writes down what it was asked."""
    calls = []

    def starter(task, manual):
        calls.append((task['id'], manual))
        return answers[min(len(calls), len(answers)) - 1]

    return starter, calls


class TestTick:
    def test_a_due_task_fires_and_a_future_one_is_left_alone(self):
        due = _save(trigger={'kind': 'interval', 'minutes': 1}, name='到点了')
        later = _save(now=NOW + timedelta(hours=40), name='明天')
        starter, calls = _starter_recording([{'ok': True, 'run_id': 'run-1'}])
        scheduler_module.set_run_starter(starter)

        results = scheduler_module.tick(NOW + timedelta(minutes=2))

        assert [row['id'] for row in results] == [due['id']]
        assert results[0]['status'] == 'started' and results[0]['run_id'] == 'run-1'
        assert results[0]['manual'] is False and results[0]['name'] == '到点了'
        assert calls == [(due['id'], False)]
        assert store.get_task(due['id'])['last_run']['status'] == 'started'
        assert store.get_task(later['id'])['history'] == []

    def test_a_disabled_task_is_not_fired(self):
        task = _save(trigger={'kind': 'interval', 'minutes': 1})
        store.set_enabled(task['id'], False, NOW)
        starter, calls = _starter_recording([{'ok': True}])
        scheduler_module.set_run_starter(starter)

        assert scheduler_module.tick(NOW + timedelta(minutes=5)) == []
        assert calls == []

    def test_a_queued_fire_is_written_as_queued(self):
        task = _save(trigger={'kind': 'interval', 'minutes': 1})
        scheduler_module.set_run_starter(lambda task, manual: {'ok': True, 'queued': True, 'note': '第 2 位'})

        row = scheduler_module.tick(NOW + timedelta(minutes=2))[0]

        assert row['status'] == 'queued' and row['run_id'] == ''
        assert store.get_task(task['id'])['last_run']['note'] == '第 2 位'

    def test_a_refused_fire_is_recorded_and_the_clock_still_moves(self):
        """A task the executor refuses must not be asked again every tick, forever."""
        task = _save(trigger={'kind': 'interval', 'minutes': 1})
        scheduler_module.set_run_starter(lambda task, manual: {'ok': False, 'error': '需要模型'})

        first = scheduler_module.tick(NOW + timedelta(minutes=2))[0]
        assert first['status'] == 'refused' and first['note'] == '需要模型'
        moved = store.get_task(task['id'])['next_run']
        assert store.stamp(moved) > NOW + timedelta(minutes=2), 'a refused task kept its past moment'

    def test_a_start_that_raises_is_written_as_an_error_and_names_itself_once(self, caplog):
        task = _save(trigger={'kind': 'interval', 'minutes': 1})
        other = _save(trigger={'kind': 'interval', 'minutes': 1}, name='另一个')

        def exploding(task, manual):
            if task['id'] == task_id:
                raise RuntimeError('the executor fell over')
            return {'ok': True, 'run_id': 'run-2'}

        task_id = task['id']
        scheduler_module.set_run_starter(exploding)
        with caplog.at_level(logging.ERROR, logger='scheduler'):
            results = scheduler_module.tick(NOW + timedelta(minutes=2))

        by_id = {row['id']: row for row in results}
        assert by_id[task['id']]['status'] == 'error' and 'fell over' in by_id[task['id']]['note']
        assert by_id[other['id']]['status'] == 'started', 'one broken task stopped the whole tick'
        assert [record.getMessage() for record in caplog.records] == [t('sched.startFailed', name='每天早八')]

    def test_the_same_moment_does_not_fire_twice(self):
        _save(trigger={'kind': 'interval', 'minutes': 1})
        starter, calls = _starter_recording([{'ok': True}])
        scheduler_module.set_run_starter(starter)

        assert len(scheduler_module.tick(NOW + timedelta(minutes=2))) == 1
        assert scheduler_module.tick(NOW + timedelta(minutes=2)) == []
        assert len(calls) == 1

    def test_a_task_whose_stored_moment_is_unreadable_is_skipped(self, tmp_path):
        """Re-saving it from the panel repairs it; guessing a moment would fire it wrongly."""
        task = _save(trigger={'kind': 'interval', 'minutes': 1})
        path = tmp_path / 'schedules.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        payload['tasks'][0]['next_run'] = 'sometime'
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        scheduler_module.set_run_starter(lambda task, manual: {'ok': True})

        assert scheduler_module.tick(NOW + timedelta(minutes=2)) == []
        assert store.get_task(task['id'])['next_run'] == 'sometime'

    def test_an_unwired_starter_refuses_by_name_instead_of_starting_anything(self):
        task = _save(trigger={'kind': 'interval', 'minutes': 1})
        row = scheduler_module.tick(NOW + timedelta(minutes=2))[0]
        assert row['status'] == 'refused' and row['note'] == t('sched.notWired')
        assert store.get_task(task['id'])['last_run']['note'] == t('sched.notWired')


class TestFireNow:
    def test_a_manual_fire_runs_a_task_that_is_switched_off(self):
        """立即执行 is a button, not the schedule: a disabled task can still be run by hand."""
        task = _save()
        store.set_enabled(task['id'], False, NOW)
        starter, calls = _starter_recording([{'ok': True, 'run_id': 'run-9'}])
        scheduler_module.set_run_starter(starter)

        answer = scheduler_module.fire_now(task['id'])

        assert answer['ok'] is True and answer['result']['manual'] is True
        assert calls == [(task['id'], True)]

    def test_a_manual_fire_keeps_a_cron_slot_where_it_was(self):
        task = _save()
        scheduler_module.set_run_starter(lambda task, manual: {'ok': True})
        before = store.get_task(task['id'])['next_run']

        scheduler_module.fire_now(task['id'])

        assert store.get_task(task['id'])['next_run'] == before

    def test_a_manual_fire_of_an_interval_re_anchors_it(self):
        task = _save(trigger={'kind': 'interval', 'minutes': 30})
        scheduler_module.set_run_starter(lambda task, manual: {'ok': True})
        now = cron.now()

        scheduler_module.fire_now(task['id'])

        assert store.stamp(store.get_task(task['id'])['next_run']) > now + timedelta(minutes=29)

    def test_a_refusal_is_reported_and_recorded(self):
        task = _save()
        scheduler_module.set_run_starter(lambda task, manual: {'ok': False, 'error': '画布找不到'})

        answer = scheduler_module.fire_now(task['id'])

        assert answer['ok'] is False and answer['error'] == '画布找不到'
        assert store.get_task(task['id'])['last_run']['status'] == 'refused'

    def test_a_task_that_is_not_there_is_refused_by_name(self):
        assert scheduler_module.fire_now('nope') == {'ok': False, 'error': t('sched.taskMissing', id='nope')}


class TestTheLanguageOfAFire:
    def test_a_fire_pins_the_task_own_language(self):
        """``set_lang`` is thread-local and a daemon starts fresh — read it from the task."""
        _save(lang='en')
        seen = []
        scheduler_module.set_run_starter(lambda task, manual: seen.append(get_lang()) or {'ok': True})
        set_lang('zh')

        scheduler_module.tick(NOW + timedelta(hours=40))

        assert seen == ['en']


class TestLoadCanvas:
    def test_an_unwired_source_refuses_by_name(self):
        assert scheduler_module.load_canvas('x') == {'workflow': None, 'error': t('sched.notWired')}

    def test_a_wired_source_answers_with_the_canvas(self):
        scheduler_module.set_canvas_source(lambda name: {'workflow': {'nodes': [{'type': 'name'}]}, 'error': ''})
        assert scheduler_module.load_canvas('红果短剧')['workflow'] == {'nodes': [{'type': 'name'}]}

    def test_a_source_that_raises_is_refused_with_its_own_message(self, caplog):
        def broken(name):
            raise OSError('the file went away')

        scheduler_module.set_canvas_source(broken)
        with caplog.at_level(logging.ERROR, logger='scheduler'):
            answer = scheduler_module.load_canvas('红果短剧')

        assert answer['workflow'] is None and 'the file went away' in answer['error']
        assert [record.getMessage() for record in caplog.records] == [t('sched.canvasReadFailed', name='红果短剧')]

    def test_a_source_that_answers_nonsense_is_not_believed(self):
        scheduler_module.set_canvas_source(lambda name: 'yes')
        assert scheduler_module.load_canvas('x')['error'] == t('sched.notWired')


class TestTheThread:
    def test_starting_twice_starts_one_clock_and_stopping_ends_it(self):
        assert scheduler_module.is_running() is False
        assert scheduler_module.start() is True
        try:
            assert scheduler_module.is_running() is True
            assert scheduler_module.start() is False, 'a second call started a second clock'
        finally:
            scheduler_module.stop()
        assert scheduler_module.is_running() is False

    def test_stopping_a_clock_that_never_started_is_safe(self):
        scheduler_module.stop()
        assert scheduler_module.is_running() is False

    def test_booting_counts_the_moments_the_server_was_down(self):
        """Startup is where a missed moment is recorded — the restart does not replay it."""
        task = _save()
        # ``start()`` asks the REAL clock, so the moment that was missed is written in the past
        # directly rather than simulated with a fake ``now``.
        payload = store.get_task(task['id'])
        payload['next_run'] = (cron.now() - timedelta(days=2)).isoformat()
        store._save([payload])

        assert scheduler_module.start() is True
        try:
            assert store.get_task(task['id'])['missed']['count'] == 1
            assert store.stamp(store.get_task(task['id'])['next_run']) > cron.now()
        finally:
            scheduler_module.stop()


class TestStatus:
    def test_it_says_which_box_this_is_and_what_it_calls_now(self):
        status = scheduler_module.status()
        assert status['running'] is False and status['wired'] is False
        assert status['now_local'] == cron.now().astimezone().strftime('%Y-%m-%d %H:%M')
        assert 'UTC' in status['local_zone']
        assert status['tick_seconds'] == max(5, int(Config.SCHEDULER_TICK_SECONDS or 20))

    def test_a_tick_interval_that_is_unset_or_absurd_still_ticks_sanely(self, monkeypatch):
        """``0`` reads as "not stated" (the house rule for a setting), and a tiny one is floored."""
        monkeypatch.setattr(Config, 'SCHEDULER_TICK_SECONDS', 0)
        assert scheduler_module.status()['tick_seconds'] == 20
        monkeypatch.setattr(Config, 'SCHEDULER_TICK_SECONDS', 3)
        assert scheduler_module.status()['tick_seconds'] == 5
        monkeypatch.setattr(Config, 'SCHEDULER_TICK_SECONDS', 60)
        assert scheduler_module.status()['tick_seconds'] == 60

    def test_the_env_var_wins_over_the_os_name(self, monkeypatch):
        monkeypatch.setenv('TZ', 'Asia/Shanghai')
        assert scheduler_module.local_zone_name().startswith('Asia/Shanghai')
        monkeypatch.delenv('TZ')
        assert scheduler_module.local_zone_name(), 'the OS answer is missing entirely'


def test_the_shared_starter_is_retention_queue_then_clock(monkeypatch):
    """One definition, two entry points (`__main__` and the frozen launcher).

    The order matters: a parked request is restored before serving starts, and the clock's first
    tick records the moments that passed while the server was down — so both run before the tick
    thread exists, not after.
    """
    import app as app_module

    calls = []
    monkeypatch.setattr(app_module, '_housekeep', lambda *args, **kwargs: calls.append('housekeep'))
    monkeypatch.setattr(app_module, '_load_pending_queue', lambda: 0)
    monkeypatch.setattr(app_module.scheduler, 'start', lambda: calls.append('clock') or True)
    app_module.start_background_services()
    assert calls == ['housekeep', 'clock']
