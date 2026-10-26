"""Compare two recorded runs of the same workflow, node by node and row by row.

A run record stores each node's status and row count, and the rows themselves in
``node_rows``. This service reads two runs, reports which nodes are present in both,
and asks ``DataAnalysisService.diff`` for the table difference of one chosen node.
The diff is computed here, never assembled in the browser: added/removed counts and
sample rows are one answer, and two implementations of "what changed" would drift.

The default node is the latest-started common node with rows — usually the last
table the user looked at — but an explicit ``node_id`` always wins. A missing run
or node is a named refusal; a different workflow shape is REPORTED (``same_shape``)
and the comparison continues over the nodes the two runs actually share.
"""

import pandas as pd

from i18n import t
from services.data_analysis import DataAnalysisService

MAX_COMPARE_ROWS = 200_000
MAX_SAMPLE_ROWS = 200


def _header(run: dict) -> dict:
    return {
        'run_id': str(run.get('run_id') or ''),
        'workflow_name': str(run.get('workflow_name') or ''),
        'started_at': str(run.get('started_at') or ''),
        'finished_at': str(run.get('finished_at') or ''),
        'status': str(run.get('status') or ''),
        'mode': str(run.get('mode') or ''),
        'workflow_fingerprint': str(run.get('workflow_fingerprint') or ''),
    }


def _node_summary(node: dict) -> dict:
    return {
        'node_id': str(node.get('node_id') or ''),
        'title': str(node.get('title') or ''),
        'node_type': str(node.get('node_type') or ''),
        'component_name': str(node.get('component_name') or ''),
        'status_a': str(node.get('status') or ''),
        'status_b': str(node.get('status') or ''),
        'rows_a': int(node.get('row_count') or 0),
        'rows_b': int(node.get('row_count') or 0),
    }


def _shape(run: dict) -> list:
    return sorted((str(node.get('node_id') or ''), str(node.get('node_type') or '')) for node in run.get('nodes') or [])


def _default_node(common: list) -> str:
    """The latest-started common node that actually holds rows in either run.

    ``started_at`` is second-granularity, so ties fall back to the larger row count
    and then the id; the choice is deterministic and visible in the response.
    """
    candidates = [row for row in common if row['rows_a'] or row['rows_b']]
    if not candidates:
        return ''
    chosen = max(
        candidates, key=lambda row: (row.get('started_at') or '', row['rows_a'] + row['rows_b'], row['node_id'])
    )
    return chosen['node_id']


def compare_runs(store, run_a: str, run_b: str, node_id: str = '', key: str = '', limit: int = 50) -> dict:
    """The comparison object both the API and its tests read."""
    left = store.get_run(str(run_a or ''))
    if left is None:
        raise LookupError(t('compare.runMissing', rid=run_a or '(empty)'))
    right = store.get_run(str(run_b or ''))
    if right is None:
        raise LookupError(t('compare.runMissing', rid=run_b or '(empty)'))
    if str(run_a) == str(run_b):
        raise ValueError(t('compare.sameRun'))

    limit = max(1, min(int(limit or 50), MAX_SAMPLE_ROWS))
    by_a = {str(node.get('node_id') or ''): node for node in left.get('nodes') or []}
    by_b = {str(node.get('node_id') or ''): node for node in right.get('nodes') or []}
    common = []
    for node_id_a, node in by_a.items():
        if node_id_a not in by_b:
            continue
        summary = _node_summary(node)
        summary['status_b'] = str(by_b[node_id_a].get('status') or '')
        summary['rows_b'] = int(by_b[node_id_a].get('row_count') or 0)
        summary['started_at'] = str(node.get('started_at') or '')
        summary['row_delta'] = summary['rows_b'] - summary['rows_a']
        common.append(summary)

    chosen = str(node_id or '').strip() or _default_node(common)
    if node_id and chosen not in by_a:
        raise LookupError(t('compare.nodeMissing', node=chosen, rid=left.get('run_id') or run_a))
    if node_id and chosen not in by_b:
        raise LookupError(t('compare.nodeMissing', node=chosen, rid=right.get('run_id') or run_b))

    diff = None
    chosen_meta = None
    if chosen:
        chosen_meta = next((row for row in common if row['node_id'] == chosen), None)
        rows_a = store.load_rows(left['run_id'], chosen)
        rows_b = store.load_rows(right['run_id'], chosen)
        if len(rows_a) > MAX_COMPARE_ROWS or len(rows_b) > MAX_COMPARE_ROWS:
            raise ValueError(t('compare.tooManyRows', node=chosen, max=MAX_COMPARE_ROWS))
        frame_a = pd.DataFrame(rows_a)
        frame_b = pd.DataFrame(rows_b)
        diff = DataAnalysisService.diff(frame_a, frame_b, key=(str(key or '').strip() or None), limit=limit)

    return {
        'a': _header(left),
        'b': _header(right),
        'same_workflow': str(left.get('workflow_name') or '') == str(right.get('workflow_name') or ''),
        'same_shape': _shape(left) == _shape(right),
        'nodes': common,
        'node': {field: value for field, value in (chosen_meta or {}).items() if field != 'started_at'},
        'diff': diff,
        'key_used': str(key or '').strip() or None,
    }
