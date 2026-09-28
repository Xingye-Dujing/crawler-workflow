"""Nothing may live after a terminator in the same block — it never runs.

``/api/workflow/load`` carried a second copy of its own body after the final
``return`` (a paste that survived several refactors, fingerprint line included):
reading it suggested the handler re-checked the name or re-loaded the file, and
editing the dead copy would have "changed" behavior that never executes. The
same block sat in ``xiaohongshu._note_id``.

The gate is the whole backend, not those two handlers: any ``return`` /
``raise`` / ``break`` / ``continue`` followed by another statement in the SAME
block is unreachable by definition, so one walk over every module pins the
class of bug rather than its two instances.
"""

import ast
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / 'backend'

TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def _block_bodies(fn):
    """Every statement list a terminator can strand code in: the function body
    and each compound statement's own body (``orelse``/``finalbody`` arrive as
    separate If/Try nodes from ast.walk)."""
    yield fn.body
    for node in ast.walk(fn):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            yield node.body


def _unreachable():
    """(file, function, line) for every statement that follows a terminator."""
    found = []
    for path in sorted(BACKEND_DIR.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for body in _block_bodies(fn):
                for i, stmt in enumerate(body[:-1]):
                    if isinstance(stmt, TERMINATORS):
                        found.append((path, fn.name, body[i + 1].lineno))
    return found


class TestNoUnreachableCode:
    def test_no_backend_function_strands_statements_after_a_terminator(self):
        bad = _unreachable()
        assert not bad, 'unreachable code after return/raise/break/continue: ' + ', '.join(
            f'{p.relative_to(BACKEND_DIR)}::{fn}() line {line}' for p, fn, line in bad
        )


class TestLoadWorkflowWritesStateOnce:
    """The dead copy reset the ambient run name and fingerprint a second time;
    the live handler must own exactly one write of each."""

    @classmethod
    @pytest.fixture(scope='class')
    def load_fn(cls):
        tree = ast.parse((BACKEND_DIR / 'app.py').read_text(encoding='utf-8'))
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name == 'load_workflow':
                return fn
        pytest.fail('load_workflow is gone from app.py')

    def _state_keys_written(self, load_fn):
        keys = []
        for node in ast.walk(load_fn):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript):
                sub = node.targets[0]
                if (
                    isinstance(sub.value, ast.Name)
                    and sub.value.id == 'execution_state'
                    and isinstance(sub.slice, ast.Constant)
                ):
                    keys.append(sub.slice.value)
        return keys

    def test_fingerprint_is_written_exactly_once(self, load_fn):
        keys = self._state_keys_written(load_fn)
        assert keys.count('fingerprint') == 1, keys

    def test_workflow_name_is_written_exactly_once(self, load_fn):
        keys = self._state_keys_written(load_fn)
        assert keys.count('workflow_name') == 1, keys
