"""``/api/schedules*`` — the panel's surface, driven through the real client.

The four verbs are one contract: every answer carries the WHOLE payload (tasks + canvas verdicts +
clock status), so the panel repaints from any reply and can never be left showing half an update.
The rule that matters most here is the canvas verdict — a timer has no browser request behind it, so
a canvas whose steps would call a model must be refused while the user is still choosing it, and
refused again at the moment of the fire.

Two boundaries are stubbed and nothing else:

* ``app._begin_run``, so a test never starts a crawl (this is the seam the real ``_start_scheduled_run``
  calls through, which is why the glue is exercised here as well);
* the schedules file, redirected per test, so a task written by one test is invisible to the next.

The client fixture sends ``X-Lang: en``, so every refusal is compared against the catalogue's own
English wording through :func:`_en` rather than a sentence copied into the test.
"""

import contextlib
import os

import pytest
from scheduling import store

from config import Config
from i18n import set_lang, t

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """A store of this test's own; the canvas directory stays the suite's isolated one."""
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    yield


def _en(key, **params):
    """The catalogue's English wording: what this file's requests (``X-Lang: en``) ask for."""
    previous = set_lang('en')
    try:
        return t(key, **params)
    finally:
        set_lang(previous)


NAME_NODE = {'id': 'n1', 'type': 'name', 'params': {'workflow_name': '日常'}}
#: A clean step with no method chosen means the ``llm`` default — a model, so a timer may not run it.
MODEL_NODE = {'id': 'n2', 'type': 'process', 'params': {'operation': 'clean'}}


@pytest.fixture
def canvas(app_module):
    """Write real canvas files (the verdict is read from the file) and remove them afterwards."""
    manager = app_module.workflow_manager
    made = []

    def _make(name, nodes):
        manager.save(name, {'nodes': nodes, 'connections': []})
        made.append(name)
        return name

    yield _make
    for name in made:
        with contextlib.suppress(OSError):
            os.remove(manager.path_for(name))


def _save_payload(workflow, **over):
    payload = {
        'name': '每天早八',
        'workflow': workflow,
        'trigger': {'kind': 'daily', 'at': '08:00'},
        'timezone': 'Asia/Shanghai',
        'lang': 'zh',
        'enabled': True,
    }
    payload.update(over)
    return payload


def _save(client, workflow, **over):
    response = client.post('/api/schedules/save', json=_save_payload(workflow, **over))
    body = response.get_json()
    assert response.status_code == 200, body
    assert body['ok'] is True, body
    return body


def _row(body, task_id):
    """The task as the panel reads it. A fire answers with the whole table, not one row — the panel
    repaints from it — so a test finds the task by id the same way the panel's renderer does."""
    for row in body['tasks']:
        if row['id'] == task_id:
            return row
    raise AssertionError(f'no task {task_id} in {body}')


class TestReadingThePanel:
    def test_the_payload_carries_the_tasks_the_canvas_verdicts_and_the_clock(self, client, canvas):
        canvas('可以定时的画布', [NAME_NODE])

        body = client.get('/api/schedules').get_json()

        assert body['ok'] is True and body['tasks'] == []
        assert body['status']['running'] is False and body['status']['tick_seconds'] == 20
        assert body['status']['now_local'] and body['status']['local_zone']
        verdicts = {row['name']: row for row in body['canvases']}
        assert verdicts['可以定时的画布']['runnable'] is True
        assert verdicts['可以定时的画布']['why_not'] == ''

    def test_a_canvas_whose_steps_would_call_a_model_is_shown_as_not_runnable(self, client, canvas):
        canvas('要模型的画布', [NAME_NODE, MODEL_NODE])

        verdicts = {row['name']: row for row in client.get('/api/schedules').get_json()['canvases']}

        assert verdicts['要模型的画布']['runnable'] is False
        assert verdicts['要模型的画布']['why_not'] == _en('sched.canvasNeedsModel', name='要模型的画布')

    def test_a_broken_canvas_file_is_not_offered_at_all(self, client, app_module, canvas):
        name = canvas('坏文件', [NAME_NODE])
        with open(app_module.workflow_manager.path_for(name), 'w', encoding='utf-8') as handle:
            handle.write('{not json')

        # ``describe`` marks it broken and keeps it deletable in the 画布 panel; the schedule picker
        # must not offer a name that cannot be loaded.
        names = [row['name'] for row in client.get('/api/schedules').get_json()['canvases']]
        assert name not in names

    def test_a_saved_task_comes_back_as_the_panel_reads_it(self, client, canvas):
        canvas('可以定时的画布', [NAME_NODE])

        body = _save(client, '可以定时的画布')

        assert body['task']['name'] == '每天早八'
        assert body['task']['trigger_text'] == _en('sched.everyDay', at='08:00')
        assert body['task']['next_run_local'].endswith('(Asia/Shanghai)')
        assert [row['id'] for row in body['tasks']] == [body['task']['id']]


