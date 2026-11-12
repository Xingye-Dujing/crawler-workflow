"""Enumerate CI's pylint targets as files, identically on Windows, Linux and macOS.

The workflow used to enumerate targets with PowerShell (``Get-ChildItem``), so adding a Linux
runner would have changed the gate rather than widened the code it checks. This module is the
one portable answer: every target is a *file* (a bare directory name can resolve to an installed
distribution in ``site-packages`` — ``packaging`` did), each tier refuses an empty list instead
of reporting a green run over no sources, and the command carries the same standard the local
invocation uses.

Usage (from the repository root):

    python tools/ci_lint_tiers.py product
    python tools/ci_lint_tiers.py tests

The third tier (``.pylintrc.probes``) stays local on purpose: ``backend/test_*.py`` are
gitignored measurement scripts, so a hosted runner has nothing to lint.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: (root, recurse, drop files named ``test_*``). The product roots are the same list CI has always
#: linted; ``test_*.py`` under ``backend/`` are the local measurement scripts, not product code.
#:
#: ``desktop`` MUST recurse: the packaging build products live beside ``installer.py``, not under a
#: hand-maintained folder, so ``desktop/bootstrap/`` (the installer, its macOS twin, the theme and
#: the plan/bert helpers — roughly 2,400 lines that decide where the app is installed and which
#: bytes are downloaded) was silently outside BOTH pylint here and the two ruff commands in
#: ``.github/workflows/ci.yml``. A gate that names ``desktop`` while never opening the files that
#: ship is the failure mode this list exists to prevent.
PRODUCT_ROOTS = (
    ('backend', True, True),
    ('desktop', True, False),
    ('tools', True, False),
    ('ml_train/scripts', False, False),
)

#: One tier per standard: product code may not be exempt from anything, and ``tests/`` is exempt
#: only from the pytest idioms its own ``.pylintrc.tests`` names.
TIERS = {
    'product': (PRODUCT_ROOTS, '.pylintrc'),
    'tests': ((('tests', True, False),), '.pylintrc.tests'),
}

#: FATAL, ERROR and WARNING are zero; CONVENTION and REFACTOR advice is present by design, so the
#: scoping lives on the command line exactly as it did in the workflow and never in a tier config.
PYLINT_FLAGS = ('--persistent=n', '--disable=C,R', '--fail-on=W,E,F', '--jobs=2')


def _sources(root: Path, recurse: bool, drop_probes: bool) -> list[Path]:
    """Every product source under ``root``, excluding other people's code.

    Recursing means the exclusions have to be explicit. ``desktop/.venv-build`` is the build
    environment (``site-packages`` inside it, ~9,700 files) — the same rule
    ``tests/unit/gates/test_lint_gate.py`` states, so the gate and this tier agree, and linting it
    is also how the command line overflowed (measured: ``WinError 206`` at 9,803 files).
    """
    pattern = '**/*.py' if recurse else '*.py'
    found = [path for path in root.glob(pattern) if path.is_file() and _is_ours(path, root)]
    if drop_probes:
        found = [path for path in found if not path.name.startswith('test_')]
    return found


#: Generated or third-party trees, by the same names the lint gate refuses. `ml_train` is here for
#: the global walk; `ml_train/scripts` is named as a root of its own, so it is still linted.
SKIP_DIRS = {'dist', 'build', '.git', 'node_modules', 'data', 'logs', 'scratchpad', 'ml_train'}
SITE_PACKAGES = 'site-packages'
VENV_PREFIX = '.venv'


def _is_ours(path: Path, root: Path) -> bool:
    """True when every part of the path is ours: no environment, no generated tree."""
    parts = path.relative_to(root).parts
    return not any(part in SKIP_DIRS or part == SITE_PACKAGES or part.startswith(VENV_PREFIX) for part in parts)


def targets(tier: str, root: Path = REPO) -> list[Path]:
    """Every file the tier owns, in a stable order."""
    roots, _ = TIERS[tier]
    files: list[Path] = []
    for relative, recurse, drop_probes in roots:
        files.extend(_sources(root / relative, recurse, drop_probes))
    return sorted(files, key=lambda path: path.as_posix())


def _argument(path: Path) -> str:
    """One pylint target as a command-line argument.

    Paths inside the repository are passed RELATIVE to ``REPO`` (the invocation's cwd) so the
    Windows ``CreateProcess`` limit measures this repository's names, not its absolute location.
    After the tree grew past 400 files the absolute form overflowed 32,767 characters on a
    checkout whose root is 41 characters long (WinError 206), while the relative form left more
    than half of the budget unused. A path outside ``REPO`` (the unit test's tmp tree) stays
    absolute: ``relative_to`` would raise, and that caller has no repository-relative spelling.
    """
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def command(tier: str, files: list[Path]) -> list[str]:
    """The pylint invocation for one tier, with the paths as explicit arguments."""
    _, rcfile = TIERS[tier]
    return [
        sys.executable,
        '-m',
        'pylint',
        *PYLINT_FLAGS,
        f'--rcfile={rcfile}',
        *(_argument(path) for path in files),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Lint one of the two CI lint tiers.')
    parser.add_argument('tier', choices=sorted(TIERS))
    args = parser.parse_args(argv)

    files = targets(args.tier, root=REPO)
    if not files:
        print(f'no {args.tier} sources found to lint', file=sys.stderr)
        return 1
    print(f'linting {len(files)} {args.tier} files')
    result = subprocess.run(command(args.tier, files), cwd=REPO, check=False)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
