"""Refuse a release whose version is not a prefix of the application's own ``APP_VERSION``.

The installer's ``AppVersion``, the receipt's ``current-version`` and the update feed's
``version`` all describe the same build. A dispatch that left the workflow's default in place
shipped ``1.0.0`` beside a program that reported ``2026.x`` — every later audit and rollback
then disagreed with the program itself. This is a one-line gate for the release workflows.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO / 'backend' / 'services' / 'version.py'


def app_version() -> str:
    text = VERSION_FILE.read_text(encoding='utf-8')
    match = re.search(r"^APP_VERSION\s*=\s*'([^']+)'", text, re.MULTILINE)
    if not match:
        raise SystemExit(f'cannot read APP_VERSION from {VERSION_FILE}')
    return match.group(1)


def check(version: str) -> str:
    """Return the version, or refuse it by name. A release may name a prefix of APP_VERSION."""
    wanted = str(version or '').strip()
    current = app_version()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:\.\d+)?', wanted):
        raise SystemExit(f'release version is not 3-4 numeric groups: {wanted or "(empty)"}')
    if not current.startswith(wanted):
        raise SystemExit(f'release version {wanted} is not a prefix of APP_VERSION {current}')
    return wanted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Check a release version against APP_VERSION.')
    parser.add_argument('version')
    args = parser.parse_args(argv)
    print(f'release version {check(args.version)} matches APP_VERSION {app_version()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
