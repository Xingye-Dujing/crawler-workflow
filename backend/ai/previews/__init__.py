"""Strict-shape artifact previews, one module per kind.

Importing this package registers every built-in previewer, the same side-effect style as
``ai.validators``. The API looks previews up by artifact kind: a new previewable format is a new
module and one ``register`` call, never a new branch in a route. A preview only describes — the
existing apply endpoint stays the one door that changes state.
"""

from __future__ import annotations

import importlib

from ai.previews.base import (
    PREVIEWS,
    Preview,
    Previewer,
    PreviewItem,
    preview,
    register,
    registered_kinds,
)

_BUILTIN_MODULES = (
    'ai.previews.memory',
    'ai.previews.workflow',
    'ai.previews.monitor',
    'ai.previews.chart',
)
_BUILTINS_LOADED = False
_BUILTIN_PREVIEWERS: dict[str, Previewer] = {}


def load_builtin_previews() -> None:
    """Register every built-in previewer; idempotent after ``reset_for_tests``."""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    if _BUILTIN_PREVIEWERS:
        PREVIEWS.update(_BUILTIN_PREVIEWERS)
    else:
        for name in _BUILTIN_MODULES:
            importlib.import_module(name)
        _BUILTIN_PREVIEWERS.update(PREVIEWS)
    _BUILTINS_LOADED = True


def reset_for_tests() -> None:
    """Drop every registration; the next load restores the built-ins."""
    global _BUILTINS_LOADED
    PREVIEWS.clear()
    _BUILTINS_LOADED = False


load_builtin_previews()

__all__ = [
    'PREVIEWS',
    'Preview',
    'PreviewItem',
    'Previewer',
    'load_builtin_previews',
    'preview',
    'registered_kinds',
    'register',
    'reset_for_tests',
]
