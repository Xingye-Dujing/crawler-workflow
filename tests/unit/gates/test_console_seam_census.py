"""A module that logs from the run path must be forwarded, or a console assertion measures nothing.

``tests/api/conftest.py`` answers ``app.add_log`` patches for the modules that print during a run:
they resolve ``add_log`` in their OWN namespace, so a test that patches the app seam captures
nothing unless the owner is forwarded to it (``tests/executor_seams.py::forward``). That is a list,
and a list is where this repo has already been burned twice — when the run start moved out of
``app.py``, and again on 2026-10-29 when the scheduled fire's narration moved to
``engine.run_schedule`` and two schedule cases silently asserted on an empty list until the forward
joined them.

So the census is asked of the source, not remembered by whoever moves a file: every module under
``backend/engine/`` that imports ``add_log`` from ``runtime.state`` must appear in the fixture.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'
CONFTEST = REPO / 'tests' / 'api' / 'conftest.py'


def _module_name(path: Path) -> str:
    relative = path.relative_to(BACKEND).with_suffix('')
    parts = list(relative.parts)
    if parts and parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def _importers():
    """``{module dotted name}`` for EVERY backend module that resolves ``add_log`` as its global.

    The census used to scan ``engine/*.py`` only, so 20+ executors, the settlement pass, the
    queue and the session routes were outside the gate while still printing through their own
    ``add_log``. A test that patched ``app.add_log`` and asserted one of those lines captured
    nothing — it was testing the patch, not the code.
    """
    found = set()
    for path in sorted(BACKEND.rglob('*.py')):
        if path.name.startswith('test_') or '__pycache__' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != 'runtime.state':
                continue
            if any(alias.name == 'add_log' for alias in node.names):
                found.add(_module_name(path))
    return found


def _dotted(node) -> str:
    """``api.biblio`` from an ``ast.Attribute`` chain; '' for anything the gate cannot name."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ''
    parts.append(node.id)
    return '.'.join(reversed(parts))


def _forwarded():
    """The modules the api fixture forwards ``app.add_log`` into, read by AST.

    A regex over the source matched a loop variable (``forward(monkeypatch, owner, ...)``)
    and could not tell a comment from a call. The calls are explicit, so the AST is exact.
    """
    tree = ast.parse(CONFTEST.read_text(encoding='utf-8'))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == 'forward' and len(node.args) >= 3):
            continue
        marker = node.args[2]
        if not (isinstance(marker, ast.Constant) and marker.value == 'add_log'):
            continue
        name = _dotted(node.args[1])
        if name:
            found.add(name)
    return found


class TestTheConsoleSeamCensus:
    def test_every_engine_module_that_logs_is_forwarded(self):
        importers = _importers()
        assert importers, 'no engine module imports add_log any more — this gate measures nothing'
        unforwarded = sorted(importers - _forwarded())
        assert not unforwarded, (
            f'{unforwarded} print to the console but are not forwarded to the app seam: a test that '
            'patches app.add_log would assert on a list the module never filled'
        )

    def test_the_forward_list_names_only_modules_that_log(self):
        """The other half: a forward for a module that no longer logs is a fixture pretending."""
        stale = sorted(_forwarded() - _importers())
        assert not stale, f'{stale} are forwarded but never resolve add_log — drop them from the fixture'
