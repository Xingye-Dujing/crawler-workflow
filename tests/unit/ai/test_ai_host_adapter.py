"""The host adapter delegates the product's registries instead of copying them.

A tool keeps its legacy handler; only its declaration changes. The approval lists are the SAME lists
the old door used, so a migration cannot silently make a deletion auto-approve.
"""

from __future__ import annotations

import pytest
from agent_workspace import AgentWorkspace
from ai import skills as legacy_skills
from ai import tools as legacy_tools
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

    def test_the_handler_is_the_legacy_function(self, host):
        tools = {spec.name: spec for spec in host.tools()}
        name = next(iter(tools))
        assert tools[name].handler is legacy_tools.TOOLS[name].handler


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
    def test_the_framework_sees_the_host_catalogue(self, host):
        workspace = AgentWorkspace(host)
        try:
            assert workspace.tools.get('project_facts') is not None
            assert workspace.skills.get('project', 'default') is not None
            assert workspace.commands.names() == ['compact', 'mode', 'skills', 'status']
        finally:
            workspace.close()
