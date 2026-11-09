"""Place a user's fine-tuned BERT pack into the model folder the installer was told to use.

The pack is a separate ~780 MB archive (``CaiXiHui-bert-models-win64.zip``): four ONNX folders,
each with ``model.onnx``, ``tokenizer.json`` and a ``cixi_bert.json`` sidecar. The user picks the
archive; this module reads it and unpacks complete folders into the destination. The online
installer passes ``<data>/bert_models`` (the model location follows the data folder); a
full/portable install can use ``<exe dir>/bert_models``.

Why the online installer must not put them inside ``app/``: that folder is replaced wholesale on
every application update (the old copy moves to ``app.previous``), so a 780 MB pack there would
disappear on the first update. The registry label is computed by the caller: relative to ``app/``
when the folder is inside the install root, absolute otherwise (the macOS data folder).

Rules, matching ``desktop/bert_pack.py``:
* only a complete pack folder is copied (the three files above);
* an existing model folder is never deleted or overwritten;
* an existing registry entry with the same name wins (the user may have pointed it elsewhere).
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path

from services.components.archive import ArchiveError, safe_extract


class BertPackError(Exception):
    """A BERT pack that cannot be used; the sentence names the missing piece."""


@lru_cache(maxsize=1)
def _registry():
    """``desktop/bert_pack.py`` loaded by path: it is a script, not an importable package."""
    candidates = [
        Path(__file__).resolve().with_name('bert_pack.py'),
        Path(__file__).resolve().parents[1] / 'bert_pack.py',
    ]
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise BertPackError('bert_pack.py 不在安装器包里，无法登记模型')
    import importlib.util

    spec = importlib.util.spec_from_file_location('installer_bert_pack', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pack_problem(source: str | Path) -> str:
    """``''`` when the path looks like a usable pack, else a sentence naming what is wrong."""
    text = str(source or '').strip()
    if not text:
        return '请选择一个 .zip 模型包或已解压的 bert_models 文件夹'
    path = Path(text).expanduser()
    if not path.exists():
        return f'路径不存在：{path}'
    if path.is_dir():
        models = path / 'bert_models' if (path / 'bert_models').is_dir() else path
        try:
            complete = any(_registry().read_pack(child) is not None for child in models.iterdir() if child.is_dir())
        except OSError as exc:
            return f'文件夹读不出来：{exc}'
        if not complete:
            return '文件夹里没有完整的 BERT 模型（需要 model.onnx、tokenizer.json、cixi_bert.json）'
        return ''
    if path.suffix.lower() != '.zip':
        return '请选择 .zip 模型包或已解压的 bert_models 文件夹'
    try:
        with zipfile.ZipFile(path) as holder:
            names = holder.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        return f'不是可读的 zip：{exc}'
    if not any(name.endswith('model.onnx') for name in names):
        return '压缩包里没有 model.onnx'
    if not any(name.endswith('tokenizer.json') for name in names):
        return '压缩包里没有 tokenizer.json'
    if not any(name.endswith('cixi_bert.json') for name in names):
        return '压缩包里没有 cixi_bert.json'
    return ''


def _source_models(staging: Path) -> Path:
    """The folder holding model folders, whether the zip wraps ``bert_models`` or not."""
    candidates = [staging / 'bert_models']
    candidates.extend(child / 'bert_models' for child in staging.iterdir() if child.is_dir())
    candidates.append(staging)
    registry = _registry()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if any(registry.read_pack(child) is not None for child in candidate.iterdir() if child.is_dir()):
            return candidate
    raise BertPackError('压缩包里没有完整的 bert_models 模型（需要 model.onnx、tokenizer.json、cixi_bert.json）')


def install(
    source: str | Path,
    root: str | Path,
    data: str | Path,
    *,
    models_dir: str | Path | None = None,
    root_label: str = '../bert_models',
) -> dict:
    """Copy a pack into ``models_dir`` and register it in ``<data>/data``.

    ``models_dir`` defaults to ``<root>/bert_models``; the online installer passes the model folder
    that follows the data directory (``<data>/bert_models``) and the matching registry label. macOS
    has no writable install root, so its label is absolute; Windows uses a relative label only when
    the folder is inside the install root.

    Returns ``{'copied': [...], 'skipped_folders': [...], 'ledger': {...}}``; the ledger is the one
    ``desktop/bert_pack.py`` wrote. A folder that already exists is left exactly as it is.
    """
    problem = pack_problem(source)
    if problem:
        raise BertPackError(problem)
    registry = _registry()
    source_path = Path(source).expanduser()
    install_root = Path(root)
    target_models = Path(models_dir) if models_dir is not None else install_root / 'bert_models'
    target_models.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.bert-models-', dir=str(target_models.parent)))
    copied: list[str] = []
    skipped: list[str] = []
    try:
        if source_path.is_dir():
            source_models = source_path / 'bert_models' if (source_path / 'bert_models').is_dir() else source_path
            from_archive = False
        else:
            try:
                safe_extract(source_path, staging, archive_type='zip')
            except (ArchiveError, OSError) as exc:
                raise BertPackError(f'解压 BERT 模型包失败：{exc}') from exc
            source_models = _source_models(staging)
            from_archive = True
        if source_models.resolve() != target_models.resolve():
            for folder in sorted(child for child in source_models.iterdir() if child.is_dir()):
                if registry.read_pack(folder) is None:
                    continue
                target = target_models / folder.name
                if target.exists():
                    skipped.append(folder.name)
                    continue
                if from_archive:
                    shutil.move(str(folder), str(target))
                else:
                    shutil.copytree(folder, target)
                copied.append(folder.name)
        ledger = registry.seed_registry(Path(data) / 'data', target_models, root_label=root_label)
        if ledger['packs'] == 0:
            raise BertPackError('放置后没有找到完整的 BERT 模型，注册表未写入')
        return {'copied': copied, 'skipped_folders': skipped, 'ledger': ledger}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
