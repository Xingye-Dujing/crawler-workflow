"""Compile node: assemble the LaTeX from visualize parents and compile it to PDF.

It reads the parents' DICT results in ``upstream`` — a visualize emits no rows, so ``current_input``
arrives empty and is read by nothing. ``emit_latex``/``emit_latex_table`` already guarantee a source
exists (``validate`` refuses a both-off visualize upstream before a run); if nothing arrives anyway —
a parent that failed — refuse BY NAME and never emit an empty PDF.

The PDF is staged under a deterministic per-node name; a downstream ``output`` renames it to the
user's file, and a chain with no output leaves it in the export dir (recorded in the run→files
ledger so 智能清除 can find it).
"""

import contextlib

from core.config import Config
from state import add_log

from i18n import t
from nodes.context import NodeCall
from services.charts import pdf

NODE_TYPE = 'compile'


def execute_compile_node(node: dict, _current_input: list, upstream: list = None, ctx: dict = None):
    docs = []
    sources = []
    for pid, res in upstream or ():
        if not isinstance(res, dict):
            continue
        if 'error' in res:
            return {'error': str(res.get('error'))}
        if res.get('latex'):
            docs.append(res['latex'])
        if res.get('latex_table'):
            docs.append(res['latex_table'])
        sources.append(str(pid))
    if not docs:
        return {'error': t('wf.compile_no_source')}
    out_name = f'compile-{node.get("id")}.pdf'
    out, name = pdf.compile_pdf(pdf.compose_tex(docs), out_name, Config.EXPORT_DIR)
    if 'error' in out:
        # Fold the reason into the returned error so _run_node_durable's single wf.node_failed
        # line carries it; a separate add_log was the duplicate line for one failure.
        out['error'] = t('run.compileFailed', err=out['error'])
        return out
    # Register the staged PDF in the run→files ledger so 智能清除 can find a compile a chain
    # leaves in the export folder with no downstream save. A later output renames it and forgets
    # this name (see nodes/executors/output.py); recording here covers the no-save case, which owns the file.
    if ctx and ctx.get('store') and ctx.get('run_id'):
        with contextlib.suppress(Exception):
            ctx['store'].record_file(ctx['run_id'], str(node.get('id') or ''), name, 'compile')
    add_log(t('run.compileSaved', name=name, size=out.get('pdf_bytes', 0)))
    return {**out, 'sources': sources}


def run(node: dict, call: NodeCall):
    return execute_compile_node(node, call.current_input, upstream=call.upstream, ctx=call.ctx)
