"""Per-conversation approval grants: exact-argument keys, spend rules and the named refusals."""

import pytest
from ai import approvals, tools
from ai.errors import AIError
from core.config import Config

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_registry():
    approvals.reset()
    yield
    approvals.reset()


def _labels():
    from i18n import t

    return {'once': t('ai.approvalOnce'), 'session': t('ai.approvalSession'), 'deny': t('ai.approvalDeny')}


class TestGrants:
    def test_a_once_grant_is_spent_by_its_own_call(self):
        approvals.grant('c1', 'run_cmd', {'command': 'pytest -q'}, 'once')
        assert approvals.consume('c1', 'run_cmd', {'command': 'pytest -q'}) is True
        assert approvals.consume('c1', 'run_cmd', {'command': 'pytest -q'}) is False

    def test_a_session_grant_survives_a_second_call(self):
        approvals.grant('c1', 'run_cmd', {'command': 'pytest -q'}, 'session')
        assert approvals.consume('c1', 'run_cmd', {'command': 'pytest -q'}) is True
        assert approvals.consume('c1', 'run_cmd', {'command': 'pytest -q'}) is True

    def test_a_grant_is_keyed_by_the_exact_arguments(self):
        approvals.grant('c1', 'run_cmd', {'command': 'pytest -q'}, 'session')
        assert approvals.consume('c1', 'run_cmd', {'command': 'pytest --maxfail=1'}) is False
        assert approvals.consume('c1', 'run_cmd', {'command': 'pytest -q', 'cwd': '.'}) is False
        # Key order is not part of the request, so it is not part of the key either.
        assert approvals.consume('c1', 'run_cmd', {'command': 'pytest -q'}) is True

    def test_a_grant_belongs_to_one_conversation_and_one_tool(self):
        approvals.grant('c1', 'run_cmd', {'command': 'echo', 'timeout': 5}, 'session')
        assert approvals.consume('c2', 'run_cmd', {'command': 'echo', 'timeout': 5}) is False
        assert approvals.consume('c1', 'workspace_write', {'command': 'echo', 'timeout': 5}) is False
        assert approvals.consume('c1', 'run_cmd', {'command': 'echo', 'timeout': 5}) is True

    def test_revoke_drops_every_grant_for_that_conversation(self):
        approvals.grant('c1', 'run_cmd', {'command': 'a'}, 'session')
        approvals.grant('c2', 'run_cmd', {'command': 'a'}, 'session')
        assert approvals.revoke('c1') == 1
        assert approvals.consume('c1', 'run_cmd', {'command': 'a'}) is False
        assert approvals.consume('c2', 'run_cmd', {'command': 'a'}) is True


class TestSettlingAQuestion:
    def test_allow_once_grants_exactly_one_call(self):
        labels = _labels()
        approvals.request('c1', 'run_cmd', {'command': 'x'}, 'call_1', labels)
        assert approvals.settle('c1', 'call_1', [{'id': 'approval', 'selected': [labels['once']]}]) == 'once'
        assert approvals.consume('c1', 'run_cmd', {'command': 'x'}) is True
        assert approvals.consume('c1', 'run_cmd', {'command': 'x'}) is False

    def test_allow_for_session_is_reused(self):
        labels = _labels()
        approvals.request('c1', 'run_cmd', {'command': 'x'}, 'call_1', labels)
        assert approvals.settle('c1', 'call_1', [{'id': 'approval', 'selected': [labels['session']]}]) == 'session'
        assert approvals.consume('c1', 'run_cmd', {'command': 'x'}) is True
        assert approvals.consume('c1', 'run_cmd', {'command': 'x'}) is True

    def test_a_denial_grants_nothing(self):
        labels = _labels()
        approvals.request('c1', 'run_cmd', {'command': 'x'}, 'call_1', labels)
        assert approvals.settle('c1', 'call_1', [{'id': 'approval', 'selected': [labels['deny']]}]) == ''
        assert approvals.consume('c1', 'run_cmd', {'command': 'x'}) is False

    def test_a_cancel_grants_nothing(self):
        labels = _labels()
        approvals.request('c1', 'run_cmd', {'command': 'x'}, 'call_1', labels)
        assert approvals.settle('c1', 'call_1', []) == ''
        assert approvals.settle('c1', 'call_1', [{'id': 'approval', 'selected': []}]) == ''
        assert approvals.consume('c1', 'run_cmd', {'command': 'x'}) is False

    def test_a_pending_request_cannot_be_answered_twice(self):
        labels = _labels()
        approvals.request('c1', 'run_cmd', {'command': 'x'}, 'call_1', labels)
        assert approvals.settle('c1', 'call_1', [{'selected': [labels['session']]}]) == 'session'
        assert approvals.settle('c1', 'call_1', [{'selected': [labels['session']]}]) == ''

    def test_another_conversation_cannot_settle_it(self):
        labels = _labels()
        approvals.request('c1', 'run_cmd', {'command': 'x'}, 'call_1', labels)
        assert approvals.settle('c2', 'call_1', [{'selected': [labels['session']]}]) == ''
        assert approvals.consume('c1', 'run_cmd', {'command': 'x'}) is False


