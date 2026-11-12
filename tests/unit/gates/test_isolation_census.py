"""A new ``Config`` path must not silently escape the throwaway data root.

The harness redirects a hand-maintained list (``ISOLATED_PATHS`` + the five database paths).
That list is the only thing between a new store and the operator's real ``data/``: a class
attribute added later would default to the checkout and every test touching it would write
there while the isolation guard watched a different tree. This asks the class itself instead
of trusting the list to stay complete.
"""

import os
from pathlib import Path

from core import config as config_module
from core.config import Config

REPO = Path(__file__).resolve().parents[3]
REAL_ROOTS = (REPO / 'data', REPO / 'logs')


def _under(value: str, root: Path) -> bool:
    root_text = str(root)
    return value == root_text or value.startswith(root_text + os.sep)


def test_no_config_path_still_points_at_the_checkout():
    leaked = {
        name: value
        for name, value in vars(Config).items()
        if isinstance(value, str) and any(_under(value, root) for root in REAL_ROOTS)
    }
    assert not leaked, (
        'these Config paths still point at the real data/ or logs/: '
        f'{sorted(leaked)}. Add them to ISOLATED_PATHS in tests/conftest.py (or make them '
        'derive from Config.DATA_DIR at call time).'
    )


def test_the_data_root_itself_is_a_throwaway_directory():
    root = str(config_module.DATA_ROOT)
    assert not _under(root, REPO), root
