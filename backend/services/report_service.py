"""One-click HTML report for a workflow run.

A run produces tables; the user's next question is always "and what do I show
someone?". The answer used to be a CSV and a screenshot. This module turns the
tables a run settled into into one self-contained ``.html`` file — inline CSS,
charts rendered server-side to base64 PNG — so it opens offline, survives being
emailed, and prints.

Three rules shape it:

* **Nothing is invented.** Every number comes from the rows, and a table that is
  only partly shown says how many rows are missing. An empty section says it is
  empty rather than being dropped, because a dropped section reads as a bug.
* **Nothing untrusted reaches the markup raw.** The tables hold text crawled
  from the internet; one ``<script>`` in a Zhihu answer would otherwise run in
  the browser of whoever opens the report. Every value goes through
  :func:`html.escape`.
* **A chart that cannot be drawn must not kill the report.** Matplotlib raises
  on negative pie values and on all-null columns; each chart is tried on its
  own and its failure becomes one line of text.
"""

import base64
import html
import logging
import os
import re
import time

import pandas as pd

from analyzers.llm_client import ABORT_MARK
from i18n import t
from services.export_browser import resolve_export_file
from services.exporter import DataExporter
from services.visualizer import VisualizationService, _localize_label

logger = logging.getLogger(__name__)

#: Rows of each node table printed in full. The rest is summarised, not hidden
#: silently — a report that shows 20 of 5 000 rows has to say so.
MAX_TABLE_ROWS = 20
#: Charts cost a matplotlib figure each; past this the report is a picture book.
MAX_CHARTS = 6
#: Columns whose value counts are the point of the report.
CATEGORY_COLUMNS = ('emotion', 'tendency', 'label', 'cluster')
#: Numeric columns that are bookkeeping rather than measurement. An entity
#: table's ``row``/``start``/``end`` are offsets into the source text, and a
#: histogram of those is a picture of where the crawler happened to find
#: something — it fills the report with charts that look informative and say
#: nothing, which is worse than having fewer charts.
POSITION_COLUMNS = frozenset({'row', 'start', 'end'})
#: A cell longer than this is trimmed for reading; the CSV export stays whole.
MAX_CELL_CHARS = 300
_SAFE_STEM = re.compile(r'[^0-9A-Za-z_\u4e00-\u9fa5.-]+')

#: The optional parts of a report, every switch on by default. A request body
#: that names nothing still produces the whole document: losing a section to a
#: field the writer could not read is worse than showing one the user meant to
#: hide, so the fallback is always "include it", never "drop it".
DEFAULT_OPTIONS = {
    'show_charts': True,
    'show_tables': True,
    'show_facts': True,
    'show_conclusion': True,
    'max_rows': None,
    'node_ids': None,
    'images': None,
}
#: The row cap the panel may raise to, and the floor it may drop to. Both bound
#: a runaway request: one node's whole table printed as markup is a document no
#: one can open, and zero rows printed is a document with a heading and nothing
#: under it.
MIN_TABLE_ROWS = 1
MAX_TABLE_ROWS_CAP = 5000
#: Extensions a report may inline as a picture. A name is handed to the report
#: from the export listing, and the listing holds CSVs and pages too; only an
#: image that resolves inside the export directory is ever read as bytes.
INLINE_IMAGE_EXT = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.gif'})
_MIME_BY_EXT = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
}


