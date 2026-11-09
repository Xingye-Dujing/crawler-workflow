"""The online installer's optional BERT pack import.

The pack is a local archive the user already has. The installer must refuse the wrong file before
any download, place complete model folders beside the application (never inside ``app/``, which an
update replaces), and register them without overwriting an entry the user already made.
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / 'desktop' / 'bootstrap' / 'bert_install.py'
pytestmark = pytest.mark.unit


@pytest.fixture(scope='module')
def bert_install():
    spec = importlib.util.spec_from_file_location('bert_install_contract', MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _pack(base: Path, folder: str = 'demo', name: str = 'Demo model') -> Path:
    target = base / 'bert_models' / folder
    target.mkdir(parents=True)
    (target / 'model.onnx').write_bytes(b'onnx-bytes')
    (target / 'tokenizer.json').write_text('{}', encoding='utf-8')
    (target / 'cixi_bert.json').write_text(
        json.dumps({'name': name, 'operation': 'sentiment', 'desc': 'test'}), encoding='utf-8'
    )
    return target


def _zip(source: Path, archive: Path) -> Path:
    with zipfile.ZipFile(archive, 'w') as holder:
        for path in sorted(source.rglob('*')):
            if path.is_file():
                holder.write(path, path.relative_to(source).as_posix())
    return archive


def test_a_complete_zip_or_unpacked_folder_is_accepted(bert_install, tmp_path):
    folder = _pack(tmp_path / 'unpacked')
    assert bert_install.pack_problem(folder.parent) == ''
    archive = _zip(tmp_path / 'unpacked', tmp_path / 'pack.zip')
    assert bert_install.pack_problem(archive) == ''


def test_the_wrong_file_or_an_incomplete_folder_is_refused_by_name(bert_install, tmp_path):
    assert '路径不存在' in bert_install.pack_problem(tmp_path / 'missing.zip')
    text = tmp_path / 'notes.txt'
    text.write_text('x', encoding='utf-8')
    assert '.zip' in bert_install.pack_problem(text)
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert '完整的 BERT 模型' in bert_install.pack_problem(empty)
    broken = tmp_path / 'broken.zip'
    with zipfile.ZipFile(broken, 'w') as holder:
        holder.writestr('bert_models/demo/model.onnx', 'x')
        holder.writestr('bert_models/demo/cixi_bert.json', '{}')
    assert 'tokenizer.json' in bert_install.pack_problem(broken)


def test_a_zip_pack_lands_beside_app_and_is_registered(bert_install, tmp_path):
    source = _pack(tmp_path / 'source')
    archive = _zip(source.parent, tmp_path / 'pack.zip')
    root = tmp_path / 'install'
    data = tmp_path / 'data'
    placed = bert_install.install(archive, root, data)
    assert (root / 'bert_models' / 'demo' / 'model.onnx').is_file()
    assert placed['copied'] == ['demo']
    registry = json.loads((data / 'data' / 'model_registry.json').read_text(encoding='utf-8'))
    assert registry == [{'name': 'Demo model', 'path': '../bert_models/demo', 'operation': 'sentiment', 'desc': 'test'}]
    assert placed['ledger']['added'] == ['Demo model']


def test_an_existing_model_folder_is_never_overwritten(bert_install, tmp_path):
    root = tmp_path / 'install'
    _pack(root, name='Existing model')
    existing = root / 'bert_models' / 'demo'
    (existing / 'keep.txt').write_text('mine', encoding='utf-8')
    (existing / 'model.onnx').write_bytes(b'existing weights')
    source = _pack(tmp_path / 'source', name='New model')
    archive = _zip(source.parent, tmp_path / 'pack.zip')
    placed = bert_install.install(archive, root, tmp_path / 'data')
    assert (existing / 'keep.txt').read_text(encoding='utf-8') == 'mine'
    assert (existing / 'model.onnx').read_bytes() == b'existing weights'
    assert placed['skipped_folders'] == ['demo']


def test_an_existing_registry_entry_wins_over_the_pack(bert_install, tmp_path):
    data = tmp_path / 'data'
    (data / 'data').mkdir(parents=True)
    (data / 'data' / 'model_registry.json').write_text(
        json.dumps([{'name': 'Demo model', 'path': 'my/own/model', 'operation': 'sentiment'}]), encoding='utf-8'
    )
    root = tmp_path / 'install'
    source = _pack(tmp_path / 'source')
    archive = _zip(source.parent, tmp_path / 'pack.zip')
    placed = bert_install.install(archive, root, data)
    rows = json.loads((data / 'data' / 'model_registry.json').read_text(encoding='utf-8'))
    assert rows == [{'name': 'Demo model', 'path': 'my/own/model', 'operation': 'sentiment'}]
    assert placed['ledger']['skipped'] == ['Demo model']


def test_an_unpacked_folder_is_copied_without_touching_the_users_copy(bert_install, tmp_path):
    source = _pack(tmp_path / 'source')
    root = tmp_path / 'install'
    placed = bert_install.install(source.parent, root, tmp_path / 'data')
    assert (root / 'bert_models' / 'demo' / 'model.onnx').is_file()
    assert (source / 'model.onnx').is_file(), 'the user source is read-only input'
    assert placed['copied'] == ['demo']


def test_a_mac_style_data_folder_gets_an_absolute_registry_path(bert_install, tmp_path):
    source = _pack(tmp_path / 'source')
    archive = _zip(source.parent, tmp_path / 'pack.zip')
    data = tmp_path / 'data'
    models = data / 'bert_models'
    placed = bert_install.install(
        archive,
        tmp_path / 'Applications',
        data,
        models_dir=models,
        root_label=models.as_posix(),
    )
    assert (models / 'demo' / 'model.onnx').is_file()
    registry = json.loads((data / 'data' / 'model_registry.json').read_text(encoding='utf-8'))
    assert registry[0]['path'] == f'{models.as_posix()}/demo'
    assert placed['copied'] == ['demo']


def test_the_registered_path_resolves_against_the_app_directory(tmp_path, monkeypatch):
    from analyzers import sentiment

    app = tmp_path / 'install' / 'app'
    app.mkdir(parents=True)
    model = tmp_path / 'install' / 'bert_models' / 'demo'
    model.mkdir(parents=True)
    monkeypatch.setattr(sentiment, 'BASE_DIR', str(app))
    assert Path(sentiment.resolve_bert_model('../bert_models/demo')) == model


def test_the_page_and_state_expose_the_optional_field():
    page = (REPO / 'desktop' / 'bootstrap' / 'installer_page.html').read_text(encoding='utf-8')
    script = (REPO / 'desktop' / 'bootstrap' / 'installer_page.js').read_text(encoding='utf-8')
    installer = (REPO / 'desktop' / 'bootstrap' / 'installer.py').read_text(encoding='utf-8')
    for marker in (
        'id="bert"',
        'id="browse-bert"',
        'id="bert-section"',
        'id="bert-hint"',
        'id="models-preview"',
        'id="shortcut"',
        'id="shortcut-choice"',
    ):
        assert marker in page
    assert "shortcut: byId('shortcut').checked" in script
    assert '采析绘.lnk' in installer
    theme = (REPO / 'desktop' / 'bootstrap' / 'ui_theme.py').read_text(encoding='utf-8')
    assert 'models_location' in theme and 'bert_source' in theme
    assert 'modelsPreview' in script and 'path_separator' in script
    assert 'bert_supported' in script and "onBrowse('bert')" in script
    assert "bert: byId('bert').value" in script
    assert 'state.bert_supported' in installer
    assert 'bert_installing' in installer
    assert 'GetOpenFileNameW' in installer


def test_elevation_and_open_use_the_real_state():
    installer = (REPO / 'desktop' / 'bootstrap' / 'installer.py').read_text(encoding='utf-8')
    script = (REPO / 'desktop' / 'bootstrap' / 'installer_page.js').read_text(encoding='utf-8')
    assert 'TokenElevation' in installer or 'GetTokenInformation' in installer
    assert 'shell32.IsUserAnAdmin' not in installer, 'group membership is not elevation'
    assert 'not is_elevated()' in installer, 'a manifest-elevated process must not ask for UAC twice'
    assert "payload.get('root')" in installer, 'Open folder must use the path on screen'
    assert "root: byId('root').value" in script


def test_the_installer_bundles_the_placement_module_and_registry_reader():
    windows = (REPO / 'desktop' / 'bootstrap' / 'installer.spec').read_text(encoding='utf-8')
    macos = (REPO / 'desktop' / 'bootstrap' / 'installer_macos.spec').read_text(encoding='utf-8')
    for spec in (windows, macos):
        assert 'bert_install.py' in spec
        assert 'bert_pack.py' in spec
