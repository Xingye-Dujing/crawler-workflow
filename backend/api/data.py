"""数据集 Blueprint — the ``/api/data/*`` cluster, split out of ``app.py``.

Upload / list / detail / delete / rename / paste / inspect / preview / clear for persisted
files. Every dependency is reachable without importing ``app``: the store and its
read-through cache come from ``stores`` (``get_dataset_store``/``_load_dataset``/
``_register_dataset``) and ``state`` (``_dataset_cache``); payload→DataFrame resolution from
``api.resolution``; the cleaning report from ``services.data_analysis``; request coercions and
the 400 helpers from ``api.http``; ``json_safe_records``/``as_bool`` from ``core.refs``.
Paths and behaviour are unchanged; none of these handlers has a monkeypatch seam.
"""

import io
import json
import logging

import pandas as pd
from core.refs import as_bool
from core.refs import json_safe_records as _json_safe_records
from flask import Blueprint, jsonify, request
from state import _dataset_cache, any_run_live
from stores import _load_dataset, _register_dataset, get_dataset_store

from api.http import _bad_body, _bad_param, _json_body, _safe_int
from api.resolution import _resolve_payload_dataframe
from i18n import t
from services.biblio.importer import BiblioDecodeError, decode_text, parse_bytes, parse_frame, parse_text
from services.data_analysis import DataAnalysisService
from services.datasets.merge import merge_datasets
from services.datasets.store import SOURCE_PASTE, SOURCE_UPLOAD

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
    biblio_format = None
    biblio_capabilities = None
    warnings: list[str] = []
    is_txt = False

    def use_biblio(parsed: dict) -> pd.DataFrame:
        nonlocal biblio_format, biblio_capabilities, warnings
        biblio_format = parsed['format']
        biblio_capabilities = parsed.get('capabilities')
        warnings = parsed['warnings']
        logger.info(t('biblio.import_ok', format=biblio_format, n=len(parsed['rows'])))
        return pd.DataFrame(parsed['rows'], columns=parsed['columns'])

    try:
        if name_lower.endswith('.json'):
            df = pd.DataFrame(json.load(file.stream))
        elif name_lower.endswith('.txt'):
            raw = file.stream.read()
            try:
                parsed = parse_bytes(raw, filename)
            except BiblioDecodeError:
                # An undecodable .txt keeps the pre-bibliometrics behaviour: the
                # whole file becomes one replacement-character text cell. It is
                # not a bibliographic export we can name, so refusing it would
                # break an upload that used to work.
                parsed = None
            except ValueError as e:
                return jsonify({'ok': False, 'error': str(e)}), 400
            if parsed is None:
                # Ordinary text keeps its old shape: one row, one ``content``
                # cell. A bibliographic export becomes a record table instead.
                try:
                    text = decode_text(raw, filename)
                except ValueError:
                    text = raw.decode('utf-8', errors='replace')
                df = pd.DataFrame({'content': [text]})
                is_txt = True
            else:
                df = use_biblio(parsed)
        elif name_lower.endswith(('.ris', '.bib', '.bibtex', '.enw', '.nbib', '.net')):
            raw = file.stream.read()
            parsed = parse_bytes(raw, filename)
            if parsed is None:
                return jsonify({'ok': False, 'error': t('api.biblioNotRecognized', name=filename)}), 400
            df = use_biblio(parsed)
        elif name_lower.endswith(('.xlsx', '.xls', '.xlsm')):
            # Spreadsheets are the format a non-technical user's data actually
            # arrives in. Without this branch the file fell through to
            # ``read_csv`` and came back as one column of mojibake — a
            # "successful" import of nonsense.
            book = pd.ExcelFile(file.stream)
            sheet_names = list(book.sheet_names)
            # ``read_excel`` defaults to the FIRST sheet, which silently imported one month of a
            # January/February/March workbook and reported that sheet's row count and columns as
            # if they were the whole file — a SILENT_SHORT the upload panel then analysed as truth.
            # More than one sheet holding rows is a choice of data, so it is refused by name.
            filled = [name for name in sheet_names if not book.parse(name, nrows=1).empty]
            if len(filled) > 1:
                return jsonify(
                    {'ok': False, 'error': t('api.excelMultiSheet', name=filename, sheets='、'.join(filled))}
                ), 400
            df = book.parse(filled[0] if filled else (sheet_names[0] if sheet_names else 0))
            parsed = parse_frame(df)
            if parsed is not None:
                df = use_biblio(parsed)
        elif name_lower.endswith(('.csv', '.tsv')):
            # ``sep=None`` would make pandas *sniff* the delimiter, which turns a
            # comma file with a stray tab inside a quoted cell into a different
            # table. Only .tsv asks for a tab; .csv keeps the comma contract the
            # exporter writes.
            raw = file.stream.read()
            parsed = None
            if name_lower.endswith('.csv'):
                try:
                    parsed = parse_text(decode_text(raw, filename))
                except BiblioDecodeError:
                    parsed = None
            if parsed is not None:
                df = use_biblio(parsed)
            else:
                df = pd.read_csv(io.BytesIO(raw), sep='\t' if name_lower.endswith('.tsv') else ',')
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
            # True only for the old whole-file single ``content`` cell; a CNKI /
            # CSSCI export has many rows and must not be described as one text.
            'is_txt': is_txt,
            'biblio_format': biblio_format,
            'biblio_capabilities': biblio_capabilities,
            'warnings': warnings,
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
    lineage = store.dataset_lineage(dataset_id) if store.exists(dataset_id) else None
    if lineage and not force:
        return jsonify({'ok': False, 'error': t('api.datasetInLineage', name=lineage['name'])}), 409
    if lineage:
        store.reset_lineage(lineage['name'])
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


