"""``scheduling/store`` — what a scheduled task is, when it fires, and what it recorded.

The panel writes through four endpoints and the clock reads the same file, so this store carries
both halves of the feature. What is pinned here is its own contract, not the HTTP surface:

* a task round-trips, and its id — the key its own history is filed under — survives an edit;
* what the user WROTE is what is stored (「每天 08:00」 stays a preset, never silently rewritten
  into the cron string it means), while the moment it fires next is computed in the task's OWN
  zone;
* a rule that can never fire is refused while the user is looking at the form, not at 03:00;
* a moment that passed while the server was down is COUNTED once and skipped, never replayed —
  the whole reason ``note_missed`` exists;
* ``last_run`` / ``history`` / ``missed`` are the record of what the server did, so a request that
  carries them is ignored rather than believed.

``Config.DATA_DIR`` is repointed per test, so every write lands in a throwaway directory — the
store resolves its path on each call for exactly this reason.
"""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from core.config import Config
from scheduling import cron, store

from i18n import t

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SHANGHAI = ZoneInfo('Asia/Shanghai')


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """One empty ``schedules.json`` per test, under a root of its own."""
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))


def _save(now=NOW, **over):
    """A valid task with one field overridden — the shape every test starts from."""
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


class TestRoundTrip:
    def test_a_task_is_written_under_the_data_root_and_reads_back(self, tmp_path):
        task = _save()
        assert store._path() == str(tmp_path / 'schedules.json')
        stored = json.loads((tmp_path / 'schedules.json').read_text(encoding='utf-8'))
        assert stored['version'] == 1 and [row['id'] for row in stored['tasks']] == [task['id']]
        assert store.get_task(task['id'])['name'] == '每天早八'

    def test_the_panel_shape_carries_the_words_only_the_server_computes(self):
        row = store.public(_save())
        assert row['trigger_text'] == store.describe_trigger({'kind': 'daily', 'at': '08:00'})
        assert row['next_run_local'].endswith('(Asia/Shanghai)')
        assert row['timezone_label'] == 'Asia/Shanghai'
        assert row['enabled'] is True
        assert row['last_run_local'] == ''  # never run

    def test_a_new_task_gets_a_new_id_and_an_edit_keeps_the_old_one(self):
        first = _save()
        second = _save(name='另一个')
        assert first['id'] != second['id']
        edited, error = store.save_task(
            {'id': first['id'], 'name': '改名了', 'workflow': '红果短剧', 'trigger': first['trigger']}, NOW
        )
        assert error == ''
        assert edited['id'] == first['id'] and edited['name'] == '改名了'
        assert len(store.all_tasks()) == 2

    def test_the_record_of_what_ran_survives_an_edit(self):
        task = _save()
        store.record_event(task['id'], 'started', run_id='abc', at=NOW)
        edited, _ = store.save_task(
            {'id': task['id'], 'name': '每天早八', 'workflow': '红果短剧', 'trigger': task['trigger']}, NOW
        )
        assert edited['last_run']['run_id'] == 'abc'
        assert len(edited['history']) == 1

    def test_a_request_cannot_forge_the_record(self):
        """``history``/``last_run`` describe the server's own night, not the form's."""
        task, error = store.save_task(
            {
                'name': 'x',
                'workflow': 'w',
                'trigger': {'kind': 'daily', 'at': '08:00'},
                'history': [{'status': 'started'}],
                'last_run': {'status': 'started'},
            },
            NOW,
        )
        assert error == ''
        assert task['history'] == [] and task['last_run'] == {}


def _cron_refusal(expr):
    """The worded refusal ``cron.parse`` gives for an expression it cannot read."""
    try:
        cron.parse(expr)
    except cron.CronError as caught:
        return str(caught)
    return ''


