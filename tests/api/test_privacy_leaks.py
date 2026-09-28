"""No route may answer a cookie value, and the sentence is checked, not hoped.

The privacy rule for this project is one line: a cookie is the login itself, so it stays on
the server's disk and inside the browser that crawls with it. Everything the panel shows
about a saved login is metadata — which account, how many entries, when it was taken,
whether that account's own browser holds the same session.

The risk in writing that as a policy is the NEXT route. So this file does not enumerate the
routes it liked: it walks ``app.url_map``, calls every GET rule it finds, and looks for a
string that exists only inside the cookie jar. A new route that reads the jar and echoes it
fails here without anyone having to remember to check.
"""

import json

import pytest
from flask import jsonify

from config import Config

pytestmark = pytest.mark.api

#: Written into the jar below. It appears in no response, no log line and no settings file,
#: which is the whole claim — so the literal has to be something no real value could collide
#: with by accident.
MARKER = 'COOKIE-VALUE-THAT-MUST-NEVER-LEAVE-THE-DISK'
#: A cookie NAME is session data too: the pair (name, value) is what a request replays.
COOKIE_NAME = 'z_c0-SECRETISH-NAME'


@pytest.fixture
def marked_jar(app_module):
    """A saved login for one platform and one named account, carrying the marker."""
    app_module.cookie_manager.delete('zhihu')
    app_module.cookie_manager.delete('zhihu', 'work')
    rows = [{'name': COOKIE_NAME, 'value': MARKER, 'domain': '.zhihu.com'}]
    app_module.cookie_manager.save('zhihu', rows)
    app_module.cookie_manager.save('zhihu', rows, 'work')
    yield MARKER
    app_module.cookie_manager.delete('zhihu')
    app_module.cookie_manager.delete('zhihu', 'work')


@pytest.fixture
def no_outbound_calls(monkeypatch):
    """The two model-catalog routes dial a port; the sweep may not, and must not skip them.

    Skipping would be the quiet failure this file exists to prevent: an unchecked route is an
    unchecked route, and the sweep's whole value is that its coverage is the route map.
    """
    import analyzers.llm_client as llm_client

    class _Answer:
        status_code = 200
        text = '{"models": []}'

        def json(self):
            return {'data': []}

    monkeypatch.setattr(llm_client.requests, 'get', lambda *a, **k: _Answer())
    monkeypatch.setattr(llm_client.requests, 'post', lambda *a, **k: _Answer())


def _get_rules(app):
    out = []
    for rule in app.url_map.iter_rules():
        methods = set(rule.methods or ()) - {'HEAD', 'OPTIONS'}
        if 'GET' in methods:
            out.append(rule)
    return sorted(out, key=lambda r: str(r.rule))


def _probe_path(rule):
    """A concrete path for one rule, substituting a harmless value for each parameter."""
    path = str(rule.rule)
    for arg in sorted(rule.arguments):
        value = 'nonexistent-run-id'
        path = path.replace(f'<{arg}>', value).replace(f'<int:{arg}>', '1')
    return path


def _sweep(client, app_module):
    """Ask every GET rule the way a visitor would, and say what came back.

    One function on purpose: the main case asserts on it, and the case that proves this
    file CAN fail asserts on the same walk rather than on a copy of its loop.
    """
    seen = []
    for rule in _get_rules(app_module.app):
        path = _probe_path(rule)
        # ``with``, because the page routes hand back a file response: dropping it without
        # closing leaks the open handle until the garbage collector gets round to it, and it
        # then complains during whichever test happens to be running — a sweep that walks
        # every GET rule is exactly the kind of caller that pays for it on someone else's
        # behalf. The same reason the export and report cases read ``with client.get(...)``.
        with client.get(path) as response:
            body = response.get_data(as_text=True)
        seen.append((path, body))
        assert MARKER not in body, f'{path} answered the cookie VALUE'
        assert COOKIE_NAME not in body, f'{path} answered the cookie NAME'
    return seen


