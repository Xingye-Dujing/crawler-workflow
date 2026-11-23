"""The product's recipes are data the framework turns into a masked, evidence-gated run.

These cases pin the seam: every declared step names a tool the workspace really has, the catalogue
is visible to the model, and the framework's mask at the first step does not offer the write.
"""

import pytest
from agent_workspace import AgentWorkspace
from ai import recipes, tools
from ai_host import CaiXiHuiHost
from ai_host.adapter import FRAMEWORK_TOOLS

pytestmark = pytest.mark.unit


class TestTheDeclaration:
    def test_every_step_names_a_registered_tool(self):
        known = set(tools.TOOLS) | set(FRAMEWORK_TOOLS)
        for recipe in recipes.RECIPES:
            assert recipe['steps']
            for step in recipe['steps']:
                assert step['tool'] in known, (recipe['id'], step['tool'])

    def test_a_requires_names_an_earlier_step(self):
        for recipe in recipes.RECIPES:
            seen = set()
            for step in recipe['steps']:
                for required in step.get('requires') or ():
                    assert required in seen, (recipe['id'], step['id'], required)
                seen.add(step['id'])

    def test_the_catalogue_is_bilingual_and_stable(self):
        rows = {row['id']: row for row in recipes.catalog()}
        assert set(rows) == {'workflow_build', 'dataset_answer'}
        assert rows['workflow_build']['title'] == '建一条可运行的工作流'
        assert [step['tool'] for step in rows['workflow_build']['steps']] == [
            'workflow_schema',
            'present_artifact',
            'workflow_validate',
        ]


class TestTheFrameworkSeesIt:
    def test_the_host_declares_the_product_recipes(self, tmp_path):
        host = CaiXiHuiHost(data_dir=tmp_path / 'ai', lang='zh')
        assert [row['id'] for row in host.recipes()] == [row['id'] for row in recipes.RECIPES]

    def test_the_first_step_mask_hides_the_write(self, tmp_path):
        host = CaiXiHuiHost(data_dir=tmp_path / 'ai', lang='zh')
        workspace = AgentWorkspace(host)
        try:
            events, _answer = workspace.ask_text('placeholder', provider='complete')
            conversation_id = next(item['conversation_id'] for item in events if item['type'] == 'meta')
            state = workspace.start_recipe(conversation_id, 'workflow_build')
            allowed = {'workflow_schema', 'apply_workflow', 'workflow_validate', 'workflow_run', 'dataset_peek'}
            masked = workspace.recipes.mask(allowed, state)
        finally:
            workspace.close()
        assert state['current']['tool'] == 'workflow_schema'
        assert state['steps'][0]['status'] == 'current'
        assert 'workflow_schema' in masked
        assert 'apply_workflow' not in masked

    def test_the_project_context_lists_the_recipes(self):
        from ai import context

        facts = context.project_facts()
        assert '## 配方' in facts
        assert 'workflow_build' in facts
        assert 'dataset_answer' in facts
