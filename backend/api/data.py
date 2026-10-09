"""数据集 Blueprint — the ``/api/data/*`` cluster, split out of ``app.py``.

Upload / list / detail / delete / rename / paste / inspect / preview / clear for persisted
files. Every dependency is reachable without importing ``app``: the store and its
read-through cache come from ``stores`` (``get_dataset_store``/``_load_dataset``/
``_register_dataset``) and ``state`` (``_dataset_cache``); payload→DataFrame resolution from
``api.resolution``; the cleaning report from ``services.data_analysis``; request coercions and
the 400 helpers from ``api.http``; ``json_safe_records``/``as_bool`` from ``utils.helpers``.
Paths and behaviour are unchanged; none of these handlers has a monkeypatch seam.
"""

import json
import logging

import pandas as pd
from flask import Blueprint, jsonify, request
from state import _dataset_cache
from stores import _load_dataset, _register_dataset, get_dataset_store

from api.http import _bad_body, _bad_param, _json_body, _safe_int
from api.resolution import _resolve_payload_dataframe
from i18n import t
from services.data_analysis import DataAnalysisService
from services.dataset_store import SOURCE_PASTE, SOURCE_UPLOAD
from utils.helpers import as_bool
from utils.helpers import json_safe_records as _json_safe_records

logger = logging.getLogger(__name__)

bp = Blueprint('data', __name__)


@bp.route('/api/data/upload', methods=['POST'])
def upload_dataset():
    """Upload a CSV, JSON, TXT or Excel file and register it for analysis/visualization."""
    file = request.files.get('file')
    if not file:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='missing file')}), 400
    filename = file.filename or 'upload'
    name_lower = filename.lower()
    try:
        if name_lower.endswith('.json'):
            df = pd.DataFrame(json.load(file.stream))
        elif name_lower.endswith('.txt'):
            text = file.stream.read().decode('utf-8', errors='replace')
            df = pd.DataFrame({'content': [text]})
        elif name_lower.endswith(('.xlsx', '.xls', '.xlsm')):
            # Spreadsheets are the format a non-technical user's data actually
            # arrives in. Without this branch the file fell through to
            # ``read_csv`` and came back as one column of mojibake — a
            # "successful" import of nonsense.
            df = pd.read_excel(file.stream)
        elif name_lower.endswith(('.csv', '.tsv')):
            # ``sep=None`` would make pandas *sniff* the delimiter, which turns a
            # comma file with a stray tab inside a quoted cell into a different
            # table. Only .tsv asks for a tab; .csv keeps the comma contract the
            # exporter writes.
            df = pd.read_csv(file.stream, sep='\t' if name_lower.endswith('.tsv') else ',')
        else:
            # An extension nobody recognises is refused, not guessed at: reading
            # a Parquet or a PDF as CSV produces a table that is technically
            # valid and completely wrong.
            return jsonify({'ok': False, 'error': t('api.unsupportedUpload', name=filename)}), 400
    except (ValueError, OSError, UnicodeDecodeError, pd.errors.ParserError, ImportError) as e:
        # A corrupt or mis-encoded file is a user-input problem, not a crash.
        # ImportError belongs here too: reading .xlsx needs openpyxl, and a
        # missing engine is a fixable environment gap, not a 500.
        return jsonify({'ok': False, 'error': t('api.parseFailed', err=e)}), 400

    is_txt = name_lower.endswith('.txt')
    try:
        dataset_id = _register_dataset(df, name=filename, source=SOURCE_UPLOAD)
    except ValueError as e:
        # Over the row ceiling: refusing beats storing half a file.
        return jsonify({'ok': False, 'error': t('api.datasetTooBig', err=e)}), 400
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            # The Upload node labels itself with this name, so it must travel
            # back with the id — otherwise a successful upload still reads
            # "no file uploaded yet".
            'name': filename,
            'columns': list(df.columns),
            'row_count': len(df),
            'is_txt': is_txt,
            # False when identical rows were already stored: the UI can then
            # say "already saved" rather than pretending it wrote something new.
            'persisted': True,
            'preview': _json_safe_records(df, 10),
        }
    )


@bp.route('/api/data/datasets', methods=['GET'])
def list_datasets():
    """Every stored file, newest first, with the workflows that read it.

    This is how a page that has only its own canvas asks "do my Upload nodes
    still have their files?" — one request, no guessing.
    """
    limit = _safe_int(request.args.get('limit'), 200, minimum=1, maximum=1000)
    datasets = get_dataset_store().list_datasets(limit=limit)
    return jsonify({'ok': True, 'datasets': datasets, 'stats': get_dataset_store().stats()})


@bp.route('/api/data/datasets/<dataset_id>', methods=['GET'])
def dataset_detail(dataset_id: str):
    """Metadata (and a short preview) for one stored file."""
    meta = get_dataset_store().meta(dataset_id)
    if meta is None:
        return jsonify({'ok': False, 'error': t('api.datasetMissing', did=dataset_id)}), 404
    df = _load_dataset(dataset_id)
    meta['preview'] = _json_safe_records(df, 10) if df is not None else []
    return jsonify({'ok': True, 'dataset': meta})


