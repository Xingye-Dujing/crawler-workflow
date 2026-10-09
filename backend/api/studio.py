"""Chart Studio Blueprint — the ``/api/studio/*`` cluster, split out of ``app.py``.

The studio runs in a same-origin iframe and authors charts from a workflow dataset. These
endpoints close the loop: hand it real rows, and take the finished chart back as a file next
to the other workflow exports. The whole cluster and its private helpers/constants move
together — none is referenced by any other route — and every dependency is reachable without
importing ``app`` (``state``/``stores``/``api.resolution``/``api.http``/``utils.helpers``).
Paths and behaviour are unchanged; no monkeypatch seam on these handlers.
"""

import base64
import logging
import os
import re
import uuid

import pandas as pd
from flask import Blueprint, jsonify
from state import _results_snapshot, execution_state
from stores import _load_dataset

from api.http import _bad_body, _json_body, _safe_int
from api.resolution import _durable_node_rows, _resolve_dataframe
from config import Config
from i18n import t
from utils.helpers import json_safe_records as _json_safe_records
from utils.helpers import sanitize_filename

logger = logging.getLogger(__name__)

bp = Blueprint('studio', __name__)

STUDIO_MAX_ROWS = 5000
# A chart PNG is a few hundred KB; 20 MB is a generous ceiling that still keeps
# a malformed payload from ballooning the process.
MAX_IMAGE_BYTES = 20 * 1024 * 1024

# Why a candidate cannot be served. Stable short codes so the browser can
# localise them; the picker shows a short form inline and the long form as a
# tooltip / toast.
SRC_NO_UPSTREAM = 'no_upstream'
SRC_NO_RESULT = 'no_result'
SRC_STALE_DATASET = 'stale_dataset'
SRC_EMPTY = 'empty'
SRC_ERROR = 'error'
STUDIO_MAX_CANDIDATES = 500
# Column names travel with each probe so the picker can tell the user what is
# inside a node before they combine it; only the first few are ever shown.
PROBE_MAX_COLUMNS = 24
# How many nodes one merged load may combine.
STUDIO_MAX_SOURCES = 50


def _first_tabular_result():
    """Return (node_id, DataFrame) for the first node that produced a tabular
    result, or (None, None). Used as a fallback so the Chart Studio still gets
    data when the user picked a node that has not produced output yet."""
    for node_id, result in _results_snapshot().items():
        if isinstance(result, list) and result:
            return node_id, pd.DataFrame(result)
    return None, None


def _merge_unique_names(names: list, used: dict) -> list:
    """Make a frame's column names unique across everything already merged.

    A repeat gets the source's ordinal appended (`freq` → `freq_2`), and that
    again (`freq_2_3`) if even that is taken — the studio binds columns by name,
    so two columns called `freq` would make the second one unreachable.
    """
    out = []
    for raw in names:
        name = str(raw)
        if name not in used:
            used[name] = 1
            out.append(name)
            continue
        # `used[name]` doubles as the ordinal to try next for that name.
        used[name] += 1
        candidate = f'{name}_{used[name]}'
        while candidate in used:
            used[name] += 1
            candidate = f'{name}_{used[name]}'
        used[candidate] = 1
        out.append(candidate)
    return out


def _merge_frames(frames: list, mode: str) -> tuple[pd.DataFrame, str]:
    """Combine several nodes' tables into one. → (DataFrame, mode actually used)

    Both modes place whole tables next to each other, the way you would paste
    them into one sheet — never interleaved. Nothing is matched up by value, so
    the result is always a full rectangle with no half-empty rows:

    rows — put the other table *below*: its rows are appended after the first
           table's, re-using the first table's column names for the columns they
           line up with. Nothing is dropped and nothing is left blank.
    side — put the other table *to the right*: its columns are appended after
           the first table's, row 1 next to row 1. A shorter table just stops
           early.
    """
    if len(frames) < 2:
        return frames[0], 'rows'
    if mode in ('side', 'columns', 'right'):
        parts = []
        used: dict = {}
        for frame in frames:
            part = frame.reset_index(drop=True).copy()
            part.columns = _merge_unique_names(list(part.columns), used)
            parts.append(part)
        return pd.concat(parts, axis=1), 'side'

    # Appending rows. Identical column sets stack by name (the ordinary case:
    # two word-frequency tables joined end to end).
    base = [str(c) for c in frames[0].columns]
    if all([str(c) for c in f.columns] == base for f in frames[1:]):
        return pd.concat(frames, ignore_index=True, sort=False), 'rows'

    # Different schemas: line the tables up by *position* instead, so the second
    # table lands under the first rather than on the empty cells beside it.
    width = max(len(f.columns) for f in frames)
    header = list(base)
    for frame in frames[1:]:
        for idx, col in enumerate(frame.columns):
            if idx >= len(header):
                header.append(str(col))
    header = header[:width]

    rows = []
    for frame in frames:
        for record in frame.itertuples(index=False, name=None):
            row = list(record)
            rows.append(row + [None] * (width - len(row)) if len(row) < width else row)
    return pd.DataFrame(rows, columns=header), 'rows'


