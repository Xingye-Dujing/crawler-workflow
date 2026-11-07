"""Which copy of a component this process uses: the installer's, or the machine's own.

Both layouts are legitimate and some users want them deliberately: the online installer puts Chrome,
chromedriver, Node and CatBus in its own folder so a machine-wide Chrome is never touched, while
another user prefers the Chrome/Node already installed and wants the installer's copy ignored even
though it exists. That choice is a setting (``component_source``), not an inference — a matching
local install is never a reason to overrule it.

The launcher has to decide BEFORE ``core.config`` is imported (its class attributes read the
environment once), so :func:`stored_source` reads the settings file directly with the standard
library. :func:`effective` is the process's answer: the launcher freezes the startup choice in
``CIXI_COMPONENT_SOURCE``, so flipping the setting while the app is running cannot make the panel
claim a different Chrome than the one this process will actually launch. That is the same rule as
installed components: a change takes effect after a restart, and the panel says so.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from services.components.paths import components_root

BUNDLED = 'bundled'
SYSTEM = 'system'
DEFAULT_SOURCE = BUNDLED

#: The setting's name in ``data/settings.json`` and the environment variable the launcher sets.
SETTING = 'component_source'
ENV_VAR = 'CIXI_COMPONENT_SOURCE'


def normalize(value) -> str:
    """Only the two names are meaningful; anything else means the default."""
    return SYSTEM if str(value or '').strip().lower() == SYSTEM else DEFAULT_SOURCE


def preference() -> str:
    """The stored choice: what the NEXT start will use (the panel shows this one)."""
    try:
        from runtime.settings import get_setting

        return normalize(get_setting(SETTING))
    except (ImportError, AttributeError, OSError):
        # A missing settings store (the installer's own probe, a cold import) is the default.
        return DEFAULT_SOURCE


def stored_source(data_root: str | Path | None = None) -> str:
    """The persisted preference, readable before ``core.config`` exists.

    Used by the desktop launcher, which must decide whether to export the bundled paths before
    ``config`` is imported. An absent or unreadable file is the default, never an error: the
    application still has a defensible answer (the installer's copy when there is one).
    """
    if data_root is None:
        return preference()
    path = Path(data_root) / 'data' / 'settings.json'
    try:
        stored = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return DEFAULT_SOURCE
    value = stored.get(SETTING) if isinstance(stored, dict) else ''
    return normalize(value)


def effective() -> str:
    """The source THIS process runs under (the launcher freezes its startup choice here)."""
    override = str(os.environ.get(ENV_VAR) or '').strip()
    return normalize(override) if override else preference()


def prefer_bundled() -> bool:
    return effective() == BUNDLED


def inside_components(path: str | Path) -> bool:
    """Whether a path belongs to the installer's own component tree."""
    text = str(path or '').strip()
    if not text:
        return False
    try:
        root = Path(components_root()).resolve()
        candidate = Path(text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return candidate == root or root in candidate.parents


def usable(path) -> str:
    """A configured path, or ``''`` when it points into a tree the user chose not to use.

    A stored path is how the app remembers "the driver is here"; without this, choosing 本机 would
    keep loading the installer's driver forever, because the value was persisted before the switch
    and a stored setting outranks every default.
    """
    text = str(path or '').strip()
    if not text or prefer_bundled():
        return text
    return '' if inside_components(text) else text
