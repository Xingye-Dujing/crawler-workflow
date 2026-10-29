"""Append this run's rows to a named lineage and pass the full table downstream.

The lineage is versioned in ``DatasetStore``; the node's output is the current full table, so
downstream analysis sees history, while the run record still carries that version's row list.
Identity is the user's explicit choice: whole-row equality or named key columns — never an
auto-picked key.
"""

import re

import pandas as pd
from runtime.state import add_log
from runtime.stores import get_dataset_store

from i18n import t
from nodes.context import NodeCall

NODE_TYPE = 'accumulate'


def emit_columns(_node: dict, merged: list[str] | None) -> list[str] | None:
    """It appends rows and passes the table through, so the schema IS the upstream schema
    (unknown when the upstream is unknown)."""
    return merged


def execute_accumulate_node(node: dict, current_input: list, ctx: dict = None):
    params = node.get('params') or {}
    name = str(params.get('lineage_name') or '').strip()
    identity = str(params.get('identity') or 'row').strip().lower()
    key_columns = [part.strip() for part in re.split('[,，;；]', str(params.get('key_columns') or '')) if part.strip()]
    result = get_dataset_store().append_lineage(
        name,
        pd.DataFrame(current_input or []),
        identity=identity,
        key_columns=key_columns,
        run_id=str((ctx or {}).get('run_id') or ''),
        node_id=str(node.get('id') or ''),
    )
    add_log(
        t(
            'accumulate.done',
            name=name,
            added=result['added'],
            total=result['rows'],
            version=result['lineage']['version'],
        )
    )
    return result['frame'].to_dict('records')


def run(node: dict, call: NodeCall) -> list:
    return execute_accumulate_node(node, call.current_input, ctx=call.ctx)