class TestWhatIsRefused:
    @pytest.mark.parametrize(
        ('over', 'expected'),
        [
            ({'name': '  '}, t('sched.nameRequired')),
            ({'name': 'x' * 61}, t('sched.nameTooLong', n=60)),
            ({'workflow': ''}, t('sched.workflowRequired')),
            ({'trigger': {'kind': 'hourly'}}, t('sched.badTrigger', kind='hourly')),
            ({'trigger': 'daily'}, t('sched.badTrigger', kind='')),
            ({'trigger': {'kind': 'daily', 'at': '8'}}, t('sched.badClock', at='8')),
            ({'trigger': {'kind': 'daily', 'at': '25:00'}}, t('sched.badClock', at='25:00')),
            # ``weekday or ''`` — a 0 reads as "not stated" and the refusal says so.
            ({'trigger': {'kind': 'weekly', 'at': '08:00', 'weekday': 0}}, t('sched.badWeekday', value='')),
            ({'trigger': {'kind': 'weekly', 'at': '08:00', 'weekday': 8}}, t('sched.badWeekday', value='8')),
            ({'trigger': {'kind': 'interval', 'minutes': 0}}, t('sched.badInterval', value='', hi=store.INTERVAL_MAX)),
            (
                {'trigger': {'kind': 'interval', 'minutes': store.INTERVAL_MAX + 1}},
                t('sched.badInterval', value=str(store.INTERVAL_MAX + 1), hi=store.INTERVAL_MAX),
            ),
            (
                {'trigger': {'kind': 'interval', 'minutes': 'ten'}},
                t('sched.badInterval', value='ten', hi=store.INTERVAL_MAX),
            ),
            ({'trigger': {'kind': 'cron', 'expr': '0 8 * *'}}, _cron_refusal('0 8 * *')),
            ({'trigger': {'kind': 'cron', 'expr': '99 8 * * *'}}, _cron_refusal('99 8 * * *')),
            ({'timezone': 'Mars/Olympus'}, t('sched.badTimezone', name='Mars/Olympus')),
        ],
    )
    def test_a_task_that_cannot_be_stored_is_refused_by_name(self, over, expected):
        raw = {'name': 'x', 'workflow': 'w', 'trigger': {'kind': 'daily', 'at': '08:00'}, **over}
        task, error = store.save_task(raw, NOW)
        assert task == {} and error == expected
        assert '{' not in error, 'a refusal reached the user with a raw template slot in it'

    def test_a_rule_that_never_fires_is_refused_while_the_user_is_watching(self):
        _, error = store.save_task(
            {'name': 'x', 'workflow': 'w', 'trigger': {'kind': 'cron', 'expr': '0 0 30 2 *'}}, NOW
        )
        assert error == t('sched.neverFires', expr='0 0 30 2 *')
        assert store.all_tasks() == []

    def test_a_one_digit_clock_is_zero_padded_rather_than_refused(self):
        task = _save(trigger={'kind': 'daily', 'at': '8:5'})
        assert task['trigger']['at'] == '08:05'
        assert task['next_run'] == datetime(2026, 10, 16, 8, 5, tzinfo=SHANGHAI).isoformat()

    def test_the_language_is_normalized_and_defaults_to_chinese(self):
        assert _save(lang='EN')['lang'] == 'en'
        assert _save(name='no lang')['lang'] == 'zh'


