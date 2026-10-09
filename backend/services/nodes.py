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

import pandas as pd
from api.http import _safe_int
from state import add_log

from config import Config
from i18n import t
from services import latex_compile
from services.run_store import RUN_RUNNING
from services.visualizer import VisualizationService


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


def _tokenize_dataframe(df: pd.DataFrame, params: dict) -> pd.DataFrame | None:
    """Apply tokenization to a DataFrame and return the result, or None if the
    column is missing."""
    column = params.get('text_column', '')
    if column not in df.columns:
        return None
    output_mode = str(params.get('output_mode') or 'word_freq').strip()
    top_n = params.get('top_n', '')
    # One of the three shapes, refused by name otherwise: the last branch of this
    # function is 词频+次数, so an unrecognised mode used to produce that table and the
    # console then announced the name the caller had written — a log line describing a
    # shape the file does not have.
    if output_mode not in ('word_freq', 'words_only', 'csv_line'):
        raise ValueError(
            t(
                'analysis.bad_option',
                op='tokenize',
                param='output_mode',
                value=output_mode,
                allowed='word_freq, words_only, csv_line',
            )
        )
    kwargs = {}
    if output_mode == 'word_freq' and top_n:
        kwargs['top_n'] = _safe_int(top_n, 120, minimum=1)
    labels, values = VisualizationService.tokenize_frequency(df, column, **kwargs)
    if not labels:
        return pd.DataFrame()
    if output_mode == 'words_only':
        return pd.DataFrame([{'word': w} for w in labels])
    if output_mode == 'csv_line':
        return pd.DataFrame([{'words': ' '.join(labels)}])
    return pd.DataFrame([{'word': w, 'frequency': v} for w, v in zip(labels, values, strict=True)])


def execute_tokenize_node(node: dict, current_input: list):
    """Tokenize node: segments a free-text column with jieba and outputs
    word-frequency pairs for downstream save or word-cloud nodes.
    Data always comes from the upstream connection — a file reaches it by
    sitting behind an Upload node, not by being configured here."""
    params = node.get('params', {})
    column = params.get('text_column', '')
    output_mode = params.get('output_mode', 'word_freq')
    # Every refusal below RAISES rather than returning []. An empty list settles the
    # node DONE, so the run read green, the export held only a header, and the one
    # sentence that explained it carried no node name — the user had to guess which
    # box was broken. Raising hands the reason to the executor, which fails THIS node
    # and prints the label with it.
    if not column:
        raise ValueError(t('wf.tokenize_no_column'))
    if not current_input:
        raise ValueError(t('wf.tokenize_no_input'))
    df = pd.DataFrame(current_input)
    result_df = _tokenize_dataframe(df, params)
    if result_df is None:
        raise ValueError(t('wf.tokenize_no_col', col=column, cols=list(df.columns)))
    add_log(t('wf.tokenize_done', mode=output_mode, col=column, n=len(result_df)))
    return result_df.to_dict('records')


def execute_resume_node(node: dict, ctx: dict):
    """Adopt a stored node output from an earlier run as this node's rows.

    This is the node you drop in when the original source is no longer
    co-operating — logged out, blocked, expensive — but its rows are already
    paid for and sitting in runs.db. It replaces nothing upstream: whatever it
    produces flows onward exactly as the original node's output would have.

    The store arrives through ``ctx`` (the run passes its own ledger), so this
    executor reads no store singleton directly — it is pure against ``ctx``.
    """
    store = ctx['store']
    params = node.get('params') or {}
    run_id = str(params.get('resume_run_id') or '').strip()
    node_id = str(params.get('resume_node_id') or '').strip()
    limit = _safe_int(params.get('resume_limit'), 0, minimum=0)

    if not run_id:
        # Nothing picked yet: fall back to the newest unfinished run of THIS
        # workflow's shape. Without the fingerprint filter a 'node-2' from an
        # unrelated workflow — the id repeats in every canvas — would be
        # adopted wholesale; and the run currently writing must not feed itself.
        candidates = [
            r
            for r in store.list_resumable(str(ctx.get('wf_fp') or '') or None, limit=5)
            if r.get('run_id') != ctx.get('run_id') and r.get('status') != RUN_RUNNING
        ]
        if not candidates:
            add_log(t('resume.no_run'))
            return []
        run_id = str(candidates[0].get('run_id') or '')

    def _adopted_label(nid: str) -> str:
        """The node being adopted, named the way the console names everything.

        ``node_label`` cannot help here: that node lives in another run's record, not
        on this canvas. But a bare ``node-2`` is just as unreadable, and the row it is
        about to hand over carries the title its own run stored — so the same
        「标题 #id」 form is available, and a run of a dozen nodes can be told apart.
        """
        if not nid:
            return t('resume.unpicked')
        state = store.node_statuses(run_id).get(nid) or {}
        title = str(state.get('title') or '').strip()
        return f'{title} #{nid}' if title and title != nid else nid

    rows = store.load_rows(run_id, node_id) if node_id else []
    if not rows:
        # No node picked (or the pick holds nothing): take the fullest one.
        statuses = store.node_statuses(run_id)
        best = max(statuses.values(), key=lambda n: int(n.get('row_count') or 0), default=None)
        if best and int(best.get('row_count') or 0) > 0:
            node_id = str(best.get('node_id') or '')
            rows = store.load_rows(run_id, node_id)
    if not rows:
        add_log(t('resume.empty', rid=run_id, nid=_adopted_label(node_id)))
        return []
    if limit and len(rows) > limit:
        rows = rows[:limit]
    add_log(t('resume.loaded', rid=run_id, nid=_adopted_label(node_id), n=len(rows)))
    return rows
