"""Register an unpacked BERT model folder into the app's model registry, without touching the rest.

The packaged app ships no torch, so the fine-tuned checkpoints reach it as a **separate** model pack
(``CaiXiHui-bert-models-win64.zip``, unpacked to ``<exe dir>/bert_models/``). The app lists bert
models from ``<data root>/data/model_registry.json``, so a pack that is merely present on disk is
still invisible: this module is the one that turns folders into registry entries.

Three rules it is written around:

* **Only a folder that is really loadable gets registered** — ``model.onnx`` + ``tokenizer.json`` +
  a ``cixi_bert.json`` sidecar, the three things ``ml_train/scripts/export_onnx_bert.py`` writes. A
  half-copied pack would show up in the panel and then refuse at run time, which is a worse answer
  than not offering it.
* **A user's entry is never overwritten.** Matching is by ``name``; an entry already there for that
  name — maybe pointing at a folder of their own — stays, and the pack is reported as skipped.
* **A registry file this program cannot read is left alone.** A broken JSON is the user's data;
  replacing it with a freshly generated list would silently delete the models they named.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The three files that make a folder a pack. Anything less is not offered to the panel.
PACK_FILES = ('model.onnx', 'tokenizer.json', 'cixi_bert.json')
REGISTRY_NAME = 'model_registry.json'


def read_pack(folder: Path) -> dict | None:
    """The pack description if this folder is complete, else ``None`` (never a partial answer)."""
    if not all((folder / name).is_file() for name in PACK_FILES):
        return None
    try:
        sidecar = json.loads((folder / 'cixi_bert.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not sidecar.get('operation') or not sidecar.get('name'):
        return None
    return sidecar


def discover_packs(models_dir: Path, *, root_label: str = 'bert_models') -> list[dict]:
    """Every pack under ``models_dir``, as registry entries with a project-root-relative path.

    The path is deliberately relative: ``desktop_entry`` repoints ``config.BASE_DIR`` at the exe
    folder, so ``analyzers/sentiment.resolve_bert_model`` resolves it there on every machine —
    an absolute build-machine path would be a dead reference the moment the pack is copied.
    """
    entries = []
    if not models_dir.is_dir():
        return entries
    for folder in sorted(p for p in models_dir.iterdir() if p.is_dir()):
        sidecar = read_pack(folder)
        if sidecar is None:
            continue
        entries.append(
            {
                'name': str(sidecar['name']),
                'path': f'{root_label}/{folder.name}',
                'operation': str(sidecar['operation']),
                'desc': str(sidecar.get('desc') or ''),
            }
        )
    return entries


def merge_registry(existing: list, packs: list) -> tuple[list, list, list]:
    """(merged list, added entries, skipped names). Existing entries win on a name clash.

    Unknown keys on an existing entry are kept: the registry is the user's file, and this program
    only knows four of its fields.
    """
    known = {str(item.get('name') or '') for item in existing if isinstance(item, dict)}
    added, merged = [], list(existing)
    skipped = []
    for entry in packs:
        if entry['name'] in known:
            skipped.append(entry['name'])
            continue
        merged.append(entry)
        added.append(entry)
        known.add(entry['name'])
    return merged, added, skipped


def seed_registry(data_dir: Path, models_dir: Path, *, root_label: str = 'bert_models') -> dict:
    """Register the packs that are present into ``<data_dir>/model_registry.json``.

    Returns a ledger the launcher can print: ``{'packs': n, 'added': […], 'skipped': […],
    'untouched': reason}``. Nothing is written when there is nothing to add — a file that already
    lists the pack must not be rewritten on every start (that would rewrite it while another
    process has it open, for no change).
    """
    packs = discover_packs(models_dir, root_label=root_label)
    ledger = {'packs': len(packs), 'added': [], 'skipped': [], 'untouched': ''}
    if not packs:
        ledger['untouched'] = '没有可登记的模型包目录'
        return ledger
    holder = data_dir / REGISTRY_NAME
    existing: list = []
    if holder.is_file():
        try:
            existing = json.loads(holder.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            ledger['untouched'] = f'现有 {REGISTRY_NAME} 读不出来（{exc}），不覆盖它'
            return ledger
        if not isinstance(existing, list):
            ledger['untouched'] = f'现有 {REGISTRY_NAME} 不是列表，不覆盖它'
            return ledger
    merged, added, skipped = merge_registry(existing, packs)
    ledger['added'] = [entry['name'] for entry in added]
    ledger['skipped'] = skipped
    if not added:
        ledger['untouched'] = '模型包已全部登记过'
        return ledger
    holder.parent.mkdir(parents=True, exist_ok=True)
    holder.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    return ledger