class TestTheSweepItself:
    def test_the_route_map_is_actually_walked(self, client, app_module):
        """A sweep that silently enumerated nothing would pass forever."""
        rules = _get_rules(app_module.app)
        names = {str(r.rule) for r in rules}
        # A floor, not the measured count: this suite walked 32 GET rules when it was
        # written, and the number only has to be big enough that "the walk returned the
        # root and nothing else" cannot pass it.
        assert len(rules) >= 25, f'only {len(rules)} GET rules found: the walk is broken'
        # Three routes that MUST be in the walk, because they are the ones a careless
        # implementation could hand a jar to: the cookie listing, the settings read-back
        # and the capability payload that carries account names.
        assert '/api/cookies/status' in names
        assert '/api/settings' in names
        assert '/api/capabilities' in names

    def test_no_get_route_answers_the_value_inside_a_cookie_file(
        self, client, app_module, marked_jar, no_outbound_calls
    ):
        seen = _sweep(client, app_module)
        assert len(seen) >= 25, [path for path, _ in seen]
        statuses = {path: len(body) for path, body in seen}
        # The sweep is not just "no exception": prove the metadata route really was reached
        # and did answer, or an empty answer from every route would look like a pass.
        assert statuses['/api/cookies/status'] > 2, statuses['/api/cookies/status']

    def test_the_sweep_is_the_kind_of_guard_that_can_fail(self, client, app_module, marked_jar, no_outbound_calls):
        """Swap one route's body for one that DOES hand back the jar, and show this catches it.

        Without this, the sweep above proves only that today's routes are clean — and the
        failure this file exists to prevent is a future one. The route map cannot be edited
        after the app has served a request (Flask refuses, and rightly), so the substitution
        is the view function itself: same URL, same walk, dishonest body.
        """
        original = app_module.app.view_functions['cookie_status']

        def leak():
            return jsonify({'ok': True, 'jar': app_module.cookie_manager.load('zhihu')})

        app_module.app.view_functions['cookie_status'] = leak
        try:
            # The fixture really does put a value on disk that the route can now leak…
            body = client.get('/api/cookies/status').get_data(as_text=True)
            assert MARKER in body, 'the leaking route leaked nothing: the fixture is broken'
            # …and the sweep walks that very URL, so its assertion is what fires.
            with pytest.raises(AssertionError, match='cookie VALUE'):
                _sweep(client, app_module)
        finally:
            app_module.app.view_functions['cookie_status'] = original
        assert MARKER not in client.get('/api/cookies/status').get_data(as_text=True), (
            'the swap outlived the test that made it'
        )

    def test_the_status_route_answers_metadata_because_that_is_the_whole_point(
        self, client, app_module, marked_jar, no_outbound_calls
    ):
        """The negative claim above is only worth reading if this one holds.

        A sweep that found every route empty would also find no marker in it, so the
        assertion here is that the route DID say something about the two saved logins —
        names, entry counts, dates — and said nothing else.
        """
        rows = {row['account']: row for row in client.get('/api/cookies/status').get_json()['rows']}
        # The default login is now NAMED (``default``), not a blank row — the row it produces is
        # the platform's own cookie file, and an account that has a name is keyed by that name.
        assert set(rows) >= {'default', 'work'}, rows
        for row in rows.values():
            assert row['entries'] == 1 and row['saved_at'], row
            assert row['platform'] == 'zhihu'
        assert sorted(rows['default']) == sorted(
            [
                'account',
                'entry_key',
                'entries',
                'label_args',
                'label_key',
                'needs_refresh',
                'platform',
                'profile_exists',
                'profile_imported',
                'profile_used',
                'profiles_on',
                'saved_at',
                'session_only',
            ]
        ), 'a new field on this row is new information leaving the process — check it is metadata'

    def test_the_save_path_never_puts_the_value_in_the_console(
        self, client, app_module, no_outbound_calls, profiles_off
    ):
        """The log line says WHICH account was saved; the jar is what it names, not what it prints.

        Console text reaches the browser through /api/workflow/status, so a paste echoed
        into a log line is the same leak with one more hop.
        """
        app_module.execution_state['logs'] = []
        payload = {'platform': 'weibo', 'cookies': [{'name': COOKIE_NAME, 'value': MARKER}]}
        response = client.post('/api/cookies/save', json=payload)
        assert response.status_code == 200, response.get_json()
        said = '\n'.join(app_module.execution_state['logs']) + json.dumps(response.get_json())
        assert MARKER not in said, said
        assert COOKIE_NAME not in said, said
        app_module.cookie_manager.delete('weibo')


class TestSessionsAreNotASecretInTheDefaultBoot:
    """``SECRET_KEY`` signs Flask sessions, and the built-in value is a published constant.

    The honest reason that is not a hole today: this app never imports ``flask.session`` —
    it is a cookie-less JSON API with no login of its own. That is a property of the code,
    not of the environment, so it is pinned at the import: the day a module starts using
    sessions, the shipped default key becomes a real finding and this test says so before
    the deploy does.
    """

    def test_no_backend_module_imports_flask_session(self, app_module):
        import ast
        from pathlib import Path

        backend = Path(app_module.__file__).parent
        hits = []
        for path in sorted(backend.rglob('*.py')):
            if path.name.startswith('test_'):
                continue  # the manual probe scripts in backend/ are not shipped code paths
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                imports_flask = isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 'flask'
                if imports_flask and any(alias.name == 'session' for alias in node.names):
                    hits.append(f'{path.name}:{node.lineno}')
        assert hits == [], f'Flask sessions are now in use, so the published default SECRET_KEY signs them: {hits}'

    def test_the_built_in_key_is_still_the_documented_fallback(self):
        assert Config.SECRET_KEY == 'crawler-workflow-secret-key', (
            'someone changed the shipped default — update this file and the README, because '
            'the point of the pin is that the fallback is public and therefore unused'
        )
