"""One compilable document from a finished run: figures, three-line tables, and the method that
produced them.

The HTML report answers "what happened in this run?". This answers the next question, the one a
researcher actually has to answer on paper: a numbered figure and table per chart, and a 方法 section
that states the parameters, the algorithms and the provenance — in the same words the run record and
the exported CSVs use, so a reviewer can check one against the other.

Three rules, inherited from the rest of the LaTeX pipeline:

* **Only what the run filed.** A figure enters this document because its node registered a LaTeX
  source under this run id. Nothing is re-rendered here, so the paper's figure and the preview's
  figure cannot drift apart, and a chart whose LaTeX was never asked for is reported as missing
  rather than silently skipped.
* **The method text is read from the SAVED canvas and checked against the run's own fingerprints**,
  exactly like the snapshot capture. A methods section that describes settings nobody ran is the
  most expensive kind of fabrication in this document.
* **Nothing is invented.** An empty section says it is empty; a parameter the canvas no longer holds
  is reported as unverified; a value is printed as the app's own token, because that is what the
  reader will find in the export.
"""

from __future__ import annotations

import os

from i18n import t
from services.latex_charts import LatexChartService, esc, paper_preamble
from services.workflows.manager import WorkflowManager

#: The parameter names a method section quotes, in the order a reader meets them. Values stay the
#: app's own tokens (``top_n``, ``cosine``, ``mst``) because those are what the run record and the
#: exported tables carry, and a translation here would be a fourth spelling of the same setting.
BIBLIO_METHOD_PARAMS = (
    'entity_type',
    'output_shape',
    'slice_years',
    'look_back_years',
    'selection',
    'top_n',
    'top_pct',
    'g_index',
    'threshold_c',
    'threshold_cc',
    'threshold_ccv',
    'counting',
    'link_measure',
    'lrf',
    'max_links_per_node',
    'pruning',
    'pruning_scope',
    'pathfinder_r',
    'pathfinder_lmax',
    'pathfinder_dmax',
    'citation_expansion',
    'largest_component',
    'cluster',
    'label_method',
    'burst',
    'variation',
    'watch_project',
)


#: The widest box this project's own LaTeX writer emits: a bibliometric figure is a 17.5 cm minipage
#: (picture + its formulas). A4 is 21 cm wide, so the margins below are what leaves room for it —
#: tighten them and every figure in the paper shrinks its fonts instead of its page.
WIDEST_BODY_CM = 17.5
PAGE_MARGIN_CM = 1.5

#: A4 with those margins gives 21 - 2 x 1.5 = 18 cm of text, which holds the widest body above.
TEXTWIDTH_CM = 21.0 - 2 * PAGE_MARGIN_CM

#: Shrink-to-fit, and only shrink. A pasted figure brings its own 17.5 cm minipage and a three-line
#: table is as wide as its columns demand — the 聚类标签 column alone can run past 25 cm. On the first
#: compile the reader got a PDF with the last column cut off and the picture hanging off the page.
#: Enlarging is refused on purpose: a two-column table stretched to the full text block is worse than
#: a narrow one, and re-laying-out a figure here would be a second opinion about the figure itself.
_FIT = '\\newcommand{\\cixifit}[1]{\\resizebox{\\ifdim\\width>\\textwidth\\textwidth\\else\\width\\fi}{!}{#1}}\n'


#: Rows per table block. A `tabular` cannot break across a page, and a 50-row three-line table ran
#: 2.6 cm past the bottom of the sheet on the first compile; at \\footnotesize with the preamble's
#: `\\arraystretch{1.25}` a page holds ~44, so a block is deliberately shorter than a full page — the
#: section heading, the caption and whatever shrink-to-fit did to the row height all come off it too.
TABLE_ROWS_PER_BLOCK = 26


def _read(path: str) -> str:
    try:
        with open(path, encoding='utf-8') as handle:
            return handle.read()
    except OSError:
        return ''


def _body(document: str) -> str:
    """The inside of one of this project's own standalone sources, ready to re-wrap in a numbered block."""
    if not document:
        return ''
    try:
        return LatexChartService.strip_shell(document)
    except IndexError:
        # Not a document this service wrote (a hand-edited .txt in the export folder, say). Quoting
        # it raw would put a stray \begin{document} in the middle of the paper.
        return ''