@bp.route('/api/data/datasets/<dataset_id>', methods=['DELETE'])
def dataset_delete(dataset_id: str):
    """Forget one file and every pointer to it.

    Refused while a saved workflow still reads it: the delete would succeed and
    the workflow would only discover the gap on its next open, as an Upload node
    with no rows and a run that quietly returns 0 results. The panel shows the
    referencing workflows for the same reason.
    """
    store = get_dataset_store()
    refs = store.referenced_by(dataset_id) if store.exists(dataset_id) else []
    force = str(request.args.get('force') or '') in ('1', 'true', 'yes')
    if refs and not force:
        return jsonify({'ok': False, 'error': t('api.datasetInUse', workflows=', '.join(refs)), 'workflows': refs}), 409
    removed = store.delete(dataset_id)
    _dataset_cache.pop(dataset_id, None)
    if not removed:
        return jsonify({'ok': False, 'error': t('api.datasetMissing', did=dataset_id)}), 404
    return jsonify({'ok': True, 'dataset_id': dataset_id})


@bp.route('/api/data/datasets/<dataset_id>/rename', methods=['POST'])
def dataset_rename(dataset_id: str):
    """Relabel a stored file. The name is what the list and the Upload node show.

    A rename is not a re-hash: the id is content, so the dataset keeps its
    identity, every workflow pointer stays valid, and no rows are rewritten.
    """
    body = _json_body()
    if body is None:
        return _bad_body()
    raw = body.get('name')
    if not isinstance(raw, str):
        return _bad_param('name')
    store = get_dataset_store()
    renamed = store.rename(dataset_id, raw)
    if renamed is None:
        if not store.exists(dataset_id):
            return jsonify({'ok': False, 'error': t('api.datasetMissing', did=dataset_id)}), 404
        # An empty or fully-unusable label is refused rather than stored, because
        # a nameless row in the list is unclickable and unfindable.
        return jsonify({'ok': False, 'error': t('api.datasetNameInvalid', name=raw)}), 400
    return jsonify({'ok': True, 'dataset_id': dataset_id, 'name': renamed})


@bp.route('/api/data/paste', methods=['POST'])
def paste_dataset():
    """Register hand-typed/pasted JSON records (array of objects) as a dataset."""
    data = _json_body()
    if data is None:
        return _bad_body()
    records = data.get('data')
    if not isinstance(records, list):
        return jsonify({'ok': False, 'error': t('api.fieldTypeInvalid', name='data')}), 400
    df = pd.DataFrame(records)
    try:
        dataset_id = _register_dataset(df, name=data.get('name', 'pasted'), source=SOURCE_PASTE)
    except ValueError as e:
        return jsonify({'ok': False, 'error': t('api.datasetTooBig', err=e)}), 400
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            'name': data.get('name', 'pasted'),
            'columns': list(df.columns),
            'row_count': len(df),
            'preview': _json_safe_records(df, 10),
        }
    )


@bp.route('/api/data/inspect', methods=['POST'])
def inspect_dataset():
    """Return null counts / dtypes / duplicate counts for a dataset."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error
    return jsonify({'ok': True, 'report': DataAnalysisService.inspect(df)})


@bp.route('/api/data/preview', methods=['POST'])
def preview_dataset():
    """Paginated tabular preview of any dataset (uploaded, pasted, a
    workflow node's result, or inline data) — backs the generic Data
    Preview panel so users can inspect real rows instead of only JSON/charts."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    limit = _safe_int(data.get('limit'), 50, minimum=1, maximum=500)
    offset = _safe_int(data.get('offset'), 0, minimum=0)
    total = len(df)
    page = df.iloc[offset : offset + limit]
    return jsonify(
        {
            'ok': True,
            'columns': list(df.columns),
            'rows': _json_safe_records(page),
            'total_rows': total,
            'offset': offset,
            'limit': limit,
        }
    )


@bp.route('/api/data/clear', methods=['POST'])
def clear_datasets():
    """Housekeeping on stored files.

    By default it drops only *orphans* — files no saved workflow points at and
    nobody has read for a while. That used to be a blunt "forget everything",
    which made no sense once a saved workflow came to depend on those files.
    ``?all=1`` really does empty the store, pointers included, for the rare
    case of wanting a clean slate.
    """
    store = get_dataset_store()
    payload = _json_body()
    if payload is None:
        return _bad_body()
    # Read as a switch, not against one spelling: the browser's 清空 sends a real JSON
    # ``true``, and comparing against ``'1'`` would answer that request with the *orphan*
    # sweep — a panel that then reloads still holding referenced files, reporting a wipe that
    # never happened. The query-string form stays valid for a hand-typed call.
    wipe = as_bool(payload.get('all')) or str(request.args.get('all') or '') in ('1', 'true', 'yes')
    if wipe:
        removed = store.clear()
        _dataset_cache.clear()
        logger.warning(t('ds.cleared', n=removed))
        return jsonify({'ok': True, 'removed': removed, 'orphans': 0})

    _dataset_cache.clear()
    removed = store.purge_unreferenced()
    kept = store.stats()
    logger.info(t('ds.purge_result', n=removed, kept=kept['datasets']))
    return jsonify({'ok': True, 'removed': removed, 'kept': kept['datasets']})