class TestTheToolGate:
    def _off(self, monkeypatch):
        monkeypatch.setattr(tools, 'get_setting', lambda key, *a, **k: key != 'ai_auto_approve')

    def test_auto_approve_on_keeps_todays_behaviour(self, monkeypatch):
        monkeypatch.setattr(tools, 'get_setting', lambda key, *a, **k: True)
        tools.require_approval('rerun_node', {'node_id': 'n2'}, {'conversation_id': 'c1'})

    def test_a_mutating_tool_needs_a_grant_when_auto_approve_is_off(self, monkeypatch):
        self._off(monkeypatch)
        with pytest.raises(AIError) as caught:
            tools.require_approval('rerun_node', {'node_id': 'n2'}, {'conversation_id': 'c1'})
        assert caught.value.key == 'ai.approvalRequired'

    def test_a_grant_lets_the_same_call_through(self, monkeypatch):
        self._off(monkeypatch)
        approvals.grant('c1', 'rerun_node', {'node_id': 'n2'}, 'wait')
        tools.require_approval('rerun_node', {'node_id': 'n2'}, {'conversation_id': 'c1'})
        with pytest.raises(AIError):
            tools.require_approval('rerun_node', {'node_id': 'n2'}, {'conversation_id': 'c1'})

    def test_executing_an_apply_tool_asks_before_touching_the_records(self, monkeypatch):
        """``apply_node_result`` is ``write:project``; the old gate only checked write:files/exec:cmd."""
        from ai.types import ToolSpec

        asked = []
        monkeypatch.setattr(tools, 'APPROVAL_TOOLS', ('demo_apply',))
        monkeypatch.setattr(tools, 'require_approval', lambda name, args, ctx: asked.append(name))
        spec = ToolSpec(
            name='demo_apply',
            description='demo',
            parameters={},
            permission='write:project',
            handler=lambda args, ctx: {'ok': True},
        )
        monkeypatch.setitem(tools.TOOLS, 'demo_apply', spec)
        assert tools.execute('demo_apply', {'node_id': 'n1'}, {}) == {'ok': True}
        assert asked == ['demo_apply']

    def test_a_setting_tool_is_not_blocked_by_the_approval_switch(self, monkeypatch):
        """``workspace_set`` is a panel setting, not a per-call act: an approval grant is keyed to
        exact args and can never cover a folder choice, so requiring one made the tool unusable
        whenever ai_auto_approve was off — even after the user approved it."""
        self._off(monkeypatch)
        tools.require_approval('workspace_set', {'path': '/tmp'}, {'conversation_id': 'c1'})

    def test_execute_refuses_run_cmd_without_a_grant(self, monkeypatch):
        self._off(monkeypatch)
        with pytest.raises(AIError) as caught:
            tools.execute('run_cmd', {'command': 'pytest -q'}, {'conversation_id': 'c1'})
        assert caught.value.key == 'ai.approvalRequired'
        assert caught.value.params['tool'] == 'run_cmd'

    def test_a_cloud_host_refuses_even_with_a_grant(self, monkeypatch):
        """The safety switch is not a capability: a shared host has no user filesystem at all."""
        monkeypatch.setattr(Config, 'CLOUD_MODE', True)
        approvals.grant('c1', 'workspace_write', {'path': 'a.txt', 'content': 'x'}, 'session')
        with pytest.raises(AIError) as caught:
            tools.execute('workspace_write', {'path': 'a.txt', 'content': 'x'}, {'conversation_id': 'c1'})
        assert caught.value.key == 'ai.workspaceCloud'
