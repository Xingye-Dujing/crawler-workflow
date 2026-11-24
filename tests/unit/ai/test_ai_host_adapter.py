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


class TestTheReferenceSeam:
    def test_the_picker_offers_every_capability_skill(self, host):
        from capabilities_kernel import knowledge as kernel
        from capabilities_kernel import registry

        expected = {kernel.skill_id(manifest) for kind in kernel.KINDS for manifest in registry.manifests(kind)}
        rows = host.reference_candidates('default')
        skills = {row['id']: row for row in rows if row['kind'] == 'capability'}
        assert set(skills) == expected
        assert skills['node.tokenize']['detail'] == 'process'
        assert skills['node.tokenize']['label'] == 'tokenize'
        # An operator and a chart are capabilities too: the picker never truncates one kind away.
        assert 'operator.drop_null' in skills
        assert 'chart.bar' in skills

    def test_a_skill_reference_is_the_body_skill_load_returns(self, host):
        from ai import knowledge

        assert host.resolve_reference('capability', 'node.tokenize') == knowledge.load('node.tokenize')['markdown']

    def test_an_unknown_reference_kind_or_id_is_empty(self, host):
        assert host.resolve_reference('capability', 'node.nope') == ''
        assert host.resolve_reference('gadget', 'x') == ''
        assert host.resolve_reference('workflow', 'no-such-file') == ''

    def test_the_framework_merges_host_candidates_with_its_own(self, host):
        workspace = AgentWorkspace(host)
        try:
            workspace.add_file('default', 'note.txt')
            kinds = {row['kind'] for row in workspace.reference_candidates('default')}
        finally:
            workspace.close()
        assert {'capability', 'file'} <= kinds


class TestStrictMode:
    def test_only_the_unblocking_verbs_are_core(self, host):
        """``core_tools`` is a priority group, not the universal list.

        It used to return all of ``UNIVERSAL_TOOLS`` (21 names). The framework kept every core verb
        and checked the count afterwards, so a "12 tool" turn was offered 27 — and not one tool of
        the active skill. Measured on the real registry, every skill lost its own verbs.
        """
        assert set(host.core_tools()) == {'request_dataset_access', 'skill_catalog', 'skill_load'}
        assert 'request_dataset_access' in legacy_tools.UNIVERSAL_TOOLS

    def test_a_ranked_query_keeps_the_budget_and_the_skills_own_tools(self, host):
        """An English question reaches the descriptions: the 12-slot budget holds and the skill's
        own verbs are inside it."""
        from agent_workspace.tools import CONTROL_TOOLS, ToolRegistry

        registry = ToolRegistry(store=None, host=host, settings=None, context=None, workspace_provider=None)
        for spec in host.tools():
            registry.register(spec)
        universal = set(legacy_tools.UNIVERSAL_TOOLS)
        for skill_id, skill in legacy_skills.BUILTIN.items():
            own = tuple(name for name in skill.tools if name not in universal)
            if not own:
                continue
            offered = {
                row['name']
                for row in registry.schemas(
                    set(skill.tools) | universal,
                    query='dataset rows count',
                    limit=12,
                    priority=tuple(skill.tools),
                )
            }
            assert set(own) <= offered, f'{skill_id} lost its own tools to the budget: {sorted(set(own) - offered)}'
            # A skill's own list is the floor of the budget: python declares eight verbs of its own,
            # so its turn is offered 13 slots rather than 12 — the budget, not a ceiling.
            ceiling = max(12, len(skill.tools))
            assert len(offered - set(CONTROL_TOOLS)) <= ceiling, f'{skill_id} exceeded the budget: {sorted(offered)}'

    def test_a_query_the_ranking_cannot_read_offers_the_whole_allowlist(self, host):
        """A Chinese question against English descriptions scores 0 for every tool.

        The 12-slot cut then has nothing to decide with — it was an alphabetical tie-break that
        dropped four of the routing eval's own verbs (``workflow_run``, ``workflow_validate``, …)
        while the full offer list already scores 26/26 on both local models. So the registry offers
        the allowlist instead, and it says so: the largest allowlist this host declares
        (``conductor``) came to 36 tools, measured here rather than assumed.
        """
        from agent_workspace.tools import CONTROL_TOOLS, ToolRegistry

        registry = ToolRegistry(store=None, host=host, settings=None, context=None, workspace_provider=None)
        for spec in host.tools():
            registry.register(spec)
        universal = set(legacy_tools.UNIVERSAL_TOOLS)
        widest = 0
        for skill_id, skill in legacy_skills.BUILTIN.items():
            allowed = set(skill.tools) | universal
            offered = {
                row['name']
                for row in registry.schemas(
                    allowed,
                    query='这个数据集里有多少行',
                    limit=12,
                    priority=tuple(skill.tools),
                )
            }
            assert allowed <= offered, f'{skill_id} lost {sorted(allowed - offered)} to a cut on no signal'
            assert offered <= allowed | set(CONTROL_TOOLS), f'{skill_id} was offered tools outside its allowlist'
            widest = max(widest, len(offered - set(CONTROL_TOOLS)))
        assert widest <= 40, f'the widest allowlist grew to {widest} tools — re-measure the local models first'

    def test_strict_mode_is_on_by_default_and_can_be_read_from_settings(self, host):
        assert host.settings().get('tools.strict_local') is True
