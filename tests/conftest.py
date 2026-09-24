"""Session-wide isolation harness for the whole test suite.

Two facts about this codebase drive everything here:

1. ``backend/`` is the application's sys.path root — every module imports the
   next by top-level name (``from config import Config``). So backend/ goes on
   sys.path at *conftest import time*; a test file that does ``from config
   import ...`` at module level is collected before any fixture runs.
2. Several paths are captured at import time and written to immediately:
   ``app.history_service`` opens ``data/history.db``, ``settings_store._PATH``
   was computed from ``Config.DATA_DIR``, and the lazy ``_RUN_STORE`` /
   ``_DATASET_STORE`` singletons read ``Config.*_DB`` at first use. Therefore
   the autouse ``isolated_paths`` fixture mutates those module globals *before*
   anything constructs a store, and ``import app`` stays behind the session
   ``app_module`` fixture so only API/integration tests pay the import cost.

Real ``data/`` and ``logs/`` must never gain a byte from a test run.
"""

import contextlib
import sys
from itertools import count
from pathlib import Path

import pytest
from run_wait import describe_state, wait_until_quiet

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / 'backend'
TESTS_DIR = REPO_ROOT / 'tests'

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _warm_http_stack() -> bool:
    """Spend urllib3's import-time IPv6 probe before the network guard exists.

    ``urllib3.util.connection`` opens an AF_INET6 socket once, on import, to ask
    the OS what it supports. Under ``--disable-socket`` that probe — a library's
    capability check, not a test reaching the network — surfaces as a
    "A test tried to use socket.socket" warning attached to whichever test
    happens to import ``requests`` first. Importing it here, while conftest is
    still being read, keeps the guard's warnings about the thing it is for.
    """
    from urllib3.util.connection import HAS_IPV6

    return bool(HAS_IPV6)


_warm_http_stack()


# ─── path isolation ─────────────────────────────────────────────────────


@pytest.fixture(scope='session')
def capabilities_matrix(tmp_path_factory):
    """The crawl matrix as a JSON file, for the JS harnesses that render a panel.

    Dumped from ``crawl_capabilities.as_dict()`` at run time instead of checked
    in: the Data Source panel is *generated* from this payload, so a harness has
    to see what the server would actually send. A committed copy is precisely how
    the panel and the executor drift back apart — it would keep passing while the
    real endpoint said something else.
    """
    import json

    import crawl_capabilities

    path = tmp_path_factory.mktemp('capabilities') / 'capabilities.json'
    path.write_text(json.dumps(crawl_capabilities.as_dict(), ensure_ascii=False), encoding='utf-8')
    return path


@pytest.fixture(scope='session', autouse=True)
def data_root(tmp_path_factory):
    """Redirect every write path the backend knows about into a throwaway dir.

    Session scope + autouse: runs once before the first test body, so the app
    (and any store built lazily from Config) only ever sees tmp paths.
    """
    root = tmp_path_factory.mktemp('isolated')
    from config import Config

    for attr, rel in (
        ('DATA_DIR', 'data'),
        ('COOKIE_DIR', 'data/cookies'),
        ('EXPORT_DIR', 'data/exports'),
        ('WORKFLOW_DIR', 'data/workflows'),
        ('LLM_CHECKPOINT_DIR', 'data/checkpoints'),
        # A crawler built by any test would otherwise drop a real Chrome profile
        # into the user's data/ directory and keep reusing it across runs.
        ('BROWSER_PROFILE_DIR', 'data/chrome_profile'),
        ('LOG_DIR', 'logs'),
    ):
        path = root / rel
        path.mkdir(parents=True, exist_ok=True)
        setattr(Config, attr, str(path))
    Config.RUNS_DB = str(root / 'data' / 'runs.db')
    Config.DATASETS_DB = str(root / 'data' / 'datasets.db')

    import settings_store

    settings_store._PATH = str(root / 'data' / 'settings.json')
    settings_store._values = None

    return root


@pytest.fixture(scope='session')
def app_module(data_root):
    """The Flask app module, imported only once isolation is in place."""
    import app

    return app