def _block(body: str, *, table: bool, caption: str, label: str) -> str:
    r"""One numbered item, kept in the order the run produced it.

    ``[H]`` (float package) — a float that is not allowed to move. A plain ``figure``/``table`` lets TeX
    carry the item past the section the reader is in, and the first compile produced a page holding
    nothing but the heading 「图表」 while the pictures drifted away. ``[H]`` keeps the reading order
    图 1, 表 1, 图 2, 表 2 exactly as built; a too-tall item is cut into page-sized blocks first, since
    ``[H]`` refuses to move and would otherwise run past the bottom of the sheet.

    A table's caption sits above the tabular and a figure's below its picture — the paper convention
    this project's three-line tables are written for.
    """
    if not body:
        return ''
    if table:
        blocks = _table_blocks(body, caption=caption, label=label)
        if blocks:
            return blocks
    kind = 'table' if table else 'figure'
    captioned = f'\\caption{{{caption}}}\n\\label{{{label}}}\n'
    return (
        _float(kind, captioned + f'\\cixifit{{{body}}}\n')
        if table
        else _float(kind, f'\\cixifit{{{body}}}\n' + captioned)
    )


def _float(kind: str, inner: str) -> str:
    return f'\\begin{{{kind}}}[H]\n\\centering\n{inner}\\end{{{kind}}}\n'


def _split_table(body: str):
    r"""``(prefix, spec, header, rows, suffix)`` of one of our own three-line tables, else ``None``.

    This splits OUR emission rather than parsing arbitrary LaTeX: ``_tabular`` writes exactly one row
    per line between ``\midrule`` and ``\bottomrule``, so a line is a row even when a cell's text
    carries an escaped backslash. Anything that is not that shape yields ``None`` and is pasted
    unchanged — a hand-edited .txt in the export folder must not be cut up into a broken table.
    """
    open_marker = '\\begin{tabular}{'
    start = body.find(open_marker)
    if start < 0:
        return None
    spec_end = body.find('}', start + len(open_marker))
    close = body.find('\\end{tabular}', spec_end)
    if spec_end < 0 or close < 0:
        return None
    middle = body[spec_end + 1 : close]
    if '\\toprule' not in middle or '\\midrule' not in middle:
        return None
    head_part, row_part = middle.split('\\midrule', 1)
    lines = [line for line in row_part.split('\n') if line.strip()]
    if not lines or lines[-1].strip() != '\\bottomrule':
        # The closing rule must be alone on its line. A hand-edited body that shares a line with it
        # would come back with a second \\bottomrule pasted after the chunk, and a table that grows
        # its own rules is not something to cut up.
        return None
    head = [line for line in head_part.split('\n') if line.strip()]
    rows = lines[:-1]
    if not head or not rows:
        return None
    return body[:start], body[start + len(open_marker) : spec_end], head, rows, body[close + len('\\end{tabular}') :]


def _table_blocks(body: str, *, caption: str, label: str) -> str:
    r"""A table too long for a page, cut into page-sized blocks with its header repeated.

    Only the first block is numbered: a continued table carries ``\\caption*`` (caption package), because
    two numbers for one table is a citation a reader cannot point at. Every row survives the cut — the
    row count the paper quotes is the row count the run stored.
    """
    parts = _split_table(body)
    if not parts:
        return ''
    prefix, spec, head, rows, suffix = parts
    if len(rows) <= TABLE_ROWS_PER_BLOCK:
        # It fits a page as it is; do not touch what does not need touching.
        return ''
    out = []
    for index in range(0, len(rows), TABLE_ROWS_PER_BLOCK):
        chunk = rows[index : index + TABLE_ROWS_PER_BLOCK]
        tabular = (
            f'{prefix}\\begin{{tabular}}{{{spec}}}\n'
            + '\n'.join(head)
            + '\n\\midrule\n'
            + '\n'.join(chunk)
            + f'\n\\bottomrule\n\\end{{tabular}}{suffix}'
        )
        titled = (
            f'\\caption{{{caption}}}\n\\label{{{label}}}\n'
            if index == 0
            else f'\\caption*{{{caption}{t("report.table_continued")}}}\n'
        )
        out.append(_float('table', titled + f'\\cixifit{{{tabular}}}\n'))
    return '\n'.join(out)


