"""Rewrite the installer's version records after an in-app update.

``desktop/install_receipt.py`` is the READER the release chain verifies with; this is the writer for
the other half of the same contract. The Inno installer stamps ``current-version`` and
``versions/<v>/install.json`` once, and the in-app updater used to leave both naming the version the
installer had put there — so an audit after a successful update reported the old release, and the
two records disagreed with ``services/version.py``.

The shapes are deliberately the same rules the reader refuses:

* ``current-version`` is ASCII (a version token, never a path) and has one trailing newline;
* ``install.json`` is UTF-8 WITHOUT a BOM;
* both are staged under a unique ``.partial`` name and renamed, so a crash leaves the previous
  valid pair rather than half a record;
* the receipt is written BEFORE the pointer. A crash between the two leaves the old pointer naming
  the old, still-valid receipt; the reverse order would point at a receipt that does not exist.

A portable folder has no ``current-version`` and is left alone: these are installer records, and the
running program's own version is ``services/version.py``.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from core.atomic import replace

POINTER_NAME = 'current-version'
RECEIPT_NAME = 'install.json'
APP = 'CaiXiHui'
#: The same token shape the installer and the reader accept.
TOKEN = re.compile(r'^[0-9A-Za-z][0-9A-Za-z.+-]*$')


def _atomic_write(path: Path, data: bytes) -> None:
    staged = path.with_name(f'{path.name}.{uuid.uuid4().hex}.partial')
    staged.write_bytes(data)
    replace(staged, path)


def _old_channel(root: Path) -> str:
    """The channel the previous receipt recorded, or ``stable`` when there is nothing readable."""
    try:
        token = (root / POINTER_NAME).read_text(encoding='ascii').strip()
        if not TOKEN.fullmatch(token):
            return 'stable'
        receipt = json.loads((root / 'versions' / token / RECEIPT_NAME).read_text(encoding='utf-8'))
        channel = str(receipt.get('channel') or '').strip()
        return channel or 'stable'
    except (OSError, ValueError, TypeError):
        return 'stable'


def record(version: str, root, *, artifact: str = '') -> str:
    """Write the pointer and receipt for *version*; returns the receipt path or ``''``.

    ``''`` means this is not an installer-managed layout (no ``current-version``), which is the
    normal answer for a portable folder and is not a failure.
    """
    text = str(version or '').strip()
    if not TOKEN.fullmatch(text) or '..' in text:
        raise ValueError(f'unsafe version token for the install receipt: {version!r}')
    base = Path(root)
    pointer = base / POINTER_NAME
    if not pointer.is_file():
        return ''
    receipt_path = base / 'versions' / text / RECEIPT_NAME
    receipt = {
        'app': APP,
        'artifact': str(artifact or f'{APP}-{text}'),
        'channel': _old_channel(base),
        'method': 'self-update',
        'version': text,
        'root': str(base),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    # ``ensure_ascii=False`` keeps a non-ASCII install root readable; the file is opened as bytes
    # above, so no platform default encoding can creep in. UTF-8 without a BOM is the contract.
    _atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8'))
    _atomic_write(pointer, f'{text}\n'.encode('ascii'))
    return str(receipt_path)
