"""Where the components live for this process.

The bootstrap installer passes its own root explicitly. The running application resolves it in the
same order the rest of the app resolves machine facts: an environment override first (the launcher
sets it for a portable layout), then the folder beside the executable, then the source checkout's
data directory. Nothing is cached in a module constant.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from core.machine import is_frozen


def components_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root)
    override = str(os.environ.get('CIXI_COMPONENTS_DIR') or '').strip()
    if override:
        return Path(override)
    if is_frozen():
        return Path(sys.executable).resolve().parent.parent / 'components'
    # Imported lazily: the bootstrap installer must be able to import this module without Flask.
    from core.config import Config

    return Path(Config.DATA_DIR) / 'components'


def install_root(root: str | Path | None = None) -> Path:
    """The folder that holds ``app/``, ``components/`` and the manifest."""
    return components_root(root).parent if root is None else Path(root)
