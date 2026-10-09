"""Workflow node executors — the A-4 sequence that moves ``_execute_*_node`` out of ``app.py``.

``app.py`` is the HTTP layer plus, historically, the whole node-execution subsystem. This module
takes the executors one at a time so ``app.py`` stops growing every time an analyzer or chart type
is added. Each executor is imported back into ``app.py`` **under its original ``_execute_*_node``
name** (``from services.nodes import execute_name_node as _execute_name_node``), so ``_execute_node``'s
dispatch table and any test that pokes the app-module symbol are unaffected — the function just
lives here now. Executors depend only on their arguments (node/current_input/upstream/run_ctx/ctx)
plus the shared services/engine modules; anything still reaching a raw ``app``-module global is a
reason to keep that executor in ``app.py`` until the seam is ready, not to import it half-moved.

First slice: ``execute_name_node`` — the metadata node, the most self-contained executor (pure:
takes the node dict, returns no rows), so it proves the pattern with zero behaviour change.
"""

from state import add_log

from config import Config
from i18n import t
from services import latex_compile


def execute_name_node(node: dict) -> list:
    """The name node is metadata, not data: its label was already lifted into
    ``workflow_name`` before the run started (so the history panel can group by
    it). It produces no rows — downstream source/upload nodes read nothing
    from their inputs, which is exactly why the node must connect to one."""
    return []


def execute_compile_node(node: dict, current_input: list, upstream: list = None, ctx: dict = None):
    """Compile node: read the LaTeX one or more ``visualize`` parents produced — from their DICT results in
    ``upstream``, because a visualize emits no rows so ``current_input`` is empty here — assemble it into
    ONE document, and compile it to a staged PDF with the user's MiKTeX.

    ``emit_latex``/``emit_latex_table`` already guarantee a source exists (``validate`` refuses a both-off
    visualize upstream before a run); if nothing arrives anyway — a parent that failed — refuse BY NAME and
    never emit an empty PDF. The PDF is staged under a deterministic per-node name; a downstream ``output``
    renames it to the user's file, and a chain with no output simply leaves it in the export dir.
    """
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
    out, name = latex_compile.compile_pdf(latex_compile.compose_tex(docs), out_name, Config.EXPORT_DIR)
    if 'error' in out:
        add_log(t('run.compileFailed', err=out['error']))
        return out
    add_log(t('run.compileSaved', name=name, size=out.get('pdf_bytes', 0)))
    return {**out, 'sources': sources}
