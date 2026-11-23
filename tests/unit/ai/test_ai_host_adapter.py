"""The host adapter delegates the product's registries instead of copying them.

A tool keeps its legacy handler; only its declaration changes. The approval lists are the SAME lists
the old door used, so a migration cannot silently make a deletion auto-approve.
"""

from __future__ import annotations

import pytest
from agent_workspace import AgentWorkspace
from ai import skills as legacy_skills
from ai import tools as legacy_tools
from ai import validators as legacy_validators
from ai_host import CaiXiHuiHost
from ai_host.adapter import FRAMEWORK_TOOLS

pytestmark = pytest.mark.unit


@pytest.fixture
def host(tmp_path):
    return CaiXiHuiHost(data_dir=tmp_path / 'ai', lang='zh')


class TestTheToolCatalogue:
    def test_every_legacy_tool_is_ported_or_already_served_by_the_framework(self, host):
        tools = {spec.name: spec for spec in host.tools()}
        assert set(tools) | set(FRAMEWORK_TOOLS & set(legacy_tools.TOOLS)) >= set(legacy_tools.TOOLS)
        assert not set(tools) & set(FRAMEWORK_TOOLS)

    def test_approval_flags_come_from_the_product_lists(self, host):
        tools = {spec.name: spec for spec in host.tools()}
        for name in set(legacy_tools.APPROVAL_TOOLS) & set(tools):
            assert tools[name].mutating is True, name
        for name in set(legacy_tools.ALWAYS_APPROVAL_TOOLS) & set(tools):
            assert tools[name].always_ask is True, name

    def test_the_handler_runs_the_legacy_function_behind_the_product_gate(self, host):
        tools = {spec.name: spec for spec in host.tools()}
        name = next(iter(tools))
        assert tools[name].handler.__wrapped__ is legacy_tools.TOOLS[name].handler


class TestTheSkillCatalogue:
    def test_every_builtin_skill_is_declared(self, host):
        skills = {spec.id: spec for spec in host.skills()}
        assert set(skills) == set(legacy_skills.BUILTIN)

    def test_a_skill_keeps_its_prompt_and_tools(self, host):
        skills = {spec.id: spec for spec in host.skills()}
        legacy = legacy_skills.BUILTIN['project']
        assert skills['project'].prompt == legacy.prompt
        assert skills['project'].tools == tuple(legacy.tools)


class TestTheWorkspaceBoots:
    def test_the_product_settings_win_for_keys_it_already_owns(self, host, monkeypatch):
        def fake_setting(key, default=None):
            return {'ai_max_tool_rounds': 7, 'ai_auto_approve': False}.get(key, default)

        monkeypatch.setattr('ai_host.adapter.get_setting', fake_setting)
        settings = host.settings()
        assert settings.get('tools.max_rounds') == 7
        assert settings.get('approval.auto') is False
        assert settings.all()['tools.max_rounds'] == 7
        # A key the product has never heard of still comes from the workspace's own file.
        assert settings.get('chat.temperature') is not None

    def test_the_framework_sees_the_host_catalogue(self, host):
        workspace = AgentWorkspace(host)
        try:
            assert workspace.tools.get('project_facts') is not None
            assert workspace.skills.get('project', 'default') is not None
            assert workspace.commands.names() == ['compact', 'init', 'mode', 'skills', 'status']
            assert workspace.commands.host_names() == ['init']
        finally:
            workspace.close()

    def test_the_old_artifact_validators_gate_the_framework(self, host):
        workspace = AgentWorkspace(host)
        try:
            assert workspace.artifact_registry.kinds() == sorted(legacy_validators.registered_kinds())
            problems = workspace.artifact_registry.problems('workflow', {})
            assert problems and 'node list' in problems[0]
            assert workspace.artifact_registry.problems('note', {}) == []
        finally:
            workspace.close()