def _method_lines(run: dict, nodes: list) -> list[str]:
    """One line per node that shaped the analysis, from the canvas the run actually used."""
    manager = WorkflowManager()
    workflow_name = str(run.get('workflow_name') or '')
    lines: list[str] = []
    unverified: list[str] = []
    for entry in nodes:
        node_id = str(entry.get('node_id') or '')
        node_type = str(entry.get('node_type') or '')
        title = str(entry.get('title') or node_id)
        params, verified = manager.captured_params(workflow_name, node_id, str(entry.get('fingerprint') or ''))
        if not params:
            continue
        if not verified:
            unverified.append(title)
        if node_type == 'biblio':
            entity = str(params.get('entity_type') or '')
            words = [f'{key}={params[key]}' for key in BIBLIO_METHOD_PARAMS if params.get(key) not in (None, '')]
            lines.append(
                t('report.method_biblio', title=title, entity=t(f'biblio.entity.{entity}'), body='；'.join(words))
            )
        elif node_type == 'fuse':
            lines.append(t('report.method_fuse', title=title))
        elif node_type == 'analysis':
            steps = params.get('steps') or [{'op': params.get('operation') or ''}]
            ops = '→'.join(str(step.get('op') or '') for step in steps if isinstance(step, dict) and step.get('op'))
            if ops:
                lines.append(t('report.method_analysis', title=title, ops=ops))
        elif node_type == 'source':
            lines.append(
                t(
                    'report.method_source',
                    title=title,
                    platform=str(params.get('platform') or ''),
                    collect=str(params.get('collect') or ''),
                    target=params.get('target_count') or '',
                )
            )
        elif node_type == 'upload':
            lines.append(t('report.method_upload', title=title, name=str(params.get('dataset_name') or '')))
    if unverified:
        lines.append(t('report.method_unverified', names='、'.join(unverified[:6])))
    if not lines:
        # No canvas file (an inline-submitted run), or nothing but name/upload nodes on it. The
        # section still exists and says what it is missing — a paper that silently has no method
        # reads as a method nobody wrote down.
        lines.append(t('report.method_no_canvas'))
    return lines


def build_document(
    entries: list[dict], *, title: str, meta: dict, methods: list[str], missing: list | None = None
) -> str:
    """An ``article`` + ``ctex`` document: title, method section, then every figure with its table
    beside it, in the order the run produced them.

    ``missing`` names the chart nodes that filed no LaTeX source. They are not invented here, and they
    are not dropped either: a paper that quietly has two figures where the run drew five reads as if
    the other three never existed.
    """
    head = (
        '% 采析绘 论文成稿（LaTeX）——由一次运行的已登记图与三线表合成，用 xelatex 编译\n'
        '\\documentclass[12pt]{article}\n'
        # The same preamble every pasted body was written against. Repeating a package list here
        # would be a second opinion about the figures' own colours and styles, and the first
        # `\draw[cA,...]` would die with `Undefined color`.
        + paper_preamble()
        + '\\usepackage{graphicx}\n'
        + f'\\usepackage[a4paper,margin={PAGE_MARGIN_CM}cm]{{geometry}}\n'
        '\\usepackage{caption}\n\\captionsetup{font=small}\n'
        # ``[H]``: the float placement that means "here, and nowhere else". See ``_block``.
        + '\\usepackage{float}\n'
        + _FIT
        + '\\title{'
        + esc(title or '')
        + '}\n\\date{}\n\\begin{document}\n\\maketitle\n'
    )
    blocks: list[str] = []
    if methods:
        blocks.append(
            '\\section*{' + esc(t('report.method_section')) + '}\n' + '\n\n'.join(esc(line) for line in methods) + '\n'
        )
    provenance = [
        t('report.method_provenance', workflow=meta.get('workflow') or '—', run_id=meta.get('run_id') or '—'),
        t('report.method_window', started=meta.get('started') or '—', finished=meta.get('finished') or '—'),
        t('report.method_counts', figures=meta.get('figures', 0), tables=meta.get('tables', 0)),
    ]
    if missing:
        provenance.append(
            t('report.missing_charts', count=len(missing), names='、'.join(str(name) for name in missing[:6]))
        )
    blocks.append('\\vspace{6pt}\n' + '\n\n'.join(esc(line) for line in provenance) + '\n')
    blocks.append('\\clearpage\n\\section{' + esc(t('report.figure_section')) + '}\n')
    items = 0
    for index, entry in enumerate(entries, start=1):
        caption = esc(entry['caption'])
        figure = _block(_body(entry.get('figure')), table=False, caption=caption, label=f'fig:cixi-{index}')
        table = _block(
            _body(entry.get('table')),
            table=True,
            caption=caption + t('report.table_suffix'),
            label=f'tab:cixi-{index}',
        )
        if not figure and not table:
            continue
        items += 1
        # The figure and its three-line table are put next to each other, not in a shared box: a
        # picture and a wide table together are often taller than a page, and a box that cannot be
        # broken overflows it silently. Adjacent items in reading order is what the reader wants.
        blocks.append(figure + table)
    if not items:
        # A document of nothing but a title and a heading would compile, and a reader would call it
        # the paper. The caller refuses instead.
        return ''
    return head + '\n'.join(blocks) + '\n\\end{document}\n'