def _column_names(df) -> list:
    """Column names for the picker's tooltip. Capped: the picker shows a handful
    and the probe runs for every node on the canvas."""
    try:
        return [str(c) for c in list(df.columns)[:PROBE_MAX_COLUMNS]]
    except Exception:
        return []


def _probe_source(payload: dict | None) -> tuple[bool, int, str, list]:
    """Can this payload produce a table right now? → (available, rows, reason,
    columns).

    Deliberately cheap. The picker probes every node on the canvas in one go, so
    for the two common cases — an uploaded dataset and a node's stored run
    result — the row count and column names are read straight off the stored
    DataFrame / list instead of materialising a copy. Only payloads carrying
    inline records have to go through _resolve_dataframe, because those are
    computed rather than stored.
    """
    if not isinstance(payload, dict):
        return False, 0, SRC_NO_UPSTREAM, []

    dataset_id = payload.get('dataset_id')
    if dataset_id:
        df = _load_dataset(dataset_id)
        if df is None:
            return False, 0, SRC_STALE_DATASET, []
        rows = len(df)
        return (True, rows, '', _column_names(df)) if rows else (False, 0, SRC_EMPTY, [])

    node_id = payload.get('node_id')
    if not node_id:
        return False, 0, SRC_NO_UPSTREAM, []
    result = execution_state['results'].get(node_id)
    if isinstance(result, list):
        rows = len(result)
        if not rows:
            return False, 0, SRC_EMPTY, []
        first = result[0]
        cols = list(first.keys()) if isinstance(first, dict) else []
        return True, rows, '', [str(c) for c in cols[:PROBE_MAX_COLUMNS]]

    # Nothing live: fall back to the rows the node last stored, so a probe right
    # after a page refresh answers instead of reporting "no data".
    stored = _durable_node_rows(node_id, payload.get('workflow_name') or '')
    if stored:
        cols = list(stored[0].keys()) if isinstance(stored[0], dict) else []
        return True, len(stored), '', [str(c) for c in cols[:PROBE_MAX_COLUMNS]]

    try:
        df = _resolve_dataframe(payload)
    except KeyError:
        return False, 0, SRC_NO_RESULT, []
    except Exception:
        logger.exception(t('misc.source_probe_failed'))
        return False, 0, SRC_ERROR, []
    rows = 0 if df is None else len(df)
    return (True, rows, '', _column_names(df)) if rows else (False, 0, SRC_EMPTY, [])


def _studio_dataset_merged(data: dict, sources: list):
    """Load several nodes at once and hand the studio a single merged table.

    A source that cannot be served is *skipped*, not fatal: the picker already
    greys those out, so this only happens when the probe went stale (a server
    restart wipes the in-memory results). Every source's fate is reported back so
    the bar can say "2 of 3 loaded" rather than quietly pretending.
    """
    limit = _safe_int(data.get('limit'), STUDIO_MAX_ROWS, minimum=1, maximum=STUDIO_MAX_ROWS)
    mode = str(data.get('merge') or 'concat').lower()
    frames = []
    report = []
    for src in sources[:STUDIO_MAX_SOURCES]:
        src = src if isinstance(src, dict) else {}
        node_id = str(src.get('node_id') or '')
        try:
            df = _resolve_dataframe(src)
            if df is None or df.empty:
                report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_EMPTY})
                continue
            frames.append(df)
            report.append(
                {
                    'node_id': node_id,
                    'ok': True,
                    'rows': len(df),
                    'columns': len(df.columns),
                    'reason': '',
                }
            )
        except KeyError:
            report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_NO_RESULT})
        except Exception:
            logger.exception(t('misc.studio_source_failed'))
            report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_ERROR})

    if not frames:
        return jsonify(
            {
                'ok': False,
                'code': 'no_result',
                'error': t('api.noSourceTable'),
                'sources': report,
            }
        )

    merged, used_mode = _merge_frames(frames, mode)
    total = len(merged)
    page = merged.iloc[:limit]
    return jsonify(
        {
            'ok': True,
            'columns': [str(c) for c in merged.columns],
            'rows': _json_safe_records(page),
            'total_rows': total,
            'truncated': total > limit,
            'merged': len(frames) > 1,
            'merge_mode': used_mode,
            'sources': report,
            'fallback': None,
        }
    )


