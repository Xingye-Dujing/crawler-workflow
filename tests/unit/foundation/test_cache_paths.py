"""Every download path this project publishes must stay on the project's own drive.

The machine this was written on already had half a gigabyte of Hugging Face weights in the user's
home directory, downloaded by the topic step before any cache variable was set. The regression this
suite guards is not a missing folder but an import-order mistake: a library reads its cache root when
it is imported, so the decision has to be published by ``core.config`` before any heavy import.
"""

import json
import os
from pathlib import Path

import pytest
from core import cache as cache_module
from core import config as config_module

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def clean_cache_env(monkeypatch):
    """Remove every variable this module sets so the test measures its own defaults."""
    for name in (
        *cache_module.CACHE_VARS,
        *cache_module.FIXED_ENV,
        'CIXI_CACHE_DIR',
        'HF_ENDPOINT',
        'CIXI_HF_ENDPOINT',
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_setup_points_every_cache_inside_the_project(clean_cache_env):
    chosen = cache_module.setup(str(REPO))
    home = str(Path.home())
    assert chosen['HF_HOME'] == str(REPO / 'ml_train' / '.hf-cache')
    assert chosen['HF_HUB_CACHE'] == str(REPO / 'ml_train' / '.hf-cache' / 'hub')
    assert chosen['TORCH_HOME'] == str(REPO / 'ml_train' / '.cache' / 'torch')
    assert chosen['MPLCONFIGDIR'] == str(REPO / 'ml_train' / '.cache' / 'matplotlib')
    for value in chosen.values():
        assert home not in value, f'{value} would write to the user home directory'
        assert value.startswith(str(REPO)), f'{value} escaped the checkout'


def test_explicit_cache_root_still_wins(clean_cache_env, tmp_path):
    clean_cache_env.setenv('CIXI_CACHE_DIR', str(tmp_path))
    assert cache_module.cache_root(str(REPO)) == str(tmp_path)
    assert cache_module.setup(str(REPO))['CIXI_CACHE_DIR'] == str(tmp_path)


def test_config_publishes_the_cache_before_it_imports_a_downloader():
    source = (REPO / 'backend' / 'core' / 'config.py').read_text(encoding='utf-8')
    call = source.index('_setup_caches()')
    first_downloader = min(
        (
            source.index(name)
            for name in ('from analyzers', 'from services', 'import torch', 'from transformers')
            if name in source
        ),
        default=len(source),
    )
    assert call < first_downloader


def test_started_app_already_has_a_project_local_hf_home(clean_cache_env):
    # core.config is imported at collection time; re-running setup is idempotent and must name
    # the same project directory the app uses, whatever the test runner's own environment said.
    chosen = cache_module.setup(config_module.BASE_DIR)
    assert Path(chosen['HF_HOME']).resolve() == (REPO / 'ml_train' / '.hf-cache').resolve()
    assert str(Path.home()) not in os.environ.get('HF_HOME', '')


def test_download_manifest_targets_stay_under_the_dataset_folder():
    assets = json.loads((REPO / 'ml_train' / 'scripts' / 'assets.json').read_text(encoding='utf-8'))
    for row in assets.get('datasets', []):
        target = Path(row.get('target') or f'raw/{row["id"]}')
        assert '..' not in target.parts
        assert not target.is_absolute()
        assert target.parts[0] in {'classification', 'stance', 'ner', 'retrieval', 'evaluation', 'raw'}
