"""Read back the managed-install records the Inno Setup [Code] section writes.

Two files, both deliberately easy to get wrong:

* ``current-version`` -- ASCII, no BOM, atomically renamed into place; a version TOKEN, never
  a path. A traversal here would let the next reader open a file outside the install root.
* ``versions/<token>/install.json`` -- UTF-8 WITHOUT BOM. Inno's ``SaveStringToFile`` writes
  the machine's ANSI codepage, so a non-ASCII user path turns the receipt into bytes nobody
  can decode (anomalyco/hex hit this as #1352). The installer uses
  ``SaveStringsToUTF8FileWithoutBOM``; this module refuses anything else.

The exe itself does NOT live under versions/. These records are written by the INSTALLER and
rewritten through the same rules by an in-app self-update
(``backend/services/update_receipt.py``, called from the new build's boot): a receipt read after an
update names the version now running, which is why this reader exists. ``backend/services/version.py``
is still the running program's own answer; this file is the install record an operator/audit reads
from disk.

    .venv/Scripts/python.exe desktop/install_receipt.py --root "%LOCALAPPDATA%\\Programs\\CaiXiHui"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

POINTER_NAME = 'current-version'
RECEIPT_NAME = 'install.json'
APP = 'CaiXiHui'
BOM = b'\xef\xbb\xbf'
TOKEN = re.compile(r'^[0-9A-Za-z][0-9A-Za-z.+-]*$')
RECEIPT_KEYS = ('app', 'artifact', 'channel', 'method', 'version', 'root')


class ReceiptError(Exception):
    """A named refusal: the install layout is not what a verifier may trust."""


def decode_without_bom(raw: bytes, name: str, encoding: str) -> str:
    """Refuse a BOM and a mis-decoded byte before either can become a silent fallback."""
    if raw.startswith(BOM):
        raise ReceiptError(f'{name} carries a UTF-8 BOM; it must be written without one')
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError as error:
        raise ReceiptError(f'{name} is not valid {encoding}: {error}') from error


def parse_pointer(raw: bytes) -> str:
    """The version token, or a refusal that names why it cannot be used as a path segment."""
    text = decode_without_bom(raw, POINTER_NAME, 'ascii')
    lines = text.splitlines()
    if len(lines) != 1:
        raise ReceiptError(f'{POINTER_NAME} must hold exactly one line, got {len(lines)}')
    token = lines[0].strip()
    if not token or not TOKEN.fullmatch(token) or '..' in token:
        raise ReceiptError(f'{POINTER_NAME} is not a safe version token: {token!r}')
    return token


def parse_receipt(raw: bytes) -> dict[str, object]:
    """The install receipt, with every field the release chain promises to write."""
    text = decode_without_bom(raw, RECEIPT_NAME, 'utf-8')
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise ReceiptError(f'{RECEIPT_NAME} is not JSON: {error}') from error
    if not isinstance(payload, dict):
        raise ReceiptError(f'{RECEIPT_NAME} must be a JSON object')
    missing = [key for key in RECEIPT_KEYS if not payload.get(key)]
    if missing:
        raise ReceiptError(f'{RECEIPT_NAME} is missing keys: ' + ', '.join(missing))
    if payload['app'] != APP:
        raise ReceiptError(f'{RECEIPT_NAME} names app={payload["app"]!r}, expected {APP!r}')
    root = str(payload['root'])
    if any(character in root for character in '\r\n\t'):
        raise ReceiptError(f'{RECEIPT_NAME} root holds a control character')
    return payload


def read_install(root: Path) -> dict[str, object]:
    """Follow the pointer and prove the receipt it names agrees with it."""
    pointer = root / POINTER_NAME
    if not pointer.is_file():
        raise ReceiptError(f'missing {POINTER_NAME} in {root}')
    token = parse_pointer(pointer.read_bytes())
    receipt_path = root / 'versions' / token / RECEIPT_NAME
    if not receipt_path.is_file():
        raise ReceiptError(f'current-version points at {token!r}, but {receipt_path} is missing')
    receipt = parse_receipt(receipt_path.read_bytes())
    if receipt['version'] != token:
        raise ReceiptError(f'current-version says {token!r}, install.json says {receipt["version"]!r}')
    return {
        'version': token,
        'channel': receipt['channel'],
        'method': receipt['method'],
        'root': receipt['root'],
        'receipt': str(receipt_path),
    }


def main(argv: list[str] | None = None) -> int:
    """Print the verified install record, or refuse by name with a non-zero exit."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    args = parser.parse_args(argv)
    try:
        record = read_install(Path(args.root))
    except (ReceiptError, OSError) as error:
        print(f'install receipt refused: {error}', file=sys.stderr)
        return 1
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
