"""The offline downloader asks the hub for the right repo type.

A dataset id sent to the models API 404s by name; the older downloader did exactly that,
so every evaluation dataset looked missing even with a working mirror.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_hub(monkeypatch, tmp_path):
    seen = {}

    def snapshot_download(**kwargs):
        seen.update(kwargs)
        payload = tmp_path / 'asset'
        payload.mkdir(exist_ok=True)
        (payload / 'config.json').write_text('{}', encoding='utf-8')
        return str(payload)

    monkeypatch.setitem(sys.modules, 'huggingface_hub', types.SimpleNamespace(snapshot_download=snapshot_download))
    return seen


def _fetch_assets(monkeypatch):
    # The dev script lives outside backend/ and sets project-local caches at import.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'ml_train' / 'scripts'))
    return importlib.import_module('fetch_assets').download


def test_a_dataset_is_fetched_as_a_dataset(fake_hub, monkeypatch):
    row = _fetch_assets(monkeypatch)({'id': 'lcqmc', 'repo': 'C-MTEB/LCQMC'}, 'datasets')
    assert row['ok'] is True, row.get('error')
    assert fake_hub['repo_type'] == 'dataset'


def test_a_model_is_fetched_as_a_model(fake_hub, monkeypatch):
    row = _fetch_assets(monkeypatch)({'id': 'bge-base-zh', 'repo': 'BAAI/bge-base-zh-v1.5'}, 'models')
    assert row['ok'] is True, row.get('error')
    assert fake_hub['repo_type'] is None


def test_a_dataset_is_copied_when_symlinks_are_unavailable(fake_hub, monkeypatch, tmp_path):
    fetch = _fetch_assets(monkeypatch)

    def refuse(self, *args, **kwargs):
        raise OSError('symlinks disabled')

    monkeypatch.setattr(Path, 'symlink_to', refuse)
    monkeypatch.setattr(fetch.__globals__['_env'], 'DATASETS_DIR', tmp_path / 'datasets')
    (tmp_path / 'datasets' / 'retrieval' / 'lcqmc').mkdir(parents=True)
    row = fetch({'id': 'lcqmc', 'repo': 'C-MTEB/LCQMC', 'target': 'retrieval/lcqmc'}, 'datasets')
    assert row['ok'] is True, row.get('error')
    assert (tmp_path / 'datasets' / 'retrieval' / 'lcqmc' / 'config.json').is_file()
