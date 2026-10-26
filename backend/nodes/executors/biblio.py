"""Bibliometric node: records in, one node/attribute row per entity out.

The result is a plain row table on purpose (not a chart spec): the run store persists it, a resume
reuses it, and a downstream Visualize node draws it. GraphML/CSV artifacts are a side effect of the
node, registered in the run→files ledger when a run context is present.
"""

import contextlib

import pandas as pd
from state import add_log
from stores import _load_dataset

from config import Config
from i18n import t
from nodes.context import NodeCall
from services import bibliometrics
from utils.helpers import as_bool
from utils.helpers import json_safe_records as _json_safe_records

NODE_TYPE = 'biblio'


def execute_biblio_node(node: dict, current_input: list, upstream: list = None, ctx: dict = None):
    params = node.get('params') or {}
    label = str(node.get('title') or node.get('id') or 'biblio')
    if not current_input:
        raise ValueError(t('engine.biblio_no_input', nid=label))
    if upstream is not None and len(upstream) > 1:
        raise ValueError(t('engine.biblio_multi_input', nid=label, n=len(upstream)))

    basemap_df = None
    basemap_id = str(params.get('basemap_dataset_id') or '').strip()
    if basemap_id:
        basemap_df = _load_dataset(basemap_id)
        if basemap_df is None:
            raise ValueError(t('biblio.dual_map_needs_basemap', nid=label))
    result = bibliometrics.build(pd.DataFrame(current_input), params, label, basemap_df=basemap_df)
    summary = result.get('summary') or {}
    entity = str(summary.get('entity_type') or params.get('entity_type') or 'keyword')
    window = summary.get('window') or {}
    for note in result.get('notes') or []:
        add_log(note)

    shape = str(summary.get('output_shape') or params.get('output_shape') or 'nodes')
    rows = {
        'edges': result['edges'],
        'clusters': result['clusters'],
        'bursts': result['bursts'],
        'variation': result['variation'],
        'dual_map': result['rows'],
    }.get(shape, result['rows'])

    # Cross-run monitoring runs BEFORE the export so the JSON artifact carries what was filed. Its
    # failures are NOT swallowed: a monitor that ate its own error would report a clean run while
    # watching nothing at all.
    watch = _watch_capture(node, ctx, params, rows, shape, entity)
    if watch:
        for note in watch['notes']:
            add_log(note)
        summary['watch'] = {
            'project': watch['project']['name'],
            'snapshot': watch['snapshot'],
            'baseline': watch['baseline'],
            'totals': _watch_totals(watch['diff']),
        }
        if ctx and ctx.get('store') and ctx.get('run_id'):
            with contextlib.suppress(Exception):
                ctx['store'].record_file(ctx['run_id'], str(node.get('id') or ''), watch['file'], 'biblio_watch')

    if as_bool(params.get('export_files'), True):
        try:
            files = bibliometrics.export_result(result, Config.EXPORT_DIR, f'{label}-{node.get("id") or "biblio"}')
        except Exception as exc:
            raise ValueError(t('biblio.export_failed', err=exc)) from exc
        if ctx and ctx.get('store') and ctx.get('run_id'):
            for kind, path in files.items():
                with contextlib.suppress(Exception):
                    ctx['store'].record_file(ctx['run_id'], str(node.get('id') or ''), path, kind)

    add_log(
        t(
            'biblio.build_done',
            entity=t(f'biblio.entity.{entity}'),
            nodes=summary.get('nodes', len(result.get('rows') or [])),
            edges=summary.get('edges', len(result.get('edges') or [])),
            start=window.get('start', ''),
            end=window.get('end', ''),
        )
    )
    return _json_safe_records(pd.DataFrame(rows))


def _watch_capture(node: dict, ctx: dict | None, params: dict, rows: list, shape: str, entity: str) -> dict | None:
    """File this run's network into a project and diff it against the capture before it.

    ``None`` when the node watches nothing, which is every canvas written before the parameter
    existed. The run record is read for the workflow's name and start moment because a capture
    labelled with an opaque id cannot be read back as a timeline in the panel.
    """
    if not str(params.get('watch_project') or '').strip():
        return None
    from stores import get_biblio_store

    from services import biblio_monitor

    store = (ctx or {}).get('store')
    run_id = str((ctx or {}).get('run_id') or '')
    run_record = store.get_run(run_id) if store and run_id else None
    return biblio_monitor.watch(
        rows,
        params,
        node_id=str(node.get('id') or 'biblio'),
        run_id=run_id,
        workflow_name=str((run_record or {}).get('workflow_name') or ''),
        entity_type=entity,
        shape=shape,
        biblio=get_biblio_store(),
        export_dir=Config.EXPORT_DIR,
        stamp=str((run_record or {}).get('started_at') or ''),
    )


def _watch_totals(diff: dict | None) -> dict:
    """The uncapped counts of the comparison, so the artifact says how much there was even though
    the diff caps what it names."""
    if not diff:
        return {}
    return {
        f'{group}.{key}': int((diff[group][key] or {}).get('total') or 0)
        for group, keys in (
            ('nodes', ('added', 'removed', 'changed')),
            ('edges', ('added', 'removed', 'weight_changed')),
            ('clusters', ('added', 'removed', 'relabeled', 'size_changed')),
            ('bursts', ('added', 'removed', 'strength_changed')),
        )
        for key in keys
    }


def run(node: dict, call: NodeCall) -> list:
    return execute_biblio_node(node, call.current_input, upstream=call.upstream, ctx=call.ctx)