@pytest.fixture(autouse=True)
def clean_globals(request):
    """Undo the process-global side effects tests can leave behind.

    ``sys.stdout`` is snapshotted per test because the run worker replaces it
    with ``_LogTee`` and only restores it at thread end; ``ml_base`` keeps a
    process-wide classifier cache whose entries would leak one test's fitted
    model into the next; the settings cache may have been warmed mid-test; and
    the i18n thread-local is restored because Werkzeug dispatches requests on
    the *calling* thread — a test that sent ``X-Lang: en`` would otherwise
    leave the language flipped for every later test on the main thread.

    The console is **reset, not restored**: a test that calls an executor
    function directly never goes through the run start that clears it, so it
    leaves its narration for the next test to read. Restoring a snapshot could
    not fix that either, because the snapshot is taken after the leak — which is
    how 25 lines from one crawl-matrix test surfaced as "a run nobody started"
    three files later. A test that reads lines it never wrote now fails on its
    own empty console, which is the honest place for that to be reported.

    ``execution_state['running']`` gets a **tripwire** instead, because a leaked
    busy flag is not a stale read but a changed answer: every later serial test
    waits out its quiet-server timeout on a run that does not exist. So the flag
    is put back to keep the session readable *and* the offender named to keep it
    honest — hundreds of cascading failures had no cause in them otherwise.
    """
    stdout_backup = sys.stdout
    i18n = sys.modules.get('i18n')
    lang_backup = i18n.get_lang() if i18n is not None else None
    app = sys.modules.get('app')
    running_backup = app.execution_state.get('running') if app is not None else None
    yield
    sys.stdout = stdout_backup
    if i18n is not None:
        i18n.set_lang(lang_backup or 'zh')
    ml = sys.modules.get('analyzers.ml_base')
    if ml is not None:
        ml._shared_classifiers.clear()
    ss = sys.modules.get('settings_store')
    if ss is not None:
        ss._values = None
    if app is not None:
        app.reset_console_state()
        if app.execution_state.get('running') != running_backup:
            leaked = app.execution_state.get('running')
            app.execution_state['running'] = running_backup
            pytest.fail(
                f"{request.node.nodeid} left execution_state['running'] at {leaked!r} "
                f'(it was {running_backup!r} before). Take the `client` fixture or restore '
                'it with monkeypatch.setitem: a leaked flag makes the server look busy to '
                'every later test in the session.'
            )


# ─── Flask test client ──────────────────────────────────────────────────


def _wait_for_quiet_server(module, timeout: float = 30.0) -> None:
    """Block until no run is in flight, no worker thread is left, and nothing is
    still waiting to start.

    The rules live in ``run_wait`` because every test that posts a run needs the
    same one; see that module for why "the thread I saw is gone" is not it.
    """
    if wait_until_quiet(module, timeout):
        return
    raise AssertionError(
        f'the previous run never finished within {timeout}s ({describe_state(module)}) '
        '— every later execute test would be queued behind it'
    )


def _snapshot_state(state: dict) -> dict:
    backup = {}
    for key, value in state.items():
        if isinstance(value, dict):
            backup[key] = dict(value)
        elif isinstance(value, (set, list)):
            backup[key] = type(value)(value)
        else:
            backup[key] = value
    return backup


# Hands each client fixture its own store files. See the note in `client`.
_CLIENT_SEQ = count(1)