class TestWhatTheTaskMeans:
    def test_a_preset_is_stored_as_the_user_wrote_it(self):
        """The panel offers presets; the file keeps the sentence, arithmetic comes from the table."""
        task = _save(trigger={'kind': 'daily', 'at': '08:00'})
        assert task['trigger'] == {'kind': 'daily', 'at': '08:00'}
        assert store.trigger_cron(task['trigger']) == '0 8 * * *'

    def test_sunday_is_written_as_sunday_in_cron(self):
        task = _save(trigger={'kind': 'weekly', 'at': '08:30', 'weekday': 7})
        assert store.trigger_cron(task['trigger']) == '30 8 * * 0'
        assert task['next_run'] == datetime(2026, 10, 18, 8, 30, tzinfo=SHANGHAI).isoformat()

    def test_every_kind_reads_as_a_sentence(self):
        assert store.describe_trigger({'kind': 'daily', 'at': '08:00'}) == t('sched.everyDay', at='08:00')
        assert store.describe_trigger({'kind': 'weekly', 'at': '08:00', 'weekday': 1}) == t(
            'sched.everyWeek', weekday=t('sched.weekday1'), at='08:00'
        )
        assert store.describe_trigger({'kind': 'interval', 'minutes': 30}) == t('sched.everyMinutes', n=30)
        assert store.describe_trigger({'kind': 'cron', 'expr': '0 8 * * *'}) == t('sched.cronAt', expr='0 8 * * *')

    def test_a_moment_is_rendered_in_the_task_own_zone(self):
        moment = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)  # 08:00 Shanghai
        assert store.describe_time(moment.isoformat(), 'Asia/Shanghai') == '2026-10-16 08:00 (Asia/Shanghai)'
        # A blank zone is THIS machine's own zone, so the expected wall clock is asked of the
        # machine (`astimezone()`, the same definition the store uses) and never written down:
        # a literal 08:00 here was +08:00 wearing a test's clothes, and a UTC machine (CI) reads
        # 00:00 for the very same instant — a green-on-my-laptop failure.
        local_clock = f'{moment.astimezone():%Y-%m-%d %H:%M}'
        assert store.describe_time(moment.isoformat(), '') == f'{local_clock} ({store.zone_label("")})'
        assert store.describe_time('', 'Asia/Shanghai') == ''
        assert store.describe_time('not a moment', 'Asia/Shanghai') == ''

    def test_a_daily_rule_in_shanghai_is_not_the_server_local_one(self):
        """The whole reason a task carries its own zone: the same 08:00 is a different instant."""
        task = _save(timezone='Asia/Shanghai')
        assert store.stamp(task['next_run']).astimezone(UTC) == datetime(2026, 10, 16, 0, 0, tzinfo=UTC)


class TestSwitchingItOff:
    def test_switching_off_clears_the_moment_and_switching_on_recomputes_it(self):
        task = _save()
        off, error = store.set_enabled(task['id'], False, NOW)
        assert error == '' and off['enabled'] is False and off['next_run'] == ''
        # Three days later it comes back on: the moment is in the FUTURE, not one it slept through.
        later = NOW + timedelta(days=3)
        on, error = store.set_enabled(task['id'], True, later)
        assert error == '' and on['enabled'] is True
        assert store.stamp(on['next_run']) > later

    def test_switching_a_task_that_is_not_there_is_refused_by_name(self):
        _, error = store.set_enabled('nope', False, NOW)
        assert error == t('sched.taskMissing', id='nope')


class TestOneEvent:
    def test_a_fire_is_written_into_the_history_and_the_moment_moves(self):
        task = _save()
        after = store.record_event(task['id'], 'started', note='', run_id='run-1', at=NOW)
        assert after['last_run']['status'] == 'started' and after['last_run']['run_id'] == 'run-1'
        assert [row['status'] for row in after['history']] == ['started']
        assert store.stamp(after['next_run']) == datetime(2026, 10, 16, 8, 0, tzinfo=SHANGHAI)

    def test_a_manual_fire_keeps_a_cron_slot_on_its_wall_clock(self):
        """立即执行 is not the schedule: pressing the button must not move tomorrow's 08:00."""
        task = _save()
        before = task['next_run']
        after = store.record_event(task['id'], 'started', at=NOW + timedelta(hours=2), advance=False)
        assert after['next_run'] == before

    def test_an_interval_re_anchors_from_the_manual_fire_anyway(self):
        """A period has no wall clock to keep — its anchor IS the last fire."""
        task = _save(trigger={'kind': 'interval', 'minutes': 30})
        assert store.stamp(task['next_run']) == NOW + timedelta(minutes=30)
        after = store.record_event(task['id'], 'started', at=NOW + timedelta(minutes=5), advance=False)
        assert store.stamp(after['next_run']) == NOW + timedelta(minutes=35)

    def test_a_refusal_is_recorded_like_any_other_outcome(self):
        task = _save()
        after = store.record_event(task['id'], 'refused', note='找不到画布「红果短剧」', at=NOW)
        assert after['last_run'] == {
            'at': NOW.isoformat(),
            'status': 'refused',
            'run_id': '',
            'note': '找不到画布「红果短剧」',
        }

    def test_the_history_keeps_the_last_twenty_newest_first(self):
        task = _save()
        for index in range(store.HISTORY_MAX + 5):
            after = store.record_event(task['id'], 'started', note=str(index), at=NOW + timedelta(minutes=index))
        assert len(after['history']) == store.HISTORY_MAX
        assert after['history'][0]['note'] == str(store.HISTORY_MAX + 4)

    def test_an_event_for_a_task_that_is_not_there_answers_none(self):
        assert store.record_event('nope', 'started', at=NOW) is None


