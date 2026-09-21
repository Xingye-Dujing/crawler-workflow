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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / 'backend'

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── path isolation ─────────────────────────────────────────────────────


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
def clean_globals():
    """Undo the process-global side effects tests can leave behind.

    ``sys.stdout`` is snapshotted per test because the run worker replaces it
    with ``_LogTee`` and only restores it at thread end; ``ml_base`` keeps a
    process-wide classifier cache whose entries would leak one test's fitted
    model into the next; the settings cache may have been warmed mid-test; and
    the i18n thread-local is restored because Werkzeug dispatches requests on
    the *calling* thread — a test that sent ``X-Lang: en`` would otherwise
    leave the language flipped for every later test on the main thread.
    """
    stdout_backup = sys.stdout
    i18n = sys.modules.get('i18n')
    lang_backup = i18n.get_lang() if i18n is not None else None
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


# ─── Flask test client ──────────────────────────────────────────────────


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

    marker = request.node.get_closest_marker('serial')
    if marker is not None and app_module.execution_state.get('running'):
        pytest.skip('another serial execute test is still finishing')

    module = app_module
    state_backup = _snapshot_state(module.execution_state)
    seq = id(request) % (10**6)
    run_store = RunStore(str(data_root / f'api-runs-{seq}.db'))
    dataset_store = DatasetStore(str(data_root / f'api-datasets-{seq}.db'))
    module._RUN_STORE = run_store
    module._DATASET_STORE = dataset_store
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
        {'标题': '三亚旅游攻略', '作者': '旅人甲', '点赞': 12,
         '正文': '三亚的海非常蓝，适合冬天度假。', '链接': 'https://example.com/a1'},
        {'标题': '海口美食推荐', '作者': '吃货乙', '点赞': 30,
         '正文': '海南粉的汤底非常鲜美。', '链接': 'https://example.com/a2'},
        {'标题': '三亚潜水体验', '作者': '旅人甲', '点赞': 7,
         '正文': '水下能见度很高，珊瑚很多。', '链接': 'https://example.com/a3'},
        {'标题': '三亚旅游攻略（重发）', '作者': '旅人甲', '点赞': 15,
         '正文': '三亚的海非常蓝，适合冬天度假！', '链接': 'https://example.com/a1'},
        {'标题': '博鳌论坛小镇', '作者': '记者丙', '点赞': 3,
         '正文': '小镇非常安静，适合散步。', '链接': ''},
    ]


@pytest.fixture
def sample_df(sample_rows):
    import pandas as pd

    return pd.DataFrame(sample_rows)