def _as_str_list(value):
    """A list of strings from a value that may be a list, one string, or nothing.

    ``None`` (the caller named nothing) stays ``None`` so the caller can tell
    "everything" from "an explicit empty selection"; a browser that sends a
    single id instead of a one-item list is normalised here rather than raising.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item or '').strip()]
    return None


def _normalize_options(options) -> dict:
    """The caller's switches over :data:`DEFAULT_OPTIONS`, tolerating odd input.

    The booleans, the row cap and the two lists are all read here so each reader
    downstream can trust the shape: a report is a deliverable, and it must not
    abort because a stray ``'7'`` arrived where an int belongs.
    """
    opts = dict(DEFAULT_OPTIONS)
    if isinstance(options, dict):
        opts.update(options)
    for key in ('show_charts', 'show_tables', 'show_facts', 'show_conclusion'):
        opts[key] = True if opts.get(key) is None else bool(opts.get(key))
    try:
        limit = int(opts['max_rows']) if opts['max_rows'] not in (None, '') else MAX_TABLE_ROWS
    except (TypeError, ValueError):
        limit = MAX_TABLE_ROWS
    opts['max_rows'] = max(MIN_TABLE_ROWS, min(limit, MAX_TABLE_ROWS_CAP))
    opts['node_ids'] = _as_str_list(opts.get('node_ids'))
    opts['images'] = _as_str_list(opts.get('images'))
    return opts


def safe_stem(name: str, fallback: str = 'report') -> str:
    """A filename stem that cannot escape the export directory.

    The report's title is whatever the user typed into the dialog, so it is
    cleaned the same way every other exported name is: separators and dot-runs
    collapse, and a name that survives as nothing falls back to a default.
    """
    stem = _SAFE_STEM.sub('_', str(name or '').strip()).strip('._')
    return stem[:60] or fallback


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    return str(value)


def _cell(value) -> str:
    """One table cell, trimmed and escaped."""
    text = _text(value).replace('\n', ' ').strip()
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + '…'
    return html.escape(text, quote=True)


def _numeric_columns(df: pd.DataFrame) -> list:
    """Columns that are numbers in the pandas sense, not merely numeric text.

    The position bookkeeping columns are dropped here rather than at each
    reader, because both of them — the chart picker and the model's digest —
    would otherwise have to remember the same rule (see POSITION_COLUMNS).
    """
    picked = []
    for name in df.columns:
        if str(name) in POSITION_COLUMNS:
            continue
        if pd.api.types.is_numeric_dtype(df[name]):
            picked.append(str(name))
    return picked


def _category_columns(df: pd.DataFrame) -> list:
    return [name for name in CATEGORY_COLUMNS if name in set(map(str, df.columns))]


def build_conclusion_prompt(summary: str, lang: str = 'zh') -> str:
    """Ask for a closing paragraph about the run, from its counts only.

    The instruction says what may not be done as much as what should: a model
    given a summary of numbers will happily invent the story behind them, and
    this text lands in a document someone else will trust.
    """
    language = '中文' if (lang or 'zh').startswith('zh') else 'English'
    return (
        'You are writing the closing section of a data-collection report.\n'
        f'Write 2-4 sentences in {language} describing what the numbers below show: how much was\n'
        'collected, and which categories or values dominate.\n'
        'Stay inside these numbers. Do not explain why they are that way, do not predict anything,\n'
        'and do not invent entities, dates or causes that are not listed. No heading, no bullet list.\n'
        '\nCollected data:\n' + summary + '\n'
    )


def summarize(nodes: list, top: int = 5) -> str:
    """A plain-text digest of the run, for the optional model-written conclusion.

    Deliberately no row dumps: the conclusion is about the shape of the data
    (how many rows, which categories dominate), and sending thousands of crawled
    sentences would cost the request without saying anything the counts do not.
    """
    lines = []
    for entry in nodes:
        rows = entry.get('rows') or []
        title = _text(entry.get('title')) or _text(entry.get('id'))
        lines.append(f'- {title}: {len(rows)} rows')
        if not rows:
            continue
        df = pd.DataFrame(rows)
        for column in _category_columns(df):
            counts = df[column].dropna().astype(str).value_counts().head(top)
            if counts.empty:
                continue
            joined = ', '.join(f'{name}×{int(how_many)}' for name, how_many in counts.items())
            lines.append(f'    {column}: {joined}')
        for column in _numeric_columns(df)[:3]:
            values = pd.to_numeric(df[column], errors='coerce').dropna()
            if not values.empty:
                lines.append(f'    {column}: min {values.min():g}, mean {values.mean():g}, max {values.max():g}')
    return '\n'.join(lines)


class ReportService:
    """Builds and writes the report. Stateless apart from its output directory."""

    def __init__(self, export_dir: str):
        self.export_dir = export_dir

    # ── charts ──────────────────────────────────────────────────

    def _charts(self, frames: list) -> list:
        """Every chart the run's tables justify, as ``(title, data_uri)``.

        Category columns become share-of-total bars; numeric columns become
        histograms. Which columns qualify is decided per table, so a run whose
        entity node and emotion node both produced something shows both.
        """
        charts = []
        for entry in frames:
            df = entry['frame']
            title = entry['title']
            if df.empty or len(df) < 2:
                continue
            for column in _category_columns(df):
                if len(charts) >= MAX_CHARTS:
                    break
                counts = df[column].dropna().astype(str).value_counts()
                # The 未处理 marker is a gap in the run, not a category: drawing
                # it as one would put a bar on the chart that reads as an answer.
                counts = counts[~counts.index.str.lower().isin((ABORT_MARK.lower(), 'nan'))]
                if len(counts) < 2 or len(counts) > 12:
                    # A dozen slices is unreadable, and one distinct value is
                    # already stated by the number itself.
                    continue
                counts.name = column
                charts.append((f'{title} · {_localize_label(column)}', self._pie(counts)))
            for column in _numeric_columns(df):
                if len(charts) >= MAX_CHARTS:
                    break
                if df[column].dropna().nunique() < 2:
                    continue
                charts.append((f'{title} · {_localize_label(column)}', self._histogram(df, column)))
        return charts

    @staticmethod
    def _pie(counts: pd.Series) -> str:
        frame = pd.DataFrame({'category': counts.index.tolist(), 'count': counts.values.tolist()})
        return VisualizationService.render_image(
            frame, 'bar', x='category', y='count', agg='sum', title=str(counts.name or '')
        )

    @staticmethod
    def _histogram(df: pd.DataFrame, column: str) -> str:
        return VisualizationService.render_image(df, 'histogram', x=column)

    def _chart_block(self, frames: list, images=None) -> str:
        """The matplotlib charts and any chosen Chart-Studio pictures, in order.

        A picture the picker named but that no longer resolves is skipped rather
        than blanking the section: one deleted file is a gap, not a lost report.
        If drawing the built-in charts raises, the failure line still prints and
        the studio pictures are attempted, because they cost nothing to inline.
        """
        figures = []
        note = ''
        try:
            charts = self._charts(frames)
        except Exception as e:  # a chart must never take the report down
            logger.exception(t('report.chartsFailed'))
            charts = []
            note = f'<p class="warn">{html.escape(t("report.chart_failed", err=_text(e)))}</p>'
        for title, uri in charts:
            figures.append(
                f'<figure><img src="{uri}" alt="" loading="lazy"><figcaption>{_cell(title)}</figcaption></figure>'
            )
        figures += self._image_figures(images)
        if not figures:
            return note or f'<p class="muted">{html.escape(t("report.no_charts"))}</p>'
        return note + '<div class="charts">' + ''.join(figures) + '</div>'

    def _image_figures(self, images) -> list:
        """Saved Chart-Studio PNGs, base64-inlined so the report stays offline.

        The picker hands back names from the export listing, and that listing
        holds spreadsheets and stray pages too, so each name is resolved through
        the same door the download route uses and accepted only as an image.
        """
        figures = []
        for name in images or []:
            path = resolve_export_file(self.export_dir, name)
            ext = os.path.splitext(path)[1].lower() if path else ''
            if ext not in INLINE_IMAGE_EXT:
                continue
            try:
                with open(path, 'rb') as handle:
                    payload = handle.read()
            except OSError:
                continue
            if not payload:
                continue
            mime = _MIME_BY_EXT.get(ext, 'image/png')
            uri = f'data:{mime};base64,' + base64.b64encode(payload).decode('ascii')
            label = os.path.splitext(os.path.basename(path))[0]
            figures.append(
                f'<figure><img src="{uri}" alt="" loading="lazy"><figcaption>{_cell(label)}</figcaption></figure>'
            )
        return figures

    # ── tables ──────────────────────────────────────────────────

    def _table_block(self, entry: dict, row_limit: int = MAX_TABLE_ROWS) -> str:
        df = entry['frame']
        # Match the file exports: the 平台 column shows the word the reader knows (微博, not
        # weibo). The stored frame keeps the raw key; only this rendered copy is translated.
        df = DataExporter._localized_platform(df)
        rows = len(df)
        if rows == 0:
            return f'<p class="muted">{_cell(entry["title"])} — {html.escape(t("report.no_rows"))}</p>'
        shown = df.head(row_limit)
        head = ''.join(f'<th>{_cell(_localize_label(column))}</th>' for column in df.columns)
        body = ''.join(
            '<tr>' + ''.join(f'<td>{_cell(value)}</td>' for value in record) + '</tr>'
            for record in shown.astype(str).values.tolist()
        )
        note = ''
        if rows > row_limit:
            note = f'<p class="muted">{html.escape(t("report.more_rows", shown=row_limit, total=rows))}</p>'
        return (
            f'<section><h3>{_cell(entry["title"])}</h3>'
            f'<p class="meta">{html.escape(t("report.row_count", n=rows, cols=len(df.columns)))}</p>'
            f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{note}</section>'
        )

    # ── document ────────────────────────────────────────────────

    def build(self, title: str, nodes: list, meta: dict = None, conclusion: str = '', options: dict = None) -> str:
        """The report as one HTML string. ``nodes`` is [{'id','title','rows'}].

        ``options`` chooses what the document shows — which sections, how many
        rows per table, which nodes, and any Chart-Studio pictures to inline. It
        is normalised first, so an empty or malformed body yields the full report
        rather than a partial one (see :data:`DEFAULT_OPTIONS`).
        """
        opts = _normalize_options(options)
        keep = opts['node_ids']
        frames = []
        for entry in nodes:
            ident = _text(entry.get('id'))
            if keep is not None and ident not in keep:
                continue
            rows = entry.get('rows') or []
            frame = pd.DataFrame(rows) if rows else pd.DataFrame()
            frames.append({'id': ident, 'title': _text(entry.get('title')) or ident, 'frame': frame})
        total_rows = sum(len(frame['frame']) for frame in frames)
        non_empty = sum(1 for frame in frames if not frame['frame'].empty)
        meta = meta or {}

        facts = [
            (t('report.fact.workflow'), meta.get('workflow_name')),
            (t('report.fact.run'), meta.get('run_id')),
            (t('report.fact.status'), meta.get('status')),
            (t('report.fact.started'), meta.get('started_at')),
            (t('report.fact.finished'), meta.get('finished_at')),
        ]
        fact_rows = ''.join(
            f'<tr><th>{html.escape(label)}</th><td>{_cell(value)}</td></tr>' for label, value in facts if value
        )
        summary = f'<p>{html.escape(t("report.summary", nodes=len(frames), rows=total_rows, tables=non_empty))}</p>'
        conclusion_block = ''
        if str(conclusion or '').strip() and opts['show_conclusion']:
            paragraphs = ''.join(f'<p>{_cell(part)}</p>' for part in str(conclusion).split('\n\n') if part.strip())
            conclusion_block = f'<section><h2>{html.escape(t("report.conclusion"))}</h2>{paragraphs}</section>'
        generated = _text(meta.get('generated_at')) or time.strftime('%Y-%m-%d %H:%M:%S')
        header = (
            f'<header><h1>{_cell(title)}</h1>'
            f'<p class="meta">{html.escape(t("report.generated"))} {html.escape(generated)}</p></header>'
        )
        sections = ''
        if opts['show_charts']:
            charts_html = self._chart_block(frames, opts['images'])
            sections += f'<section><h2>{html.escape(t("report.charts"))}</h2>{charts_html}</section>'
        if opts['show_facts'] and fact_rows:
            facts_html = f'<table class="facts">{fact_rows}</table>'
            sections += f'<section><h2>{html.escape(t("report.run_facts"))}</h2>{facts_html}</section>'
        if opts['show_tables']:
            tables_html = ''.join(self._table_block(frame, opts['max_rows']) for frame in frames)
            sections += f'<section><h2>{html.escape(t("report.tables"))}</h2>{tables_html}</section>'
        return (
            '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_cell(title)}</title><style>{_CSS}</style></head><body>'
            f'{header}{summary}{conclusion_block}{sections}</body></html>'
        )

    def save(self, markup: str, name: str) -> dict:
        """Write the report into the export directory and describe what landed.

        The name always starts with the report prefix and always ends ``.html``:
        the export panel offers downloads by extension, ``.html`` is refused
        there on purpose, and :func:`services.export_browser.resolve_report_path`
        only admits files this writer signed with that prefix. A title that
        survives cleaning as nothing falls back rather than landing as
        ``report-.html``.
        """
        from services.export_browser import REPORT_PREFIX

        os.makedirs(self.export_dir, exist_ok=True)
        stem = safe_stem(name, fallback='run')
        filename = f'{REPORT_PREFIX}{stem}.html'
        path = os.path.join(self.export_dir, filename)
        # Never clobber an earlier report: a timestamp suffix keeps both.
        if os.path.exists(path):
            filename = f'{REPORT_PREFIX}{stem}-{time.strftime("%Y%m%d-%H%M%S")}.html'
            path = os.path.join(self.export_dir, filename)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(markup)
        return {'name': filename, 'path': path, 'bytes': os.path.getsize(path)}


_CSS = """
/* The report is the paper edition of the canvas, so it borrows the same design
   tokens: paper-white ground, #1a1a1a ink (never pure black), hairline rules on
   one rgba pair, and the single ochre accent the nodes are drawn with. A report
   is opened to be read, printed and forwarded and its charts are rendered for
   light paper, so the document fixes its own colours — following the OS dark-mode
   setting flipped the page to black while the pictures kept black axis text,
   readable in neither. */
