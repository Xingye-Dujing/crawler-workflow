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


def default_data_root(env: dict | None = None, home: Path | None = None) -> Path:
    """The launcher's own default, shown here so the folder can be moved before the first run."""
    values = os.environ if env is None else env
    base = values.get('APPDATA') or values.get('LOCALAPPDATA') or str((home or Path.home()) / 'AppData' / 'Roaming')
    return Path(base) / 'CaiXiHui'


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


def preset_choices(preset: str, defaults: list[str], downloadable: list[str]) -> dict[str, bool]:
    """The checkbox state a preset means.

    一键安装 is exactly the catalogue's defaults and 仅主程序 is the application alone; there is
    no third "everything" preset, because the defaults ARE every downloadable component — two
    radio buttons that tick the same boxes made the choice look like it did something.
    """
    wanted = {'app'} if preset == 'app' else set(defaults)
    return {component_id: component_id in wanted for component_id in downloadable}


def chosen_ids(chosen: dict[str, bool], downloadable: list[str]) -> list[str]:
    """The ticked components, in catalogue order.

    The checkboxes are the answer for every preset: a user who unticks Chrome must not still get
    Chrome because a radio button said "one-click". Requirements are still added by
    :func:`with_requirements`, so CatBus without Node cannot produce a doomed install.
    """
    return [component_id for component_id in downloadable if chosen.get(component_id)]


def with_requirements(selected: list[str], requires: dict[str, list[str]], downloadable: list[str]) -> list[str]:
    """Insert every selected component's requirements ahead of it.

    A novice who ticks CatBus but not Node should get a working install, not a download that ends in
    "catbus needs node". Only downloadable ids are added: a manual component (MiKTeX) is something
    the catalogue only detects, so it stays the user's own step.
    """
    ordered = list(selected)
    changed = True
    while changed:
        changed = False
        for component_id in list(ordered):
            for required in requires.get(component_id, ()):
                if required in downloadable and required not in ordered:
                    ordered.insert(ordered.index(component_id), required)
                    changed = True
    return ordered


def total_size(sizes: dict[str, int], ids: list[str]) -> int:
    return sum(int(sizes.get(component_id) or 0) for component_id in ids)
