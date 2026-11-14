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


def test_the_cookie_jar_fixture_binds_its_directory_once():
    """``quiet_jar`` restores the bytes it snapshotted, in the directory it snapshotted.

    Re-reading ``Config.COOKIE_DIR`` at teardown made the fixture answer a different
    question when a test repointed it (the live tier's ``real_jar`` at the user's jar):
    measured 2026-11-14, the throwaway root's (empty) snapshot was restored INTO
    ``data/cookies`` and deleted every saved login. The fixture must hold the path as a
    local and hand that same name to both helpers.
    """
    import ast

    source = (REPO / 'tests' / 'conftest.py').read_text(encoding='utf-8')
    tree = ast.parse(source)

    def arg_name(call: ast.Call) -> str:
        first = call.args[0] if call.args else None
        if isinstance(first, ast.Name):
            return first.id
        if isinstance(first, ast.Attribute):
            return f'{getattr(first.value, "id", "")}.{first.attr}'
        return ''

    bodies = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'quiet_jar']
    assert len(bodies) == 1, 'the quiet_jar fixture moved; retarget this gate'
    calls = {
        call.func.id: arg_name(call)
        for call in ast.walk(bodies[0])
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id
        in (
            '_cookie_snapshot',
            '_cookie_restore',
        )
    }
    assert calls == {'_cookie_snapshot': 'directory', '_cookie_restore': 'directory'}, calls
