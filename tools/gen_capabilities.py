"""Render the capability artifacts. Thin CLI over ``capabilities_kernel.generate``.

Usage (from the repository root):

    python tools/gen_capabilities.py
    python tools/gen_capabilities.py --check

The gate calls the same ``generate.check()`` from pytest, so a committed artifact cannot outlive
the manifest it was rendered from.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    if str(ROOT / 'backend') not in sys.path:
        sys.path.insert(0, str(ROOT / 'backend'))
    from capabilities_kernel import generate

    return generate.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
