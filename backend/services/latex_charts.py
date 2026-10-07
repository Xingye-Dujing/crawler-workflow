"""LaTeX figure + three-line-table generator for the ``visualize`` node.

A chart is emitted here as *source*, not a raster: a self-contained ``standalone`` document the user compiles
with MiKTeX ``xelatex`` (the figures carry Chinese, so ``ctex``). The look mirrors the hand-tuned paper this tool
feeds — 仿宋 (FangSong) CJK text, a muted paper palette, a light dotted grid, thousands-separated ticks, value
labels on bars, and boxed leader-line labels on the topic/network/sankey figures — because these are figures for
a paper, not a dashboard. Every figure and table shares ONE ``cixi`` axis style and a pair of tikz styles
(``lblbox``/``leadline``) defined once in the preamble, so a merged ``compile`` document restyles all charts at once.

The numbers come from the SAME helpers ``VisualizationService`` uses to draw the chart, so the LaTeX and the
on-screen figure are two projections of one value and cannot disagree (the palette is the paper's own, which is
deliberately a touch deeper than the on-screen ``CATEGORY_COLORS``).

Two types have no faithful TikZ equivalent in this build (no province geometry, no word-cloud/sankey layout
engine — see ``visualizer.py:397``): ``map`` is drawn as a province-centroid **bubble map** and ``wordcloud``
as a frequency-sized word block, and BOTH list every value in an appendix ``tabular`` so content stays
complete even where a centroid is missing. A chart whose required field is absent refuses by name
(``ChartConfigError``), the rule the renderers already follow.
"""

import math
import re

import pandas as pd

from i18n import t
from services.visualizer import (
    ChartConfigError,
    VisualizationService,
    _box_stats,
    _finite,
    _histogram_bins,
    _localize_label,
)

# ── paper preamble ──────────────────────────────────────────────────────
# Exactly the packages a figure copied into a paper needs; harmless if the document already loads them.
# fontspec under ctex/xelatex makes the 仿宋 \setCJKmainfont below available; ctex would load it anyway.
_PACKAGES = (
    '\\usepackage{ctex}\n'
    '\\usepackage{fontspec}\n'
    '\\usepackage{pgfplots}\n'
    '\\pgfplotsset{compat=1.18}\n'
    '\\usepackage{amssymb}\n'
    '\\usepackage{booktabs}\n'
    '\\usepackage{xcolor}\n'
    '\\usetikzlibrary{arrows.meta,calc,positioning,backgrounds}\n'
)

_CYCLE_NAMES = ['cA', 'cB', 'cC', 'cD', 'cE', 'cF', 'cG', 'cH', 'cI', 'cJ']

#: The paper's own palette, taken color-for-color from the reference figures it is made to match. Deeper and
#: more restrained than the on-screen ``CATEGORY_COLORS``: these print in grayscale and carry a caption.
_PAPER_PALETTE = [
    '22557A',
    'B5563C',
    '3E7A5A',
    'C79A3B',
    '6A5A8C',
    '2E7D8C',
    '9C6B3C',
    '5C8A5C',
    '8A5A6B',
    '4A6B8A',
]


def _preamble_extras() -> str:
    """仿宋 CJK text + the paper palette + the shared ``cixi`` axis style and two reusable tikz styles.

    One style block instead of repeating the paper rules per ``axis``: a figure that quietly kept
    gridlines in one branch and dropped them in another is the kind of inconsistency a reader spots. The
    merged ``compile`` document embeds this preamble once, so ``lblbox``/``leadline`` are in scope for every
    boxed label regardless of how many charts are stitched together.
    """
    lines = [
        r'\setCJKmainfont[scale=0.95,AutoFakeBold=2.0]{FangSong}',
        r'\setCJKsansfont[AutoFakeBold=2.0]{FangSong}',
        r'\setCJKmonofont[AutoFakeBold=2.0]{FangSong}',
    ]
    lines += [rf'\definecolor{{{n}}}{{HTML}}{{{h}}}' for n, h in zip(_CYCLE_NAMES, _PAPER_PALETTE, strict=False)]
    entries = ','.join(f'{{color={n},mark=*,solid,thick}}' for n in _CYCLE_NAMES[: len(_PAPER_PALETTE)])
    lines.append(rf'\pgfplotsset{{cycle list={{{entries}}}}}')
    lines.append(
        r'\pgfplotsset{cixi/.style={'
        r'axis lines=left,xmajorgrids=false,ymajorgrids=true,'
        r'major grid style={black!12,dotted},'
        r'scaled ticks=false,/pgf/number format/1000 sep={,},'
        r'tick label style={font=\scriptsize},'
        r'label style={font=\small},'
        r'legend style={font=\scriptsize,draw=none,at={(0.5,1.03)},anchor=south},'
        r'width=9cm,height=5.6cm}}'
    )
    # A boxed label + its leader line: the reference draws topic/network/sankey captions this way so long
    # Chinese labels never collide with a data point.
    lines.append(
        r'\tikzset{lblbox/.style={font=\scriptsize,align=center,inner sep=1.6pt,'
        r'fill=white,draw=black!14,line width=0.3pt,rounded corners=2pt,text=black},'
        r'leadline/.style={black!30,line width=0.3pt}}'
    )
    lines.append(r'\renewcommand{\arraystretch}{1.25}')
    return '\n'.join(lines)


def _esc(value) -> str:
    """Make a label safe for LaTeX text. Chinese passes through (ctex); TeX's ten specials are escaped."""
    out = []
    for ch in str(value):
        if ch in '\\&%#_{}$':
            out.append('\\' + ch)
        elif ch == '~':
            out.append('\\textasciitilde{}')
        elif ch == '^':
            out.append('\\textasciicircum{}')
        else:
            out.append(ch)
    return ''.join(out)


