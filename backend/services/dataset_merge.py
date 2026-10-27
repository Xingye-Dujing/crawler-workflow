"""Merge stored datasets into one table, with provenance.

Two crawls of the same platform have the same columns; two uploaded files often do
too. This is the dataset-panel counterpart of the canvas fan-in merge: it checks
that the column sets agree, keeps the first table's column order, and adds a
``来源`` column naming the dataset each row came from. A column mismatch is a
named refusal — ``pd.concat`` would answer it with an outer join full of holes,
which looks like a complete table until a chart reads the empty cells.

The result is a new dataset in the same store (content identity and dedupe are
the store's, so merging identical rows twice reuses the same id). No source file
is changed.
"""

import pandas as pd
from core.config import Config

from i18n import t
from services.dataset_store import SOURCE_MERGE

SOURCE_COLUMN = '来源'
MAX_NAME = 120


def merge_datasets(store, dataset_ids, name: str) -> dict:
    """The merged dataset's metadata plus per-source row counts."""
    ids = []
    for raw in dataset_ids or []:
        clean = str(raw or '').strip()
        if clean and clean not in ids:
            ids.append(clean)
    if len(ids) < 2:
        raise ValueError(t('data.mergeNeedTwo'))

    clean_name = str(name or '').strip()
    if not clean_name:
        raise ValueError(t('data.mergeNameRequired'))
    if len(clean_name) > MAX_NAME:
        raise ValueError(t('data.mergeNameTooLong', n=MAX_NAME))

    frames = []
    sources = []
    reference = None
    for dataset_id in ids:
        frame = store.get(dataset_id)
        if frame is None:
            raise ValueError(t('data.mergeMissing', id=dataset_id))
        meta = store.meta(dataset_id) or {}
        label = str(meta.get('name') or dataset_id)
        columns = [str(column) for column in frame.columns]
        if reference is None:
            reference = columns
        elif set(columns) != set(reference):
            extra = [column for column in columns if column not in reference]
            missing = [column for column in reference if column not in columns]
            raise ValueError(
                t(
                    'data.mergeColumns',
                    name=label,
                    extra=', '.join(extra) or '-',
                    missing=', '.join(missing) or '-',
                )
            )
        frames.append(frame.reindex(columns=reference))
        sources.append({'dataset_id': dataset_id, 'name': label, 'rows': int(len(frame))})

    total = sum(row['rows'] for row in sources)
    if total > Config.DATASET_MAX_ROWS:
        raise ValueError(t('data.mergeTooLarge', n=total, max=Config.DATASET_MAX_ROWS))

    # A dataset that already carries its own 来源 column keeps it: the user's
    # per-row provenance is more specific than the table's filename.
    if frames and SOURCE_COLUMN not in frames[0].columns:
        for frame, source in zip(frames, sources, strict=True):
            frame.insert(0, SOURCE_COLUMN, source['name'] or source['dataset_id'])

    merged = pd.concat(frames, ignore_index=True, sort=False)
    meta = store.put(merged, name=clean_name, source=SOURCE_MERGE)
    return {
        'dataset': meta,
        'rows': int(len(merged)),
        'columns': [str(column) for column in merged.columns],
        'sources': sources,
    }
