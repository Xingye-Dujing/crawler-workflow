"""Where the components live for this process.

The bootstrap installer passes its own root explicitly. The running application resolves it in the
same order the rest of the app resolves machine facts: an environment override first (the launcher
sets it for a portable layout), then the folder beside the executable, then the source checkout's
data directory. Nothing is cached in a module constant.

Two folders matter and they are not the same one: the *install root* holds ``app/``, ``components/``
and ``install-manifest.json``, while ``components_root()`` is the ``components/`` directory inside it
(one subfolder per component id). Every manifest write and every install takes the install root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from core.machine import is_frozen


def install_root(root: str | Path | None = None) -> Path:
    """The folder holding ``app/``, ``components/`` and ``install-manifest.json``.

    An explicit ``root`` is returned as given (that is what the installer and the tests pass).
    ``CIXI_COMPONENTS_DIR`` names the components directory, so the install root is its parent.
    """
    if root:
        return Path(root)
    return components_root().parent


def components_root(root: str | Path | None = None) -> Path:
    """The directory that holds one folder per component id (``<install root>/components``)."""
    if root:
        return Path(root)
    override = str(os.environ.get('CIXI_COMPONENTS_DIR') or '').strip()
    if override:
        return Path(override)
    if is_frozen():
        # Two layouts ship: the online installer puts the application in ``<root>/app`` with
        # ``<root>/components`` beside it, while the portable zip is one folder with the exe at its
        # top. Reading the folder NAME keeps both working without a marker file.
        executable_dir = Path(sys.executable).resolve().parent
        if executable_dir.name == 'app':
            return executable_dir.parent / 'components'
        return executable_dir / 'components'
    # Imported lazily: the bootstrap installer must be able to import this module without Flask.
    from core.config import Config

    return Path(Config.DATA_DIR) / 'components'
