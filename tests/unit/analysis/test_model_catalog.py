"""One catalogue serves the panel, the executor and the AI tools.

The old registry is still hand-edited by the operator; the new manifests are code-reviewed data.
Both must answer the same question about a default model, and an unknown id must refuse by name
instead of falling through to option zero.
"""

import json
from pathlib import Path

import pytest
from core.config import BASE_DIR, Config

from services.models import catalog, probe
from services.models.manifest import ManifestError, from_legacy, from_manifest

pytestmark = pytest.mark.unit


def _registry(tmp_path, rows):
    (tmp_path / 'model_registry.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')


def test_legacy_registry_rows_keep_their_four_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    _registry(
        tmp_path, [{'name': '网暴模型', 'path': 'ml_train/models/x', 'desc': 'six classes', 'operation': 'tendency'}]
    )
    rows = catalog.legacy_rows()
    named = [row for row in rows if row['name'] == '网暴模型']
    assert len(named) == 1
    assert named[0] == {
        'name': '网暴模型',
        'path': 'ml_train/models/x',
        'desc': 'six classes',
        'operation': 'tendency',
    }


def test_missing_registry_adds_no_legacy_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    assert catalog.legacy_rows() == []


def test_defaults_come_from_the_versioned_manifests(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    # The measured winner is the declared default; a plain registry row is only a fallback.
    assert catalog.default_for('sentiment').endswith('sentiment_mixed_rbt3')
    assert catalog.default_for_declared('sentiment').endswith('sentiment_mixed_rbt3')
    assert catalog.default_for('emotion').endswith('emotion_ewect_six')
    assert catalog.default_for('tendency').endswith('tendency_stance_v2_cyberbully')
    assert catalog.default_for('no-such-task') == ''


def test_unknown_model_refuses_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    with pytest.raises(catalog.UnknownModelError, match='nope'):
        catalog.get('nope')
    assert catalog.find('nope') is None


def test_public_rows_carry_the_machine_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    rows = catalog.public_rows()
    by_id = {row['id']: row for row in rows}
    chosen = by_id['sentiment_weibosenti_bin']
    assert chosen['runnable'] is True, chosen['why_not']
    assert chosen['outputs'] == ['sentiment', 'score']
    assert chosen['score_kind'] == 'polarity'
    assert chosen['quality'][0]['metric'] == 'accuracy'
    assert chosen['license'] and chosen['docs']


def test_runnable_refuses_a_missing_checkpoint_by_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    manifest = from_manifest(
        {
            'id': 'missing-model',
            'name': 'Missing',
            'family': 'text_classification',
            'task': 'sentiment',
            'path': str(tmp_path / 'not-here'),
            'license': 'MIT',
            'docs': 'docs/models/missing.md',
        }
    )
    ok, why_not = probe.runnable(manifest)
    assert not ok and 'not-here' in why_not


def test_manifest_validation_names_the_bad_field():
    with pytest.raises(ManifestError, match='family'):
        from_manifest({'id': 'x-model', 'family': 'magic', 'path': 'x'})
    with pytest.raises(ManifestError, match='license'):
        from_manifest({'id': 'x-model', 'family': 'text_classification', 'path': 'x'})
    with pytest.raises(ManifestError, match='escapes'):
        from_manifest(
            {
                'id': 'x-model',
                'family': 'text_classification',
                'path': '../x',
                'license': 'MIT',
                'docs': 'docs/x.md',
            }
        )


def test_legacy_row_without_path_is_dropped():
    assert from_legacy({'name': 'ghost'}) is None
    assert from_legacy('not an object') is None


#: New 2026-11-21 candidates: addressable, downloadable, but unmeasured — never a silent default.
NEW_CANDIDATES = (
    'bge-base-zh',
    'bge-large-zh',
    'bge-reranker-v2-m3',
    'cluener-ner',
    'cold-offensive',
)


def test_new_candidates_are_addressable_without_claiming_a_default(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    rows = {row['id']: row for row in catalog.public_rows()}
    for model_id in NEW_CANDIDATES:
        row = rows[model_id]
        assert row['runnable'] is True, row['why_not']
        assert row['default_for'] == [], f'{model_id}: an unmeasured model cannot be a default'
        assert (Path(BASE_DIR) / row['docs']).is_file(), f'{model_id}: missing model doc'
    # The measured winners keep their defaults after adding candidates.
    assert catalog.default_for('sentiment').endswith('sentiment_mixed_rbt3')
    assert catalog.default_for('reranker').endswith('bge-reranker-base')


def test_every_new_candidate_has_a_downloader_asset():
    assets = json.loads((Path(BASE_DIR) / 'ml_train' / 'scripts' / 'assets.json').read_text(encoding='utf-8'))
    paths = {item['repo'] for item in assets['models']}
    rows = {row['id']: row for row in catalog.public_rows()}
    for model_id in NEW_CANDIDATES:
        assert rows[model_id]['path'] in paths, f'{model_id}: not in the asset table'
