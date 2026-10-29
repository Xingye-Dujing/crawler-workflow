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
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'
CONFTEST = REPO / 'tests' / 'api' / 'conftest.py'


def _importers():
    """``{module dotted name}`` for engine modules that resolve ``add_log`` as their own global."""
    found = set()
    for path in sorted((BACKEND / 'engine').glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != 'runtime.state':
                continue
            if any(alias.name == 'add_log' for alias in node.names):
                found.add(f'engine.{path.stem}')
    return found


def _forwarded():
    """The modules the api fixture forwards ``app.add_log`` into, read out of its own source."""
    text = CONFTEST.read_text(encoding='utf-8')
    blocks = re.findall(r'def _forward_run_console\(.*?\n(?=\n@pytest|\ndef |\nclass )', text, re.S)
    assert len(blocks) == 1, 'the console-forwarding fixture was renamed or duplicated — this gate stopped looking'
    return {match.group(1) for match in re.finditer(r"forward\(monkeypatch, ([\w.]+), 'add_log'", blocks[0])}


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
