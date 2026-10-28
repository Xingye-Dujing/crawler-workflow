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
    'services/biblio/cluster.py',
    'services/charts/visualizer.py',
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

        The answer travels through a FILE the child writes, not through a captured pipe. Measured on
        the CI runner: ``subprocess.run(capture_output=True)`` came back ``returncode=0, stderr=''``
        with ``stdout=None`` — the child had run and exited cleanly, so a pipe-based assertion would
        be failing on a transport the harness swallowed rather than on the boot. What this test
        claims is which modules ``import app`` loads; that claim should not depend on how the number
        is carried.
        """
        report = tmp_path / 'boot_modules.txt'
        script = (
            'import os, sys, app\n'
            f'roots = {list(HEAVY_ROOTS)!r}\n'
            "leaked = sorted({name.split('.')[0] for name in sys.modules if name.split('.')[0] in roots})\n"
            "with open(os.environ['CIXI_BOOT_REPORT'], 'w', encoding='utf-8') as handle:\n"
            '    handle.write("|".join(leaked))\n'
        )
        environment = {
            **os.environ,
            'PYTHONPATH': str(BACKEND),
            'CRAWLER_DATA_ROOT': str(tmp_path),
            'CIXI_BOOT_REPORT': str(report),
        }
        completed = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True,
            env=environment,
            timeout=180,
            check=False,  # asserted below, with the child's own returncode and stderr attached
        )
        # Bytes, not ``text=True``: a piped child writes the machine's ANSI code page, and the
        # CI runner's cp1252 cannot decode the UTF-8 the app prints — the reader thread raised
        # ``UnicodeDecodeError`` and pytest reported it as an unhandled thread exception. The
        # boundary is crossed in bytes precisely so the decode below is the only decoding.
        failure = completed.stderr.decode('utf-8', 'replace')
        assert completed.returncode == 0, (
            f'`import app` failed on this machine: rc={completed.returncode} stderr={failure[-1500:]}'
        )
        assert report.is_file(), f'the child exited 0 without writing its report to {report}'
        leaked = [name for name in report.read_text(encoding='utf-8').strip().split('|') if name]
        assert not leaked, f'`import app` loaded {leaked}; the boot path is supposed to stay out of them'
