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
PRODUCT_ROOTS = (
    ('backend', True, True),
    ('desktop', False, False),
    ('tools', False, False),
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
    pattern = '**/*.py' if recurse else '*.py'
    found = [path for path in root.glob(pattern) if path.is_file()]
    if drop_probes:
        found = [path for path in found if not path.name.startswith('test_')]
    return found


def targets(tier: str, root: Path = REPO) -> list[Path]:
    """Every file the tier owns, in a stable order."""
    roots, _ = TIERS[tier]
    files: list[Path] = []
    for relative, recurse, drop_probes in roots:
        files.extend(_sources(root / relative, recurse, drop_probes))
    return sorted(files, key=lambda path: path.as_posix())


def command(tier: str, files: list[Path]) -> list[str]:
    """The pylint invocation for one tier, with the paths as explicit arguments."""
    _, rcfile = TIERS[tier]
    return [
        sys.executable,
        '-m',
        'pylint',
        *PYLINT_FLAGS,
        f'--rcfile={rcfile}',
        *(str(path) for path in files),
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
