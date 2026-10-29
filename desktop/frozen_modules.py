"""Enumerate the first-party modules a frozen build must carry, from the FILE TREE.

The build used to call PyInstaller's ``collect_submodules`` for this. It does not work here, for
two reasons that both end in a shipped app that dies on the user's machine:

· ``collect_submodules`` IMPORTS the package to read its ``__path__``. This app is not allowed to
  be imported at build time — ``runtime.state``/``runtime.stores`` construct their singletons at
  import, so a spec that imported them would create a data root during the build;
· when the package is not on the spec process's own ``sys.path`` it returns an empty list and
  says nothing. The spec hands ``backend`` to PyInstaller as ``pathex`` (the ANALYSIS sees it) but
  never to its own interpreter, so every ``collect_submodules('api')``-style call in the spec
  collected ZERO modules, and the packaged app carried only what the static import graph happened
  to reach. ``nodes.executors`` is reached only by ``importlib.import_module('nodes.executors')``
  — a string the graph cannot follow — so the built exe failed at startup with
  ``ModuleNotFoundError: No module named 'nodes.executors'``.

Listing the tree needs no imports at all, so this module is pure ``pathlib``. It is shared by the
spec and by ``tests/unit/desktop/test_desktop_packaging.py``, which is the point: the build list and
the check that guards it are computed by the same function.
"""

from __future__ import annotations

from pathlib import Path

#: Files that are never part of the shipped runtime: the measurement scripts AGENTS keeps out of
#: pytest (``test_*.py``) and the compiled caches a checkout accumulates.
_SKIP_PREFIXES = ('test_',)
_SKIP_DIRS = {'__pycache__'}


def package_module_names(backend: Path | str, package: str) -> list[str]:
    """Every dotted module name under ``backend/<package>``, in sorted order.

    ``backend/nodes/executors/source.py`` → ``nodes.executors.source``; a package's ``__init__.py``
    → the package name itself (``nodes.executors``), because that is the name the registry imports
    by string. Empty when the package does not exist — the caller decides whether that is a
    refusal, so this stays a reader and not an opinion.
    """
    root = Path(backend) / package
    if not root.is_dir():
        return []
    names: list[str] = []
    for path in sorted(root.rglob('*.py')):
        if _SKIP_DIRS & set(path.parts):
            continue
        stem = path.stem
        if stem.startswith(_SKIP_PREFIXES):
            continue
        relative = path.relative_to(root)
        parts = list(relative.parts)
        if stem == '__init__':
            parts.pop()  # the directory is the module
        else:
            parts[-1] = stem  # 'executors/source.py' → 'source', not 'source.py'
        if not parts:
            continue
        names.append('.'.join([package, *parts]))
    return sorted(set(names))
