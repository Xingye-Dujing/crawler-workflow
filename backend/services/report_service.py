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

import html
import logging
import os
import re
import time

import pandas as pd

from analyzers.llm_client import ABORT_MARK
from i18n import t
from services.visualizer import VisualizationService

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
                charts.append((f'{title} · {column}', self._pie(counts)))
            for column in _numeric_columns(df):
                if len(charts) >= MAX_CHARTS:
                    break
                if df[column].dropna().nunique() < 2:
                    continue
                charts.append((f'{title} · {column}', self._histogram(df, column)))
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

    def _chart_block(self, frames: list) -> str:
        blocks = []
        try:
            charts = self._charts(frames)
        except Exception as e:  # a chart must never take the report down
            logger.exception(t('report.chartsFailed'))
            return f'<p class="warn">{html.escape(t("report.chart_failed", err=_text(e)))}</p>'
        for title, uri in charts:
            block = f'<figure><img src="{uri}" alt="" loading="lazy"><figcaption>{_cell(title)}</figcaption></figure>'
            blocks.append(block)
        if not blocks:
            return f'<p class="muted">{html.escape(t("report.no_charts"))}</p>'
        return '<div class="charts">' + ''.join(blocks) + '</div>'

    # ── tables ──────────────────────────────────────────────────

    def _table_block(self, entry: dict) -> str:
        df = entry['frame']
        rows = len(df)
        if rows == 0:
            return f'<p class="muted">{_cell(entry["title"])} — {html.escape(t("report.no_rows"))}</p>'
        shown = df.head(MAX_TABLE_ROWS)
        head = ''.join(f'<th>{_cell(column)}</th>' for column in df.columns)
        body = ''.join(
            '<tr>' + ''.join(f'<td>{_cell(value)}</td>' for value in record) + '</tr>'
            for record in shown.astype(str).values.tolist()
        )
        note = ''
        if rows > MAX_TABLE_ROWS:
            note = f'<p class="muted">{html.escape(t("report.more_rows", shown=MAX_TABLE_ROWS, total=rows))}</p>'
        return (
            f'<section><h3>{_cell(entry["title"])}</h3>'
            f'<p class="meta">{html.escape(t("report.row_count", n=rows, cols=len(df.columns)))}</p>'
            f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{note}</section>'
        )

    # ── document ────────────────────────────────────────────────

    def build(self, title: str, nodes: list, meta: dict = None, conclusion: str = '') -> str:
        """The report as one HTML string. ``nodes`` is [{'title','rows'}]."""
        frames = []
        for entry in nodes:
            rows = entry.get('rows') or []
            frame = pd.DataFrame(rows) if rows else pd.DataFrame()
            frames.append({'title': _text(entry.get('title')) or _text(entry.get('id')), 'frame': frame})
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
        if str(conclusion or '').strip():
            paragraphs = ''.join(f'<p>{_cell(part)}</p>' for part in str(conclusion).split('\n\n') if part.strip())
            conclusion_block = f'<section><h2>{html.escape(t("report.conclusion"))}</h2>{paragraphs}</section>'
        generated = _text(meta.get('generated_at')) or time.strftime('%Y-%m-%d %H:%M:%S')
        header = (
            f'<header><h1>{_cell(title)}</h1>'
            f'<p class="meta">{html.escape(t("report.generated"))} {html.escape(generated)}</p></header>'
        )
        return (
            '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_cell(title)}</title><style>{_CSS}</style></head><body>'
            f'{header}{summary}{conclusion_block}'
            f'<section><h2>{html.escape(t("report.charts"))}</h2>{self._chart_block(frames)}</section>'
            f'<section><h2>{html.escape(t("report.run_facts"))}</h2><table class="facts">{fact_rows}</table></section>'
            f'<section><h2>{html.escape(t("report.tables"))}</h2>'
            + ''.join(self._table_block(frame) for frame in frames)
            + '</section></body></html>'
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
/* A report is opened to be read, printed and forwarded, and its pictures are
   rendered for light paper. Following the OS dark-mode setting used to flip the
   page to a black background while the charts kept their black axis text —
   readable in neither. So the document decides its own colours. */
body { font: 14px/1.6 system-ui, "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0 auto; max-width: 1000px;
       padding: 24px; color: #1c1c1e; background: #fff; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 28px 0 10px; border-bottom: 1px solid #e2e2e6; padding-bottom: 6px; }
h3 { font-size: 14px; margin: 20px 0 6px; }
p.meta, .muted { color: #6b6b70; font-size: 12px; }
.warn { color: #a4382b; font-size: 12px; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
th, td { border: 1px solid #d8d8dd; padding: 5px 7px; text-align: left; vertical-align: top;
         overflow-wrap: break-word; }
thead th { background: #f3f3f6; }
table.facts { width: auto; }
table.facts th { width: 120px; background: #f3f3f6; }
/* A grid, not flexbox: with flex the leftover chart of an unfinished row grew
   to the whole width and dwarfed its siblings. Every cell is the same size now,
   whatever the window width is. */
.charts { display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
figure { margin: 0; min-width: 0; }
figure img { width: 100%; height: auto; background: #fff; }
figcaption { font-size: 12px; color: #6b6b70; margin-top: 4px; }
@media print {
  body { max-width: none; padding: 0; }
  .charts { grid-template-columns: repeat(2, 1fr); }
  section { break-inside: avoid; }
}
"""