class TestWhatTheDownTimeMissed:
    def test_a_moment_that_passed_while_the_server_was_down_is_counted_once(self):
        """Three days down is ONE missed moment per task, not three crawls owed."""
        task = _save()
        missed = store.note_missed(NOW + timedelta(days=3))
        assert missed == ['每天早八']
        after = store.get_task(task['id'])
        assert after['missed'] == {'count': 1, 'last_at': datetime(2026, 10, 16, 8, 0, tzinfo=SHANGHAI).isoformat()}
        assert after['history'][0]['status'] == 'missed'
        assert store.stamp(after['next_run']) > NOW + timedelta(days=3)

    def test_a_second_restart_does_not_re_count_the_same_moment(self):
        _save()
        store.note_missed(NOW + timedelta(days=3))
        assert store.note_missed(NOW + timedelta(days=3, minutes=1)) == []
        assert store.all_tasks()[0]['missed']['count'] == 1

    def test_a_task_that_is_not_due_yet_is_left_alone(self):
        task = _save()
        assert store.note_missed(NOW) == []
        assert store.get_task(task['id'])['next_run'] == task['next_run']

    def test_a_disabled_task_is_not_reported_as_missed(self):
        task = _save()
        store.set_enabled(task['id'], False, NOW)
        assert store.note_missed(NOW + timedelta(days=3)) == []

    def test_an_empty_store_reports_nothing(self):
        assert store.note_missed(NOW) == []


class TestAnUnreadableFile:
    def test_it_is_moved_aside_rather_than_deleted_or_overwritten(self, tmp_path):
        path = tmp_path / 'schedules.json'
        path.write_text('{not json', encoding='utf-8')
        assert store.all_tasks() == []
        assert not path.exists()
        assert (tmp_path / 'schedules.json.corrupt').read_text(encoding='utf-8') == '{not json'
        # And the store is usable again: the next save writes a fresh file.
        _save()
        assert len(store.all_tasks()) == 1


class TestDeleting:
    def test_a_deleted_task_is_gone_and_a_second_delete_says_so(self):
        task = _save()
        assert store.delete_task(task['id']) is True
        assert store.all_tasks() == []
        assert store.delete_task(task['id']) is False


def test_next_fire_is_strictly_after_the_moment_asked_about():
    """The store's own clock helper: a task due exactly now fires at the NEXT moment, not this one."""
    spec = store.next_fire({'trigger': {'kind': 'daily', 'at': '08:00'}, 'timezone': 'Asia/Shanghai'}, NOW)
    assert spec == datetime(2026, 10, 16, 8, 0, tzinfo=SHANGHAI)
    assert cron.next_after(cron.parse('0 8 * * *'), spec, SHANGHAI) == datetime(2026, 10, 17, 8, 0, tzinfo=SHANGHAI)
