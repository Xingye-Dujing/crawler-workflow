"""Fusion node: several source tables in, ONE normalized record table out.

It reads ``upstream`` rather than ``current_input`` on purpose: the engine's fan-in merge has already
flattened the parents into one row list and lost which table each row came from, and the whole point
of this node is that a term carries its source. The output is a plain row table in the canonical
record shape, so any ``biblio`` node downstream needs no remapping.
"""

import contextlib

import pandas as pd
from core.config import Config
from core.refs import as_bool
from core.refs import json_safe_records as _json_safe_records
from runtime.state import add_log

from i18n import t
from nodes.context import NodeCall
from services.biblio import fuse

NODE_TYPE = 'fuse'


def execute_fuse_node(node: dict, _current_input: list, upstream: list = None, ctx: dict = None):
    params = node.get('params') or {}
    label = str(node.get('title') or node.get('id') or 'fuse')
    parents = list(upstream or ())
    if not parents:
        raise ValueError(t('fuse.no_input', nid=label))
    result = fuse.fuse(parents, params, label)
    for note in result.get('notes') or []:
        add_log(note)
    summary = result.get('summary') or {}
    add_log(
        t(
            'fuse.build_done',
            parents=summary.get('parents', len(parents)),
            rows=summary.get('rows', len(result['rows'])),
            sources='、'.join(summary.get('sources') or []),
        )
    )
    if as_bool(params.get('export_files'), False):
        try:
            path = fuse.export_records(result['rows'], Config.EXPORT_DIR, f'{label}-{node.get("id") or "fuse"}')
        except Exception as exc:
            raise ValueError(t('biblio.export_failed', err=exc)) from exc
        if ctx and ctx.get('store') and ctx.get('run_id'):
            with contextlib.suppress(Exception):
                ctx['store'].record_file(ctx['run_id'], str(node.get('id') or ''), path, 'fuse_records')
    return _json_safe_records(pd.DataFrame(result['rows']))


def run(node: dict, call: NodeCall) -> list:
    return execute_fuse_node(node, call.current_input, upstream=call.upstream, ctx=call.ctx)
