"""Every run helper lives at module scope — nothing may move back into a closure.

AGENTS pins the rule ("a run helper that needs no state from the claim lives at module scope,
and a captured name is a parameter") because a helper inside ``begin_run`` is unreachable to a
test: the checkpoint/resume rules it implements can only be asserted through the whole run start.
On 2026-10-29 the last six were lifted (``_carries_artifact``, ``_node_of``, ``_inputs_for``,
``_component_run``, ``_run_workflow_wrapper`` and ``run`` → ``_run_worker``), proved verbatim by
``ast.dump`` + ``symtable`` in ``build/lift_run_orchestration.py``.

The 1900-line module became the ``engine/run/`` package on 2026-11-24, so the gate reads every
module of it: the rule is about module scope, not about one file name.

A proven move is only permanent if a gate re-asks it, so this file fails when:
  * a module-level function in ``engine/run/`` nests another function again, or
  * one of the six lifted names disappears from the package's module scope, or
  * the run thread stops being ``target=_run_worker`` with ``name='run'`` — the process
    monitor's kill guard matches on that thread name, and renaming it silently unarmours it.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

RUN_PACKAGE = Path(__file__).resolve().parents[3] / 'backend' / 'engine' / 'run'

LIFTED = ('_carries_artifact', '_node_of', '_inputs_for', '_component_run', '_run_workflow_wrapper', '_run_worker')

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _trees() -> dict[str, ast.Module]:
    """Every module of the package, by file name, so a failure names the file that broke it."""
    paths = sorted(RUN_PACKAGE.glob('*.py'))
    assert paths, f'{RUN_PACKAGE} holds no module — the run package moved or was renamed'
    return {path.name: ast.parse(path.read_text(encoding='utf-8')) for path in paths}


def _define_functions(tree: ast.Module) -> list[str]:
    return [node.name for node in tree.body if isinstance(node, _FUNCTIONS)]


def _top_level_functions(trees: dict[str, ast.Module]) -> dict[str, ast.FunctionDef]:
    """{name: node} across the whole package — a helper may live in any of its modules."""
    found: dict[str, ast.FunctionDef] = {}
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, _FUNCTIONS):
                found[node.name] = node
    return found


def _the_function(trees: dict[str, ast.Module], name: str) -> ast.FunctionDef:
    """`name`'s definition, from the module that owns it."""
    for tree in trees.values():
        if name in _define_functions(tree):
            for node in tree.body:
                if isinstance(node, _FUNCTIONS) and node.name == name:
                    return node
    raise AssertionError(f'{name} is not defined at module scope anywhere in {RUN_PACKAGE.name}/')


class TestRunHelpersStayAtModuleScope:
    def test_no_module_level_function_nests_another(self):
        offenders = {}
        for file_name, tree in _trees().items():
            for node in tree.body:
                if not isinstance(node, _FUNCTIONS):
                    continue
                inners = sorted(
                    {inner.name for inner in ast.walk(node) if isinstance(inner, _FUNCTIONS) and inner is not node}
                )
                if inners:
                    offenders[f'{file_name}::{node.name}'] = inners
        assert not offenders, (
            f'{offenders} define a function inside a function again: no test can reach it, and the lift of '
            '2026-10-29 (build/lift_run_orchestration.py) is being undone by an unproven re-embedding'
        )

    def test_the_six_lifted_helpers_are_module_level_functions(self):
        present = set(_top_level_functions(_trees()))
        missing = sorted(set(LIFTED) - present)
        assert not missing, f'{missing} left module scope — a test that calls them directly now gets an AttributeError'
        assert 'begin_run' in present

    def test_the_run_thread_targets_the_module_worker_and_keeps_its_name(self):
        thread_calls = [
            node
            for node in ast.walk(_the_function(_trees(), 'begin_run'))
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
