"""``backend/core`` is the foundation layer: stdlib only, and nothing of ours but itself.

The direction is the whole point of the package. ``refs``/``machine``/``procs`` answer questions
every other layer asks (how to read a switch, where Chrome lives on this OS, how to spawn a child),
so they must be answerable without loading Flask, pandas, Selenium or the application — that is
also the startup-budget rule ``test_boot_import_budget`` protects from the other side.

A module added here that imports a domain package would invert the arrow, and the inversion would
only show up as a circular import months later. So the scan is over the package, not a file list:
the next module is covered the day it is created.
"""

import ast
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / 'backend' / 'core'
STDLIB = set(sys.stdlib_module_names)

#: Layers that sit ABOVE core: importing any of them would invert the arrow (and only show up as a
#: circular import later). The heavy stacks are listed for the startup budget: pandas/numpy/requests
#: are already on the app's boot path, so they are allowed here — sklearn/scipy/matplotlib/Selenium
#: are the ones ``test_boot_import_budget`` exists to keep off it.
ABOVE_CORE = {
    'app',
    'api',
    'crawlers',
    'services',
    'analyzers',
    'engine',
    'nodes',
    'sessions',
    'scheduling',
    'i18n',
    'runtime',
}
HEAVY = {'sklearn', 'scipy', 'matplotlib', 'joblib', 'torch', 'transformers', 'selenium', 'flask'}


def _roots(path: Path) -> set[str]:
    """Every top-level module name imported by *path* (``from x.y import z`` answers ``x``)."""
    tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split('.')[0])
    return found


class TestTheFoundationImportsNoLayerAboveIt:
    def test_core_exists_and_holds_the_four_foundation_modules(self):
        modules = {path.stem for path in CORE.glob('*.py')} - {'__init__'}
        assert modules == {'config', 'refs', 'machine', 'procs'}, (
            f'core/ holds {sorted(modules)}; a new module belongs here only if every layer may import it — '
            'say so in the package docstring and extend this contract deliberately'
        )

    def test_nothing_in_core_imports_a_domain_layer_or_a_heavy_library(self):
        forbidden = set()
        for path in sorted(CORE.glob('*.py')):
            if path.name == '__init__.py':
                continue
            for root in _roots(path):
                if root in STDLIB or root == 'core':
                    continue
                if root in ABOVE_CORE or root in HEAVY:
                    forbidden.add(f'{path.name} imports {root}')
        assert forbidden == set(), (
            'core/ reached upward: ' + '; '.join(sorted(forbidden)) + ' — those imports belong to a layer above core'
        )

    def test_the_old_utils_tree_is_gone(self):
        """The move is only finished when the old package cannot come back by habit."""
        assert not (CORE.parent / 'utils').exists(), 'backend/utils/ still exists; the three modules live in core/ now'


class TestTheBackendRootStaysThin:
    """The root holds the composition root and the message machinery, nothing else.

    ``state``/``stores``/``settings_store``/``crawl_gate``/``transport`` used to sit beside
    ``app.py``; they are the process-wide runtime layer now (``runtime/``). A new root module is
    how that layer starts to grow back: it is importable by everything, so it attracts imports
    from every direction and the next one is a cycle nobody sees until collection fails.
    """

    def test_only_app_and_i18n_are_modules_at_the_root(self):
        root = CORE.parent
        modules = {path.name for path in root.glob('*.py')} - {'__init__.py'}
        assert modules == {'app.py', 'i18n.py'}, (
            f'backend/ holds {sorted(modules)}; process-wide wiring belongs in runtime/, domain code in its '
            'own package — the root is the composition root (app.py) and the message machinery (i18n.py)'
        )

    def test_the_runtime_package_never_imports_the_application(self):
        """``runtime`` is imported BY ``app``; importing it back would close the cycle at import."""
        offenders = []
        for path in sorted((CORE.parent / 'runtime').glob('*.py')):
            roots = _roots(path)
            if 'app' in roots:
                offenders.append(path.name)
        assert offenders == [], (
            f'runtime/ imports app: {offenders} — the composition root imports runtime, not the reverse'
        )
