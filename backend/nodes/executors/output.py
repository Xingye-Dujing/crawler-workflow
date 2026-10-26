"""Save node: merge every incoming table into one, export it, and pass it onward.

The merge lives here because a save node is where a user naturally puts it: several batches of
one crawl are the normal reason two nodes are wired into one save, and taking only the FIRST
parent's rows used to export one of them and report success. A PDF save is a different node in
disguise — it compiles the LaTeX a ``visualize`` or ``compile`` parent produced instead of
concatenating rows.
"""

import contextlib
import os

import pandas as pd
from state import _wf_local, add_log

from config import Config
from i18n import t
from nodes.context import NodeCall
from nodes.labels import node_label
from services import latex_compile
from services.exporter import DataExporter, UnsupportedFormatError
from services.run_files import record_file
from services.run_windows import window_for_save
from utils.helpers import as_bool, sanitize_filename

NODE_TYPE = 'output'


def merge_upstream_tables(
    current_input: list,
    upstream: list,
    label: str,
    platform_of: dict | None = None,
    label_of=None,
) -> tuple:
    """Every incoming table as one, or the reason they cannot be one.

    A node with several incoming connections used to take only the FIRST and mention the
    rest in one console line, so wiring three crawls into one save node exported one of
    them and reported success — the shape this project bans everywhere else. The save node
    is the merge point because that is where a user naturally puts it: several batches of
    the same crawl, one file to analyse.

    Two refusals, both about not guessing:

    * a parent whose result is not a table at all — a chart spec or a refusal envelope —
      cannot contribute rows, and skipping it silently would export the others as if the
      canvas had only those;
    * parents whose COLUMN SETS differ are refused rather than passed to ``pd.concat``,
      which answers a mismatch with an outer join: the missing columns come back as NaN
      and the file looks like a complete table with holes in it. A crawler whose columns
      changed between two runs is exactly how that happens, and the reason names the
      columns so the canvas can be fixed.

    A parent with ZERO rows is not a refusal — an empty batch is a real answer, and it is
    reported so the row counts still add up to what was written.

    ``label_of`` turns a parent's id into the console's 「title #id」 the way every other
    message in this file does (``node_label``), defaulting to the bare id for a direct
    caller with no graph in scope: these sentences name THE PARENT — the wire the user has
    to go cut — and 「上游 node-2」 sends them counting boxes to work out which one that was.
    """
    name_parent = label_of if callable(label_of) else (str)
    tables = []
    for pid, result in upstream or ():
        if isinstance(result, list):
            tables.append((str(pid), result))
            continue
        raise ValueError(t('wf.merge_not_tabular', nid=label, up=name_parent(pid)))
    if not tables:
        # No upstream list at all (a direct caller, or a node with no wire): the rows in
        # hand are the whole answer, which is what this node did before merging existed.
        return list(current_input or []), (str(label), len(current_input or []))
    if len(tables) == 1:
        return list(tables[0][1]), (tables[0][0], len(tables[0][1]))

    frames = [(pid, pd.DataFrame(rows)) for pid, rows in tables]
    # Stamp the SOURCE PLATFORM onto every frame, uniformly, BEFORE the column-set comparison:
    # this is what makes a merge of several crawls (the same column schema, different platforms)
    # distinguishable downstream — the 跨平台对比 step reads it. It is strictly ADDITIVE: one new
    # column, added to every frame, so the column-set-equality refusal below still sees matching
    # sets, and no row is reordered or dropped, so the SimHash "row count only holds for this
    # merge order" invariant is untouched. A frame that already names the platform keeps its own
    # spelling (we never overwrite); unknown parents fall back to '' rather than a guess.
    if platform_of is not None:
        for _pid, _frame in frames:
            if 'platform' not in _frame.columns:
                _frame.insert(0, 'platform', str(platform_of.get(str(_pid), '') or ''))
    # The reference columns come from the first frame that HAS any: an empty table answers
    # with no columns at all, and taking its shape as the truth would call every other
    # table's columns "extra".
    reference = next((list(frame.columns) for _pid, frame in frames if len(frame.columns)), [])
    for pid, frame in frames[1:]:
        # A table with ZERO rows has nothing that can disagree — there is no cell to line
        # up — so it is skipped here and contributes nothing to the concatenation. Refusing
        # it would make an honest empty batch look like a misconfigured canvas.
        if len(frame) and set(frame.columns) != set(reference):
            extra = [str(name) for name in frame.columns if name not in reference]
            missing = [str(name) for name in reference if name not in frame.columns]
            raise ValueError(
                t(
                    'wf.merge_columns',
                    nid=label,
                    up=name_parent(pid),
                    extra=', '.join(extra) or '-',
                    missing=', '.join(missing) or '-',
                )
            )
    merged = pd.concat([frame for _pid, frame in frames], ignore_index=True, sort=False)
    # One fragment per upstream table, each built by ``t()`` — the row-count word (行 / rows)
    # belongs to the language catalogue, not to a sentence pasted into the console. Joining with
    # a catalogued separator keeps 中文 the 「、」 list it reads as and English a comma list; a
    # 「」-joined literal once leaked 「…40 行」 into the ENGLISH console line.
    detail = t('wf.merge_detail_sep').join(
        t('wf.merge_table_detail', name=name_parent(pid), n=len(frame)) for pid, frame in frames
    )
    add_log(t('wf.merge_done', nid=label, n=len(merged), tables=len(frames), detail=detail))
    return merged.to_dict('records'), (str(label), len(merged))