@bp.route('/api/data/diff', methods=['POST'])
def diff_datasets():
    """Row-level comparison of any two tables — two saved datasets, two workflow
    node outputs, or a mix. Each side is a resolver payload (``{dataset_id}`` or
    ``{node_id, workflow_name}`` or inline ``{data}``), so this one endpoint answers
    every pairing without a second reader.

    Optional ``key`` names a column to detect *changed* rows by; without it only
    ``added``/``removed`` are reported, because aligning whole rows by a column the
    server picked for you would be guessing about the data."""
    data = _json_body()
    if data is None:
        return _bad_body()
    side_a, side_b = data.get('a'), data.get('b')
    if not isinstance(side_a, dict) or not isinstance(side_b, dict):
        return jsonify({'ok': False, 'error': t('api.diffTwoSources')}), 400
    a_df, error_a = _resolve_payload_dataframe(side_a)
    if error_a is not None:
        return error_a
    b_df, error_b = _resolve_payload_dataframe(side_b)
    if error_b is not None:
        return error_b
    limit = _safe_int(data.get('limit'), 200, minimum=1, maximum=5000)
    raw_key = data.get('key')
    key = raw_key if isinstance(raw_key, str) and raw_key else None
    report = DataAnalysisService.diff(a_df, b_df, key=key, limit=limit)
    # The row samples carry raw numpy scalars; run them through the same JSON-safe
    # record path the preview route uses, so the browser never sees a NaN or int64.
    report['added'] = _json_safe_records(pd.DataFrame(report['added']))
    report['removed'] = _json_safe_records(pd.DataFrame(report['removed']))
    for pair in report['changed']:
        pair['a'] = _json_safe_records(pd.DataFrame([pair['a']]))[0]
        pair['b'] = _json_safe_records(pd.DataFrame([pair['b']]))[0]
    return jsonify({'ok': True, 'diff': report})


@bp.route('/api/data/lineages', methods=['GET'])
def dataset_lineages():
    store = get_dataset_store()
    name = str(request.args.get('name') or '').strip()
    if not name:
        return jsonify({'ok': True, 'lineages': store.list_lineages()})
    lineage = store.lineage(name)
    if lineage is None:
        return jsonify({'ok': False, 'error': t('api.lineageMissing', name=name)}), 404
    return jsonify({'ok': True, 'lineage': lineage, 'history': store.lineage_history(name)})


@bp.route('/api/data/lineages/reset', methods=['POST'])
def dataset_lineage_reset():
    data = _json_body()
    if data is None:
        return _bad_body()
    name = data.get('name')
    if not isinstance(name, str):
        return _bad_param('name')
    clean = name.strip()
    if not clean:
        return _bad_param('name')
    if not get_dataset_store().reset_lineage(clean):
        return jsonify({'ok': False, 'error': t('api.lineageMissing', name=clean)}), 404
    return jsonify({'ok': True, 'reset': True})


@bp.route('/api/data/merge', methods=['POST'])
def merge_dataset_rows():
    data = _json_body()
    if data is None:
        return _bad_body()
    dataset_ids = data.get('dataset_ids')
    if not isinstance(dataset_ids, list) or not all(isinstance(item, str) for item in dataset_ids):
        return _bad_param('dataset_ids')
    name = data.get('name', '')
    if not isinstance(name, str):
        return _bad_param('name')
    try:
        result = merge_datasets(get_dataset_store(), dataset_ids, name)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, **result})


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
        # A full-store wipe is a bulk destructive write, so it holds the same two lines as
        # ``exports_clear`` / ``history_clear``: an explicit ``confirm: true`` (a stray or
        # cross-origin call must not empty the store) and a live-run guard (a running node may
        # be reading one of these very datasets). The orphan sweep below needs neither.
        if payload.get('confirm') is not True:
            return jsonify({'ok': False, 'error': t('api.needConfirm')}), 400
        if any_run_live():
            return jsonify({'ok': False, 'error': t('ds.clearBusy')}), 409
        removed = store.clear()
        _dataset_cache.clear()
        logger.warning(t('ds.cleared', n=removed))
        return jsonify({'ok': True, 'removed': removed, 'orphans': 0})

    _dataset_cache.clear()
    removed = store.purge_unreferenced()
    kept = store.stats()
    # Silence is the normal case, and this route is not only a button: the page boot sweeps
    # orphans on EVERY tab that opens (app.js), so an unconditional line here added one more
    # identical sentence to the run console per page load — measured on the CI runner, where
    # eighty of them buried the console test's own three lines. `services/runs/housekeeping.py`
    # already keeps to this rule for the automatic sweep; a manual 清理 still reports through
    # its own toast from this response, so nothing loses its answer by being silent here.
    if removed:
        logger.info(t('ds.purge_result', n=removed, kept=kept['datasets']))
    return jsonify({'ok': True, 'removed': removed, 'kept': kept['datasets']})
