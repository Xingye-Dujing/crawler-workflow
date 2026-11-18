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


class TestPruningOldRoots:
    """A finished session may clean up after itself — never after a session still running.

    Keeping "the newest three" roots deleted the root of the longest run (it is always the oldest by
    mtime), which is exactly the root a full tier in one shell is using while another shell runs one
    file. Its ``data/`` and stores disappeared mid-test, and that run reported a dozen unrelated
    failures — a static source scan, a ``caplog`` count, the console totals — with no cause in them.
    """

    @staticmethod
    def _root(parent, name, age_minutes, now):
        path = parent / name
        path.mkdir()
        (path / 'data').mkdir()
        stamp = now - age_minutes * 60
        os.utime(path, (stamp, stamp))
        return path

    def test_a_live_root_survives_a_prune_however_old_it_is(self, tmp_path):
        import isolation_guard

        now = 1_800_000_000.0
        live = self._root(tmp_path, 'isolated-111', 30, now)
        for index in range(5):
            self._root(tmp_path, f'isolated-{index}', 300 + index, now)
        isolation_guard.prune_isolated_roots(tmp_path, current=None, keep=1, now=now)
        assert live.is_dir(), 'a root younger than the idle window was deleted under a running session'
        # ``keep`` is spent among the idle roots only: the newest of them stays for post-mortem.
        assert sorted(path.name for path in tmp_path.iterdir() if path != live) == ['isolated-0']

    def test_the_current_root_is_never_pruned(self, tmp_path):
        import isolation_guard

        now = 1_800_000_000.0
        mine = self._root(tmp_path, 'isolated-222', 900, now)
        self._root(tmp_path, 'isolated-333', 950, now)
        isolation_guard.prune_isolated_roots(tmp_path, current=mine, keep=0, now=now)
        assert mine.is_dir()

    def test_keep_still_bounds_what_an_idle_session_leaves_behind(self, tmp_path):
        import isolation_guard

        now = 1_800_000_000.0
        for index in range(6):
            self._root(tmp_path, f'isolated-{index}', 400 + index, now)
        isolation_guard.prune_isolated_roots(tmp_path, current=None, keep=2, now=now)
        left = sorted(path.name for path in tmp_path.iterdir())
        assert left == ['isolated-0', 'isolated-1'], left

    def test_the_session_tells_the_prune_which_root_is_its_own(self):
        """The guard's decision is tested above; this is the WIRING, which is what a live session
        depends on. Dropping `current=ISOLATED_ROOT` restores the original bug — a session older than
        the idle window deletes the root it is using — with every guard case still green."""
        import ast

        source = (REPO / 'tests' / 'conftest.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'prune_isolated_roots'
        ]
        assert len(calls) == 1, 'the prune moved; retarget this gate'
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in calls[0].keywords}
        assert keywords.get('current') == 'ISOLATED_ROOT', keywords
        assert keywords.get('keep') == 'KEEP_ISOLATED_RUNS', keywords


class TestTheLeakMessage:
    """A tripwire that names the victim instead of the owner costs an afternoon every time."""

    def test_a_live_worker_and_its_run_are_named(self):
        import threading

        import isolation_guard

        finished = threading.Thread(target=lambda: None, name='crawler-run-42', daemon=True)
        finished.start()
        finished.join(1)
        assert isolation_guard.leak_context({'thread': finished, 'run_id': ''}) == '', (
            'a finished worker was reported as alive'
        )
        blocker = threading.Event()
        running = threading.Thread(target=blocker.wait, name='crawler-run-43', daemon=True)
        running.start()
        try:
            text = isolation_guard.leak_context({'thread': running, 'run_id': 'r_abc'})
            assert 'STILL ALIVE' in text and 'crawler-run-43' in text, text
            assert 'r_abc' in text, text
        finally:
            blocker.set()
            running.join(2)

    def test_nothing_running_means_no_sentence(self):
        import isolation_guard

        assert isolation_guard.leak_context({'thread': None, 'run_id': ''}) == ''
