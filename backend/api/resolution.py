"""Payload → DataFrame resolution — the ``_resolve_dataframe`` / ``_durable_node_rows`` /
``_resolve_payload_dataframe`` / ``NoRunDataError`` web, split out of ``app.py``.

These turn a request body (a persisted file id, a workflow node's live-or-recorded result,
or inline records) into a DataFrame, and give the "node ran nothing" case a named, friendly
400. They are shared by the ``data``/``analysis``/``studio``/``visualize``/``export`` route
clusters, so lifting them out lets those clusters become Blueprints without importing the
Flask module. Every dependency is cycle-free (``stores``/``state``/``flask``/``i18n``);
nothing here reads an ``app``-only global, and there are no monkeypatch seams on these names.
"""

import pandas as pd
from flask import jsonify
from state import execution_state
from stores import _load_dataset, get_run_store


class NoRunDataError(KeyError):
    """Asked to draw from a node that produced no rows live and filed none away.

    This is the expected state of a canvas nobody has executed yet, not a fault. It is a
    named type so the API turns it into a friendly, non-error response rather than leaking a
    raw ``KeyError`` string (whose ``str()`` even carries spurious quotes) into a cell that
    the dashboard rehydrates on every cold load.
    """

    code = 'no_run_data'


def _durable_node_rows(node_id: str, workflow_name: str = '') -> list:
    """Rows this node produced in an earlier run, newest first — or [].

    Previews, charts and exports all resolve a node by id, and
    execution_state['results'] only exists while the process has been running
    without a refresh. Everything since then is in the run store, so asking
    there is what keeps a reopened workflow inspectable instead of blank.

    Asking by id alone is the trap: ``node-2`` exists on every canvas ever
    drawn, so a lookup with no workflow attached to it would happily return a
    stranger's rows — a table that looks correct and belongs to another
    workflow. So an identity is required: the request's own workflow name (what
    the browser is showing, which beats what this process happened to run last),
    or the fingerprint/name the last run recorded. With neither, the answer is
    empty, and the panel says there is nothing recorded.
    """
    store = get_run_store()
    requested = str(workflow_name or '').strip()
    if requested:
        exact = store.latest_rows(node_id, workflow_name=requested)
        if exact[1]:
            return exact[1]
        # ``A + B`` is how a parallel run is recorded; the same canvas filed its
        # earlier runs under ``A`` alone, so both spellings are offered rather than
        # leaving a week-old run's rows unreachable behind one string. Only after the
        # name the browser is showing matched nothing, though: a workflow genuinely
        # called ``R&B`` would otherwise have the ``R`` of somebody else's
        # ``R + B`` offered as a candidate, and a stranger's table under the user's
        # own node name is exactly the false data this function exists to refuse.
        parts = [part.strip() for part in requested.split('+') if part.strip()]
        if not parts or parts == [requested]:
            return []
        return store.latest_rows(node_id, workflow_name=requested, workflow_names=parts)[1]
    fingerprint = execution_state.get('fingerprint') or ''
    ambient = execution_state.get('workflow_name') or ''
    if not fingerprint and not ambient:
        return []
    return store.latest_rows(node_id, fingerprint=fingerprint, workflow_name=ambient)[1]


def _resolve_dataframe(payload: dict) -> pd.DataFrame:
    """Resolve a DataFrame from a request payload that may reference a
    persisted file, a workflow node's result (live *or* recorded), or inline
    records."""
    dataset_id = payload.get('dataset_id')
    if dataset_id:
        df = _load_dataset(dataset_id)
        if df is None:
            raise KeyError(f'Unknown dataset_id: {dataset_id}')
        return df

    node_id = payload.get('node_id')
    if node_id:
        result = execution_state['results'].get(node_id)
        if isinstance(result, list):
            return pd.DataFrame(result)
        # Nothing live: fall back to the rows this node last filed away, which
        # is also the only copy left after a restart.
        rows = _durable_node_rows(node_id, payload.get('workflow_name') or '')
        if rows:
            return pd.DataFrame(rows)
        raise NoRunDataError(f'No tabular result available for node: {node_id}')

    records = payload.get('data')
    if records is not None:
        return pd.DataFrame(records)

    raise KeyError('No data source provided (dataset_id, node_id, or data)')


def _resolve_payload_dataframe(data: dict):
    """``(df, None)`` for a usable payload, or ``(None, response)`` for its 400.

    :func:`_resolve_dataframe` reports an unknown reference as a KeyError, which
    every route here already turned into a 400 — but a reference of the wrong
    *shape* (``{"data": 42}``) dies in the pandas constructor with a
    ValueError/TypeError instead, and that escaped as an HTML 500. Both are the
    caller's mistake, so both answer the same way, with the reason.
    """
    try:
        return _resolve_dataframe(data), None
    except NoRunDataError as e:
        # Expected empty on an unexecuted node: keep the 400 for callers that branch on
        # status, but name it with a code so the browser shows "run once first" instead of
        # the raw reference string.
        return None, (jsonify({'ok': False, 'error': str(e), 'code': e.code}), 400)
    except (KeyError, TypeError, ValueError) as e:
        return None, (jsonify({'ok': False, 'error': str(e)}), 400)
