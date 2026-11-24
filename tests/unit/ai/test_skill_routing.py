"""The automatic skill router: the host's cues actually decide, and `auto` reaches it.

`auto` is the panel's default. Before this measured slice the host handed the framework an empty
skill, so every automatic turn answered as `general`: the router existed but had nothing to read.
These cases pin the two halves — the host declares Chinese cues the router can score, and a turn
started with `auto` records which skill it chose.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from agent_workspace import AgentWorkspace
from ai_host import CaiXiHuiHost

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
EVAL = REPO / 'tools' / 'eval_skill_routing.py'


@pytest.fixture(scope='module')
def tasks():
    """The eval table, read from the tool that prints it — one table, two readers."""
    spec = importlib.util.spec_from_file_location('eval_skill_routing', EVAL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['eval_skill_routing'] = module
    spec.loader.exec_module(module)
    return module.TASKS


@pytest.fixture(scope='module')
def workspace(tmp_path_factory):
    host = CaiXiHuiHost(data_dir=tmp_path_factory.mktemp('ai') / 'ai', lang='zh')
    instance = AgentWorkspace(host)
    yield instance
    instance.close()


class TestTheHostCues:
    def test_every_row_of_the_table_routes_to_an_acceptable_skill(self, workspace, tasks):
        misses = []
        for task in tasks:
            chosen = workspace.skills.route(task['prompt'], 'default')
            if chosen not in task['skills']:
                misses.append(f'{task["id"]}: chose {chosen}, expected {task["skills"]}')
        assert misses == [], 'the automatic router lost: ' + '; '.join(misses)

    def test_an_empty_sentence_is_general_rather_than_a_guess(self, workspace):
        assert workspace.skills.route('', 'default') == 'general'
        assert workspace.skills.route('   ', 'default') == 'general'

    def test_every_host_skill_declares_a_cue_set(self, workspace):
        """A skill with no keyword can only be reached by its English id being typed."""
        from ai import skills as legacy_skills

        missing = [identifier for identifier, spec in legacy_skills.BUILTIN.items() if not spec.keywords]
        assert missing == [], f'skills auto-routing cannot read: {missing}'

    def test_a_cue_is_carried_across_the_host_boundary(self, workspace):
        """`ai.types.SkillSpec` is converted to the framework's own; the cues ride along."""
        found = {spec.id: spec for spec in workspace.host.skills()}
        assert found['charts'].keywords, 'the adapter dropped the host keywords'