def pdf_filename(params: dict) -> str:
    """The final PDF file name from an output node's params: sanitized, extension forced to ``.pdf``.

    Deliberately NOT ``DataExporter.normalize_filename`` — that re-applies a *tabular* extension from its
    whitelist and would turn 「report.pdf」 into 「report.csv」. A PDF's name is its own contract.
    """
    base = os.path.splitext(sanitize_filename(params.get('filename', 'export.pdf')))[0]
    name = f'{base}.pdf'
    if as_bool(params.get('filename_timestamp')):
        name = DataExporter.stamp_filename(name, Config.EXPORT_DIR)
    return name


def output_pdf(node: dict, upstream: list, ctx: dict = None) -> dict:
    """Write the PDF an output node owes when its upstream carries LaTeX (visualize) or an already-compiled
    artifact (compile). Validation guarantees every parent here is one of those two and never mixes them,
    so exactly one source kind is present and ``xelatex`` runs once per chain — never twice.
    """
    params = node.get('params', {})
    docs = []
    staged_pdf = ''
    for _pid, res in upstream or ():
        if not isinstance(res, dict):
            continue
        if 'error' in res:
            # The parent already failed for its OWN named reason; carry that up verbatim rather than
            # inventing a second message for a single failure.
            return {'error': str(res.get('error'))}
        if res.get('pdf_file'):
            staged_pdf = res['pdf_file']
        if res.get('latex'):
            docs.append(res['latex'])
        if res.get('latex_table'):
            docs.append(res['latex_table'])
    filename = pdf_filename(params)
    if staged_pdf:
        # The compile node already produced this (staged in EXPORT_DIR); finalize it under the user's name.
        staged = os.path.join(Config.EXPORT_DIR, staged_pdf)
        try:
            os.replace(staged, os.path.join(Config.EXPORT_DIR, filename))
        except OSError as e:
            return {'error': t('api.compilePdfFailed', err=e)}
        size = os.path.getsize(os.path.join(Config.EXPORT_DIR, filename))
        add_log(t('run.compileSaved', name=filename, size=size))
        record_file(ctx, str(node.get('id') or ''), filename, 'pdf')
        # The compile node recorded the staged name; the rename made that file this one, so drop
        # the stale row rather than leave 智能清除 pointing at a name that no longer exists.
        if ctx and ctx.get('store'):
            with contextlib.suppress(Exception):
                ctx['store'].forget_file(staged_pdf)
        return {'pdf_file': filename, 'pdf_bytes': size}
    if not docs:
        return {'error': t('wf.compile_no_source')}
    out, name = latex_compile.compile_pdf(latex_compile.compose_tex(docs), filename, Config.EXPORT_DIR)
    if 'error' in out:
        return out
    add_log(t('run.compileSaved', name=name, size=out.get('pdf_bytes', 0)))
    record_file(ctx, str(node.get('id') or ''), name, 'pdf')
    return {'pdf_file': name, 'pdf_bytes': out.get('pdf_bytes', 0)}


