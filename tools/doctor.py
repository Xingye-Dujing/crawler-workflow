"""The capability doctor, from the repository root:

    python tools/doctor.py --all
    python tools/doctor.py --capability node:tokenize

Every row is a live check against the manifest tree; the artifact row re-renders the generated
files and compares bytes. Exit code 1 when any row is unchecked, so a script can gate on it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Check every capability manifest against the kernel contract.')
    parser.add_argument('--all', action='store_true', help='every capability (the default)')
    parser.add_argument('--capability', action='append', default=[], help='kind:id (repeatable)')
    args = parser.parse_args(argv)

    if str(ROOT / 'backend') not in sys.path:
        sys.path.insert(0, str(ROOT / 'backend'))
    from capabilities_kernel import doctor

    rows = doctor.check_all(args.capability)
    print(doctor.report(rows))
    legacy = doctor.legacy_node_types()
    if legacy:
        print(f'\n{len(legacy)} node type(s) still declared in nodes/catalog.py (P2): {", ".join(legacy)}')
    return 0 if all(row['ok'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