body { font: 14px/1.65 "Literata", Georgia, "Songti SC", "SimSun", system-ui, "Microsoft YaHei", serif;
       margin: 0 auto; max-width: 960px; padding: 40px 28px 64px; color: #1a1a1a; background: #fff; }
h1 { font-size: 26px; font-weight: 600; letter-spacing: .2px; margin: 0 0 6px; }
header { border-bottom: 2px solid #1a1a1a; padding-bottom: 14px; margin-bottom: 22px; }
h2 { font-size: 15px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.4px;
     margin: 34px 0 12px; color: #9a7740; border-bottom: 1px solid rgba(26,26,26,.15); padding-bottom: 6px; }
h3 { font-size: 14px; font-weight: 600; margin: 22px 0 6px; }
p { margin: 0 0 12px; }
p.meta, .muted { color: rgba(26,26,26,.4); font-size: 12px; }
.warn { color: #a85454; font-size: 12px; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; margin-bottom: 8px; }
th, td { border: 1px solid rgba(26,26,26,.12); padding: 6px 9px; text-align: left; vertical-align: top;
         overflow-wrap: break-word; }
thead th { background: rgba(26,26,26,.05); font-weight: 600; }
tbody tr:nth-child(even) td { background: rgba(26,26,26,.02); }
table.facts { width: auto; }
table.facts th { width: 140px; background: rgba(26,26,26,.05); }
/* A grid, not flexbox: with flex the leftover chart of an unfinished row grew
   to the whole width and dwarfed its siblings. Every cell is the same size now,
   whatever the window width is. */
.charts { display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
figure { margin: 0; min-width: 0; border: 1px solid rgba(26,26,26,.08); border-radius: 6px; padding: 10px;
         background: #fff; }
figure img { width: 100%; height: auto; background: #fff; }
figcaption { font-size: 12px; color: rgba(26,26,26,.4); margin-top: 6px; }
@media print {
  body { max-width: none; padding: 0; }
  .charts { grid-template-columns: repeat(2, 1fr); }
  section { break-inside: avoid; }
}
"""
