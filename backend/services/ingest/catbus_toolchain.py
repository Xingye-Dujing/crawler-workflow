"""Where this machine's CatBus toolchain lives — one detector for both run modes.

The canvas second backend (``services.ingest.catbus``) and the AI workspace's direct-command path
both have to answer the same question: which Node, which 采析绘 adapter, and which catbus main CLI?
Two answers would be a second opinion that drifts, so the *discovery* lives here and both call it.

Both run modes are handled by the same code, never by two parallel branches:
- **source / web**: the settings-panel value wins over the environment; a machine CLI on ``PATH``
  counts, and a built checkout is found from the adapter's own path.
- **installer (bundled)**: the launcher's exported value wins over a stale settings.json, and only
  paths inside the installer's component tree count — a ``catbus`` on ``PATH`` is NOT a fallback.

This module only *finds* paths. Running a version check stays with the caller that owns the
subprocess boundary; discovery itself has no side effects and can be asked on a cold import.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.config import Config


def ordered_by_source(setting_value, env_value):
    """The two hand-written values in the order this process's component source dictates.

    One ordering rule shared by Node and the adapter: in installer mode the launcher's exported
    value wins over a (possibly stale) settings.json; in source/web mode the panel value wins.
    """
    from services.components import source

    return (env_value, setting_value) if source.prefer_bundled() else (setting_value, env_value)


def first_usable(*values) -> str:
    """First value that survives the component-source gate, or '' when none does."""
    from services.components import source

    for value in values:
        usable = source.usable(value)
        if usable:
            return usable
    return ''


def explicit_paths() -> tuple[str, str]:
    """The Node and adapter paths the user supplied, filtered by component source.

    An empty result means "look it up on this machine": :mod:`core.machine` answers that, with
    ``PATH`` only as its last fallback, never something the user must edit by hand.
    """
    from runtime.settings import get_setting

    node_conf, node_env = ordered_by_source(get_setting('catbus_node'), Config.CATBUS_NODE)
    cli_conf, cli_env = ordered_by_source(get_setting('catbus_cli'), Config.CATBUS_CLI)
    return first_usable(node_conf, node_env), first_usable(cli_conf, cli_env)


def local_checkout(entry: str = '') -> tuple[str, str]:
    """``(checkout root, runnable main CLI)`` found from the adapter's own path.

    The adapter entry is ``<checkout>/dist/integrations/crawler-workflow/cli.js`` (or its source
    twin), so the checkout root is one of its ancestors that holds ``dist/cli/main.js``. A machine
    that can already run the canvas backend therefore almost always has a runnable main CLI too —
    no ``CATBUS_BIN`` / ``CATBUS_HOME`` required. Explicit env vars still win when set, subject to
    the same source gate. Returns ``('', '')`` when nothing is there: an absence is reported, not
    guessed around.
    """
    from services.components import source

    candidates: list[tuple[str, Path]] = []
    env_home = first_usable(os.environ.get('CATBUS_HOME'))
    env_bin = first_usable(os.environ.get('CATBUS_BIN'))
    if env_home:
        candidates.append((env_home, Path(env_home) / 'dist' / 'cli' / 'main.js'))
    if env_bin:
        candidates.append((str(Path(env_bin).resolve().parent), Path(env_bin)))
    if entry:
        # Nearest ancestors first; the CLI sits at <root>/dist/cli/main.js, a few levels up.
        for parent in Path(entry).resolve().parents:
            candidates.append((str(parent), parent / 'dist' / 'cli' / 'main.js'))
    for root, main in candidates:
        if main.is_file() and source.usable(str(main)):
            return root, str(main)
    return '', ''


def direct_cli_candidates(entry: str = '') -> dict:
    """The catbus main CLI paths a direct command may use — ONE answer for both run modes.

    In installer mode only the chosen tree counts: a ``catbus`` on ``PATH`` is deliberately ignored,
    the same way :func:`core.machine.find_catbus_cli` refuses a machine adapter there. In source/web
    mode the global CLI and a local checkout are both reported. The caller decides which to use;
    whether to install anything is always the user's choice.
    """
    from services.components import source

    found = {'cli': '', 'local_root': '', 'local_cli': ''}
    if not source.prefer_bundled():
        from shutil import which

        found['cli'] = which('catbus') or ''
    root, local = local_checkout(entry)
    found['local_root'], found['local_cli'] = root, local
    return found
