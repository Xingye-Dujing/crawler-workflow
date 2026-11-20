"""The one schema for a model entry: new manifests and the old editable registry.

Old ``data/model_registry.json`` rows are still four strings. They are accepted as legacy entries so
no existing workflow changes meaning, but a NEW manifest must say what it is, what it writes, where
its licence and documentation are, and which family runs it. A half-declared model is refused by
name here instead of becoming a blank pick in the panel.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

MODEL_ID_RE = re.compile(r'^[a-z][a-z0-9._-]{1,63}$')

#: Every family this program knows how to run. A manifest naming an unknown family is refused, not
#: folded into the text classifier -- a reranker answered by a classifier is a silent wrong answer.
FAMILIES = frozenset(
    {
        'text_classification',
        'token_classification',
        'encoder',
        'reranker',
        'zero_shot',
        'sklearn_text',
        'tabular',
    }
)


class ManifestError(ValueError):
    """A model entry cannot be addressed safely or completely."""


@dataclass(frozen=True)
class ModelManifest:
    id: str
    name: str
    family: str
    task: str
    path: str
    desc: str = ''
    operation: str = ''
    labels: tuple = ()
    outputs: tuple = ()
    score_kind: str = 'score'
    precision: str = ''
    size_mb: int = 0
    vram_mb: int = 0
    rows_per_sec: float = 0.0
    quality: tuple = ()
    use_for: tuple = ()
    avoid_for: tuple = ()
    license: str = ''
    docs: str = ''
    pack: str = ''
    requires: tuple = ()
    default_for: tuple = ()
    meta: dict = field(default_factory=dict, compare=False)

    def to_legacy(self) -> dict:
        """The four keys the old ``/api/models`` picker and its tests consume."""
        return {'name': self.name, 'path': self.path, 'desc': self.desc, 'operation': self.operation or self.task}

    def public(self, *, runnable: bool = True, why_not: str = '') -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'family': self.family,
            'task': self.task,
            'operation': self.operation or self.task,
            'path': self.path,
            'desc': self.desc,
            'labels': list(self.labels),
            'outputs': list(self.outputs),
            'score_kind': self.score_kind,
            'precision': self.precision,
            'size_mb': self.size_mb,
            'vram_mb': self.vram_mb,
            'rows_per_sec': self.rows_per_sec,
            'quality': list(self.quality),
            'use_for': list(self.use_for),
            'avoid_for': list(self.avoid_for),
            'license': self.license,
            'docs': self.docs,
            'pack': self.pack,
            'requires': list(self.requires),
            'default_for': list(self.default_for),
            'runnable': runnable,
            'why_not': why_not,
            'legacy': self.meta.get('legacy', False),
            'revision': revision(self),
        }

    def source_of_truth(self) -> str:
        """A printable identity: the id plus the resolved path, never a bare folder name."""
        return f'{self.id}@{self.path or "no-path"}'


def revision(manifest: ModelManifest) -> str:
    """A short fingerprint of the weights a node actually loads.

    A canvas stores the model NAME, not the bytes behind it. When an operator retrains a checkpoint
    under the same folder, a resumed run must not adopt rows produced by the old weights; the
    fingerprint feeds the node's identity so the two are different runs.
    """
    digest = hashlib.sha256((manifest.id + '|' + manifest.path).encode('utf-8'))
    if manifest.path and os.path.isdir(manifest.path):
        for name in ('model.safetensors', 'model.onnx'):
            candidate = os.path.join(manifest.path, name)
            if os.path.isfile(candidate):
                stat = os.stat(candidate)
                digest.update(f'|{name}:{stat.st_size}:{int(stat.st_mtime)}'.encode())
                break
    return digest.hexdigest()[:12]


def from_manifest(data: dict, *, base_dir: str = '') -> ModelManifest:
    """Validate one ``model.json``; a bad value raises with the field name in the message."""
    if not isinstance(data, dict):
        raise ManifestError('a model manifest must be a JSON object')
    model_id = str(data.get('id') or '').strip()
    if not MODEL_ID_RE.match(model_id):
        raise ManifestError(f'id {model_id!r}: use a lowercase letter then letters, digits, dots, dashes')
    family = str(data.get('family') or '').strip()
    if family not in FAMILIES:
        raise ManifestError(f'{model_id}: unknown family {family!r}; allowed: {", ".join(sorted(FAMILIES))}')
    path = str(data.get('path') or '').strip()
    if not path:
        raise ManifestError(f'{model_id}: path is empty; nothing could be loaded from it')
    if not os.path.isabs(path):
        if '..' in path.replace('\\', '/').split('/'):
            raise ManifestError(f'{model_id}: path {path!r} escapes its root')
        if base_dir:
            path = os.path.normpath(os.path.join(base_dir, path))
    if not data.get('license') or not data.get('docs'):
        raise ManifestError(f'{model_id}: license and docs are required for a registered model')
    return ModelManifest(
        id=model_id,
        name=str(data.get('name') or model_id),
        family=family,
        task=str(data.get('task') or model_id),
        path=path,
        desc=str(data.get('desc') or ''),
        operation=str(data.get('operation') or data.get('task') or ''),
        labels=tuple(str(item) for item in data.get('labels') or ()),
        outputs=tuple(str(item) for item in data.get('outputs') or ()),
        score_kind=str(data.get('score_kind') or 'score'),
        precision=str(data.get('precision') or ''),
        size_mb=int(data.get('size_mb') or 0),
        vram_mb=int(data.get('vram_mb') or 0),
        rows_per_sec=float(data.get('rows_per_sec') or 0),
        quality=tuple(dict(item) for item in data.get('quality') or () if isinstance(item, dict)),
        use_for=tuple(str(item) for item in data.get('use_for') or ()),
        avoid_for=tuple(str(item) for item in data.get('avoid_for') or ()),
        license=str(data.get('license') or ''),
        docs=str(data.get('docs') or ''),
        pack=str(data.get('pack') or ''),
        requires=tuple(str(item) for item in data.get('requires') or ()),
        default_for=tuple(str(item) for item in data.get('default_for') or ()),
        meta=dict(data.get('_meta') or {}),
    )


def from_legacy(row: dict) -> ModelManifest | None:
    """Adapt one old registry entry; a row without a path is not addressable and is dropped."""
    if not isinstance(row, dict):
        return None
    path = str(row.get('path') or '').strip()
    if not path:
        return None
    task = str(row.get('operation') or '').strip()
    model_id = os.path.basename(path.replace('\\', '/').rstrip('/')) or task or 'legacy-model'
    name = str(row.get('name') or model_id)
    # Keep the old id stable even when two folders share a basename: the path is the true key.
    digest = hashlib.sha1(path.encode('utf-8')).hexdigest()[:8]
    return ModelManifest(
        id=f'legacy-{model_id}-{digest}',
        name=name,
        family='text_classification',
        task=task,
        path=path,
        desc=str(row.get('desc') or ''),
        operation=task,
        meta={'legacy': True},
    )


def read_manifest_file(path: str, *, base_dir: str = '') -> ModelManifest:
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    return from_manifest(data, base_dir=base_dir)


def is_legacy_manifest(data: dict) -> bool:
    """A bare four-string registry row, not a full model declaration."""
    return isinstance(data, dict) and 'family' not in data