def _num(value) -> str:
    """A finite number as clean LaTeX (drop a trailing .0); never emit a nan/inf token."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return '0'
    if not math.isfinite(f):
        return '0'
    if f == int(f):
        return str(int(f))
    return f'{f:g}'


def _sym(labels) -> str:
    """A pgfplots ``symbolic coords`` set: comma-separated, each label escaped and spaces made robust."""
    return ','.join(_esc(label).replace(' ', '~') for label in labels)


def _fold_label(text, width=7) -> str:
    r"""Break a long label onto ``width``-character lines so its box stays narrow, like the reference's.

    Each line is escaped whole, never by slicing an escaped string (that would split ``\&`` into a stray
    backslash and an active ampersand). ``\\`` is a line break inside an ``align`` node.
    """
    s = str(text)
    return r'\\'.join(_esc(s[i : i + width]) for i in range(0, len(s), width))


def _cat_axis(labels, xlabel='') -> str:
    """A categorical x-axis with the paper's crowding rule.

    Beyond a handful of categories pgfplots drops every other tick and lies about the granularity, so
    we rotate the labels and show a regular, spaced subset — while keeping every DATA point, so a reader
    counts points and recovers the labels. That is the only irregularity the X axis is allowed.
    """
    rotate = (
        'xticklabel style={rotate=45,anchor=east,align=right,font=\\scriptsize},xtick distance=2,'
        if len(labels) > 10
        else 'xticklabel style={font=\\scriptsize},'
    )
    name = f',xlabel={{{_esc(xlabel)}}}' if xlabel else ''
    return f'symbolic x coords={{{_sym(labels)}}},xtick=data,{rotate}enlargelimits=0.15{name}'


def _label_key(chart_type, title) -> str:
    base = re.sub(r'[^0-9a-zA-Z]+', '-', str(title or chart_type)).strip('-').lower()
    return (base or chart_type)[:40]


class LatexChartService:
    """Render a chart's numbers as compilable LaTeX — a figure document, or a booktabs three-line table."""

    @classmethod
    def to_latex_document(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        *,
        x=None,
        y=None,
        value_field=None,
        agg='sum',
        y2=None,
        agg2=None,
        label_field='topic',
        annotations='',
        stack_fields='',
        title='',
        tokenize=False,
        **_ignored,
    ) -> str:
        body = cls._figure(
            df,
            chart_type,
            x=x,
            y=y,
            value_field=value_field,
            agg=agg,
            y2=y2,
            agg2=agg2,
            label_field=label_field,
            stack_fields=stack_fields,
            tokenize=tokenize,
        )
        return cls._document(body, chart_type, title, table=False)

    @classmethod
    def to_latex_table(
        cls,
        df: pd.DataFrame,
        chart_type: str,
        *,
        x=None,
        y=None,
        value_field=None,
        agg='sum',
        y2=None,
        label_field='topic',
        stack_fields='',
        title='',
        tokenize=False,
        **_ignored,
    ) -> str:
        head, rows = cls._table_data(
            df,
            chart_type,
            x=x,
            y=y,
            value_field=value_field,
            agg=agg,
            y2=y2,
            label_field=label_field,
            stack_fields=stack_fields,
            tokenize=tokenize,
        )
        return cls._document(cls._tabular(head, rows), chart_type, title, table=True)

    # ── document shell ────────────────────────────────────────────────

    @staticmethod
    def _wrap_body(body: str) -> str:
        """A bare ``axis`` must live inside a ``tikzpicture``; a ``tikzpicture``/``minipage``/``tabular``
        body is already a box and is left alone.
        """
        if '\\begin{axis}' in body and '\\begin{tikzpicture}' not in body:
            return '\\begin{tikzpicture}\n' + body + '\n\\end{tikzpicture}'
        return body

    @staticmethod
    def _standalone_head(kind: str, chart_type: str, title: str, caption: str) -> str:
        """The comment block a paper author pastes around, then the documentclass + shared preamble up to
        (and including) ``\\begin{document}``. The figure and the table share this one preamble."""
        return (
            f'% 采析绘 LaTeX {kind}（chart_type={chart_type}）\n'
            '% 用 MiKTeX 的 xelatex 编译（含中文，依赖 ctex）。\n'
            '% 复制进论文：导言区加载 ctex、fontspec、pgfplots(1.18)、tikz(+下列库)、booktabs、xcolor，\n'
            '% 并 \\setCJKmainfont[scale=0.95,AutoFakeBold=2.0]{FangSong}（仿宋），\n'
            '% 然后包成：\\begin{figure}[htbp]\\centering  <下面这段>  \\caption{'
            + caption
            + '}\\label{fig:'
            + _label_key(chart_type, title)
            + '}\\end{figure}\n'
            '\\documentclass[border=6pt]{standalone}\n' + _PACKAGES + _preamble_extras() + '\n\\begin{document}\n'
        )

    @classmethod
    def _document(cls, body: str, chart_type: str, title: str, *, table: bool) -> str:
        """Wrap a body in a standalone doc that compiles.

        ``standalone`` boxes its body, so a float (``figure``) or ``\\centering`` is illegal at its
        top level ("Not allowed in LR mode"). The body is emitted bare; the paper ``figure`` wrapper
        and the package list ride along as comments, which is what the user pastes into a real paper.
        """
        kind = '三线表' if table else '图'
        caption = _esc(title) if title else f'{_esc(chart_type)}（{kind}）'
        return cls._standalone_head(kind, chart_type, title, caption) + cls._wrap_body(body) + '\n\\end{document}\n'

    @staticmethod
    def _strip_shell(doc: str) -> str:
        """The body this service put between the (exactly one) begin/end ``document`` of a standalone doc.

        Safe to split on those markers because every document consumed here was produced by ``_document``,
        which emits each marker once and nothing that looks like them in the body.
        """
        return doc.split(r'\begin{document}', 1)[1].rsplit(r'\end{document}', 1)[0].strip()

    @classmethod
    def compose_from_standalone(cls, docs: list[str]) -> str:
        """Merge the bodies of several standalone documents (this service's own figure/table sources)
        into ONE standalone sharing a single preamble — so a ``compile`` node emits figure and three-line
        table together in one PDF with a single ``xelatex`` pass.

        ``standalone`` keeps its body in LR mode, so adjacent boxes are separated with ``\\par`` (a bare
        ``axis`` beside a ``tabular`` would otherwise collide). The stripped body is already box-wrapped by
        ``_wrap_body`` from its own source, so it is joined verbatim.
        """
        bodies = [cls._strip_shell(doc) for doc in docs if doc]
        body = '\n\\par\n\n'.join(bodies)
        head = cls._standalone_head('组合', 'compile', '', _esc('图表'))
        return head + body + '\n\\end{document}\n'

    # ── figure dispatch ───────────────────────────────────────────────

    @classmethod
    def _figure(cls, df, chart_type, *, x, y, value_field, agg, y2, agg2, label_field, stack_fields, tokenize) -> str:
        if chart_type in ('bar', 'line'):
            return cls._bars_or_line(df, chart_type, x, y, agg)
        if chart_type == 'dual_line':
            return cls._dual_line(df, x, y, agg, y2, agg2)
        if chart_type == 'stack_pct':
            return cls._stack_pct(df, x, stack_fields)
        if chart_type == 'scatter':
            return cls._scatter(df, x, y)
        if chart_type == 'histogram':
            return cls._histogram(df, x)
        if chart_type == 'box':
            return cls._box(df, x, y)
        if chart_type == 'pie':
            return cls._pie(df, x, y, agg)
        if chart_type == 'heatmap':
            return cls._heatmap(df, x, y, value_field, agg)
        if chart_type == 'topic_map':
            return cls._topic_map(df, x, y, value_field, label_field)
        if chart_type == 'topic_terms':
            return cls._topic_terms(df, x, y, y2)
        if chart_type == 'sankey':
            return cls._relation(df, x, y, value_field, agg, ribbons=True)
        if chart_type == 'network':
            return cls._relation(df, x, y, value_field, agg, ribbons=False)
        if chart_type == 'wordcloud':
            return cls._wordcloud(df, x, value_field, agg, tokenize)
        if chart_type == 'map':
            return cls._map(df, x, value_field, agg)
        raise ChartConfigError(f'no LaTeX figure for chart type: {chart_type}')

    @staticmethod
    def _require_pair(x, y, what):
        if not x or not y:
            raise ChartConfigError(f'{what} LaTeX requires both fields (x and y)')
        VisualizationService._require_columns(pd.DataFrame({x: [0], y: [0]}), x, y)

    # ── categorical bar / line ────────────────────────────────────────

    @classmethod
    def _bars_or_line(cls, df, chart_type, x, y, agg):
        if not x:
            raise ChartConfigError(f'{chart_type} LaTeX requires a category field (x)')
        labels, values = VisualizationService._aggregate(df, x, y, agg)
        marks = ' '.join(f'({lab},{_num(v)})' for lab, v in zip(labels, values, strict=True))
        if chart_type == 'bar':
            # Reference fig-3: a solid bar wearing its own value on top, a width that narrows as categories crowd.
            width = '0.62cm' if len(labels) <= 6 else '0.4cm' if len(labels) <= 12 else '0.25cm'
            mark = (
                f'ybar,fill=cA,draw=cA,bar width={width},'
                r'nodes near coords,'
                r'nodes near coords style={font=\scriptsize,text=black,/pgf/number format/1000 sep={,}}'
            )
        else:
            # Reference fig-2: rounded joins and a filled marker read as a measured series, not a spreadsheet spark.
            mark = 'mark=*,mark size=1.8pt,line width=0.9pt,line join=round,color=cA,mark options={solid,fill=cA}'
        ylabel = f',ylabel={{{_esc(_localize_label(y)) if y else _esc(t("chart.count"))}}}'
        head = f'\\begin{{axis}}[cixi,{_cat_axis(labels, x)}{ylabel}]'
        return f'{head}\n\\addplot[{mark}] coordinates {{{marks}}};\n\\end{{axis}}'

    @classmethod
    def _dual_line(cls, df, x, y, agg, y2, agg2):
        if not x or not y2:
            raise ChartConfigError('dual_line LaTeX requires a category field (x) and a second value field (y2)')
        labels, left = VisualizationService._aggregate(df, x, y, agg)
        _, right = VisualizationService._aggregate(df, x, y2, agg2 or 'mean')
        pts_l = ' '.join(f'({lab},{_num(v)})' for lab, v in zip(labels, left, strict=True))
        pts_r = ' '.join(f'({lab},{_num(v)})' for lab, v in zip(labels, right, strict=True))
        ln = _esc(_localize_label(y) if y else t('chart.count'))
        rn = _esc(_localize_label(y2))
        sym = _cat_axis(labels, '')
        # pgfplots' two-scale idiom: a right axis overlaid on the first. Both must share the SAME
        # x (symbolic coords + range), or the right one parses 甲 as a number and dies on ``''``.
        # Reference fig-17: a translucent connect line under solid markers so a noisy daily series stays legible,
        # and the right legend anchored SE so it never stacks on the left one.
        line = 'mark=*,mark size=1.3pt,line join=round,line width=0.9pt,draw opacity=0.4,color=cA,mark options={solid}'
        line2 = (
            'mark=triangle*,mark size=1.6pt,line join=round,line width=0.9pt,draw opacity=0.4,color=cD,'
            'mark options={solid}'
        )
        return (
            f'\\begin{{axis}}[cixi,{sym},ylabel={{{ln}}}]\n'
            f'\\addplot[{line}] coordinates {{{pts_l}}};\\addlegendentry{{{ln}}}\n\\end{{axis}}\n'
            f'\\begin{{axis}}[cixi,{sym},axis lines=right,axis x line=none,xtick=\\empty,'
            f'legend style={{font=\\scriptsize,draw=none,at={{(1.0,1.03)}},anchor=south east}},'
            f'scale only axis=true,width=9cm,height=5.6cm,ylabel={{{rn}}},'
            f'ylabel style={{color=cD}},yticklabel style={{color=cD}}]\n'
            f'\\addplot[{line2}] coordinates {{{pts_r}}};\\addlegendentry{{{rn}}}\n\\end{{axis}}'
        )

    @classmethod
    def _stack_pct(cls, df, x, stack_fields):
        fields = [s.strip() for s in str(stack_fields or '').replace('，', ',').split(',') if s.strip()]
        if not x:
            raise ChartConfigError('stack_pct LaTeX requires a category field (x)')
        if not fields:
            raise ChartConfigError('stack_pct LaTeX requires stacked fields (stack_fields)')
        VisualizationService._require_columns(df, x, *fields)
        grouped = df.groupby(x, sort=False)
        keys = list(grouped.groups.keys())
        labels = [str(k) for k in keys]
        cols = {f: grouped[f].sum().reindex(keys).fillna(0).tolist() for f in fields}
        totals = [sum(cols[f][i] for f in fields) for i in range(len(labels))]
        plots = []
        for idx, field in enumerate(fields):
            pts = ' '.join(
                f'({lab},{_num(round(cols[field][i] / totals[i] * 100, 2) if totals[i] else 0)})'
                for i, lab in enumerate(labels)
            )
            color = _CYCLE_NAMES[idx % len(_CYCLE_NAMES)]
            name = _esc(_localize_label(field))
            plots.append(
                f'\\addplot[ybar stacked,fill={color},draw={color}] coordinates {{{pts}}};'
                + f'\\addlegendentry{{{name}}}'
            )
        style = (
            f'ybar stacked,{_cat_axis(labels, x)},ylabel={{{_esc(t("chart.col.share"))}}},ymin=0,ymax=100,width=11cm'
        )
        return f'\\begin{{axis}}[cixi,{style}]\n' + '\n'.join(plots) + '\n\\end{axis}'

    @classmethod
    def _scatter(cls, df, x, y):
        if not x or not y:
            raise ChartConfigError('scatter LaTeX requires both x and y fields')
        VisualizationService._require_columns(df, x, y)
        xs = pd.to_numeric(df[x], errors='coerce')
        ys = pd.to_numeric(df[y], errors='coerce')
        pts = [f'({_num(a)},{_num(b)})' for a, b in zip(xs, ys, strict=True) if _finite([a, b])]
        body = (
            f'\\addplot[only marks,mark=*,mark size=1.8pt,color=cA,fill opacity=0.7] coordinates {{{" ".join(pts)}}};'
            if pts
            else '\\addplot[only marks] coordinates {};'
        )
        return (
            f'\\begin{{axis}}[cixi,xlabel={{{_esc(_localize_label(x))}}},ylabel={{{_esc(_localize_label(y))}}}]\n'
            f'{body}\n\\end{{axis}}'
        )

    @classmethod
    def _histogram(cls, df, x):
        if not x:
            raise ChartConfigError('histogram LaTeX requires a numeric field (x)')
        VisualizationService._require_columns(df, x)
        values = pd.to_numeric(df[x], errors='coerce').dropna()
        counts, edges = _histogram_bins(values)
        pts = ' '.join(f'({_num(edges[i])},{_num(c)})' for i, c in enumerate(counts))
        return (
            f'\\begin{{axis}}[cixi,xlabel={{{_esc(_localize_label(x))}}},ylabel={{{_esc(t("chart.count"))}}}]\n'
            f'\\addplot[ybar interval,fill=cA,draw=cA] coordinates {{{pts}}};\n\\end{{axis}}'
        )

    @classmethod
    def _box(cls, df, x, y):
        groups = []
        if x and y and y in df.columns:
            for name, g in df.groupby(x, sort=False):
                groups.append((_localize_label(name), _box_stats(pd.to_numeric(g[y], errors='coerce').dropna())))
        elif x and x in df.columns:
            groups.append((_localize_label(x), _box_stats(pd.to_numeric(df[x], errors='coerce').dropna())))
        if not groups:
            raise ChartConfigError('box LaTeX needs a category field (x) with a numeric (y), or one numeric (x)')
        lo_all = min(s[0] for _, s in groups)
        hi_all = max(s[4] for _, s in groups)
        # pgfplots has no boxplot in core, so the five-number summary is drawn by hand — whiskers,
        # box, median — which is exactly the paper convention and compiles with nothing exotic.
        draws = []
        for i, (_, s) in enumerate(groups, start=1):
            lo, q1, med, q3, hi = [_num(v) for v in s]
            draws.append(
                f'\\draw[black!60,thick] (axis cs:{i},{lo}) -- (axis cs:{i},{q1});'
                f'\\draw[black!60,thick] (axis cs:{i},{q3}) -- (axis cs:{i},{hi});'
                f'\\draw[black!60,thick] (axis cs:{i - 0.25},{lo}) -- (axis cs:{i + 0.25},{lo});'
                f'\\draw[black!60,thick] (axis cs:{i - 0.25},{hi}) -- (axis cs:{i + 0.25},{hi});'
                f'\\draw[fill=cA!18,draw=cA,thick] (axis cs:{i - 0.25},{q1}) rectangle (axis cs:{i + 0.25},{q3});'
                f'\\draw[line width=1.1pt,color=cD] (axis cs:{i - 0.25},{med}) -- (axis cs:{i + 0.25},{med});'
            )
        cat = 'xtick={' + ','.join(str(i) for i in range(1, len(groups) + 1)) + '}'
        cats_labels = 'xticklabels={' + _sym([g[0] for g in groups]) + '}'
        ylab = _esc(_localize_label(y) if y else t('chart.count'))
        return (
            '\\begin{axis}[cixi,width=10cm,height=6.2cm,ymin='
            + _num(lo_all)
            + ',ymax='
            + _num(hi_all)
            + ',xmin=0.4,xmax='
            + _num(len(groups) + 0.6)
            + ','
            + cat
            + ','
            + cats_labels
            + ',xticklabel style={font=\\scriptsize},ylabel={'
            + ylab
            + '},no markers]\n'
            + '\n'.join(draws)
            + '\n\\end{axis}'
        )

    @classmethod
    def _pie(cls, df, x, y, agg):
        if not x:
            raise ChartConfigError('pie LaTeX requires a category field (x)')
        labels, values = VisualizationService._aggregate(df, x, y, agg)
        vals = [float(v) if _finite([v]) else 0.0 for v in values]
        total = sum(vals) or 1.0
        draws, angle = [], 0.0
        n = len(labels)
        for i, (label, v) in enumerate(zip(labels, vals, strict=True)):
            sweep = v / total * 360.0
            color = _CYCLE_NAMES[i % len(_CYCLE_NAMES)]
            pct = round(v / total * 100, 1)
            mid = math.radians(angle + sweep / 2)
            ix, iy = 1.45 * math.cos(mid), 1.45 * math.sin(mid)
            # The slice wears only its share (white on the deep paper palette reads); the category name goes to
            # the boxed legend beside it, so a long Chinese label never overlaps the arc.
            seg = (
                f'\\draw[fill={color},draw=white,line width=1.1pt] (0,0) -- ({angle:.2f}:2.4cm) '
                f'arc ({angle:.2f}:{angle + sweep:.2f}:2.4cm) -- cycle;'
            )
            inner = (
                f'\\node[font=\\scriptsize,text=white] at ({ix:.2f},{iy:.2f}) {{{_num(pct)}\\%}};' if pct >= 4 else ''
            )
            ly = (n - 1) / 2 - i
            legend = (
                f'\\draw[fill={color},draw=white] (2.95,{ly - 0.16}) rectangle (3.2,{ly + 0.16});'
                f'\\node[font=\\scriptsize,text=black,anchor=west] at (3.32,{ly:.2f}) '
                f'{{{_esc(label)}\\,{_num(pct)}\\%}};'
            )
            draws.append(seg + inner + legend)
            angle += sweep
        return '\\begin{tikzpicture}\n' + '\n'.join(draws) + '\n\\end{tikzpicture}'

    @classmethod
    def _heatmap(cls, df, x, y, value_field, agg):
        if not x or not y:
            raise ChartConfigError('heatmap LaTeX requires two category fields (x and y)')
        xcats, ycats, matrix = VisualizationService._pivot(df, x, y, value_field, agg)
        vmax = max(_finite(v for line in matrix for v in line) or [1.0]) or 1.0
        cells = []
        for j, row in enumerate(matrix):  # rows = y categories, drawn top-down
            for i, value in enumerate(row):
                frac = (float(value) / vmax) if _finite([value]) else 0.0
                shade = int(frac * 92)
                # The cell text flips to white only where the cA wash is deep enough to need it.
                text = 'white' if shade >= 55 else 'black'
                cells.append(
                    f'\\draw[fill=cA!{shade},draw=white,line width=0.4pt] ({i},{-j}) rectangle ({i + 1},{-j - 1});'
                    f'\\node[font=\\tiny,text={text}] at ({i + 0.5},{-j - 0.5}) {{{_num(value)}}};'
                )
        col_lab = '\\rotatebox{45}{%s}' if len(xcats) > 6 else '%s'
        xlabels = ''.join(
            f'\\node[anchor=north,font=\\scriptsize] at ({i + 0.5},{-len(ycats) - 0.05}) {{{col_lab % _esc(c)}}};'
            for i, c in enumerate(xcats)
        )
        ylabels = ''.join(
            f'\\node[anchor=east,font=\\scriptsize] at (0,-{j + 0.5}) {{{_esc(c)}}};' for j, c in enumerate(ycats)
        )
        return (
            '\\begin{tikzpicture}[x=1.1cm,y=0.95cm]\n'
            + '\n'.join(cells)
            + '\n'
            + xlabels
            + '\n'
            + ylabels
            + '\n\\end{tikzpicture}'
        )

    @classmethod
    def _topic_map(cls, df, x, y, value_field, label_field):
        if not x or not y:
            raise ChartConfigError('topic_map LaTeX requires both coordinate fields (x=PC1, y=PC2)')
        VisualizationService._require_columns(df, x, y)
        first = pd.to_numeric(df[x], errors='coerce')
        second = pd.to_numeric(df[y], errors='coerce')
        has_size = bool(value_field) and value_field in df.columns
        sizes = pd.to_numeric(df[value_field], errors='coerce').tolist() if has_size else [None] * len(df)
        biggest = max((s for s in sizes if s is not None and s == s), default=0.0)
        has_label = bool(label_field) and label_field in df.columns
        names = df[label_field].tolist() if has_label else [''] * len(df)
        coords = [(first.iloc[i], second.iloc[i]) for i in range(len(df)) if _finite([first.iloc[i], second.iloc[i]])]
        # Pad the span from the data (a centroid beyond ±1 must not clip) and center on 0 like the reference.
        m = max((max(abs(a), abs(b)) for a, b in coords), default=1.0) or 1.0
        ext = 1.28 * m
        ticks = '-{m},-{h},0,{h},{m}'.format(m=_num(m), h=_num(m / 2))
        lines = []
        for i in range(len(df)):
            a, b = first.iloc[i], second.iloc[i]
            if not _finite([a, b]):
                continue
            r = 3.0
            size = sizes[i]
            if biggest and size is not None and size == size:
                r = max(3.0, 8.0 * math.sqrt(float(size) / biggest))
            shape = (
                f'\\draw[fill=cA!28,draw=cA,line width=0.6pt] (axis cs:{_num(a)},{_num(b)}) circle[radius={r:.1f}pt];'
            )
            lines.append(shape)
            if has_label and names[i]:
                norm = math.hypot(a, b)
                ux, uy = (1.0, 0.0) if norm < 1e-9 else (a / norm, b / norm)
                off = 0.2 * ext
                lx, ly = a + ux * off, b + uy * off
                anchor = 'west' if ux >= 0 else 'east'
                lines.append(
                    f'\\draw[leadline] (axis cs:{_num(a)},{_num(b)}) -- (axis cs:{_num(lx)},{_num(ly)});'
                    f'\\node[lblbox,anchor={anchor}] at (axis cs:{_num(lx)},{_num(ly)}) {{{_fold_label(names[i])}}};'
                )
        axis = (
            f'\\begin{{axis}}[cixi,axis lines=middle,grid=major,major grid style={{black!8,dotted}},clip=false,'
            f'xtick={{{ticks}}},ytick={{{ticks}}},xmin=-{_num(ext)},xmax={_num(ext)},ymin=-{_num(ext)},ymax={_num(ext)},'
            f'xlabel={{{_esc(t("chart.axis.pc1"))}}},ylabel={{{_esc(t("chart.axis.pc2"))}}},'
            f'width=10cm,height=7.8cm,axis line style={{black!55}}]'
        )
        return axis + '\n' + '\n'.join(lines) + '\n\\end{axis}'

    @classmethod
    def _topic_terms(cls, df, x, y, y2):
        if not x or not y or not y2:
            raise ChartConfigError('topic_terms LaTeX requires the term field (x) and BOTH frequency fields (y, y2)')
        VisualizationService._require_columns(df, x, y, y2)
        terms = [str(v) for v in df[x].tolist()]
        overall = pd.to_numeric(df[y], errors='coerce').tolist()
        within = pd.to_numeric(df[y2], errors='coerce').tolist()
        y_disp, y2_disp = _esc(_localize_label(y)), _esc(_localize_label(y2))
        pts_o = ' '.join(f'({_num(v)},{_esc(t_).replace(" ", "~")})' for t_, v in zip(terms, overall, strict=True))
        pts_w = ' '.join(f'({_num(v)},{_esc(t_).replace(" ", "~")})' for t_, v in zip(terms, within, strict=True))
        # Reference fig-5: slim paired bars, and a legend swatch drawn as a thin rectangle so it matches the bars
        # instead of a fat default line marker.
        return (
            f'\\begin{{axis}}[cixi,xbar,enlargelimits=0.15,bar width=0.13cm,bar shift=0.17cm,'
            f'legend image code/.code={{\\draw[#1] (0cm,-0.09cm) rectangle (0.5cm,0.09cm);}},'
            f'symbolic y coords={{{_sym(terms)}}},ytick=data,'
            f'yticklabel style={{font=\\scriptsize,text width=2.4cm,align=right}},'
            f'width=11cm,height={max(6, len(terms) * 0.4):.0f}cm,'
            f'xlabel={{{_esc(t("chart.count"))}}},ylabel={{{_esc(_localize_label(x))}}}]\n'
            f'\\addplot[fill=cA,draw=cA] coordinates {{{pts_o}}};\\addlegendentry{{{y_disp}}}\n'
            f'\\addplot[fill=cD,draw=cD] coordinates {{{pts_w}}};\\addlegendentry{{{y2_disp}}}\n'
            '\\end{axis}'
        )

    @classmethod
    def _relation(cls, df, x, y, value_field, agg, *, ribbons: bool) -> str:
        nodes, links = VisualizationService._sankey_links(df, x, y, value_field, agg)
        if not links:
            raise ChartConfigError(f'{x}/{y} yields no {("sankey" if ribbons else "network")} edges to draw')
        return cls._sankey_tikz(nodes, links) if ribbons else cls._graph_tikz(nodes, links)

    @staticmethod
    def _incident(links):
        inc = {}
        for link in links:
            for name in (link['source'], link['target']):
                inc[name] = inc.get(name, 0.0) + link['value']
        return inc

    @classmethod
    def _sankey_tikz(cls, nodes, links) -> str:
        left = list(dict.fromkeys(lk['source'] for lk in links))
        right = list(dict.fromkeys(lk['target'] for lk in links))
        inc = cls._incident(links)
        span = 1.4 * max(len(left), len(right))
        pos = {}
        for i, n in enumerate(left):
            pos[(0, n)] = -span * (i + 0.5) / len(left)
        for i, n in enumerate(right):
            pos[(1, n)] = -span * (i + 0.5) / len(right)
        # A ribbon wears its SOURCE node's color (reference fig-9); the node bars are the palette's own, solid.
        cyc = len(_CYCLE_NAMES)
        left_color = {n: _CYCLE_NAMES[i % cyc] for i, n in enumerate(left)}
        right_color = {n: _CYCLE_NAMES[i % cyc] for i, n in enumerate(right)}
        biggest_inc = max(inc.values()) or 1.0
        biggest_link = max(lk['value'] for lk in links) or 1.0
        out = []
        for lk in links:
            sy = pos.get((0, lk['source']))
            ty = pos.get((1, lk['target']))
            if sy is None or ty is None:
                continue
            col = left_color.get(lk['source'], 'cA')
            w = max(0.8, 3.4 * math.sqrt(lk['value'] / biggest_link))
            out.append(
                f'\\draw[{col}!55,line width={w:.2f}pt,opacity=0.4] '
                f'(0.35,{sy:.2f}) .. controls (4,{sy:.2f}) and (4,{ty:.2f}) .. (8,{ty:.2f});'
            )
        for n in left:
            yy = pos[(0, n)]
            col = left_color[n]
            h = max(0.4, inc.get(n, 0.0) / biggest_inc)
            out.append(
                f'\\draw[fill={col}!70,draw={col},line width=0.7pt] '
                f'(0,{yy - h / 2:.2f}) rectangle (0.35,{yy + h / 2:.2f});'
                f'\\node[lblbox,anchor=east] at (0,{yy:.2f}) {{{_fold_label(n, 9)}}};'
            )
        for n in right:
            yy = pos[(1, n)]
            col = right_color[n]
            h = max(0.4, inc.get(n, 0.0) / biggest_inc)
            out.append(
                f'\\draw[fill={col}!70,draw={col},line width=0.7pt] '
                f'(8,{yy - h / 2:.2f}) rectangle (8.35,{yy + h / 2:.2f});'
                f'\\node[lblbox,anchor=west] at (8.35,{yy:.2f}) {{{_fold_label(n, 9)}}};'
            )
        return '\\begin{tikzpicture}\n' + '\n'.join(out) + '\n\\end{tikzpicture}'

    @classmethod
    def _graph_tikz(cls, nodes, links) -> str:
        names = list(dict.fromkeys(nm for lk in links for nm in (lk['source'], lk['target'])))
        inc = cls._incident(links)
        max_inc = max(inc.values()) or 1.0
        biggest_link = max(lk['value'] for lk in links) or 1.0
        radius = max(2.8, 0.46 * len(names))
        pos = {}
        for i, name in enumerate(names):
            ang = 360.0 * i / len(names)
            pos[name] = (radius * math.cos(math.radians(ang)), radius * math.sin(math.radians(ang)))
        idx = {n: i for i, n in enumerate(names)}
        out = [f'\\coordinate (n{i}) at ({x:.2f},{y:.2f});' for i, (x, y) in enumerate(pos.values())]
        for lk in links:
            w = max(0.3, 4.0 * math.sqrt(lk['value'] / biggest_link))
            a = idx[lk['source']]
            b = idx[lk['target']]
            out.append(f'\\draw[black!12,line width={w:.2f}pt] (n{a}) -- (n{b});')
        for i, name in enumerate(names):
            r = 0.14 + 0.5 * math.sqrt(inc.get(name, 0.0) / max_inc)
            x, y = pos[name]
            # A hub label is pulled outward on a leader line and sits on its own side, so words in the left half
            # no longer run over the centre like they did with a fixed anchor=west.
            norm = math.hypot(x, y) or 1.0
            ux, uy = x / norm, y / norm
            ex, ey = x + ux * r, y + uy * r
            lx, ly = x + ux * (r + 0.22), y + uy * (r + 0.22)
            anchor = 'west' if ux >= 0 else 'east'
            font = '\\small' if inc.get(name, 0.0) / max_inc >= 0.6 else '\\tiny'
            out.append(
                f'\\draw[fill=cA!55,draw=cA,line width=0.7pt] (n{i}) circle ({r:.2f});'
                f'\\draw[leadline] ({ex:.2f},{ey:.2f}) -- ({lx:.2f},{ly:.2f});'
                f'\\node[font={font},anchor={anchor},text=black] at ({lx:.2f},{ly:.2f}) {{{_esc(name)}}};'
            )
        return '\\begin{tikzpicture}\n' + '\n'.join(out) + '\n\\end{tikzpicture}'

    @classmethod
    def _wordcloud(cls, df, x, value_field, agg, tokenize):
        if not x:
            raise ChartConfigError('wordcloud LaTeX requires a text/category field (x)')
        if tokenize:
            labels, values = VisualizationService.tokenize_frequency(df, x)
        else:
            labels, values = VisualizationService._aggregate(df, x, value_field, agg)
        if not labels:
            raise ChartConfigError('word cloud has no words to show')
        top = list(zip(labels, values, strict=True))[:80]
        vals = [float(v) if _finite([v]) else 0.0 for _, v in top]
        vmax, vmin = (max(vals) or 1.0), min(vals)
        spans = []
        for (label, _), v in zip(top, vals, strict=True):
            frac = (v - vmin) / (vmax - vmin) if vmax > vmin else 0.5
            size = 8 + frac * 20
            # The rarer the term, the lighter the ink: frequency reads twice — from size and from color.
            shade = int(28 + frac * 67)
            spans.append(
                f'{{\\fontsize{{{size:.0f}}}{{{1.2 * size:.0f}}}\\selectfont '
                f'\\textcolor{{cA!{shade}}}{{{_esc(label)}}}}}'
            )
        cloud = (
            '\\parbox{14cm}{\\raggedright\\linespread{1.35}\\selectfont ' + ' \\hspace{0.5em} '.join(spans) + '\\par}'
        )
        appendix = cls._tabular(
            [_esc(_localize_label(x)), _esc(t('chart.count'))], [[_esc(w), _num(v)] for w, v in top]
        )
        return (
            '\\begin{minipage}{15cm}\n' + cloud + '\n\n% 全部词频（保证内容完整）：\n' + appendix + '\n\\end{minipage}'
        )

    @classmethod
    def _map(cls, df, x, value_field, agg):
        if not x:
            raise ChartConfigError('map LaTeX requires a region-name field (x)')
        labels, values = VisualizationService._aggregate(df, x, value_field, agg)
        pairs = list(zip(labels, values, strict=True))
        vals = [float(v) if _finite([v]) else 0.0 for _, v in pairs]
        vmax = max(vals) or 1.0
        bubbles = []
        for (label, _), v in zip(pairs, vals, strict=True):
            coord = _PROVINCE_CENTROIDS.get(str(label).strip())
            if not coord:
                continue  # still listed in the appendix below, so nothing is lost
            lon, lat = coord
            px = (lon - _CHINA_LON0) / (_CHINA_LON1 - _CHINA_LON0) * 16.0
            py = (lat - _CHINA_LAT0) / (_CHINA_LAT1 - _CHINA_LAT0) * 12.0
            r = 0.14 + 0.7 * math.sqrt(v / vmax)
            shade = int(30 + (v / vmax) * 65)
            dot = f'\\draw[fill=cA!{shade},draw=cA,line width=0.6pt] ({px:.2f},{py:.2f}) circle ({r:.2f});'
            tag = f'\\node[lblbox,anchor=south] at ({px:.2f},{py + r + 0.05:.2f}) {{{_esc(label)}}};'
            bubbles.append(dot + tag)
        pic = (
            '\\begin{tikzpicture}\n\\draw[black!25,dashed] (0,0) rectangle (16,12);\n'
            + '\n'.join(bubbles)
            + '\n\\end{tikzpicture}'
        )
        appendix = cls._tabular(
            [_esc(_localize_label(x)), _esc(_localize_label(value_field) if value_field else _esc(t('chart.count')))],
            [[_esc(w), _num(v)] for w, v in pairs],
        )
        return (
            '\\begin{minipage}{17cm}\n'
            + pic
            + '\n\n% 质心气泡图（无省界几何下的近似）；下面列出全部地区数值：\n'
            + appendix
            + '\n\\end{minipage}'
        )

    # ── booktabs three-line table ─────────────────────────────────────

    @classmethod
    def _table_data(cls, df, chart_type, *, x, y, value_field, agg, y2, label_field, stack_fields, tokenize):
        if chart_type == 'stack_pct':
            fields = [s.strip() for s in str(stack_fields or '').replace('，', ',').split(',') if s.strip()]
            if not x or not fields:
                raise ChartConfigError('stack_pct LaTeX table requires a category field (x) and stacked fields')
            VisualizationService._require_columns(df, x, *fields)
            grouped = df.groupby(x, sort=False)
            keys = list(grouped.groups.keys())
            cols = {f: grouped[f].sum().reindex(keys).fillna(0).tolist() for f in fields}
            totals = [sum(cols[f][i] for f in fields) for i in range(len(keys))]
            head = [_esc(_localize_label(x))] + [f'{_esc(_localize_label(f))} (\\%)' for f in fields]
            rows = [
                [_esc(str(k))] + [_num(round(cols[f][i] / totals[i] * 100, 2) if totals[i] else 0) for f in fields]
                for i, k in enumerate(keys)
            ]
            return head, rows
        if chart_type in ('sankey', 'network'):
            nodes, links = VisualizationService._sankey_links(df, x, y, value_field, agg)
            head = [_esc(_localize_label(x)), _esc(_localize_label(y)), _esc(value_field or t('chart.count'))]
            return head, [[_esc(lk['source']), _esc(lk['target']), _num(lk['value'])] for lk in links]
        if chart_type == 'topic_map':
            VisualizationService._require_columns(df, x, y)
            has_label = bool(label_field) and label_field in df.columns
            names = df[label_field].tolist() if has_label else [''] * len(df)
            a = pd.to_numeric(df[x], errors='coerce').tolist()
            b = pd.to_numeric(df[y], errors='coerce').tolist()
            head = [
                _esc(_localize_label(label_field) if has_label else t('chart.col.topic')),
                _esc(_localize_label(x)),
                _esc(_localize_label(y)),
            ]
            return head, [[_esc(str(nm)), _num(xa), _num(xb)] for nm, xa, xb in zip(names, a, b, strict=True)]
        if chart_type == 'topic_terms':
            VisualizationService._require_columns(df, x, y, y2)
            terms = df[x].tolist()
            head = [_esc(_localize_label(x)), _esc(_localize_label(y)), _esc(_localize_label(y2))]
            return head, [
                [_esc(str(tm)), _num(o), _num(w)]
                for tm, o, w in zip(
                    terms, pd.to_numeric(df[y], errors='coerce'), pd.to_numeric(df[y2], errors='coerce'), strict=True
                )
            ]
        # the categorical/aggregated family (bar/line/dual_line/pie/scatter/histogram/box/heatmap/map/wordcloud)
        if not x:
            raise ChartConfigError(f'{chart_type} LaTeX table requires a category field (x)')
        labels, values = VisualizationService._aggregate(df, x, y, agg)
        head = [
            _esc(_localize_label(x)),
            _esc(_localize_label(y) if y else (value_field and _localize_label(value_field) or t('chart.count'))),
        ]
        return head, [[_esc(w), _num(v)] for w, v in zip(labels, values, strict=True)]

    @staticmethod
    def _tabular(head, rows) -> str:
        spec = 'l' + 'r' * (len(head) - 1) if len(head) > 1 else 'l'
        body = '\n'.join(' & '.join(str(c) for c in row) + r'\\' for row in rows)
        head_row = ' & '.join(rf'\textbf{{{c}}}' for c in head)
        # \footnotesize + the preamble's \arraystretch{1.25} are the reference tables' spacing; a bold header
        # row is the only emphasis a three-line table may add over \toprule/\midrule/\bottomrule.
        return (
            '{\\footnotesize\n'
            f'\\begin{{tabular}}{{{spec}}}\n\\toprule\n'
            + head_row
            + r'\\'
            + f'\n\\midrule\n{body}\n\\bottomrule\n\\end{{tabular}}\n'
            + '}\n'
        )


