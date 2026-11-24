"""Capability CLI: `python tools/capability_cli.py list|show|validate`. Thin wrapper over services."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'backend') not in sys.path:
    sys.path.insert(0, str(ROOT / 'backend'))


def main(argv: list[str] | None = None) -> int:
    from services.capability_cli import main as run

    return run(argv)


if __name__ == '__main__':
    raise SystemExit(main())
