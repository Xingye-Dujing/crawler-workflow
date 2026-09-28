"""What ``python app.py cloud`` changes on the server side.

The flag is the server's fact, not the page's: hiding the Ollama controls and the
「无头」 switch is the visible half of a deployment that has no display and no local
daemon, and every request behind a hidden control still has to be answered here. Each
case below therefore checks a refusal that NAMES what it refused — the failure mode this
repo keeps paying for is a run that quietly does the other thing and reports success.
"""

import os

import pytest

from config import Config

pytestmark = [pytest.mark.api, pytest.mark.usefixtures('seeded_logins')]


@pytest.fixture
def cloud(monkeypatch):
    """This process is a cloud host for the duration of one test."""
    monkeypatch.setattr(Config, 'CLOUD_MODE', True)


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setattr(Config, 'CLOUD_MODE', False)


def _canvas_with_model():
    return {
        'nodes': [
            {'id': 'n-1', 'type': 'source', 'params': {'platform': 'zhihu', 'keyword': '三亚', 'target_count': 3}},
            {'id': 'n-2', 'type': 'process', 'params': {'operation': 'clean', 'text_column': '正文'}},
        ],
        'connections': [{'from': 'n-1', 'to': 'n-2'}],
        'settings': {'mode': 'serial', 'headless': True},
    }


class TestTheServerStatesItsOwnShape:
    def test_config_reports_the_flag_the_process_was_started_with(self, client):
        # /api/config is read at request time, not captured at import: a page that booted
        # before this answer existed would otherwise keep the wrong controls forever.
        assert client.get('/api/config').get_json()['cloud_mode'] is Config.CLOUD_MODE

    def test_a_cloud_boot_flips_it(self, client, cloud):
        assert client.get('/api/config').get_json()['cloud_mode'] is True

    def test_the_panel_is_told_to_keep_every_control_on_a_desktop_boot(self, client, desktop):
        assert client.get('/api/config').get_json()['cloud_mode'] is False


class TestNoLocalModelOnASharedServer:
    def test_a_run_that_wants_a_local_daemon_is_refused_by_name(self, client, cloud):
        body = client.post(
            '/api/workflow/execute',
            json={'workflow': _canvas_with_model(), 'llm': {'provider': 'ollama', 'model': 'qwen3.5:9b'}},
        ).get_json()
        assert body['ok'] is False, body
        assert 'ollama' in body['error'], 'the refusal must name the transport it refused'
        assert 'OpenRouter' in body['error'], 'and say what this host does support'

    def test_the_refusal_is_not_mistaken_for_a_missing_key(self, client, cloud):
        """An empty key with a local transport reports the TRANSPORT.

        Asking for an OpenRouter key while about to dial a port nothing listens on is how
        a user types a key into the wrong box and still has a run that answers nothing.
        """
        body = client.post(
            '/api/workflow/execute', json={'workflow': _canvas_with_model(), 'llm': {'provider': 'ollama'}}
        ).get_json()
        assert 'ollama' in body['error'] and 'API Key' not in body['error'], body

    def test_openrouter_is_never_refused_for_being_a_transport(self, client, cloud):
        body = client.post(
            '/api/workflow/execute', json={'workflow': _canvas_with_model(), 'llm': {'provider': 'openrouter'}}
        ).get_json()
        assert body['ok'] is False
        assert 'key' in body['error'].lower(), (
            f'the only thing missing here is the key, so that is what must be said: {body}'
        )

    def test_a_crawl_that_never_calls_a_model_is_not_asked_about_one(self, client, cloud):
        """The flag removes a transport, it does not remove crawling."""
        workflow = _canvas_with_model()
        workflow['nodes'] = workflow['nodes'][:1]
        workflow['connections'] = []
        response = client.post(
            '/api/workflow/execute', json={'workflow': workflow, 'llm': {'provider': 'ollama'}, 'queue': False}
        )
        assert response.status_code == 200, response.get_json()

    def test_the_local_model_list_refuses_instead_of_dialing_a_port(self, client, cloud):
        """A 502「connection refused」 reads as a broken button; this host has no button."""
        response = client.get('/api/llm/ollama/models')
        assert response.status_code == 400
        assert 'ollama' in response.get_json()['error']

    def test_the_connection_test_refuses_the_transport_it_cannot_try(self, client, cloud):
        body = client.post('/api/llm/test', json={'provider': 'ollama', 'model': 'qwen3.5:9b'}).get_json()
        assert body['ok'] is False and 'ollama' in body['error'], body

    def test_a_report_still_ships_and_says_which_paragraph_it_skipped(self, client, cloud, app_module, monkeypatch):
        """The conclusion is a note inside the deliverable, not the deliverable.

        The existing failure path logs 「结论生成失败」 and carries on; on this host the
        honest line names the transport instead, and a connection error to a port nothing
        listens on must never be what the user reads.
        """
        app_module.execution_state['results'] = {'node-1': [{'正文': '张先生在海边游泳'}]}

        def never(self, prompt, max_retries=2):
            raise AssertionError('a cloud boot must not dial a local daemon for a paragraph')

        monkeypatch.setattr(app_module.LLMClient, 'chat', never)
        response = client.post('/api/report/generate', json={'include_conclusion': True, 'llm': {'provider': 'ollama'}})
        assert response.status_code == 200, response.get_json()
        assert response.get_json()['ok'] is True
        said = [line for line in app_module.execution_state['logs'] if 'ollama' in line.lower()]
        assert len(said) == 1, f'the skipped transport was said {len(said)} times: {said}'