class TestSaving:
    def test_the_verdict_is_asked_again_at_save_time_not_only_when_the_form_opens(self, client, canvas):
        """A hand-written POST must not be able to schedule a canvas the form would refuse."""
        canvas('要模型的画布', [NAME_NODE, MODEL_NODE])

        response = client.post('/api/schedules/save', json=_save_payload('要模型的画布'))

        body = response.get_json()
        assert response.status_code == 400 and body['ok'] is False
        assert body['error'] == _en('sched.canvasNeedsModel', name='要模型的画布')
        assert body['tasks'] == [], 'a refused save wrote a task anyway'
        assert store.all_tasks() == []

    def test_a_canvas_that_is_not_there_is_refused_by_name(self, client):
        response = client.post('/api/schedules/save', json=_save_payload('没有这个画布'))
        body = response.get_json()

        assert response.status_code == 400
        assert body['error'] == _en('sched.canvasMissing', name='没有这个画布')

    def test_an_existing_task_is_updated_in_place(self, client, canvas):
        canvas('可以定时的画布', [NAME_NODE])
        first = _save(client, '可以定时的画布')['task']

        updated = _save(
            client, '可以定时的画布', id=first['id'], name='改了名字', trigger={'kind': 'interval', 'minutes': 45}
        )

        assert updated['task']['id'] == first['id']
        assert updated['task']['name'] == '改了名字'
        assert len(updated['tasks']) == 1

    @pytest.mark.parametrize(
        ('over', 'key'),
        [
            ({'name': ''}, 'sched.nameRequired'),
            ({'trigger': {'kind': 'daily', 'at': '25:00'}}, 'sched.badClock'),
            ({'timezone': 'Mars/Olympus'}, 'sched.badTimezone'),
            ({'trigger': {'kind': 'cron', 'expr': '0 0 30 2 *'}}, 'sched.neverFires'),
        ],
    )
    def test_a_task_that_cannot_be_stored_answers_400_with_the_reason(self, client, canvas, over, key):
        canvas('可以定时的画布', [NAME_NODE])

        response = client.post('/api/schedules/save', json=_save_payload('可以定时的画布', **over))
        body = response.get_json()

        assert response.status_code == 400 and body['ok'] is False
        assert body['error'].startswith(_en(key).split('{')[0]), body['error']
        assert '{' not in body['error'], 'the panel was handed a raw template'

    def test_a_body_that_is_not_json_is_refused(self, client):
        response = client.post('/api/schedules/save', data='not json', content_type='text/plain')
        assert response.status_code == 400


