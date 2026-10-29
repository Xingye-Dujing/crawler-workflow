"""A module file beside a package of the same name is invisible dead code.

Python's ``FileFinder`` checks the package directory before the module file, so
``services/biblio/metrics/`` wins and ``services/biblio/metrics.py`` is never imported — yet it
still looks like product code in a diff, still grows with edits, and still passes any lint or
line count that reads files rather than the import graph.

Measured 2026-10-29: the Stage-5b split wrote the package but left the 1,996-line original in
place. Every test was green because nothing could ever import the leftover. This gate scans the
tree for that shape and proves itself against a synthetic package, so a clean run is a fact.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'


def _shadowed_modules(root: Path) -> list[str]:
    """Every ``x.py`` that loses the import to a sibling ``x/`` package, relative to *root*."""
    found = []
    for package in sorted(root.rglob('*')):
        if not package.is_dir() or '__pycache__' in package.parts:
            continue
        twin = package.with_suffix('.py')
        if twin.is_file():
            found.append(twin.relative_to(root).as_posix())
    return found


class TestNoModuleIsShadowedByItsPackage:
    def test_the_backend_has_no_shadowed_module(self):
        shadowed = _shadowed_modules(BACKEND)
        assert shadowed == [], (
            f'imported nowhere — a package of the same name wins the import: {shadowed}. '
            'Delete the file (the package is the code) or rename one of them'
        )

    def test_the_scan_finds_the_shape_it_is_guarding(self, tmp_path):
        """The gate has to be able to fail: a synthetic ``pkg/x.py`` + ``pkg/x/`` is exactly the
        defect, and a package without the twin must stay clean."""
        pkg = tmp_path / 'pkg'
        shadow = pkg / 'metrics'
        shadow.mkdir(parents=True)
        (shadow / '__init__.py').write_text('', encoding='utf-8')
        (pkg / 'metrics.py').write_text('X = 1\n', encoding='utf-8')
        (pkg / 'fine').mkdir()
        (pkg / 'fine' / '__init__.py').write_text('', encoding='utf-8')
        assert _shadowed_modules(tmp_path) == ['pkg/metrics.py']

    def test_a_clean_tree_reports_nothing(self, tmp_path):
        pkg = tmp_path / 'pkg' / 'clean'
        pkg.mkdir(parents=True)
        (pkg / '__init__.py').write_text('', encoding='utf-8')
        (tmp_path / 'pkg' / 'single.py').write_text('Y = 1\n', encoding='utf-8')
        assert _shadowed_modules(tmp_path) == []
