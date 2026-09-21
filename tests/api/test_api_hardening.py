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

import pytest

pytestmark = pytest.mark.api

RECORDS = [{'title': 'sanya', 'score': 3}, {'title': 'haikou', 'score': 5}]
# Routes whose only job on this input is to refuse it: none of them may reach
# the store, the filesystem or a model with a body that is not an object.
BODY_ROUTES = [
    '/api/workflow/save',
    '/api/workflow/delete',
    '/api/workflow/processes/kill',
    '/api/settings',
    '/api/llm/test',
    '/api/data/paste',
    '/api/data/inspect',
    '/api/analysis/run',
    '/api/export/save',
    '/api/runs/discard',
]
NON_OBJECT_BODIES = ['null', '[1, 2]', '"abc"', '123']


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
        assert 'typed-wrong' not in client.get('/api/workflow/list').get_json()['workflows']


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
        assert 'untitled' in client.get('/api/workflow/list').get_json()['workflows']

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
        assert 'untitled' in client.get('/api/workflow/list').get_json()['workflows']
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
        assert 'untitled' not in client.get('/api/workflow/list').get_json()['workflows']


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