class TestSwitchingAndDeleting:
    def test_off_clears_the_moment_and_on_computes_a_new_one(self, client, canvas):
        canvas('可以定时的画布', [NAME_NODE])
        task = _save(client, '可以定时的画布')['task']

        off = client.post('/api/schedules/toggle', json={'id': task['id'], 'enabled': False}).get_json()
        assert off['ok'] is True and off['task']['enabled'] is False and off['task']['next_run'] == ''

        on = client.post('/api/schedules/toggle', json={'id': task['id'], 'enabled': True}).get_json()
        assert on['task']['enabled'] is True and on['task']['next_run_local']

    def test_toggling_something_that_is_not_there_answers_404(self, client):
        response = client.post('/api/schedules/toggle', json={'id': 'nope', 'enabled': True})
        assert response.status_code == 404
        assert response.get_json()['error'] == _en('sched.taskMissing', id='nope')

    def test_deleting_removes_the_task_and_a_second_delete_answers_404(self, client, canvas):
        canvas('可以定时的画布', [NAME_NODE])
        task = _save(client, '可以定时的画布')['task']

        gone = client.post('/api/schedules/delete', json={'id': task['id']})
        assert gone.status_code == 200 and gone.get_json()['tasks'] == []

        again = client.post('/api/schedules/delete', json={'id': task['id']})
        assert again.status_code == 404
        assert again.get_json()['error'] == _en('sched.taskMissing', id=task['id'])


class TestTheRunVerb:
    """立即执行 is the same start path as a fire, so the same answers come back."""

    def _ready(self, client, canvas, name='可以定时的画布', **over):
        canvas(name, [NAME_NODE])
        return _save(client, name, **over)['task']

    def test_a_started_run_is_recorded_with_its_run_id(self, client, canvas, app_module, monkeypatch):
        # The task's own language (not the request's) is what the fire narrates in — see _fire.
        task = self._ready(client, canvas, lang='en')
        monkeypatch.setattr(
            app_module, '_begin_run', lambda data, lang: {'status': 200, 'body': {'ok': True, 'run_id': 'run-7'}}
        )
        lines = []
        monkeypatch.setattr(app_module, 'add_log', lines.append)

        body = client.post('/api/schedules/run', json={'id': task['id']}).get_json()

        assert body['ok'] is True and body['result']['status'] == 'started' and body['result']['run_id'] == 'run-7'
        row = _row(body, task['id'])
        assert row['last_run']['status'] == 'started' and row['last_run']['run_id'] == 'run-7'
        assert lines == [_en('sched.firedManual', name='每天早八')]

    def test_a_busy_server_answers_queued_and_says_no_console_line_of_its_own(
        self, client, canvas, app_module, monkeypatch
    ):
        task = self._ready(client, canvas)
        monkeypatch.setattr(
            app_module, '_begin_run', lambda data, lang: {'status': 200, 'body': {'ok': True, 'queued': True}}
        )
        lines = []
        monkeypatch.setattr(app_module, 'add_log', lines.append)

        body = client.post('/api/schedules/run', json={'id': task['id']}).get_json()

        assert body['result']['status'] == 'queued' and body['result']['run_id'] == ''
        assert lines == [], 'a queued fire narrated itself; the queue narrates when it really starts'

    def test_a_refused_run_answers_400_and_is_kept_in_the_history(self, client, canvas, app_module, monkeypatch):
        task = self._ready(client, canvas)
        monkeypatch.setattr(
            app_module,
            '_begin_run',
            lambda data, lang: {'status': 400, 'body': {'ok': False, 'error': '已经有运行在进行'}},
        )
        monkeypatch.setattr(app_module, 'add_log', lambda line: None)

        response = client.post('/api/schedules/run', json={'id': task['id']})
        body = response.get_json()

        assert response.status_code == 400 and body['ok'] is False and body['error'] == '已经有运行在进行'
        row = _row(body, task['id'])
        assert row['last_run']['status'] == 'refused'
        assert row['last_run']['note'] == '已经有运行在进行'

    def test_running_something_that_is_not_there_answers_404(self, client):
        response = client.post('/api/schedules/run', json={'id': 'nope'})
        assert response.status_code == 404
        assert response.get_json()['error'] == _en('sched.taskMissing', id='nope')