@bp.route('/api/studio/dataset', methods=['POST'])
def studio_dataset():
    """Full tabular dump of a node's result / uploaded dataset.

    /api/data/preview is deliberately paginated for on-screen browsing; the
    studio needs the whole table in one shot so it can bind columns and series
    itself, so this returns everything up to STUDIO_MAX_ROWS.

    Two request shapes:

      {"node_id": …}                       one node — what the picker sends when
                                           exactly one row is selected
      {"sources": [{…}, {…}], "merge": …}  several nodes, merged into one table

    Node results only exist after a workflow run, and they live in memory, so a
    freshly (re)started server has none. For a single node we fall back to
    whichever node does have data and say so via `fallback`; a merged load never
    does that silently — it reports each source instead.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    sources = data.get('sources')
    if isinstance(sources, list) and sources:
        if len(sources) > 1:
            return _studio_dataset_merged(data, sources)
        src = sources[0] if isinstance(sources[0], dict) else {}
        limit = data.get('limit', STUDIO_MAX_ROWS)
        data = dict(src)
        data.setdefault('limit', limit)

    fallback_note = None
    try:
        df = _resolve_dataframe(data)
    except (KeyError, TypeError, ValueError) as e:
        # KeyError is a reference to a node whose result is gone — the case the
        # fallback below exists for. TypeError/ValueError are a payload of the
        # wrong *shape* (``{"data": 42}``), which used to escape the pandas
        # constructor as an HTML 500 the browser could not parse; both answer
        # with the same ok:false + code the picker already localises.
        fb_id, fb_df = _first_tabular_result()
        if fb_df is None or fb_df.empty:
            return jsonify({'ok': False, 'code': 'no_result', 'error': str(e)})
        df = fb_df
        fallback_note = {'requested': data.get('node_id'), 'used': fb_id}

    limit = _safe_int(data.get('limit'), STUDIO_MAX_ROWS, minimum=1, maximum=STUDIO_MAX_ROWS)
    total = len(df)
    page = df.iloc[:limit]
    return jsonify(
        {
            'ok': True,
            'columns': [str(c) for c in df.columns],
            'rows': _json_safe_records(page),
            'total_rows': total,
            'truncated': total > limit,
            'fallback': fallback_note,
        }
    )


@bp.route('/api/studio/sources', methods=['POST'])
def studio_sources():
    """Pre-flight for the studio's source picker.

    Every node on the canvas is listed, but only those that can actually hand
    the studio a table are selectable. The browser works out the static dead
    ends itself (a Visualize node with nothing connected has no payload at all);
    this endpoint answers the runtime half — has the node produced a result yet,
    is the uploaded dataset still around — so the user is told *why* a row is
    unselectable before clicking Load instead of after.

    Body: {"candidates": [{"node_id": str, "payload": {...} | null}]}
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    candidates = data.get('candidates')
    if not isinstance(candidates, list):
        return jsonify({'ok': False, 'error': t('api.badRequest', what='candidates list')}), 400

    sources = []
    for item in candidates[:STUDIO_MAX_CANDIDATES]:
        item = item if isinstance(item, dict) else {}
        available, rows, reason, cols = _probe_source(item.get('payload'))
        sources.append(
            {
                'node_id': str(item.get('node_id') or ''),
                'available': available,
                'rows': rows,
                'reason': reason,
                'cols': cols,
            }
        )
    return jsonify({'ok': True, 'sources': sources})


@bp.route('/api/studio/save-image', methods=['POST'])
def studio_save_image():
    """Persist a chart rendered in the studio (PNG data URL) into EXPORT_DIR."""
    data = _json_body()
    if data is None:
        return _bad_body()
    image = data.get('image') or ''
    match = re.match(r'^data:image/(png|jpeg|jpg|webp);base64,(.+)$', image, re.DOTALL)
    if not match:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='image data URL')}), 400

    ext = match.group(1)
    if ext == 'jpeg':
        ext = 'jpg'
    try:
        payload = base64.b64decode(match.group(2), validate=False)
    except (ValueError, TypeError) as e:
        return jsonify({'ok': False, 'error': t('api.parseFailed', err=e)}), 400
    if not payload:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='empty image')}), 400
    if len(payload) > MAX_IMAGE_BYTES:
        # A full-canvas chart is a few hundred KB; anything far past the cap is
        # either a mistake or an attempt to exhaust memory.
        return jsonify({'ok': False, 'error': t('api.badRequest', what='image too large')}), 400

    name = data.get('name') or 'studio-chart'
    name = re.sub(r'\.(png|jpe?g|webp)$', '', str(name), flags=re.IGNORECASE)
    filename = sanitize_filename(f'{name}-{uuid.uuid4().hex[:8]}.{ext}')
    filepath = os.path.join(Config.EXPORT_DIR, filename)
    try:
        os.makedirs(Config.EXPORT_DIR, exist_ok=True)
        with open(filepath, 'wb') as fh:
            fh.write(payload)
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Could not write file: {e}'}), 500

    logger.info(t('misc.studio_saved', path=filepath, bytes=len(payload)))
    return jsonify({'ok': True, 'filename': filename, 'path': filepath, 'bytes': len(payload)})