def execute_output_node(
    node: dict,
    current_input: list,
    upstream: list = None,
    ctx: dict = None,
    platform_of: dict | None = None,
    label_of=None,
):
    """Save node: merges every incoming table, exports it, and passes it downstream.

    'save_csv' is kept as a back-compat alias for older saved workflows;
    both routes go through the same DataExporter used by the standalone
    /api/export/save endpoint, so behaviour is identical whether the save
    happens inside a workflow or on its own.

    It hands ON the merged table rather than the first parent's rows, so a chain of
    analyses may hang off this node and see everything that was written to the file.

    ``ctx`` is the run context (optional): a save written by a run is registered in the
    run→files ledger so 智能清除 can find it; a direct call outside a run writes the file but
    attributes it to no record — which is correct, because none made it.
    """
    params = node.get('params', {})
    op = node.get('operation', params.get('operation', ''))
    # PDF is not a tabular export: when the format is pdf the node compiles the LaTeX its upstream
    # visualize / compile produced (see output_pdf) and never reaches the row merge below, which would
    # refuse a dict upstream with wf.merge_not_tabular.
    _fmt = str(params.get('format') or DataExporter.infer_format(params.get('filename', '')) or '').lower()
    if op in ('save', 'save_csv') and _fmt == 'pdf':
        return output_pdf(node, upstream, ctx=ctx)
    if not current_input and not upstream:
        return []

    merged_rows, _ = merge_upstream_tables(
        current_input,
        upstream,
        node_label(node, node.get('id', '')),
        platform_of=platform_of,
        label_of=label_of,
    )
    if not merged_rows:
        return []

    df = pd.DataFrame(merged_rows)

    if op in ('save', 'save_csv'):
        fmt = params.get('format', 'csv' if op == 'save_csv' else None)
        filename = params.get('filename', 'export.csv')
        fmt = fmt or DataExporter.infer_format(filename)
        # Sanitize first, then (re)apply the extension: the other way round a
        # name like ".." lost its extension and landed as a hidden file.
        filename = DataExporter.normalize_filename(sanitize_filename(filename), fmt)
        # The stamp is resolved here and never written back into ``params``,
        # because a run-time value inside a node's parameters would change its
        # fingerprint on every attempt: 继续 could not recognise the node, every
        # LLM cache key would miss and a renamed chain would re-crawl.
        #
        # One limitation this trades away, stated so it is not discovered later:
        # on 继续 an output node whose stored rows still match its fingerprint is
        # *restored*, so this line never runs and no second file appears. Re-running
        # for a new timestamp means re-running the chain it writes out of.
        if as_bool(params.get('filename_time_range')):
            # Which stretch of the calendar this table covers is a fact about the CRAWL,
            # and a save node is handed only rows — so the window is whatever this run's
            # crawl nodes recorded (``note_window``). Zero of them and two different ones
            # are both refusals stated by name: a file called 「January」 that holds March
            # is worse than a file that was never written, and the name is the thing being
            # chosen here.
            tag, refusal = window_for_save(getattr(_wf_local, 'idx', None))
            if refusal:
                # A time range in the filename is decoration, never a reason to withhold the
                # file. When the upstream crawl carried no single honest window (none, or two
                # different ones), ignore the checkbox and export under the plain name — the
                # user still gets their data and only the name loses the tag. Refusing here
                # (the old behaviour) threw away the whole result over a label nobody needed.
                add_log(t('export.window_ignored', nid=node_label(node, str(node.get('id') or '')), reason=refusal))
            else:
                filename = DataExporter.tagged_filename(filename, tag)
        if as_bool(params.get('filename_timestamp')):
            filename = DataExporter.stamp_filename(filename, Config.EXPORT_DIR)
        filepath = os.path.join(Config.EXPORT_DIR, filename)
        try:
            DataExporter.save(df, filepath, fmt=fmt, text_column=params.get('text_column'))
        except UnsupportedFormatError as e:
            # Refused, and the reason travels: the executor prints it as this node's
            # failure with the node's own label. A second add_log here said the same
            # sentence again, unattributed — the version the user could not act on.
            return {'error': str(e)}
        record_file(ctx, str(node.get('id') or ''), filename, 'export')
        # No "data saved to <path>" line: the exporter has already announced
        # "exported N rows to <path> (fmt)" one line above, and saying the same
        # fact twice in two wordings is two chances to word them differently.

    return merged_rows


def run(node: dict, call: NodeCall):
    # ``upstream`` reaches it so several incoming tables become ONE: a crawl split over several
    # batches is the normal reason a user wires two nodes into a save node, and taking only the
    # first exported one of them as if it were all of them. ``platform_of`` (parent id → crawled
    # platform, built by the run loop where the node graph is in scope) lets the merge stamp which
    # rows came from which platform; it is None for a direct caller, which then sees exactly the
    # pre-stamp merge shape.
    return execute_output_node(
        node,
        call.current_input,
        upstream=call.upstream,
        ctx=call.ctx,
        platform_of=call.platform_of,
        label_of=call.label_of,
    )