class TestTheGlueAppInstalled:
    """``_start_scheduled_run`` is what the scheduler calls; ``_begin_run`` is the only thing stubbed."""

    def _task(self, client, canvas, name='可以定时的画布', **over):
        canvas(name, [NAME_NODE])
        return _save(client, name, **over)['task']

    def test_it_asks_for_the_canvas_and_refuses_a_model_one(self, client, canvas, app_module, monkeypatch):
        set_lang('en')  # a direct call skips the per-request X-Lang routing (clean_globals restores it)
        canvas('要模型的画布', [NAME_NODE, MODEL_NODE])
        task = {'id': 'x', 'name': '要模型', 'workflow': '要模型的画布', 'lang': 'zh'}
        called = []
        monkeypatch.setattr(
            app_module, '_begin_run', lambda data, lang: called.append(data) or {'status': 200, 'body': {'ok': True}}
        )

        answer = app_module._start_scheduled_run(task, False)

        assert answer == {'ok': False, 'error': _en('sched.canvasNeedsModel', name='要模型的画布')}
        assert called == [], 'a refused canvas was handed to the executor anyway'

    def test_a_switched_off_model_node_does_not_hold_the_schedule(self, client, canvas, app_module, monkeypatch):
        """A disabled node is not on the canvas — the engine's own rule, which validate, naming,
        fingerprint and execution all obey. ``_workflow_needs_llm`` walked the DRAWN nodes, so a
        canvas whose only model-shaped box was switched off was refused 「需要模型」 at save time
        AND again at every fire, forever: the user had turned the cost off and the timer kept
        charging it to the rule."""
        set_lang('en')
        off = dict(MODEL_NODE, params=dict(MODEL_NODE['params'], enabled=False))
        canvas('模型关掉的画布', [NAME_NODE, off])
        canvas('模型开着的画布', [NAME_NODE, MODEL_NODE])
        task = {'id': 'x', 'name': '关掉也要模型', 'workflow': '模型关掉的画布', 'lang': 'zh'}
        called = []
        monkeypatch.setattr(
            app_module, '_begin_run', lambda data, lang: called.append(data) or {'status': 200, 'body': {'ok': True}}
        )

        answer = app_module._start_scheduled_run(task, False)

        assert answer['ok'] is True, answer
        assert called, 'a canvas that calls no model was refused anyway'
        # The switch-off is what makes the difference: the same node left ON stays refused.
        still_on = dict(task, workflow='模型开着的画布')
        assert app_module._start_scheduled_run(still_on, False) == {
            'ok': False,
            'error': _en('sched.canvasNeedsModel', name='模型开着的画布'),
        }

    def test_it_hands_the_language_of_the_task_to_the_run(self, client, canvas, app_module, monkeypatch):
        task = self._task(client, canvas, lang='en')
        seen = []
        monkeypatch.setattr(
            app_module,
            '_begin_run',
            lambda data, lang: seen.append((data, lang)) or {'status': 200, 'body': {'ok': True, 'run_id': 'r1'}},
        )
        monkeypatch.setattr(app_module, 'add_log', lambda line: None)

        answer = app_module._start_scheduled_run(task, False)

        assert answer == {'ok': True, 'queued': False, 'run_id': 'r1', 'error': ''}
        assert seen[0][0]['lang'] == 'en'
        assert seen[0][0]['workflow_name'] == '每天早八'
        assert seen[0][0]['workflow']['nodes'], 'the loaded canvas was not passed on'
        assert seen[0][1] == ''

    def test_a_scheduled_fire_and_a_manual_one_narrate_differently(self, client, canvas, app_module, monkeypatch):
        set_lang('en')
        task = self._task(client, canvas)
        monkeypatch.setattr(
            app_module, '_begin_run', lambda data, lang: {'status': 200, 'body': {'ok': True, 'run_id': 'r1'}}
        )
        lines = []
        monkeypatch.setattr(app_module, 'add_log', lines.append)

        app_module._start_scheduled_run(task, False)
        app_module._start_scheduled_run(task, True)

        assert lines == [
            _en('sched.fired', name='每天早八'),
            _en('sched.firedManual', name='每天早八'),
        ]
