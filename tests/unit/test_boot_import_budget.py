"""The boot path may not load the numeric stack.

Measured on this machine before the fix: ``import app`` cost **9.2 s**, and 5.4 s of that was one
top-level ``from sklearn.ensemble import IsolationForest`` in ``analyzers/anomaly.py`` — every
analyzer is imported by ``app``, so a process that never runs an ML node still paid for all of
sklearn. Afterwards: **2.07 s** and none of those packages in ``sys.modules``.

Two checks, because they answer different questions. The AST check names the file to fix when a
top-level import comes back. The subprocess check is the one that cannot be fooled: a module that
imports a third module which imports sklearn leaks just as badly, and only a fresh interpreter
says so. Neither measures wall-clock — a budget in seconds would fail a slow runner and pass a
fast one while proving nothing either way.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / 'backend'

#: Packages whose import is expensive enough that loading them at boot is a defect. ``torch`` and
#: ``transformers`` are already deferred by ``analyzers/sentiment.py`` (and are excluded from the
#: desktop build entirely); the rest is what this change moved.
HEAVY_ROOTS = ('sklearn', 'scipy', 'matplotlib', 'joblib', 'torch', 'transformers')

#: Files reachable from ``import app`` that must stay light. A module listed here is on the boot
#: path, so a top-level import of anything in :data:`HEAVY_ROOTS` in it costs every start.
BOOT_PATH_MODULES = (
    'analyzers/anomaly.py',
    'analyzers/clustering.py',
    'analyzers/keyword.py',
    'analyzers/ml_base.py',
    'analyzers/significance.py',
    'services/biblio_cluster.py',
    'services/visualizer.py',
)


def _top_level_imports(path: Path) -> list:
    """Module-body import names only — an import inside a function is the point of the rule."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


class TestNoHeavyTopLevelImports:
    @pytest.mark.parametrize('relative', BOOT_PATH_MODULES)
    def test_module_body_imports_stay_light(self, relative):
        offenders = [name for name in _top_level_imports(BACKEND / relative) if name.split('.')[0] in HEAVY_ROOTS]
        assert not offenders, (
            f'backend/{relative} imports {offenders} at module level. It sits on the boot path '
            'through `import app`, so this is seconds of process start paid by every run — move '
            'the import into the function that uses it, as `analyzers/ml_base.py` does.'
        )

    def test_the_boot_path_list_is_not_stale(self):
        """A renamed or deleted file would silently shrink the guard to nothing."""
        missing = [relative for relative in BOOT_PATH_MODULES if not (BACKEND / relative).is_file()]
        assert not missing, f'boot-path modules no longer present: {missing}'


class TestBootImportBudget:
    def test_importing_app_loads_none_of_the_numeric_stack(self, tmp_path):
        """Run in a fresh interpreter: transitive leakage is what actually costs the boot.

        ``CRAWLER_DATA_ROOT`` points the child at its own data and log directories, the same
        isolation the rest of the suite uses — importing the app must not touch the developer's
        ``data/`` or ``logs/``, which the suite fails over byte-for-byte.
        """
        script = (
            'import sys, app\n'
            f'roots = {list(HEAVY_ROOTS)!r}\n'
            "leaked = sorted({name.split('.')[0] for name in sys.modules if name.split('.')[0] in roots})\n"
            "print('|'.join(leaked))\n"
        )
        environment = {
            **os.environ,
            'PYTHONPATH': str(BACKEND),
            'CRAWLER_DATA_ROOT': str(tmp_path),
        }
        completed = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True,
            check=True,
            env=environment,
            text=True,
            timeout=180,
        )
        leaked = [name for name in completed.stdout.strip().split('|') if name]
        assert not leaked, f'`import app` loaded {leaked}; the boot path is supposed to stay out of them'