class TestNoWindowToLogInto:
    def test_the_login_browser_is_refused_before_anything_is_bought(self, client, cloud, app_module, monkeypatch):
        """Nobody is standing at this server's screen.

        The panel drops the button on the same flag, but the route answers to saved
        workflows, stale tabs and hand-written POSTs too — and the honest answer there is
        the reason, not a browser that opens on nobody.
        """

        def never(*args, **kwargs):
            raise AssertionError('a cloud boot must not buy a login browser')

        monkeypatch.setattr(app_module, 'get_crawler', never)
        response = client.post('/api/cookies/generate', json={'platform': 'zhihu'})
        assert response.status_code == 400
        assert '窗口' in response.get_json()['error'] or 'window' in response.get_json()['error'].lower()

    def test_a_desktop_boot_still_offers_it(self, client, desktop, app_module, monkeypatch):
        started = {}

        def pretend(platform, **kwargs):
            started['platform'] = platform
            raise RuntimeError('no chrome here')

        monkeypatch.setattr(app_module, 'get_crawler', pretend)
        response = client.post('/api/cookies/generate', json={'platform': 'zhihu'})
        # 202 = the job was accepted and the worker found no browser; a 400 here would
        # mean the refusal leaked into the machine that still has a display.
        assert response.status_code in (202, 500), response.get_json()
        assert started.get('platform') == 'zhihu'


class TestEverythingRunsHeadless:
    def test_a_run_asked_for_a_window_is_recorded_headless(self, client, cloud, app_module, monkeypatch):
        """The chip on the record has to describe the run that happened.

        ``headless`` arrives from the canvas's own settings, so without this a cloud boot
        would file 「窗口」 for a crawl that could only have run without one — and the
        resume banner matches on that record.
        """
        from run_wait import run_finished

        class _Quiet:
            def __init__(self):
                self.results = lambda: []

            def search(self, *args, **kwargs):
                return []

            def get_detail(self, url):
                return None

            def close(self):
                pass

        monkeypatch.setattr(app_module, 'get_crawler', lambda platform, **kwargs: _Quiet())
        workflow = _canvas_with_model()
        workflow['nodes'] = workflow['nodes'][:1]
        workflow['connections'] = []
        body = client.post(
            '/api/workflow/execute',
            json={'workflow': dict(workflow, settings={'mode': 'serial', 'headless': False}), 'queue': False},
        ).get_json()
        assert body.get('ok'), body
        assert run_finished(app_module), 'the run never settled'
        run = app_module.get_run_store().get_run(body['run_id'])
        # The column is an INTEGER (0/1), and the console's chip reads it as a bool: the
        # point of the assertion is which of the two the record holds.
        assert bool(run['headless']) is True, 'the record says what this host can actually do'


