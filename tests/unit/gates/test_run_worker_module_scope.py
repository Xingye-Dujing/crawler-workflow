"""Every run helper lives at module scope — nothing may move back into a closure.

AGENTS pins the rule ("a run helper that needs no state from the claim lives at module scope,
and a captured name is a parameter") because a helper inside ``begin_run`` is unreachable to a
test: the checkpoint/resume rules it implements can only be asserted through the whole run start.
On 2026-10-29 the last six were lifted (``_carries_artifact``, ``_node_of``, ``_inputs_for``,
``_component_run``, ``_run_workflow_wrapper`` and ``run`` → ``_run_worker``), proved verbatim by
``ast.dump`` + ``symtable`` in ``build/lift_run_orchestration.py``.

A proven move is only permanent if a gate re-asks it, so this file fails when:
  * a module-level function in ``engine/run.py`` nests another function again, or
  * one of the six lifted names disappears from module scope, or
  * the run thread stops being ``target=_run_worker`` with ``name='run'`` — the process
    monitor's kill guard matches on that thread name, and renaming it silently unarmours it.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

RUN_PY = Path(__file__).resolve().parents[3] / 'backend' / 'engine' / 'run.py'

LIFTED = ('_carries_artifact', '_node_of', '_inputs_for', '_component_run', '_run_workflow_wrapper', '_run_worker')


def _tree():
    return ast.parse(RUN_PY.read_text(encoding='utf-8'))


def _top_level_functions(tree):
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


class TestRunHelpersStayAtModuleScope:
    def test_no_module_level_function_nests_another(self):
        offenders = {
            outer: sorted(
                {inner.name for inner in ast.walk(node) if isinstance(inner, ast.FunctionDef) and inner is not node}
            )
            for outer, node in _top_level_functions(_tree()).items()
        }
        nested = {name: inners for name, inners in offenders.items() if inners}
        assert not nested, (
            f'{nested} define a function inside a function again: no test can reach it, and the lift of '
            '2026-10-29 (build/lift_run_orchestration.py) is being undone by an unproven re-embedding'
        )

    def test_the_six_lifted_helpers_are_module_level_functions(self):
        present = set(_top_level_functions(_tree()))
        missing = sorted(set(LIFTED) - present)
        assert not missing, f'{missing} left module scope — a test that calls them directly now gets an AttributeError'
        assert 'begin_run' in present

    def test_the_run_thread_targets_the_module_worker_and_keeps_its_name(self):
        thread_calls = [
            node
            for node in ast.walk(_top_level_functions(_tree())['begin_run'])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'Thread'
        ]
        assert len(thread_calls) == 1, f'begin_run builds {len(thread_calls)} threads; the kill guard names one'
        keywords = {kw.arg: kw.value for kw in thread_calls[0].keywords}
        assert isinstance(keywords.get('target'), ast.Name) and keywords['target'].id == '_run_worker', (
            'the run thread no longer runs the module-level worker — begin_run grew its closure back'
        )
        assert isinstance(keywords.get('name'), ast.Constant) and keywords['name'].value == 'run', (
            "kill_process protects the run worker by the thread NAME 'run'; without it a stray SystemExit "
            'can orphan a Chrome and hold its profile lock'
        )