@pytest.fixture
def client(app_module, data_root, request):
    """Per-test client with fresh durable stores of its own.

    Swapping in private store instances is what the app's own lazy getters do
    anyway; restoring the bound attributes (not the data) keeps tests ordering
    independent. Requests default to ``X-Lang: en`` so message assertions do
    not depend on console language.
    """
    from services.dataset_store import DatasetStore
    from services.run_store import RunStore

    # A serial test needs a genuinely quiet server before it presses Run.
    # This used to ``pytest.skip`` on a busy slot, which turned one slow run
    # into a test that silently never happened; and since a busy server now
    # *queues* the request, a test that posted anyway would read a console that
    # its own run had not written to yet — a failure with no cause in it.
    if request.node.get_closest_marker('serial') is not None:
        _wait_for_quiet_server(app_module)

    module = app_module
    state_backup = _snapshot_state(module.execution_state)
    # The run queue is module state, not execution_state: a request one test
    # parked would otherwise be started by the next test's finishing run and
    # write results into a state that test never asked for.
    queue_backup = list(module._RUN_QUEUE)
    module._RUN_QUEUE.clear()
    # A monotonic counter, NOT an id()-derived number: Request objects are freed
    # and their addresses reused, so two tests could land on the same .db file and
    # read each other's rows (a purge that removed one file too many, a registry
    # with a stranger in it). Every test needs a file no other test ever had.
    seq = next(_CLIENT_SEQ)
    run_store = RunStore(str(data_root / f'api-runs-{seq}.db'))
    dataset_store = DatasetStore(str(data_root / f'api-datasets-{seq}.db'))
    # Tripwire for that class of bug: a store built for this test holds nothing
    # but its own schema, so anything already in it means the file was shared.
    assert dataset_store.stats()['datasets'] == 0, f'{dataset_store.db_path} is not a fresh store'
    assert run_store.stats()['runs'] == 0, f'{run_store.db_path} is not a fresh store'
    module._RUN_STORE = run_store
    module._DATASET_STORE = dataset_store
    # The housekeeper caches both store handles, so it has to be rebuilt
    # alongside them or a later test would sweep an already-closed database.
    module._HOUSEKEEPER = None
    module._dataset_cache.clear()
    stdout_backup = sys.stdout
    # Default every request to English so message assertions don't track the
    # console language. environ_base (not the pre-Werkzeug-3 ``headers=`` keyword)
    # is the version-proof way to seed a default header.
    test_client = module.app.test_client()
    test_client.environ_base['HTTP_X_LANG'] = 'en'
    try:
        yield test_client
    finally:
        sys.stdout = stdout_backup
        _restore_state(module.execution_state, state_backup)
        module._RUN_QUEUE[:] = queue_backup
        module._dataset_cache.clear()
        for store in (run_store, dataset_store):
            with contextlib.suppress(Exception):
                store._conn.close()
        module._RUN_STORE = None
        module._DATASET_STORE = None


def _restore_state(state: dict, backup: dict) -> None:
    state.clear()
    state.update(backup)


# ─── sample data factories ──────────────────────────────────────────────


# The column names below are the ones the real crawlers emit (see the
# _URL_FIELDS / _BODY_FIELDS tuples in services/run_store.py), so fixtures
# exercise the same identity/dedupe code paths production uses.
@pytest.fixture
def sample_rows():
    """Five crawled-row dicts, with rows 0 and 3 sharing a URL on purpose —
    dedupe and item-fingerprint tests get their duplicate for free."""
    return [
        {
            '标题': '三亚旅游攻略',
            '作者': '旅人甲',
            '点赞': 12,
            '正文': '三亚的海非常蓝，适合冬天度假。',
            '链接': 'https://example.com/a1',
        },
        {
            '标题': '海口美食推荐',
            '作者': '吃货乙',
            '点赞': 30,
            '正文': '海南粉的汤底非常鲜美。',
            '链接': 'https://example.com/a2',
        },
        {
            '标题': '三亚潜水体验',
            '作者': '旅人甲',
            '点赞': 7,
            '正文': '水下能见度很高，珊瑚很多。',
            '链接': 'https://example.com/a3',
        },
        {
            '标题': '三亚旅游攻略（重发）',
            '作者': '旅人甲',
            '点赞': 15,
            '正文': '三亚的海非常蓝，适合冬天度假！',
            '链接': 'https://example.com/a1',
        },
        {'标题': '博鳌论坛小镇', '作者': '记者丙', '点赞': 3, '正文': '小镇非常安静，适合散步。', '链接': ''},
    ]


@pytest.fixture
def sample_df(sample_rows):
    import pandas as pd

    return pd.DataFrame(sample_rows)