class TestThePristineTemplateOnACloudBoot:
    """Where a device directory comes from when nobody can press 「浏览器生成」.

    The launcher is the browser seam, so no Chrome is started here; the real one is the
    device tier's case (``tests/integration/test_profile_template.py``).
    """

    @pytest.fixture
    def profiles_root(self, tmp_path, monkeypatch):
        import browser_profiles

        root = tmp_path / 'profiles'
        values = {'use_browser_profile': True, 'browser_profile_dir': str(root)}
        monkeypatch.setattr(browser_profiles, 'get_setting', lambda key: values[key])
        return root

    @staticmethod
    def _launcher(calls, *, dirty=False, broken=False):
        """A stand-in for "start a blank Chrome here": it writes what Chrome would.

        ``dirty`` puts a store with a ROW in it, not a file with a login-shaped name —
        a blank first run creates those names itself, so only the content tells the two
        cases apart (see ``browser_profiles._SESSION_TABLES``).
        """

        def launch(path):
            calls.append(path)
            if broken:
                raise RuntimeError('chromedriver missing')
            os.makedirs(path, exist_ok=True)
            with open(os.path.join(path, 'First Run'), 'w', encoding='utf-8') as handle:
                handle.write('x')
            if dirty:
                import sqlite3

                store = os.path.join(path, 'Default', 'Login Data')
                os.makedirs(os.path.dirname(store), exist_ok=True)
                db = sqlite3.connect(store)
                try:
                    db.execute('CREATE TABLE logins (id INTEGER PRIMARY KEY, username_value TEXT)')
                    db.execute("INSERT INTO logins (username_value) VALUES ('someone')")
                    db.commit()
                finally:
                    db.close()

        return launch

    def test_the_route_builds_it_once_and_then_reports_that_it_existed(
        self, client, cloud, app_module, monkeypatch, profiles_root
    ):
        calls = []
        monkeypatch.setattr(app_module, 'warm_profile_dir', self._launcher(calls))
        first = client.post('/api/browser/profiles/template')
        assert first.status_code == 200, first.get_json()
        assert first.get_json()['built'] is True, first.get_json()
        second = client.post('/api/browser/profiles/template')
        assert second.get_json() == {'ok': True, 'built': False, 'existed': True}, second.get_json()
        assert len(calls) == 1, f'the second call bought another browser: {calls}'

    def test_force_rebuilds_it(self, client, cloud, app_module, monkeypatch, profiles_root):
        calls = []
        monkeypatch.setattr(app_module, 'warm_profile_dir', self._launcher(calls))
        client.post('/api/browser/profiles/template')
        assert client.post('/api/browser/profiles/template', json={'force': True}).status_code == 200
        assert len(calls) == 2, calls

    def test_a_browser_that_will_not_start_is_a_502_with_its_reason(
        self, client, cloud, app_module, monkeypatch, profiles_root
    ):
        monkeypatch.setattr(app_module, 'warm_profile_dir', self._launcher([], broken=True))
        response = client.post('/api/browser/profiles/template')
        assert response.status_code == 502, response.get_json()
        assert 'chromedriver' in response.get_json()['reason'], response.get_json()

    def test_a_template_someone_logged_into_is_never_shipped(
        self, client, cloud, app_module, monkeypatch, profiles_root
    ):
        calls = []
        monkeypatch.setattr(app_module, 'warm_profile_dir', self._launcher(calls, dirty=True))
        response = client.post('/api/browser/profiles/template')
        assert response.status_code == 502, response.get_json()
        assert 'not-pristine' in response.get_json()['reason'], response.get_json()

    def test_saving_a_cookie_makes_it_first_when_there_is_none(
        self, client, cloud, app_module, monkeypatch, profiles_root
    ):
        """The one moment the user is present to ask for a device is the paste.

        The template has to exist BEFORE the account directory is created, because that
        creation is what seeds it — so this asserts the order, not merely that both
        happened.
        """
        import browser_profiles

        calls = []
        monkeypatch.setattr(app_module, 'warm_profile_dir', self._launcher(calls))
        # The plant still needs a browser; record that the template was already there when
        # the account directory was made, instead of letting this test launch a Chrome.
        order = []

        def spy_factory(platform, **kwargs):
            order.append(('crawler', bool(browser_profiles.template_exists())))
            raise RuntimeError('no browser in the fast tier')

        monkeypatch.setattr(app_module, 'get_crawler', spy_factory)
        payload = {'platform': 'zhihu', 'cookies': [{'name': 'a', 'value': 'v'}], 'account': 'work'}
        assert client.post('/api/cookies/save', json=payload).status_code == 200
        assert calls == [str(profiles_root / '_template')], calls
        assert order == [('crawler', True)], f'the account browser ran before the template existed: {order}'

    def test_the_panel_can_ask_whether_a_template_is_there(self, client, cloud, app_module, monkeypatch, profiles_root):
        body = client.get('/api/browser/profiles').get_json()
        assert body['template'] == {'exists': False, 'pristine': True}, body['template']
        monkeypatch.setattr(app_module, 'warm_profile_dir', self._launcher([]))
        client.post('/api/browser/profiles/template')
        assert client.get('/api/browser/profiles').get_json()['template'] == {'exists': True, 'pristine': True}

    def test_a_template_that_picked_up_a_session_is_reported_as_dirty(
        self, client, cloud, app_module, monkeypatch, profiles_root
    ):
        """The row is the panel's only way to see this, and the sentence has to be true.

        ``build_template`` destroys and rebuilds a dirty directory on its own, so nothing
        breaks either way — what would break is the panel claiming 「干净」 about a
        directory that holds somebody's login while it waits to be rebuilt.
        """
        import sqlite3

        monkeypatch.setattr(app_module, 'warm_profile_dir', self._launcher([]))
        client.post('/api/browser/profiles/template')
        store = str(profiles_root / '_template' / 'Default' / 'Network' / 'Cookies')
        os.makedirs(os.path.dirname(store), exist_ok=True)
        db = sqlite3.connect(store)
        try:
            db.execute('CREATE TABLE cookies (id INTEGER PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO cookies (name) VALUES ('SUB')")
            db.commit()
        finally:
            db.close()
        assert client.get('/api/browser/profiles').get_json()['template'] == {'exists': True, 'pristine': False}
