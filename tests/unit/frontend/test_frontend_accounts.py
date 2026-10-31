"""The account UI against the REAL app.js + accounts.js.

What the page does with ``/api/config.auth`` is JS: the CSRF header on mutating fetches, the forced
change-password dialog, and the administrator's registry panel. The Python API tests prove the
server refuses; these prove the page sends the token and never keeps a password.
"""

import json
import shutil
from pathlib import Path

import pytest
from frontend_catalogue import with_catalogue
from node_runner import run_node

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
JS_DIR = ROOT / 'backend' / 'static' / 'js'
HARNESS = ROOT / 'tests' / 'frontend' / 'harness_accounts.mjs'


@pytest.fixture(scope='module')
def booted():
    if shutil.which('node') is None:
        pytest.skip('node not on PATH')
    proc = run_node(HARNESS, *with_catalogue([JS_DIR / 'app.js', JS_DIR / 'accounts.js']))
    assert proc.returncode == 0, f'harness failed: {proc.stderr[-2000:]}'
    return json.loads(proc.stdout)


def _headers(call):
    return {str(key).lower(): value for key, value in (call.get('headers') or {}).items()}


class TestTheCsrfToken:
    def test_a_mutating_request_echoes_the_session_token(self, booted):
        posted = booted['csrf']['posted']
        assert posted['method'] == 'POST'
        assert _headers(posted)['x-csrf-token'] == 'csrf-1', posted

    def test_a_read_does_not_carry_it(self, booted):
        fetched = booted['csrf']['fetched']
        assert 'x-csrf-token' not in _headers(fetched), fetched


class TestTheForcedPasswordDialog:
    def test_a_named_debt_opens_the_dialog_once(self, booted):
        assert booted['forced']['mustChange'] is True
        assert len(booted['forced']['dialogs']) == 1
        dialog = booted['forced']['dialogs'][0]
        assert dialog['dismissable'] is False, 'a debt that can be dismissed is not forced'
        assert dialog['fields'] == ['acc-current', 'acc-new', 'acc-confirm']


class TestTheChangePasswordForm:
    def test_the_password_goes_to_the_server_and_nowhere_else(self, booted):
        changed = booted['changed']
        assert changed['authHasPassword'] is False
        assert changed['cleared'] == ['', '', ''], 'the fields must not keep a typed password'
        bodies = [call['body'] for call in changed['request'] if call['method'] == 'POST']
        assert bodies, changed['request']
        payload = json.loads(bodies[0])
        assert payload['new_password'] == 'new-password-1'
        assert payload['current_password'] == 'old-password'

    def test_a_mismatch_is_refused_before_any_request(self, booted):
        assert booted['mismatch']['requests'] == 0


class TestWhoSeesTheRegistry:
    def test_a_regular_user_gets_only_the_dialog(self, booted):
        assert len(booted['regularUser']['dialogs']) == 1
        assert booted['regularUser']['requests'] == []

    def test_an_admin_gets_the_table_without_a_credential(self, booted):
        panel = booted['adminPanel']
        assert panel['request'][0]['url'] == '/api/accounts'
        assert panel['overlay'] is True
        assert 'alice' in panel['html'] and 'boss' in panel['html']
        assert 'scrypt' not in panel['html'] and 'password_hash' not in panel['html']


class TestTheRegistryActions:
    def test_create_sends_the_password_once_and_clears_the_box(self, booted):
        created = booted['created']
        assert created['request'][0]['method'] == 'POST'
        payload = json.loads(created['request'][0]['body'])
        assert payload == {'username': 'carol', 'password': 'carol-password-1', 'role': 'user'}
        assert created['cleared'] == ''

    def test_delete_needs_the_typed_username(self, booted):
        deleted = booted['deleted']
        request = deleted['request'][0]
        assert request['method'] == 'DELETE'
        assert json.loads(request['body']) == {'confirm_username': 'alice'}
