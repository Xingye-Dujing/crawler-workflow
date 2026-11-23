"""Machine-level surfaces answer one authority question, not one per module.

Before this, ``/api/settings``, ``/api/lexicon``, ``/api/components``, ``/api/update`` and the
analysis trainer each carried their own ``accounts_mode() and not is_admin()``, while the AI
workspace's filesystem picker and command runner checked only ``CLOUD_MODE``. On an accounts host
that left a hole: an ordinary account could re-root the workspace at ``data/users/<other>/`` and
read it. The policy module is the single answer; these cases pin both halves — an ordinary account
is refused, an administrator is not.
"""

import pytest
from ai import workspace
from ai.errors import AIError
from runtime import account_context, policy
from runtime.account_context import Account

pytestmark = pytest.mark.api

READER = Account('u_aaaaaaaaaaaa', 'reader', 'user')
ADMIN = Account('u_bbbbbbbbbbbb', 'admin', 'admin')


def _accounts_on(monkeypatch, on=True):
    monkeypatch.setattr('services.accounts.service.accounts_mode', lambda: on)


def test_the_login_free_owner_may_do_everything(monkeypatch):
    _accounts_on(monkeypatch, False)
    with account_context.use(None):
        assert policy.may_administer_machine() is True


def test_an_ordinary_account_may_not_administer_the_machine(monkeypatch):
    _accounts_on(monkeypatch)
    with account_context.use(READER):
        assert policy.may_administer_machine() is False
    with account_context.use(ADMIN):
        assert policy.may_administer_machine() is True
    # No identity with a registry is a refusal, never a wildcard.
    with account_context.use(None):
        assert policy.may_administer_machine() is False


def test_the_workspace_picker_refuses_an_ordinary_account(monkeypatch, tmp_path):
    _accounts_on(monkeypatch)
    with account_context.use(READER):
        for call in (
            lambda: workspace.browse(str(tmp_path)),
            lambda: workspace.pick_folder(str(tmp_path)),
        ):
            with pytest.raises(AIError) as caught:
                call()
            assert caught.value.key == policy.machine_refusal_key(), caught.value.key
        assert workspace.volumes() == [], 'the drive list is a host fingerprint'


def test_an_admin_still_uses_the_workspace(monkeypatch, tmp_path):
    _accounts_on(monkeypatch)
    (tmp_path / 'inner').mkdir()
    with account_context.use(ADMIN):
        browsed = workspace.browse(str(tmp_path))
        assert browsed['path'] == str(tmp_path)
        assert [row['name'] for row in browsed['entries']] == ['inner']
        assert browsed['roots'] == workspace.volumes()


@pytest.fixture()
def python_routes_client(client, monkeypatch):
    """The script library is shared machine state; the inline runner runs as the server user."""
    _accounts_on(monkeypatch)

    def as_reader():
        return account_context.use(READER)

    return client, as_reader


def test_an_ordinary_account_may_not_author_or_run_inline_python(python_routes_client):
    client, as_reader = python_routes_client
    with as_reader():
        assert client.post('/api/ai/ws/python/scripts', json={'name': 'x', 'code': 'print(1)'}).status_code == 403
        assert client.post('/api/ai/ws/python/run', json={'code': 'print(1)'}).status_code == 403
    # The read-only capability answer stays available: the panel must be able to say why.
    with as_reader():
        assert client.get('/api/ai/ws/python/status').status_code == 200


def test_the_python_gate_names_the_same_sentence_as_every_machine_route(python_routes_client):
    client, as_reader = python_routes_client
    with as_reader():
        body = client.post('/api/ai/ws/python/scripts', json={'name': 'x', 'code': 'print(1)'}).get_json()
    assert body['ok'] is False
    assert body['key'] == policy.machine_refusal_key()
