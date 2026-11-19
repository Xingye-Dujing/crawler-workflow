"""Strict-format validators for the artifacts the model proposes.

Importing this package registers every built-in validator, the same side-effect style as
``nodes.executors``. The agent looks them up by artifact kind: adding a format is a new module and
one ``register`` call, never a new branch in the turn loop. User skills cannot contribute one — a
skill is data, and a validator is trusted server code.
"""

from __future__ import annotations

import importlib

from ai.validators.base import (
    MAX_ARTIFACT_REPAIRS,
    VALIDATORS,
    Validation,
    Validator,
    check,
    register,
    registered_kinds,
)

_BUILTIN_MODULES = ('ai.validators.memory', 'ai.validators.workflow')
_BUILTINS_LOADED = False
#: The built-in instances, kept so a reset can restore them without re-running an imported module.
_BUILTIN_VALIDATORS: list[Validator] = []


def load_builtin_validators() -> None:
    """Register every built-in validator; idempotent after ``reset_for_tests``.

    Re-importing a module in ``sys.modules`` would not run its ``register`` call again, so restore
    the captured instances instead — a reset that cannot reload silently disables validation.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    if _BUILTIN_VALIDATORS:
        for validator in _BUILTIN_VALIDATORS:
            register(validator)
    else:
        for name in _BUILTIN_MODULES:
            importlib.import_module(name)
        _BUILTIN_VALIDATORS.extend(VALIDATORS.values())
    _BUILTINS_LOADED = True


def reset_for_tests() -> None:
    """Drop every registration and the built-in flag; the next load restores the built-ins."""
    global _BUILTINS_LOADED
    VALIDATORS.clear()
    _BUILTINS_LOADED = False


load_builtin_validators()

__all__ = [
    'MAX_ARTIFACT_REPAIRS',
    'VALIDATORS',
    'Validation',
    'Validator',
    'check',
    'load_builtin_validators',
    'register',
    'registered_kinds',
    'reset_for_tests',
]
