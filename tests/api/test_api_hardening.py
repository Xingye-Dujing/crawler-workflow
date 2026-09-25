"""Tests for the request-validation layer the JSON routes share.

Every case here is one shape of "the client got it slightly wrong", which the
audit found answers with an HTML 500 traceback:

* a body that is *valid JSON but not an object* (``null``, ``[1, 2]``, ``"abc"``)
  reached ``data.get(...)`` and raised AttributeError,
* ``limit=inf`` parsed as a float and only died later, in ``int()``,
* ``steps``/``format`` of the wrong type escaped every ``except
  (ValueError, TypeError)`` wrapper because the failure was an AttributeError,
* an empty or dot-only workflow name cleaned down to ``'untitled'`` and so
  addressed — or destroyed — a workflow the caller never named,
* and an over-long body was buffered into RAM before any handler ran.

What all of them must answer instead is the ``{ok: false, error: …}`` shape the
frontend parses, with a 4xx status. The last group pins the read-only helpers
those routes are built on, so a new caller cannot regress them unnoticed.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.api

RECORDS = [{'title': 'sanya', 'score': 3}, {'title': 'haikou', 'score': 5}]
# Routes whose only job on this input is to refuse it: none of them may reach
# the store, the filesystem or a model with a body that is not an object.
# Every POST handler that reads a field belongs here — `TestBodyPolicy` below
# fails if this list and app.py drift apart.
BODY_ROUTES = [
    '/api/analysis/run',
    '/api/analysis/train',
    '/api/cookies/delete',
    '/api/cookies/generate',
    '/api/cookies/preflight',
    '/api/cookies/refresh-profile',
    '/api/cookies/save',
    '/api/cookies/verify',
    '/api/data/clear',
    '/api/data/datasets/<dataset_id>/rename',
    '/api/data/inspect',
    '/api/data/paste',
    '/api/data/preview',
    '/api/export/save',
    '/api/exports/delete',
    '/api/history/delete',
    '/api/llm/test',
    '/api/report/generate',
    '/api/runs/delete',
    '/api/runs/discard',
    '/api/runs/resumable',
    '/api/settings',
    '/api/studio/dataset',
    '/api/studio/save-image',
    '/api/studio/sources',
    '/api/visualize/render',
    '/api/workflow/delete',
    '/api/workflow/execute',
    '/api/workflow/processes/kill',
    '/api/workflow/queue/cancel',
    '/api/workflow/rename',
    '/api/workflow/save',
]
NON_OBJECT_BODIES = ['null', '[1, 2]', '"abc"', '123']
# POST routes that read no field at all. A malformed body is not their error to
# report — `stop` stops, `purge` trims to policy, `upload` answers from a
# multipart file, the two cookie job doors only signal. Declared, so that
# "ignores the body" stays a decision and not something a later route inherits by
# accident (and so adding one here means saying what it is).
BODYLESS_POSTS = {
    '/api/cookies/generate/cancel': 'signals the login window to close',
    '/api/cookies/generate/confirm': 'signals the login window that the user is done',
    '/api/data/upload': 'multipart form field, not a JSON body',
    '/api/history/clear': 'empties the history table',
    '/api/runs/purge': 'applies the retention policy, which lives in settings',
    '/api/workflow/queue/clear': 'drops every parked request',
    '/api/workflow/stop': 'sets the stop flag',
}


def _wf_names(client) -> list:
    """Saved-workflow names; ``/api/workflow/list`` returns one object per file
    for the management panel, while these guards speak about names."""
    return [w['name'] for w in client.get('/api/workflow/list').get_json()['workflows']]


def _post_route_policies() -> dict:
    """{path: 'helper' | 'inline' | 'none'} for every POST route in app.py.

    Read from the source and not from Flask's URL map because the thing under
    test is which helper a handler calls, which the route table cannot show.
    """
    source = (Path(__file__).resolve().parents[2] / 'backend' / 'app.py').read_text(encoding='utf-8')
    lines = source.splitlines()
    starts = []
    for index, line in enumerate(lines):
        match = re.search(r"@app\.route\('([^']+)',\s*methods=\[([^\]]+)\]", line)
        if match and 'POST' in match.group(2):
            starts.append((index, match.group(1)))
    policies = {}
    for position, (index, path) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = '\n'.join(lines[index:end])
        if '_json_body()' in body:
            policies[path] = 'helper'
        elif 'request.get_json(' in body:
            policies[path] = 'inline'
        else:
            policies[path] = 'none'
    return policies


class TestBodyPolicy:
    """One body rule, in one place, for every route that reads a field.

    Three handlers used to spell the rule out inline — ``get_json(silent=True)
    or {}`` followed by an ``isinstance`` check — which read the same bytes as
    ``_json_body`` differently: the literal body ``null`` became ``{}``, so the
    answer was "platform is required" for what was a malformed request.
    """

    def test_no_post_route_reads_the_raw_request_body_any_more(self):
        inline = sorted(path for path, how in _post_route_policies().items() if how == 'inline')
        assert inline == [], f'these routes duplicate the body rule instead of calling _json_body(): {inline}'

    def test_every_route_that_reads_a_body_is_in_the_refusal_matrix(self):
        helpers = {path for path, how in _post_route_policies().items() if how == 'helper'}
        listed = set(BODY_ROUTES)
        assert helpers == listed, (
            f'missing from the matrix: {sorted(helpers - listed)}, not in app.py: {sorted(listed - helpers)}'
        )

    def test_every_post_route_that_reads_no_body_is_declared_and_explained(self):
        silent = {path for path, how in _post_route_policies().items() if how == 'none'}
        assert silent == set(BODYLESS_POSTS), f'undecided routes: {sorted(silent ^ set(BODYLESS_POSTS))}'
        assert all(BODYLESS_POSTS[path] for path in silent), 'each exemption needs a reason, not just a name'


class TestMalformedBodies:
    @pytest.mark.parametrize('route', BODY_ROUTES)
    @pytest.mark.parametrize('body', NON_OBJECT_BODIES)
    def test_a_json_body_that_is_not_an_object_is_a_400(self, client, route, body):
        response = client.post(route, data=body, content_type='application/json')
        assert response.status_code == 400, f'{route} answered {response.status_code} for {body!r}'
        payload = response.get_json()
        assert payload is not None, 'a JSON client must never get an HTML error page back'
        assert payload['ok'] is False
        assert payload['error']

    def test_a_request_with_no_body_still_reads_as_no_fields(self, client):
        # ``or {}`` behaviour the frontend depends on: an empty POST is not a
        # malformed one. The routes below then fail on the *missing field*.
        assert client.post('/api/workflow/delete', data='', content_type='application/json').status_code == 400
        assert client.post('/api/workflow/processes/kill').status_code == 400

    def test_steps_must_be_a_list_of_step_objects(self, client):
        # Neither shape can be iterated as a step: a string walks its characters,
        # a list holding a non-dict dies on ``step.get('op')``. Both used to be a
        # 500, because no ``except (ValueError, TypeError)`` catches AttributeError.
        for steps in ('abc', 12, [{'op': 'drop_null'}, None], [None], ['drop_null'], {'op': 'drop_null'}):
            response = client.post('/api/analysis/run', json={'data': RECORDS, 'steps': steps})
            assert response.status_code == 400, f'steps={steps!r} answered {response.status_code}'
            body = response.get_json()
            assert body['ok'] is False
            assert 'steps' in body['error']

    def test_a_wellformed_step_list_still_runs(self, client):
        body = client.post(
            '/api/analysis/run', json={'data': RECORDS, 'steps': [{'op': 'drop_null', 'params': {}}]}
        ).get_json()
        assert body['ok'] is True
        assert body['row_count'] == 2

    def test_export_rejects_a_non_string_format(self, client):
        response = client.post('/api/export/save', json={'data': RECORDS, 'format': 123})
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False and 'format' in body['error']

    def test_export_rejects_a_dataset_field_of_the_wrong_shape(self, client):
        # ``{"data": 42}`` dies inside the pandas constructor, which is still a
        # caller mistake rather than a server one.
        response = client.post('/api/export/save', json={'data': 42, 'format': 'csv'})
        assert response.status_code == 400
        assert response.get_json()['ok'] is False

    def test_save_refuses_a_workflow_that_is_not_an_object(self, client):
        response = client.post('/api/workflow/save', json={'name': 'typed-wrong', 'workflow': [1, 2]})
        assert response.status_code == 400
        assert response.get_json()['ok'] is False
        assert 'typed-wrong' not in _wf_names(client)


class TestNumericLimits:
    @pytest.mark.parametrize(
        'route',
        [
            '/api/history/runs',
            '/api/history/series',
            '/api/data/datasets',
            '/api/runs/list',
        ],
    )
    def test_an_infinite_limit_answers_the_default_instead_of_500(self, client, route):
        # ``int(float('inf'))`` raises OverflowError, which no
        # ``except (TypeError, ValueError)`` caught: every limit field was a
        # free 500 for anyone who typed "inf" into the UI.
        for value in ('inf', '-inf', 'nan', '1e999'):
            response = client.get(route, query_string={'limit': value})
            assert response.status_code == 200, f'{route}?limit={value} → {response.status_code}'
            assert response.get_json()['ok'] is True

    def test_the_helpers_reject_every_non_finite_number(self, app_module):
        assert app_module._safe_int('inf', 20) == 20
        assert app_module._safe_int('nan', 20, minimum=1, maximum=10) == 20
        assert app_module._safe_int(float('-inf'), 7) == 7
        assert app_module._safe_int('1e999', 7) == 7
        assert app_module._safe_int('3.9') == 3
        assert app_module._safe_int(None) == 0
        assert app_module._optional_int('inf') is None
        assert app_module._optional_int('nan') is None
        assert app_module._optional_int('12') == 12
        assert app_module._optional_float('inf') is None
        assert app_module._optional_float('0.4') == 0.4
        assert app_module._safe_float('inf', 0.5) == 0.5
        assert app_module._safe_float('2.5', 0.5) == 2.5

    def test_the_upload_ceiling_parse_cannot_be_turned_off_by_a_typo(self, app_module, monkeypatch):
        # A garbage MAX_UPLOAD_MB must fall back, not leave the limit unset.
        for raw, expected in ((None, 64), ('', 64), ('abc', 64), ('inf', 64), ('0', 1), ('20', 20), ('99999', 10240)):
            if raw is None:
                monkeypatch.delenv('MAX_UPLOAD_MB', raising=False)
            else:
                monkeypatch.setenv('MAX_UPLOAD_MB', raw)
            assert app_module._upload_limit_mb() == expected, raw


class TestPayloadCeiling:
    def test_an_over_long_body_is_refused_as_json(self, app_module, client, monkeypatch):
        # The whole body used to be buffered into RAM before a handler ran, so
        # one huge paste cost whatever memory the box had left. Werkzeug now
        # stops it — and the answer has to stay parseable, not an HTML page.
        monkeypatch.setitem(app_module.app.config, 'MAX_CONTENT_LENGTH', 1024)
        payload = {'data': [{'title': 'x' * 64, 'score': i} for i in range(64)]}
        response = client.post('/api/data/paste', json=payload)
        assert response.status_code == 413
        body = response.get_json()
        assert body is not None, 'a 413 that is not JSON is unreadable to the browser'
        assert body['ok'] is False
        assert 'MB' in body['error']

    def test_a_body_under_the_ceiling_still_gets_through(self, app_module, client, monkeypatch, paste):
        monkeypatch.setitem(app_module.app.config, 'MAX_CONTENT_LENGTH', 1024 * 1024)
        assert paste(RECORDS, name='small.csv')


class TestWorkflowNameGuard:
    """``''`` and ``'..'`` both cleaned down to ``untitled`` — for a *delete*
    that meant removing a workflow nobody had named. Saving keeps the fallback
    (a blank name field is just an unnamed file), addressing does not.
    """

    @pytest.fixture
    def untitled(self, client):
        """A real workflow living at the fallback path, so its survival means something."""
        workflow = {'nodes': [{'id': 'node-1', 'type': 'output', 'params': {}}], 'connections': []}
        body = client.post('/api/workflow/save', json={'name': '', 'workflow': workflow}).get_json()
        assert body['ok'] is True
        assert body['path'].endswith('untitled.json')
        return body['path']

    @pytest.mark.parametrize('name', ['', '   ', '..', '...', '....'])
    def test_an_unresolvable_name_cannot_delete_the_untitled_workflow(self, client, untitled, name):
        response = client.post('/api/workflow/delete', json={'name': name})
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False and 'name' in body['error']
        assert 'untitled' in _wf_names(client)

    @pytest.mark.parametrize('name', ['', '   ', '..', '...', '....'])
    def test_an_unresolvable_name_cannot_load_the_untitled_workflow(self, client, untitled, name):
        response = client.get('/api/workflow/load', query_string={'name': name})
        assert response.status_code == 400
        assert response.get_json()['ok'] is False

    @pytest.mark.parametrize('name', ['./..', '..', '../..', '/etc/passwd'])
    def test_a_traversal_shaped_name_never_reaches_the_untitled_file(self, client, untitled, name):
        # The guard's real job: whatever a name cleans down to, it must not be
        # the fallback file. (A dot-only stem cleans to one underscore — a name
        # of its own inside the workflow directory, so it simply is not there.)
        assert client.post('/api/workflow/delete', json={'name': name}).status_code in (200, 400)
        assert 'untitled' in _wf_names(client)
        loaded = client.get('/api/workflow/load', query_string={'name': name})
        assert loaded.status_code in (400, 404)

    def test_a_name_that_is_missing_entirely_is_refused_too(self, client, untitled):
        assert client.get('/api/workflow/load').status_code == 400
        assert client.post('/api/workflow/delete', json={}).status_code == 400
        assert client.post('/api/workflow/delete', json={'name': 123}).status_code == 400

    def test_untitled_named_on_purpose_is_still_addressable(self, client, untitled):
        loaded = client.get('/api/workflow/load', query_string={'name': 'untitled'}).get_json()
        assert loaded['ok'] is True
        assert loaded['workflow']['name'] == 'untitled'
        # ...and deleting it is allowed, because the user said so explicitly.
        assert client.post('/api/workflow/delete', json={'name': 'untitled'}).get_json() == {'ok': True}
        assert 'untitled' not in _wf_names(client)


class TestResultSnapshot:
    def test_a_status_poll_cannot_break_on_a_published_node(self, app_module, client):
        # The race: the run publishes node rows as they finish while these
        # endpoints iterate the same dict. Under the lock the endpoints copy
        # first, so a mutation lands between two polls, never mid-iteration.
        app_module.execution_state['results'] = {'node-1': [{'title': 'sanya'}]}
        snapshot = app_module._results_snapshot()
        assert snapshot == {'node-1': [{'title': 'sanya'}]}
        snapshot['node-2'] = [{'title': 'haikou'}]
        assert 'node-2' not in app_module.execution_state['results'], 'the snapshot must be a copy'
        # ...and it has to hand the lock back, or the next publish would wait
        # forever behind a status poll.
        assert app_module._completed_lock.acquire(blocking=False), '_results_snapshot left the lock held'
        app_module._completed_lock.release()

        # /api/workflow/status answers a bare progress object (no ``ok`` field —
        # the console polls it as fast as it can), the stats routes wrap theirs.
        status = client.get('/api/workflow/status').get_json()
        assert status['results'] == ['node-1']
        assert status['running'] is False
        for route in ('/api/stats/emotion', '/api/stats/tendency', '/api/stats/summary'):
            assert client.get(route).get_json()['ok'] is True, route
        assert client.get('/api/stats/summary').get_json()['summary'] == {
            'node-1': {'count': 1, 'sample_keys': ['title']}
        }


class TestResumeOfPurgedRun:
    """A 继续 whose run record is gone must be refused, never silently re-crawled.

    Reusing the id of a deleted run opens an EMPTY run under the same name: the
    console says 'continuing from 0 rows', the crawler goes out and pays for
    every item again, and nothing tells the user that the rows they were trying
    to keep had already been aged out.
    """

    def test_continuing_a_run_that_no_longer_exists_is_refused(self, client, app_module):
        store = app_module._RUN_STORE
        store.start_run('gone123', 'wf', 'fp')
        store.delete_run('gone123')
        response = client.post(
            '/api/workflow/execute',
            json={'workflow': {'nodes': [], 'connections': []}, 'resume_run_id': 'gone123'},
        )
        assert response.status_code == 400, response.get_json()
        assert 'gone123' in response.get_json()['error'], 'the message must name the record that is missing'
        assert store.get_run('gone123') is None, 'the refusal must not resurrect the run row'
        assert app_module.execution_state['running'] is False, 'nothing may start'

    def test_a_busy_server_refuses_it_at_the_door_instead_of_parking_it(self, client, app_module):
        """The queue would re-check at drain time, but a request that can never
        run should not be worth a '排队运行' label either."""
        app_module.execution_state['running'] = True
        response = client.post(
            '/api/workflow/execute',
            json={'workflow': {'nodes': [], 'connections': []}, 'resume_run_id': 'never-existed'},
        )
        assert response.status_code == 400
        assert app_module.queue_snapshot() == [], 'an impossible continue must not enter the queue'
        app_module.execution_state['running'] = False

    def test_a_record_purged_while_the_request_waited_is_dropped_on_drain(self, client, app_module):
        """The race the queue creates: retention deletes the interrupted run
        between parking the 继续 and draining it. The entry must be discarded with
        its reason in the console — pushing it back would refuse it after every
        single run, forever."""
        app_module._RUN_QUEUE.append(
            {
                'id': 'q1',
                'workflow_name': '继续旧运行',
                'data': {'workflow': {'nodes': [], 'connections': []}, 'resume_run_id': 'purged-later'},
                'lang': 'zh',
            }
        )
        app_module._start_next_queued()
        assert app_module.queue_snapshot() == [], 'the impossible entry must not be re-queued'
        assert app_module.execution_state['running'] is False
        assert any('purged-later' in line for line in app_module.execution_state['logs']), 'the console says why'


class TestRunPayloadShape:
    """A workflow the engine cannot walk is the caller's mistake, in JSON.

    ``WorkflowEngine`` iterates ``nodes`` expecting dicts, so a list of strings
    or a numeric ``settings`` died with an AttributeError inside the worker
    thread — which the browser received as an HTML error page, and a *queued*
    request would have died minutes later in a thread nobody was watching.
    """

    @pytest.mark.parametrize(
        'workflow',
        [
            [],
            'not-a-workflow',
            {'nodes': 'node-1'},
            {'nodes': ['node-1']},
            {'nodes': [{'id': 'node-1'}], 'settings': 5},
        ],
    )
    def test_a_workflow_that_cannot_be_walked_is_a_400(self, client, workflow):
        response = client.post('/api/workflow/execute', json={'workflow': workflow})
        assert response.status_code == 400, response.get_json()
        payload = response.get_json()
        assert payload['ok'] is False and payload['error']
        assert response.mimetype == 'application/json'

    def test_the_same_payload_is_refused_at_the_door_when_a_run_is_busy(self, client, app_module):
        """Queueing must not become a way to smuggle a broken request past the
        check and fail later as a mystery."""
        app_module.execution_state['running'] = True
        response = client.post('/api/workflow/execute', json={'workflow': [{'id': 'node-1'}]})
        assert response.status_code == 400
        assert app_module.queue_snapshot() == [], 'a request that cannot run must not enter the queue'

    def test_a_broken_queued_request_cannot_strand_the_ones_behind_it(self, client, app_module, monkeypatch):
        """Drain-time defence: an entry that dies is skipped, the next still runs.

        Without the guard the exception escaped the finishing run's ``finally``,
        so one malformed request took the whole queue down with it — after the
        browser had been told its run was parked and would start.
        """
        attempts = []

        def pretend_to_begin(data, lang):
            name = data.get('workflow_name', '')
            attempts.append(name)
            if name == 'broken':
                raise RuntimeError('boom')
            return {'status': 200, 'body': {'ok': True, 'run_id': 'r-' + name}}

        monkeypatch.setattr(app_module, '_begin_run', pretend_to_begin)
        app_module._RUN_QUEUE.extend(
            [
                {'id': 'a', 'workflow_name': 'broken', 'data': {'workflow_name': 'broken'}, 'lang': 'zh'},
                {'id': 'b', 'workflow_name': 'next', 'data': {'workflow_name': 'next'}, 'lang': 'zh'},
            ]
        )
        app_module._start_next_queued()
        assert attempts == ['broken', 'next'], 'the second request must not be stranded by the first'
        assert app_module.queue_snapshot() == []


class TestNumericSettingsFields:
    def test_infinity_in_a_timeout_is_a_warning_not_a_crash(self, client):
        # float('inf') parses fine and int() refuses it — OverflowError, which is
        # neither TypeError nor ValueError and escaped as an HTML 500.
        for value in ('inf', '1e400', 'nan'):
            response = client.post('/api/settings', json={'page_load_timeout': value})
            assert response.status_code == 200, f'{value} answered {response.status_code}'
            assert response.get_json()['ok'] is True
        assert client.get('/api/settings').get_json()['settings']['page_load_timeout'] == 40

    def test_the_studio_answers_a_malformed_reference_in_json(self, client):
        response = client.post('/api/studio/dataset', json={'data': 42})
        assert response.status_code == 200, 'the picker reads code/error from the body, not the status'
        payload = response.get_json()
        assert payload['ok'] is False and payload['code'] == 'no_result'
