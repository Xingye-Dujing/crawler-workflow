"""Session-wide isolation harness for the whole test suite.

Three facts about this codebase drive everything here:

1. ``backend/`` is the application's sys.path root — every module imports the
   next by top-level name (``from config import Config``). So backend/ goes on
   sys.path at *conftest import time*.
2. Paths are captured **at import time, into module-level singletons**:
   ``app.cookie_manager = CookieManager(Config.COOKIE_DIR)``, ``app.history_service``
   opens ``data/history.db``, ``settings_store._PATH`` and ``analyzers/ml_base.MODEL_DIR``
   are each computed once, and the lazy ``_RUN_STORE`` / ``_DATASET_STORE`` read
   ``Config.*_DB`` at first use.
3. pytest imports *every collected test module* during collection — before any fixture
   runs, and regardless of marker filters (a deselected file is still imported).

(2) and (3) together are why the redirect below happens at **conftest import time** instead of
in a fixture: a fixture is too late for anything a test module imports at its top level, and
"too late" means the singleton holds the user's REAL directory. Measured the hard way, twice —
once when the integration UI tier landed runs and uploads in ``data/`` (no switch existed then),
and once when one new file's ``from app import ...`` froze ``data/cookies`` so a cookies test
overwrote and deleted the user's saved cookies while the suite reported green.

Real ``data/`` and ``logs/`` must never gain a byte from a test run, and
:func:`pytest_sessionfinish` is what turns that sentence into a check rather than a hope: both
directories are fingerprinted at import and compared at the end, and any new, changed or missing
file fails the run — loudly, with the paths named, even if every single test passed.
"""

import contextlib
import os
import shutil
import sys
import tempfile
from itertools import count
from pathlib import Path

import pytest
from isolation_guard import enforce
from isolation_guard import fingerprint as _fingerprint_protected
from run_wait import describe_state, wait_until_quiet

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / 'backend'
TESTS_DIR = REPO_ROOT / 'tests'

#: Isolated roots live here, and the last few are kept — the way pytest keeps its own tmp dirs —
#: so a failed run's files can still be opened afterwards.
ISOLATED_PARENT = Path(tempfile.gettempdir()) / 'cixi_pytest'
KEEP_ISOLATED_RUNS = 3

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


PROTECTED_AT_IMPORT = _fingerprint_protected()


#: (Config attribute, path inside the throwaway root). The same table drives the mkdir and the
#: assignment, so a new write path cannot be added to one and missed in the other.
ISOLATED_PATHS = (
    ('DATA_DIR', 'data'),
    ('COOKIE_DIR', 'data/cookies'),
    ('EXPORT_DIR', 'data/exports'),
    ('WORKFLOW_DIR', 'data/workflows'),
    ('LLM_CHECKPOINT_DIR', 'data/checkpoints'),
    # A crawler built by any test would otherwise drop a real Chrome profile into the user's
    # data/ directory and keep reusing it across runs.
    ('BROWSER_PROFILE_DIR', 'data/chrome_profile'),
    ('LOG_DIR', 'logs'),
)


def _isolate_paths() -> Path:
    """Point every write path the backend knows about at a throwaway directory, right now.

    Called at conftest import time — see the module docstring for why it cannot be a fixture.
    The layout mirrors the real one, so a test that names ``data_root / 'data' / 'cookies'``
    is naming the same shape the application uses.
    """
    root = ISOLATED_PARENT / f'isolated-{os.getpid()}'
    # Removed before created: a process id can be reused, and an isolated root that still holds a
    # previous run's cookies, workflows or run rows would make "empty at the start" a lie.
    shutil.rmtree(root, ignore_errors=True)
    for _attr, rel in ISOLATED_PATHS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    # The env var first: it is the answer a *child process* (a self-booted server, a probe) reads,
    # and it is what makes every path derived from ``Config.DATA_DIR`` — including ones this file
    # has never heard of, like the trained-model directory — land in the throwaway root. The
    # explicit assignment below is what moves an already-imported ``config`` module.
    os.environ['CRAWLER_DATA_ROOT'] = str(root)

    from config import Config

    for attr, rel in ISOLATED_PATHS:
        setattr(Config, attr, str(root / rel))
    Config.RUNS_DB = str(root / 'data' / 'runs.db')
    Config.DATASETS_DB = str(root / 'data' / 'datasets.db')

    import settings_store

    settings_store._PATH = str(root / 'data' / 'settings.json')
    settings_store._values = None

    return root


