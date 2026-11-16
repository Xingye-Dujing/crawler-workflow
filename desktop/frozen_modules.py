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


def source_snapshot_datas(backend: Path | str, root: Path | str) -> list[tuple[str, str]]:
    """A read-only source snapshot for the packaged AI (``source/`` in the bundle).

    A frozen build carries compiled modules, so the AI's developer skill had no file to cite. This
    copies the *sources* (backend ``.py``, frontend ``.js``, ``docs/*.md``) as data; the running
    program still comes from the compiled bundle, which is why the snapshot is described as
    read-only. Probe scripts and caches are excluded, matching every other build list here.
    """
    backend_root = Path(backend)
    repo_root = Path(root)
    out: list[tuple[str, str]] = []
    for path in sorted(backend_root.rglob('*.py')):
        parts = path.relative_to(backend_root).parts
        if _SKIP_DIRS & set(parts) or path.name.startswith(_SKIP_PREFIXES):
            continue
        out.append(
            (
                str(path),
                str(Path('source/backend') / Path(*parts[:-1]).as_posix() if len(parts) > 1 else 'source/backend'),
            )
        )
    for path in sorted((backend_root / 'static' / 'js').rglob('*.js')):
        parts = path.relative_to(backend_root).parts
        if _SKIP_DIRS & set(parts):
            continue
        out.append((str(path), str(Path('source/backend') / Path(*parts[:-1]).as_posix())))
    docs = repo_root / 'docs'
    if docs.is_dir():
        for path in sorted(docs.rglob('*.md')):
            parts = path.relative_to(docs).parts
            out.append(
                (
                    str(path),
                    str(Path('source/docs') / Path(*parts[:-1]).as_posix() if len(parts) > 1 else 'source/docs'),
                )
            )
    for name in ('README.md', 'AGENTS.md'):
        path = repo_root / name
        if path.is_file():
            out.append((str(path), 'source'))
    return out


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
            # The package's own ``__init__.py``: its module name is the package itself
            # (``nodes.executors``), which is what a registry imports by string. Skipping it
            # left a package with no submodules out of the frozen build entirely.
            names.append(package)
            continue
        names.append('.'.join([package, *parts]))
    return sorted(set(names))