def generate(run_id: str, *, title: str, store, export_dir: str) -> dict:
    """Assemble, compile and register the paper document for one run.

    Returns ``{'tex_file','pdf_file','figures','tables'}``, or ``{'error': …}`` — a missing run, a
    run that filed no LaTeX, or a compiler that refused. Never a half document.
    """
    run = store.get_run(run_id) if run_id else None
    if run is None:
        return {'error': t('report.latex_no_run', rid=run_id or '(empty)')}
    files = store.files_for_run(run_id)
    by_node: dict[str, dict] = {}
    for entry in files:
        kind = str(entry.get('kind') or '')
        if kind not in ('latex', 'latex_table'):
            continue
        node_id = str(entry.get('node_id') or '')
        slot = by_node.setdefault(node_id, {})
        slot['figure' if kind == 'latex' else 'table'] = _read(os.path.join(export_dir, str(entry.get('name') or '')))
        slot.setdefault('name', str(entry.get('name') or ''))
    nodes = list(run.get('nodes') or [])
    titles = {str(node.get('node_id')): str(node.get('title') or node.get('node_id') or '') for node in nodes}
    entries = []
    for node_id, slot in by_node.items():
        caption = titles.get(node_id) or node_id
        entries.append(
            {
                'figure': slot.get('figure') or '',
                'table': slot.get('table') or '',
                'caption': caption,
            }
        )
    entries.sort(key=lambda item: item['caption'])
    # A chart node that ran but filed nothing is not a gap in the paper — it is a gap the paper names.
    filed = {str(node_id) for node_id, slot in by_node.items() if slot.get('figure') or slot.get('table')}
    missing = [
        str(node.get('title') or node.get('node_id') or '')
        for node in nodes
        if str(node.get('node_type') or '') == 'visualize' and str(node.get('node_id') or '') not in filed
    ]
    figures = sum(1 for entry in entries if entry['figure'])
    tables = sum(1 for entry in entries if entry['table'])
    if not figures and not tables:
        return {'error': t('report.latex_no_sources', rid=run_id)}

    methods = _method_lines(run, nodes)
    document = build_document(
        entries,
        title=title or str(run.get('workflow_name') or ''),
        meta={
            'workflow': str(run.get('workflow_name') or ''),
            'run_id': run_id,
            'started': str(run.get('started_at') or ''),
            'finished': str(run.get('finished_at') or ''),
            'figures': figures,
            'tables': tables,
        },
        methods=methods,
        missing=missing,
    )
    if not document:
        return {'error': t('report.latex_no_sources', rid=run_id)}

    from services import latex_compile

    stem = 'report-' + ''.join(ch for ch in run_id if ch.isalnum())[:12]
    tex_name = f'{stem}.tex'
    # The source is written BEFORE the compiler runs: it is a deliverable in its own right (the
    # reader pastes it into their paper), and when xelatex refuses, the file that would have
    # compiled is the only thing left to debug from.
    with open(os.path.join(export_dir, tex_name), 'w', encoding='utf-8') as handle:
        handle.write(document)
    result, name = latex_compile.compile_pdf(document, f'{stem}.pdf', export_dir)
    if result.get('error'):
        return {'error': result['error'], 'tex_file': tex_name}
    return {'pdf_file': name, 'tex_file': tex_name, 'figures': figures, 'tables': tables}