ISOLATED_ROOT = _isolate_paths()


def _prune_isolated_roots() -> None:
    """Drop the older throwaway roots, keeping the most recent few."""
    if not ISOLATED_PARENT.is_dir():
        return
    children = sorted((p for p in ISOLATED_PARENT.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    for stale in children[:-KEEP_ISOLATED_RUNS]:
        shutil.rmtree(stale, ignore_errors=True)


def pytest_sessionfinish(session) -> None:
    """Fail the run if a test wrote into the user's ``data/`` or ``logs/``.

    The body lives in :mod:`isolation_guard` so it can be tested at all (four conftest files exist
    in this tree, so ``import conftest`` from a test reaches whichever was collected last). This
    hook is the half that cannot move: it needs pytest to call it, and the fingerprint it compares
    against was taken at conftest import — before collection imported anything.
    """
    _prune_isolated_roots()
    enforce(session, PROTECTED_AT_IMPORT)


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
def data_root():
    """The throwaway root everything in this suite writes to — named for the tests that ask.

    The redirect itself happened at conftest import (see :func:`_isolate_paths`), which is the
    only moment early enough to matter: a fixture that *re-pointed* Config would arrive too late
    for a module-level ``import app``, and the singleton it built would keep the user's directory.
    This fixture therefore reports the root rather than moving anything, so the path a test
    asserts on and the path a captured singleton writes through cannot disagree.
    """
    return ISOLATED_ROOT


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
    stopping_backup = app.execution_state.get('stopping') if app is not None else None
    # Which run rows the process believes it still owns, and which it opened. Both are
    # read by `_reject_live_run` and by the panel's reconciler, so a leftover id would
    # make a later test's delete refused — or worse, settle a row it never wrote.
    records_backup = (
        (list(app.execution_state['open_records']), set(app.execution_state['owned_records']))
        if app is not None
        else (None, None)
    )
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
    # The pre-run cookie gate caches a verdict for a few minutes — deliberately, and
    # across threads. Left alone, one test's 「expired」 would answer the next test's
    # request without any probe having run in it, which is exactly the kind of
    # passing-without-measuring this suite refuses.
    gate = sys.modules.get('cookie_preflight')
    if gate is not None:
        gate.reset()
    # The same leak one layer down: 真排队 arms a per-platform cooldown when a crawl
    # ends, and a fast test that never started one would otherwise sit out a stranger's
    # wait — a leaked 12 s both slowed the session and made a *parallel* canvas test
    # report that two different platforms had taken turns. The live tier is deliberately
    # excluded: there, spacing across cases is the thing under test, because the site
    # answers a second search of one account with a login wall no matter which test sent
    # the first one.
    platform_gate = sys.modules.get('crawl_gate')
    if platform_gate is not None and request.node.get_closest_marker('live_site') is None:
        platform_gate.reset()
    if app is not None:
        app.reset_console_state()
        app.execution_state['open_records'][:] = records_backup[0]
        app.execution_state['owned_records'].clear()
        app.execution_state['owned_records'].update(records_backup[1])
        app.execution_state['stopped_node_ids'].clear()
        if app.execution_state.get('running') != running_backup:
            leaked = app.execution_state.get('running')
            app.execution_state['running'] = running_backup
            pytest.fail(
                f"{request.node.nodeid} left execution_state['running'] at {leaked!r} "
                f'(it was {running_backup!r} before). Take the `client` fixture or restore '
                'it with monkeypatch.setitem: a leaked flag makes the server look busy to '
                'every later test in the session.'
            )
        # A leaked 停止 is the same class of bug wearing a different name: `stopping`
        # is what `stop_requested()` reads, and every crawl's next row asks it. Left
        # set, the next test's crawl raises CrawlerStopped for a stop that happened in
        # a different file.
        if app.execution_state.get('stopping') != stopping_backup:
            leaked = app.execution_state.get('stopping')
            app.execution_state['stopping'] = stopping_backup
            pytest.fail(
                f"{request.node.nodeid} left execution_state['stopping'] at {leaked!r} "
                f'(it was {stopping_backup!r} before). Restore it with monkeypatch.setitem: '
                'a leaked stop makes every later crawl end on its first row.'
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
