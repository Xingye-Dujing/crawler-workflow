"""Upload node — the one place a file can enter a workflow.

It publishes a stored file (``data/datasets.db``) as ordinary rows, so every downstream node sees it
exactly as it sees a crawl. That is why the visualize and tokenize nodes no longer carry their own
upload UI: any node that needs data connects upstream, and the upstream may be a crawler or a file.

The file is looked up by its id, and failing that by its *name* plus row count: re-uploading after a
row was lost hands back something usable instead of forcing a second edit of the workflow.
"""

from api.http import _optional_int
from core.refs import json_safe_records as _json_safe_records
from state import add_log
from stores import _apply_dataset_meta, _load_dataset, get_dataset_store

from i18n import t
from nodes.context import NodeCall

NODE_TYPE = 'upload'


def execute_upload_node(node: dict):
    params = node.get('params', {})
    dataset_id = str(params.get('dataset_id') or '')
    if not dataset_id:
        raise ValueError(t('upload.no_file'))

    df = _load_dataset(dataset_id)
    if df is None:
        replacement = get_dataset_store().find_replacement(
            str(params.get('dataset_name') or ''),
            _optional_int(params.get('row_count')),
        )
        if replacement:
            df = _load_dataset(replacement)
            if df is not None:
                dataset_id = replacement
                add_log(t('ds.rebound', name=params.get('dataset_name') or replacement, did=replacement))
    if df is None:
        # Nothing to publish, and pretending otherwise would hand downstream an
        # empty table that looks like a successful run.
        raise ValueError(t('upload.stale'))

    stored = get_dataset_store().meta(dataset_id) or {}
    # The name in storage is authoritative: it is the one every saved workflow
    # knows the file by, and writing it back keeps this node's params usable as
    # a re-binding hint later.
    meta = {
        'dataset_id': dataset_id,
        'name': stored.get('name') or str(params.get('dataset_name') or '') or dataset_id,
        'row_count': len(df),
    }
    _apply_dataset_meta(params, meta)
    add_log(t('upload.loaded', name=params.get('dataset_name') or dataset_id, n=len(df)))
    return _json_safe_records(df)


def run(node: dict, _call: NodeCall) -> list:
    return execute_upload_node(node)
