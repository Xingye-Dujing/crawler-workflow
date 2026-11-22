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
from nodes.catalog import TABLE_NODE_TYPES
from nodes.context import NodeCall

NODE_TYPE = 'accumulate'


def validate_node(node: dict, context) -> list[dict]:
    """Name, identity mode, keys and exactly one table parent — the lineage append's contract."""
    params = node.get('params') or {}
    problems: list[dict] = []
    name = str(params.get('lineage_name') or '').strip()
    identity = str(params.get('identity') or 'row').strip().lower()
    keys = [part.strip() for part in str(params.get('key_columns') or '').replace('，', ',').split(',') if part.strip()]
    if not name:
        problems.append({'code': 'engine.accumulate_no_name', 'message_key': 'engine.accumulate_no_name'})
    if identity not in ('row', 'columns'):
        problems.append(
            {
                'code': 'engine.accumulate_bad_identity',
                'message_key': 'engine.accumulate_bad_identity',
                'context': {'value': identity},
            },
        )
    elif identity == 'columns' and not keys:
        problems.append({'code': 'engine.accumulate_no_keys', 'message_key': 'engine.accumulate_no_keys'})
    parents = context.parent_ids()
    if len(parents) != 1:
        problems.append(
            {
                'code': 'engine.accumulate_one_parent',
                'message_key': 'engine.accumulate_one_parent',
            },
        )
    elif context.node(parents[0]).get('type') not in TABLE_NODE_TYPES:
        problems.append(
            {
                'code': 'engine.accumulate_bad_parent',
                'message_key': 'engine.accumulate_bad_parent',
                'context': {'up': context.label_of(parents[0])},
            },
        )
    return problems


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
