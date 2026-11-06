"""Pure planning helpers for the online installer, kept away from Tkinter.

The GUI decides what to paint; these functions decide where to install and which components a preset
means. Keeping them importable without a display lets the test suite pin the novice default (the
domestic, no-VPN route) and the size arithmetic without starting a window.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def default_root(env: dict | None = None, home: Path | None = None) -> Path:
    """Per-user default: no admin, and the user can type D:\\ instead."""
    values = os.environ if env is None else env
    base = values.get('LOCALAPPDATA') or str((home or Path.home()) / 'AppData' / 'Local')
    return Path(base) / 'Programs' / 'CaiXiHui'


def human_size(size: int) -> str:
    value = float(size or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.0f} {unit}' if unit != 'GB' else f'{value:.1f} GB'
        value /= 1024
    return f'{value:.1f} GB'


def free_space(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def selected_ids(preset: str, chosen: dict[str, bool], downloadable: list[str]) -> list[str]:
    """The component ids a preset means; ``chosen`` is only read for the custom preset."""
    if preset == 'all':
        return list(downloadable)
    if preset == 'app':
        return ['app']
    return [component_id for component_id, on in chosen.items() if on]


def total_size(sizes: dict[str, int], ids: list[str]) -> int:
    return sum(int(sizes.get(component_id) or 0) for component_id in ids)
