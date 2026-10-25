"""Assemble the optional BERT model pack — a separate archive, because four checkpoints are not an app.

The application ships at roughly 135 MB compressed and works without a pack (uploading, cleaning,
crawling, analysing, bibliometrics). The fine-tuned checkpoints are 195 MB each even in the recipe
that changes no decision, so they are a second artifact: unpack it into ``<exe dir>/bert_models/``
and the launcher registers the folders into ``data/model_registry.json`` on the next start
(``desktop/bert_pack.py``) — nothing is reinstalled and nothing the user named is overwritten.

    python desktop/build_model_pack.py <precision> <out.zip> <onnx root> <model name>...

e.g. ``python desktop/build_model_pack.py fp16 dist/CaiXiHui-bert-models-win64.zip
../ml_train/models/onnx emotion_ewect_six sentiment_weibosenti_bin ...``. The source folders are
products of ``ml_train/scripts/export_onnx_bert.py``, which is the only place torch is needed: this
script never converts. It collects what was already measured, checks each folder is a complete pack,
and refuses by name if one is missing rather than shipping a half pack.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

#: The three files that make a folder a pack — the same list ``desktop/bert_pack.py`` reads to
#: decide whether a folder is worth offering in the model panel.
PACK_FILES = ('model.onnx', 'tokenizer.json', 'cixi_bert.json')


def collect(source_root: Path, precision: str, wanted: list[str]) -> tuple[list[Path], list[str]]:
    """Every complete ``<name>_onnx_<precision>`` folder, and the names that were not found."""
    folders, missing = [], []
    for name in wanted:
        candidate = source_root / f'{name}_onnx_{precision}'
        if not candidate.is_dir() or not all((candidate / item).is_file() for item in PACK_FILES):
            missing.append(name)
            continue
        folders.append(candidate)
    return folders, missing


def stage(folders: list[Path], staging: Path) -> list[Path]:
    """Copy the folders into ``<staging>/bert_models/`` with their own names.

    The container directory is the one the launcher scans, so the archive's layout IS the contract:
    a zip that unpacks to ``onnx/emotion_...`` would leave ``bert_models`` empty and the pack
    invisible, which reads to the user as "the models did not take".
    """
    root = staging / 'bert_models'
    shutil.rmtree(staging, ignore_errors=True)
    root.mkdir(parents=True)
    landed = []
    for folder in folders:
        target = root / folder.name
        shutil.copytree(folder, target)
        landed.append(target)
    return landed


def write_zip(staging: Path, archive: Path) -> int:
    """Deflate at level 9; fp16 weights are near-incompressible, so the container is the cheap half."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as holder:
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                holder.write(path, path.relative_to(staging).as_posix())
    return archive.stat().st_size


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print('usage: python build_model_pack.py <precision> <out.zip> <onnx root> <model name>...', file=sys.stderr)
        return 2
    precision, archive, source_root = argv[1], Path(argv[2]), Path(argv[3])
    folders, missing = collect(source_root, precision, list(argv[4:]))
    if missing:
        print(f'这些模型没有 {precision} 产物，未打包：{", ".join(missing)}', file=sys.stderr)
        return 2
    staging = archive.parent / f'{archive.stem}.staging'
    landed = stage(folders, staging)
    size = write_zip(staging, archive)
    shutil.rmtree(staging, ignore_errors=True)
    print(f'模型包：{len(landed)} 个模型 → {archive}（{size / 1024 / 1024:.1f} MB）')
    print('用法：解压到应用目录，使 bert_models/ 与 CaiXiHui.exe 同级；下次启动会自动登记进模型列表。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