# ── compact province-centroid table (capital cities) for the bubble map ──
_CHINA_LON0, _CHINA_LON1 = 73.0, 135.0
_CHINA_LAT0, _CHINA_LAT1 = 17.0, 54.0
_PROVINCE_CENTROIDS = {
    '北京': (116.41, 39.90),
    '天津': (117.20, 39.13),
    '河北': (114.51, 38.04),
    '石家庄': (114.51, 38.04),
    '山西': (112.55, 37.87),
    '太原': (112.55, 37.87),
    '内蒙古': (111.75, 40.84),
    '呼和浩特': (111.75, 40.84),
    '辽宁': (123.43, 41.80),
    '沈阳': (123.43, 41.80),
    '吉林': (125.32, 43.89),
    '长春': (125.32, 43.89),
    '黑龙江': (126.63, 45.75),
    '哈尔滨': (126.63, 45.75),
    '上海': (121.47, 31.23),
    '江苏': (118.79, 32.06),
    '南京': (118.79, 32.06),
    '浙江': (120.15, 30.28),
    '杭州': (120.15, 30.28),
    '安徽': (117.28, 31.86),
    '合肥': (117.28, 31.86),
    '福建': (119.30, 26.08),
    '福州': (119.30, 26.08),
    '江西': (115.89, 28.68),
    '南昌': (115.89, 28.68),
    '山东': (117.00, 36.65),
    '济南': (117.00, 36.65),
    '河南': (113.62, 34.75),
    '郑州': (113.62, 34.75),
    '湖北': (114.30, 30.59),
    '武汉': (114.30, 30.59),
    '湖南': (112.98, 28.19),
    '长沙': (112.98, 28.19),
    '广东': (113.26, 23.13),
    '广州': (113.26, 23.13),
    '广西': (108.32, 22.82),
    '南宁': (108.32, 22.82),
    '海南': (110.33, 20.03),
    '海口': (110.33, 20.03),
    '重庆': (106.54, 29.56),
    '四川': (104.07, 30.57),
    '成都': (104.07, 30.57),
    '贵州': (106.71, 26.65),
    '贵阳': (106.71, 26.65),
    '云南': (102.83, 24.88),
    '昆明': (102.83, 24.88),
    '西藏': (91.13, 29.66),
    '拉萨': (91.13, 29.66),
    '陕西': (108.95, 34.34),
    '西安': (108.95, 34.34),
    '甘肃': (103.82, 36.06),
    '兰州': (103.82, 36.06),
    '青海': (101.78, 36.62),
    '西宁': (101.78, 36.62),
    '宁夏': (106.23, 38.49),
    '银川': (106.23, 38.49),
    '新疆': (87.62, 43.79),
    '乌鲁木齐': (87.62, 43.79),
    '台湾': (121.51, 25.04),
    '香港': (114.17, 22.32),
    '澳门': (113.55, 22.20),
}
