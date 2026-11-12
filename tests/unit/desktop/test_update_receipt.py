"""The in-app updater rewrites the installer's records, and the reader still accepts them.

The reader (``desktop/install_receipt.py``) lived alone with its own tests; the writer is the half
an in-app update needs, and the only proof that the two agree is to write through one and read
through the other. Nothing here needs a frozen exe.
"""

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
DESKTOP = REPO / 'desktop'


def _load_reader():
    spec = importlib.util.spec_from_file_location('install_receipt_reader', DESKTOP / 'install_receipt.py')
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def reader():
    return _load_reader()


def _managed_install(root: Path, version: str = '1.0.0') -> Path:
    """What the Inno installer leaves: a pointer plus the receipt it names."""
    (root / 'versions' / version).mkdir(parents=True)
    (root / 'current-version').write_bytes(f'{version}\n'.encode('ascii'))
    receipt = {
        'app': 'CaiXiHui',
        'artifact': 'CaiXiHui-Setup.exe',
        'channel': 'stable',
        'method': 'direct',
        'version': version,
        'root': str(root),
    }
    (root / 'versions' / version / 'install.json').write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
    return root


def test_a_new_version_is_readable_by_the_release_reader(reader, tmp_path):
    from services import update_receipt

    root = _managed_install(tmp_path / 'CaiXiHui')
    written = update_receipt.record('2026.11.0', root, artifact='CaiXiHui-win64.zip')
    record = reader.read_install(root)
    assert record['version'] == '2026.11.0'
    assert record['channel'] == 'stable'
    assert record['method'] == 'self-update'
    assert Path(written) == root / 'versions' / '2026.11.0' / 'install.json'


def test_both_records_keep_the_installer_encoding_rules(tmp_path):
    from services import update_receipt

    root = _managed_install(tmp_path / '安装目录')
    update_receipt.record('2026.11.0', root)
    pointer = (root / 'current-version').read_bytes()
    assert pointer == b'2026.11.0\n', 'the pointer must stay one ASCII line'
    receipt = (root / 'versions' / '2026.11.0' / 'install.json').read_bytes()
    assert not receipt.startswith(b'\xef\xbb\xbf'), 'the receipt must be UTF-8 without a BOM'
    assert json.loads(receipt.decode('utf-8'))['root'].endswith('安装目录')
    assert not list(root.rglob('*.partial')), 'an atomic write left its staging file behind'


def test_the_receipt_is_written_before_the_pointer(tmp_path, monkeypatch):
    """A crash between the two writes must leave the OLD pointer naming a valid old receipt."""
    from services import update_receipt

    root = _managed_install(tmp_path / 'CaiXiHui')
    calls = []
    real = update_receipt._atomic_write

    def tracking(path, data):
        calls.append(Path(path).name)
        if Path(path).name == update_receipt.POINTER_NAME:
            raise OSError('simulated crash')
        return real(path, data)

    monkeypatch.setattr(update_receipt, '_atomic_write', tracking)
    with pytest.raises(OSError):
        update_receipt.record('2026.11.0', root)
    assert calls == [update_receipt.RECEIPT_NAME, update_receipt.POINTER_NAME]
    assert (root / 'current-version').read_bytes() == b'1.0.0\n'


def test_a_portable_folder_is_left_alone(tmp_path):
    from services import update_receipt

    assert update_receipt.record('2026.11.0', tmp_path) == ''
    assert not list(tmp_path.iterdir())


def test_an_unsafe_version_is_refused_before_it_becomes_a_path(tmp_path):
    from services import update_receipt

    root = _managed_install(tmp_path / 'CaiXiHui')
    for value in ('../etc', '1.0/../../x', '', '..'):
        with pytest.raises(ValueError):
            update_receipt.record(value, root)
