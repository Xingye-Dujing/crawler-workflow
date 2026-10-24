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

import json
import math
import re

import pandas as pd

from i18n import t
from services.biblio_geo import aggregate as geo_aggregate
from services.biblio_geo import display
from services.chart_contracts import (
    BIBLIO_CHART_TYPES,
    OVERLAY_ROW_LIMIT,
    OVERLAY_TABLE_LIMIT,
    OVERLAY_TOPIC_LIMIT,
    POLARITY_LABELS,
    VARIATION_ROW_LIMIT,
)
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


#: The box a network picture is sized into, in centimetres. A4 with the paper's 1.5 cm margins leaves
#: 18 cm of text and a bibliometric figure's own minipage is 17.5 cm wide, so a picture that fits here
#: cannot run off the page — and height binds first, because a ring is as tall as it is wide while the
#: caption and the formula paragraph have to reach the same page.
GRAPH_BOX_CM = (15.0, 10.5)

#: One line of a Chinese label, tall enough to count as overhang when sizing.
GRAPH_LINE_CM = 0.6


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
    # The sentiment overlay's neutral band, exactly the grey the screen uses (chart_contracts.POLARITY_COLORS).
    lines.append(r'\definecolor{cNeutral}{HTML}{9AA0A6}')
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


#: The same escaper under a public name: anything that pastes free text (a node title, a method
#: sentence) into a document assembled elsewhere has to go through it — ``top_n=50`` in a caption
#: is a ``Missing $ inserted`` error without it.
esc = _esc


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


def paper_preamble() -> str:
    """ctex + fontspec + pgfplots + booktabs + the palette + the shared tikz styles.

    Every source this service writes defines ``cA``…``cJ``, ``lblbox``, ``leadline`` and the
    ``cixi`` axis style in its own preamble. A document that pastes their BODIES has to carry the
    same definitions, or the first ``\\draw[cA,...]`` dies with ``Undefined color`` — which is why
    the paper report asks for this instead of writing its own package list.
    """
    return _PACKAGES + _preamble_extras()


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
        if chart_type in BIBLIO_CHART_TYPES:
            return cls._biblio_figure(df, chart_type)
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

    # ── network sizing ────────────────────────────────────────────────

    @staticmethod
    def _label_cm(name, font: str) -> float:
        r"""A Chinese label's width in cm, estimated per glyph: \small 0.34, \scriptsize 0.28, \tiny 0.23.

        TeX's font metrics are not ours to consult here, and the number only ever sizes a picture, so
        it errs wide (the ``+0.2`` is the ``lblbox`` padding, and an unknown font takes the widest
        factor). Sizing from an estimate is only safe in one direction: over-estimate and the picture
        is a little small, under-estimate and it runs off the page — which is the bug this prevents.
        """
        per_glyph = {r'\small': 0.34, r'\scriptsize': 0.28, r'\tiny': 0.23}.get(font, 0.34)
        return len(str(name)) * per_glyph + 0.2

    @classmethod
    def _picture_scale(cls, extent_x: float, extent_y: float, widest_label_cm: float) -> float:
        """cm per layout unit, so a picture that spans ``extent`` units still fits ``GRAPH_BOX_CM``.

        A layout's span grows with what it draws — a ring's radius is ``0.46 × nodes`` so its labels
        have arc to sit on — while the unit stayed 1 cm, so a 49-node ring measured 46 cm across and
        the paper's page cut its right half off. Clamped at 1: a picture that already fits is not
        blown up to fill the box, because then a two-node graph would print as two dots 15 cm apart.
        """
        room_x = max(1.5, GRAPH_BOX_CM[0] - 2 * widest_label_cm)
        room_y = max(1.5, GRAPH_BOX_CM[1] - 2 * GRAPH_LINE_CM)
        return max(0.02, min(1.0, room_x / max(extent_x, 0.1), room_y / max(extent_y, 0.1)))

    @classmethod
    def _fit_labels(cls, candidates, scale_cm: float) -> set:
        """The labels that can be drawn without covering one another, as a set of node names.

        ``candidates`` is ``[(name, side, x, y, font)]`` in layout units, in priority order: the first
        arrival keeps its space and a later one that would cover it is dropped (the caller counts what
        it dropped out loud). Rectangles rather than a per-side sweep, because an east label from one
        node and a north label from its neighbour collide just the same.

        The width is ``_label_cm`` — an estimate — so this is a de-collision pass, not a proof. Under-
        estimating is the one failure mode to avoid, which is why that estimate errs wide.
        """
        unit = max(scale_cm, 1e-6)
        line = GRAPH_LINE_CM / unit
        kept: list = []
        held: set = set()
        for name, side, x, y, font in candidates:
            width = cls._label_cm(name, font) / unit
            if side == 'east':
                box = (x, y - line / 2, x + width, y + line / 2)
            elif side == 'west':
                box = (x - width, y - line / 2, x, y + line / 2)
            elif side == 'north':
                box = (x - width / 2, y, x + width / 2, y + line)
            elif side == 'south':
                box = (x - width / 2, y - line, x + width / 2, y)
            else:
                box = (x - width / 2, y - line / 2, x + width / 2, y + line / 2)
            x0, y0, x1, y1 = box
            if any(x0 < kx1 and kx0 < x1 and y0 < ky1 and ky0 < y1 for kx0, ky0, kx1, ky1 in kept):
                continue
            kept.append(box)
            held.add(name)
        return held

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
        fonts = {name: r'\small' if inc.get(name, 0.0) / max_inc >= 0.6 else r'\tiny' for name in names}
        # A hub label is pulled outward on a leader line and sits on its own side, so words in the left
        # half no longer run over the centre like they did with a fixed anchor=west. The side recorded
        # here is the direction the label GROWS in, which is the opposite of its tikz anchor name.
        spots = {}
        for name in names:
            x, y = pos[name]
            r = 0.14 + 0.5 * math.sqrt(inc.get(name, 0.0) / max_inc)
            norm = math.hypot(x, y) or 1.0
            ux, uy = x / norm, y / norm
            spots[name] = (x, y, r, x + ux * (r + 0.22), y + uy * (r + 0.22), 'east' if ux >= 0 else 'west')
        ranked = sorted(names, key=lambda name: (-inc.get(name, 0.0), name))

        def _candidates(scale_cm: float) -> list:
            return [(name, spots[name][5], spots[name][3], spots[name][4], fonts[name]) for name in ranked]

        # Sized in two passes because the two quantities depend on each other: the scale is set by the
        # widest label, and which labels survive the de-collision is decided at that scale.
        scale = cls._picture_scale(2 * radius, 2 * radius, max(cls._label_cm(n, fonts[n]) for n in names))
        held = cls._fit_labels(_candidates(scale), scale)
        scale = cls._picture_scale(2 * radius, 2 * radius, max(cls._label_cm(n, fonts[n]) for n in held))
        held = cls._fit_labels(_candidates(scale), scale)
        out = [f'\\coordinate (n{i}) at ({x:.2f},{y:.2f});' for i, (x, y) in enumerate(pos.values())]
        for lk in links:
            w = max(0.3, 4.0 * math.sqrt(lk['value'] / biggest_link))
            a = idx[lk['source']]
            b = idx[lk['target']]
            out.append(f'\\draw[black!12,line width={w:.2f}pt] (n{a}) -- (n{b});')
        for i, name in enumerate(names):
            x, y, r, lx, ly, side = spots[name]
            draw = f'\\draw[fill=cA!55,draw=cA,line width=0.7pt] (n{i}) circle ({r:.2f});'
            if name in held:
                anchor = 'west' if side == 'east' else 'east'
                draw += (
                    f'\\draw[leadline] ({x + (lx - x) * 0.7:.2f},{y + (ly - y) * 0.7:.2f}) -- ({lx:.2f},{ly:.2f});'
                    f'\\node[font={fonts[name]},anchor={anchor},text=black] at ({lx:.2f},{ly:.2f}) {{{_esc(name)}}};'
                )
            out.append(draw)
        if len(held) < len(names):
            out.append(
                f'\\node[font=\\scriptsize,text=black!55,anchor=north] at (0,{-(radius + 1.0):.2f})'
                f'{{已省略 {len(names) - len(held)} 个会互相遮盖的节点标签；完整节点见三线表。}};'
            )
        return f'\\begin{{tikzpicture}}[x={scale:.3f}cm,y={scale:.3f}cm]\n' + '\n'.join(out) + '\n\\end{tikzpicture}'

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

    # ── bibliometric figures ──────────────────────────────────────────

    @staticmethod
    def _biblio_text(value) -> str:
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return ''
        return str(value).strip()

    @staticmethod
    def _biblio_float(value, default=0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    @classmethod
    def _biblio_parsed(cls, value, column: str):
        if isinstance(value, (list, dict)):
            return value
        text = cls._biblio_text(value)
        if not text:
            return []
        try:
            return json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ChartConfigError(t('chart.biblio_bad_json', col=column)) from exc

    @classmethod
    def _require_biblio(cls, df, *columns):
        VisualizationService._require_columns(df, *columns)

    @classmethod
    def _biblio_node_rows(cls, df, columns):
        cls._require_biblio(df, *columns)
        rows = {}
        for _, row in df.iterrows():
            name = cls._biblio_text(row['节点'])
            if name and name not in rows:
                rows[name] = row
        if not rows:
            raise ChartConfigError(t('chart.biblio_no_nodes'))
        return rows, list(rows)

    @classmethod
    def _biblio_links(cls, rows, names):
        cls._require_biblio(pd.DataFrame([rows[name] for name in names[:1]]), '连接')
        links = {}
        for name in names:
            for item in cls._biblio_parsed(rows[name].get('连接'), '连接'):
                if not isinstance(item, dict):
                    continue
                target = cls._biblio_text(item.get('target'))
                if target not in rows or target == name:
                    continue
                left, right = sorted((name, target))
                value = cls._biblio_float(item.get('value'), 0.0)
                if (left, right) not in links or value > links[(left, right)]['value']:
                    links[(left, right)] = {'source': left, 'target': right, 'value': value}
        if not links:
            raise ChartConfigError(t('chart.biblio_no_links'))
        return sorted(links.values(), key=lambda link: (-link['value'], link['source'], link['target']))

    @staticmethod
    def _biblio_color(index: int) -> str:
        return _CYCLE_NAMES[index % len(_CYCLE_NAMES)]

    @classmethod
    def _biblio_cluster_colors(cls, rows, names):
        colors = {}
        for name in names:
            cluster = cls._biblio_text(rows[name].get('聚类'))
            label = cls._biblio_text(rows[name].get('聚类标签')) or f'#{cluster}'
            key = f'#{cluster} {label}' if cluster else ''
            if key and key not in colors:
                colors[key] = cls._biblio_color(len(colors))
        return colors

    @staticmethod
    def _biblio_formulas(chart_type: str = '') -> str:
        # A CiteSpace-style method note belongs inside the figure: the reader should not
        # have to hunt through prose to learn which normalized link and centrality numbers
        # were plotted. Every formula is the one this implementation actually computes.
        return (
            (
                '\\medskip\\par{\\footnotesize\\textbf{计量公式：}'
                r'余弦 $\cos(C_i,C_j)=w_{ij}/\sqrt{w_i w_j}$；Dice $2w_{ij}/(w_i+w_j)$；'
                r'Jaccard $w_{ij}/(w_i+w_j-w_{ij})$。中介中心性 '
                r'$g(v)=\sum_{s\ne v\ne t}\sigma_{st}(v)/\sigma_{st}$；PageRank '
                r'$PR(p)=\frac{1-d}{N}+d\sum_{q\to p}PR(q)/L(q)$；'
                r'$\Sigma=(g(v)+1)^B$。'
                '}\n'
            )
            + (
                # The variation figure plots one more thing, and its own formula: what the marker
                # size means is not guessable from a picture.
                '\\medskip\\par{\\footnotesize\\textbf{结构变异公式：}'
                r'节点 $v$ 在相邻两期 $t$ 与 $t{+}1$ 的连边强度分布 $p,q$（各自归一化后取并集支撑）'
                r'之间的 Jensen--Shannon 散度 $D_{\mathrm{JS}}(p\|q)=\frac12 D_{\mathrm{KL}}(p\|m)'
                r'+\frac12 D_{\mathrm{KL}}(q\|m)$，其中 $m=\frac12(p+q)$，$0\le D_{\mathrm{JS}}\le 1$ 比特。'
                '}\n'
                if chart_type == 'variation'
                else ''
            )
            + (
                # The choropleth's colour and the table's share both come off the same totals, and
                # neither is guessable from the picture: how a shade was chosen is stated here, which
                # spellings collapsed into one region is stated in the figure.
                '\\medskip\\par{\\footnotesize\\textbf{地理图公式：}'
                r'地区 $r$ 的发文量 $v_r=\sum_{i\in r} f_i$（同名异写并入同一地区），占比 $s_r=v_r/\sum_j v_j$；'
                r'色阶按 $c_r=v_r/\max_j v_j$ 线性取色，底图无此区域者不计入并在图上点名。'
                '}\n'
                if chart_type == 'geo_map'
                else ''
            )
            + (
                # A share is only as meaningful as its denominator, and the denominator is the
                # decision a reader cannot recover from the figure: it excludes documents with no
                # judgement (「没有判断」 is not 中性), and both the figure and the table are excerpts.
                '\\medskip\\par{\\footnotesize\\textbf{情感叠加公式：}'
                r'节点 $v$ 的标签 $l$ 篇数 $n_{v,l}$ 为提及该节点的文档中标签为 $l$ 的篇数，'
                r"占比 $p_{v,l}=n_{v,l}/\sum_{l'}n_{v,l'}$；没有标签的文档不计入分母（不当作中性）。"
                f'图取前 {OVERLAY_ROW_LIMIT} 个节点、'
                f'表取前 {OVERLAY_TABLE_LIMIT} 个，'
                r'完整分布见节点表的「情感分布」列与 CSV 导出。'
                '}\n'
                if chart_type == 'sentiment_overlay'
                else ''
            )
            + (
                # Same denominator rule, plus the two axis caps: a heatmap that silently omits
                # the eleventh topic would otherwise look like the whole topic space.
                '\\medskip\\par{\\footnotesize\\textbf{话题叠加公式：}'
                r'节点 $v$ 在话题 $t$ 上的文档数 $n_{v,t}$ 来自提及它的已标注文档，'
                r"占比 $p_{v,t}=n_{v,t}/\sum_{t'}n_{v,t'}$；"
                f'图取前 {OVERLAY_TOPIC_LIMIT} 个话题与前 {OVERLAY_ROW_LIMIT} 个节点，'
                f'表取前 {OVERLAY_TOPIC_LIMIT} 个话题与前 {OVERLAY_TABLE_LIMIT} 个节点，'
                r'完整分布见「话题分布」列与 CSV 导出。'
                '}\n'
                if chart_type == 'topic_overlay'
                else ''
            )
        )

    @classmethod
    def _biblio_fixed_graph(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', 'x', 'y', '连接', '频次'))
        links = cls._biblio_links(rows, names)
        colors = cls._biblio_cluster_colors(rows, names)
        max_freq = max((cls._biblio_float(rows[name]['频次'], 0.0) for name in names), default=1.0) or 1.0
        xs = [cls._biblio_float(rows[name]['x'], 0.0) for name in names]
        ys = [cls._biblio_float(rows[name]['y'], 0.0) for name in names]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        span_x = max_x - min_x or 1.0
        span_y = max_y - min_y or 1.0
        positions = {
            name: (
                1.0 + 13.5 * (xs[i] - min_x) / span_x,
                1.0 + 7.5 * (ys[i] - min_y) / span_y,
            )
            for i, name in enumerate(names)
        }
        center_x = sum(value[0] for value in positions.values()) / len(positions)
        center_y = sum(value[1] for value in positions.values()) / len(positions)
        ranked = sorted(names, key=lambda name: (-cls._biblio_float(rows[name]['频次'], 0.0), name))
        fonts = {
            name: r'\small' if cls._biblio_float(rows[name]['频次'], 0.0) / max_freq >= 0.65 else r'\scriptsize'
            for name in names
        }
        widest = max(cls._label_cm(name, fonts[name]) for name in names)
        # The field itself spans 13.5 x 7.5 units; the labels hang off both sides of it, so they are
        # what the page has room for. See ``_graph_tikz`` for why the layout is sized instead of the unit.
        scale = cls._picture_scale(14.1, 8.1, widest)
        # Each label sits on the far side of its own dot, measured from the middle of the field, and
        # grows away from it — the direction ``_fit_labels`` needs.
        radii = {
            name: 0.08 + 0.52 * math.sqrt(max(0.0, cls._biblio_float(rows[name]['频次'], 0.0) / max_freq))
            for name in names
        }
        spots = {}
        for name in names:
            x, y = positions[name]
            radius = radii[name]
            dx, dy = x - center_x, y - center_y
            if abs(dx) >= abs(dy):
                side = 'east' if dx >= 0 else 'west'
                lx, ly = x + (radius + 0.14 if dx >= 0 else -(radius + 0.14)), y
            else:
                side = 'north' if dy >= 0 else 'south'
                lx, ly = x, y + (radius + 0.14 if dy >= 0 else -(radius + 0.14))
            spots[name] = (side, lx, ly)

        def _candidates(scale_cm: float) -> list:
            return [(name, spots[name][0], spots[name][1], spots[name][2], fonts[name]) for name in ranked[:120]]

        labelled = cls._fit_labels(_candidates(scale), scale)
        scale = cls._picture_scale(14.1, 8.1, max(cls._label_cm(n, fonts[n]) for n in labelled))
        labelled = cls._fit_labels(_candidates(scale), scale)
        max_weight = max((link['value'] for link in links), default=1.0) or 1.0
        out = []
        for link in links[:180]:
            x1, y1 = positions[link['source']]
            x2, y2 = positions[link['target']]
            width = 0.25 + 2.5 * math.sqrt(max(0.0, link['value'] / max_weight))
            out.append(f'\\draw[black!18,line width={width:.2f}pt] ({x1:.2f},{y1:.2f}) -- ({x2:.2f},{y2:.2f});')
        for name in names:
            x, y = positions[name]
            radius = radii[name]
            cluster = cls._biblio_text(rows[name].get('聚类'))
            label = cls._biblio_text(rows[name].get('聚类标签')) or f'#{cluster}'
            color = colors.get(f'#{cluster} {label}', 'cA')
            burst = cls._biblio_float(rows[name].get('突现强度'), 0.0) if '突现强度' in rows[name] else 0.0
            border = 'black' if burst > 0 else color
            width = '1.1pt' if burst > 0 else '0.6pt'
            out.append(
                f'\\draw[fill={color}!55,draw={border},line width={width}] ({x:.2f},{y:.2f}) circle ({radius:.2f});'
            )
            if name in labelled:
                side, lx, ly = spots[name]
                anchor = {'east': 'west', 'west': 'east', 'north': 'south', 'south': 'north'}[side]
                out.append(
                    f'\\draw[leadline] ({x:.2f},{y:.2f}) -- ({lx:.2f},{ly:.2f});'
                    f'\\node[font={fonts[name]},anchor={anchor},lblbox] at ({lx:.2f},{ly:.2f}) {{{_esc(name)}}};'
                )
        if len(labelled) < len(names):
            out.append(
                '\\node[font=\\scriptsize,text=black!55,anchor=south west] at (0,0)'
                f'{{已省略 {len(names) - len(labelled)} 个会互相遮盖的节点标签；完整节点见三线表。}};'
            )
        return f'\\begin{{tikzpicture}}[x={scale:.3f}cm,y={scale:.3f}cm]\n' + '\n'.join(out) + '\n\\end{tikzpicture}'

    @classmethod
    def _biblio_circular(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', '连接', '频次'))
        links = cls._biblio_links(rows, names)
        nodes = [{'source': link['source'], 'target': link['target'], 'value': link['value']} for link in links]
        return cls._graph_tikz(nodes, links)

    @classmethod
    def _biblio_landscape(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', '聚类', '聚类标签', '频次'))
        clusters = {}
        for name in names:
            cluster = cls._biblio_text(rows[name].get('聚类'))
            if not cluster:
                continue
            label = cls._biblio_text(rows[name].get('聚类标签')) or f'#{cluster}'
            key = f'#{cluster} {label}'
            group = clusters.setdefault(key, {'frequency': 0.0, 'nodes': 0, 'x': [], 'y': []})
            group['frequency'] += cls._biblio_float(rows[name]['频次'], 0.0)
            group['nodes'] += 1
            if 'x' in rows[name] and 'y' in rows[name]:
                group['x'].append(cls._biblio_float(rows[name].get('x'), 0.0))
                group['y'].append(cls._biblio_float(rows[name].get('y'), 0.0))
        if not clusters:
            raise ChartConfigError(t('chart.biblio_no_clusters'))
        ordered = sorted(clusters.items(), key=lambda item: (-item[1]['frequency'], item[0]))[:30]
        max_frequency = max((group['frequency'] for _, group in ordered), default=1.0) or 1.0
        radius = max(2.4, 0.48 * len(ordered))
        placed = []
        for index, (name, group) in enumerate(ordered):
            angle = 360.0 * index / len(ordered)
            if group['x'] and group['y']:
                x = sum(group['x']) / len(group['x']) / 100.0 * 12.0
                y = sum(group['y']) / len(group['y']) / 100.0 * 8.0
            else:
                x = radius * math.cos(math.radians(angle)) + 7.0
                y = radius * math.sin(math.radians(angle)) + 4.5
            size = 0.35 + 1.05 * math.sqrt(max(0.0, group['frequency'] / max_frequency))
            color = cls._biblio_color(index)
            # The label is folded at 12 glyphs and centred, so half of it hangs past the bubble.
            text = f'{_fold_label(name, 12)}\\\\{group["nodes"]}项'
            placed.append((x, y, size, color, text, cls._label_cm(name[:12] + f'{group["nodes"]}项', r'\scriptsize')))
        # Sized to the page like every other network picture (see ``_picture_scale``): the fallback ring
        # above grows with the cluster count, and 30 clusters once made a 29 cm bubble field on a 21 cm
        # sheet of paper.
        span_x = max(item[0] for item in placed) - min(item[0] for item in placed) + 2 * max(item[2] for item in placed)
        span_y = max(item[1] for item in placed) - min(item[1] for item in placed) + 2 * max(item[2] for item in placed)
        scale = cls._picture_scale(span_x, span_y, max(item[5] for item in placed) / 2.0)
        out = []
        for x, y, size, color, text, _cm in placed:
            out.append(
                f'\\draw[fill={color}!55,draw={color},line width=0.7pt,opacity=0.78]'
                f' ({x:.2f},{y:.2f}) circle ({size:.2f});'
                f'\\node[lblbox,anchor=center] at ({x:.2f},{y:.2f}) {{{text}}};'
            )
        return f'\\begin{{tikzpicture}}[x={scale:.3f}cm,y={scale:.3f}cm]\n' + '\n'.join(out) + '\n\\end{tikzpicture}'

    @classmethod
    def _biblio_timeline(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', '聚类', '聚类标签', '首年', '末年', '频次'))
        groups = {}
        for name in names:
            cluster = cls._biblio_text(rows[name].get('聚类'))
            label = cls._biblio_text(rows[name].get('聚类标签')) or f'#{cluster}'
            key = f'#{cluster} {label}'
            group = groups.setdefault(key, [])
            first = int(cls._biblio_float(rows[name].get('首年'), 0))
            last = int(cls._biblio_float(rows[name].get('末年'), first))
            frequency = cls._biblio_float(rows[name].get('频次'), 0.0)
            if first:
                group.append((first, last, name, frequency))
        if not groups:
            raise ChartConfigError(t('chart.biblio_no_years'))
        ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))[:18]
        categories = [name for name, _ in ordered]
        years = [year for _, entries in ordered for entry in entries for year in (entry[0], entry[1]) if year]
        if not years:
            raise ChartConfigError(t('chart.biblio_no_years'))
        max_frequency = max((entry[3] for _, entries in ordered for entry in entries), default=1.0) or 1.0
        body = []
        for index, (name, entries) in enumerate(ordered):
            color = cls._biblio_color(index)
            firsts = [entry[0] for entry in entries]
            lasts = [entry[1] for entry in entries]
            category_key = _esc(name).replace(' ', '~')
            body.append(
                f'\\draw[black!18,line width=1pt] (axis cs:{min(firsts)},{category_key}) -- '
                f'(axis cs:{max(lasts)},{category_key});'
            )
            coordinates = []
            for first, _last, entry_name, frequency in entries:
                size = 1.5 + 4.5 * math.sqrt(max(0.0, frequency / max_frequency))
                coordinates.append((first, entry_name, size))
            # A separate mark line per point keeps the paper palette readable without a custom
            # colormap callback; the category axis is already the cluster identity.
            for first, entry_name, size in coordinates[:12]:
                body.append(
                    f'\\draw[{color},fill={color}!60] (axis cs:{first},{category_key}) circle ({size:.1f}pt);'
                    f'\\node[lblbox,anchor=west,font=\\scriptsize] at (axis cs:{first},{category_key})'
                    f' {{{_esc(entry_name)}}};'
                )
        return (
            '\\begin{tikzpicture}\\begin{axis}[cixi,symbolic y coords={'
            + _sym(categories)
            + '},ytick=data,y=0.95cm,xmin='
            + str(min(years) - 1)
            + ',xmax='
            + str(max(years) + 1)
            + ',xlabel={年份},ylabel={聚类},width=15cm,height='
            + str(1.0 + len(ordered) * 0.95)
            + 'cm]\n'
            + '\n'.join(body)
            + '\n\\end{axis}\\end{tikzpicture}'
        )

    @classmethod
    def _biblio_burst(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', '突现起始', '突现结束', '突现强度'))
        items = []
        for name in names:
            strength = cls._biblio_float(rows[name].get('突现强度'), 0.0)
            start = int(cls._biblio_float(rows[name].get('突现起始'), 0))
            end = int(cls._biblio_float(rows[name].get('突现结束'), 0))
            if strength > 0 and start and end >= start:
                items.append((name, start, end, strength))
        if not items:
            raise ChartConfigError(t('chart.biblio_no_bursts'))
        items.sort(key=lambda item: (-item[3], item[0]))
        items = items[:70]
        categories = [item[0] for item in items]
        years = [item[1] for item in items] + [item[2] for item in items]
        body = []
        for index, (name, start, end, strength) in enumerate(items):
            color = cls._biblio_color(index % 10)
            body.append(
                f'\\draw[{color},fill={color}!65,rounded corners=1pt] (axis cs:{start},'
                f'{_esc(name).replace(" ", "~")}) rectangle (axis cs:{end + 1},'
                f'{_esc(name).replace(" ", "~")});'
                f'\\node[lblbox,anchor=west,font=\\scriptsize] at (axis cs:{start},'
                f'{_esc(name).replace(" ", "~")}) {{{_esc(name)}}};'
                f'\\node[font=\\scriptsize,anchor=east] at (axis cs:{end + 1},'
                f'{_esc(name).replace(" ", "~")}) {{B={_num(strength)}}};'
            )
        height = f'{1 + len(items) * 1.15:.2f}cm'
        return (
            '\\begin{tikzpicture}\\begin{axis}[axis y line=none,axis x line=none,y=-1.15cm,'
            'symbolic y coords={' + _sym(categories) + '},ytick=data,'
            'yticklabel style={font=\\scriptsize},'
            f'xmin={min(years) - 1},xmax={max(years) + 2},xlabel={{年份}},width=16cm,height='
            + height
            + ']\n'
            + '\n'.join(body)
            + '\n\\end{axis}\\end{tikzpicture}'
        )

    @classmethod
    def _biblio_geo(cls, df) -> str:
        """The printed twin of the choropleth: the same regions, the same totals, ranked.

        A world map's geometry does not belong in a .tex file (it is 200 KB of coastline and reads
        as a smudge at column width), so the figure prints what a reader actually compares — which
        countries lead and by how much — while the three-line table carries every value. The
        grouping is the map's own ``biblio_geo.aggregate``, so the bar and the colour cannot
        disagree about what ``England`` plus ``United Kingdom`` add up to.
        """
        result = geo_aggregate(df.to_dict('records'))
        regions = result['regions'][:18]
        if not regions:
            raise ChartConfigError(t('chart.biblio_geo_none', names='、'.join(result['unknown'][:5]) or '—'))
        total = sum(value for _iso, value, _names in result['regions']) or 1.0
        top = regions[0][1] or 1.0
        categories = [display(iso, 'zh') or iso for iso, _value, _names in regions]
        body = []
        color = cls._biblio_color(0)
        for iso, value, _names in regions:
            label = _esc(display(iso, 'zh') or iso).replace(' ', '~')
            width = round(value / top * 12.0, 3)
            body.append(
                f'\\draw[{color},fill={color}!55,rounded corners=1pt] (axis cs:0,{label}) rectangle '
                f'(axis cs:{width},{label});'
                f'\\node[font=\\scriptsize,anchor=west] at (axis cs:{round(width + 0.15, 3)},{label}) '
                f'{{{_num(value)} · {round(value / total * 100, 1)}\\%}};'
            )
        height = f'{1 + len(regions) * 1.1:.2f}cm'
        note = _esc(t('chart.biblio_geo_note'))
        return (
            '\\begin{tikzpicture}\\begin{axis}[axis y line=none,axis x line=bottom,y=-1.1cm,'
            'symbolic y coords={' + _sym(categories) + '},ytick=data,xmin=0,xmax=15,'
            'yticklabel style={font=\\scriptsize,align=right},xlabel={频次},width=16cm,height='
            + height
            + f']\n{chr(10).join(body)}\n\\end{{axis}}'
            + '\\node[font=\\scriptsize,text=gray,anchor=north west,align=left] at (current axis.south west) '
            + f'{{{note}}};\\end{{tikzpicture}}'
        )

    @classmethod
    def _biblio_timezone(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', '年份序列', '频次'))
        ordered = sorted(names, key=lambda name: (-cls._biblio_float(rows[name]['频次'], 0.0), name))[:20]
        series = {}
        for name in ordered:
            parsed = cls._biblio_parsed(rows[name].get('年份序列'), '年份序列')
            if not isinstance(parsed, dict) or not parsed:
                continue
            series[name] = {int(year): int(cls._biblio_float(count, 0)) for year, count in parsed.items()}
        if not series:
            raise ChartConfigError(t('chart.biblio_no_years'))
        years = sorted({year for item in series.values() for year in item})
        max_count = max((count for item in series.values() for count in item.values()), default=1) or 1
        body = []
        for index, name in enumerate(ordered):
            if name not in series:
                continue
            y = index * 1.15
            color = cls._biblio_color(index)
            for year, count in sorted(series[name].items()):
                size = 1.5 + 5.5 * math.sqrt(max(0, count) / max_count)
                body.append(f'\\draw[{color},fill={color}!65] (axis cs:{year},{y:.2f}) circle ({size:.1f}pt);')
            body.append(
                f'\\node[lblbox,anchor=east,font=\\scriptsize] at (axis cs:{years[0] - 0.5},{y:.2f}) {{{_esc(name)}}};'
            )
        return (
            '\\begin{tikzpicture}\\begin{axis}[axis y line=none,axis x line=none,no marks,'
            f'xmin={years[0] - 1.5},xmax={years[-1] + 1},ymin=-0.6,'
            f'ymax={len(ordered) * 1.15:.2f},xlabel={{年份}},width=16cm,'
            f'height={len(ordered) * 1.2:.2f}cm]\n' + '\n'.join(body) + '\n\\end{axis}\\end{tikzpicture}'
        )

    @classmethod
    def _biblio_heatmap(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', '聚类', '聚类标签', '年份序列', '频次'))
        groups = {}
        years = set()
        for name in names:
            cluster = cls._biblio_text(rows[name].get('聚类'))
            if not cluster:
                continue
            label = cls._biblio_text(rows[name].get('聚类标签')) or f'#{cluster}'
            key = f'#{cluster} {label}'
            parsed = cls._biblio_parsed(rows[name].get('年份序列'), '年份序列')
            if not isinstance(parsed, dict):
                continue
            group = groups.setdefault(key, {})
            for year, count in parsed.items():
                try:
                    year_int = int(float(year))
                except (TypeError, ValueError):
                    continue
                group[year_int] = group.get(year_int, 0) + int(cls._biblio_float(count, 0))
                years.add(year_int)
        if not groups or not years:
            raise ChartConfigError(t('chart.biblio_no_clusters'))
        ordered = sorted(groups, key=lambda label: (-sum(groups[label].values()), label))[:24]
        year_list = sorted(years)
        max_count = max((count for group in ordered for count in groups[group].values()), default=1) or 1
        body = []
        for row, group in enumerate(ordered):
            y = len(ordered) - row
            for column, year in enumerate(year_list):
                count = groups[group].get(year, 0)
                shade = int(10 + 80 * count / max_count) if count else 0
                fill = f'cA!{shade}' if shade else 'black!3'
                body.append(
                    f'\\draw[fill={fill},draw=black!10] ({column:.2f},{y:.2f})rectangle ({column + 1:.2f},{y + 1:.2f});'
                )
                if count:
                    color = 'white' if shade > 55 else 'black'
                    body.append(
                        f'\\node[font=\\scriptsize,text={color}] at ({column + 0.5:.2f},{y + 0.5:.2f}) {{{count}}};'
                    )
        for row, group in enumerate(ordered):
            label = _fold_label(group, 11)
            y = len(ordered) - row + 0.5
            body.append(f'\\node[font=\\scriptsize,text=black,anchor=east] at (-0.15,{y:.2f}) {{{label}}};')
        for column, year in enumerate(year_list):
            body.append(f'\\node[font=\\scriptsize,rotate=45,anchor=north west] at ({column + 0.5:.2f},0) {{{year}}};')
        pic = '\\begin{tikzpicture}[x=0.65cm,y=0.7cm]\n' + '\n'.join(body) + '\n\\end{tikzpicture}'
        return pic

    @classmethod
    def _overlay_items(cls, df, column: str, refusal: str) -> tuple[list, int]:
        """[(node, {label: documents})] and how many nodes carry no distribution at all.

        The same reading rule the ECharts builders apply (non-empty labels only, integer counts),
        so the figure and the screen cannot disagree about which documents were counted."""
        cls._require_biblio(df, '节点', column)
        items = []
        skipped = 0
        for _, row in df.iterrows():
            name = cls._biblio_text(row.get('节点'))
            if not name:
                continue
            parsed = cls._biblio_parsed(row.get(column), column)
            counts = {}
            if isinstance(parsed, dict):
                for label, value in parsed.items():
                    text = cls._biblio_text(label)
                    number = int(cls._biblio_float(value, 0.0))
                    if text and number > 0:
                        counts[text] = number
            if counts:
                items.append((name, counts))
            else:
                skipped += 1
        if not items:
            raise ChartConfigError(t(refusal))
        return items, skipped

    @staticmethod
    def _overlay_order(items: list) -> list:
        """The polarity order when the union of labels IS the three polarity values, else by frequency."""
        totals = {}
        for _name, counts in items:
            for label, count in counts.items():
                totals[label] = totals.get(label, 0) + count
        labels = sorted(totals, key=lambda label: (-totals[label], label))
        return list(POLARITY_LABELS) if set(labels) == set(POLARITY_LABELS) else labels

    @staticmethod
    def _overlay_ranked(items: list, polarity: bool) -> list:
        if polarity:
            return sorted(
                items,
                key=lambda item: (
                    -item[1].get('positive', 0) / max(1, sum(item[1].values())),
                    item[0],
                ),
            )
        return sorted(items, key=lambda item: (-sum(item[1].values()), item[0]))

    @classmethod
    def _biblio_sentiment(cls, df) -> str:
        """100 % stacked horizontal bars: each node's labelled documents by polarity.

        ``xbar stacked`` draws the segments in ``\\addplot`` order, so negative sits left and
        positive right — the way a Likert figure is read. The colours are the screen's own
        (``chart_contracts.POLARITY_COLORS``): cB / the neutral grey / cC."""
        items, skipped = cls._overlay_items(df, '情感分布', 'chart.biblio_no_sentiment')
        labels = cls._overlay_order(items)
        polarity = set(labels) == set(POLARITY_LABELS)
        items = cls._overlay_ranked(items, polarity)[:OVERLAY_ROW_LIMIT]
        names = [name for name, _counts in items]
        coords = {name: _esc(name).replace(' ', '~') for name in names}
        body = []
        colors = {'negative': 'cB', 'neutral': 'cNeutral', 'positive': 'cC'}
        for index, label in enumerate(labels):
            color = colors.get(label) or cls._biblio_color(index)
            points = []
            for name, counts in items:
                total = sum(counts.values())
                share = round(100.0 * counts.get(label, 0) / total, 2) if total else 0.0
                points.append(f'({share:g},{coords[name]})')
            body.append(
                f'\\addplot[fill={color}!88,draw=white,line width=0.4pt] coordinates {{' + ' '.join(points) + '};'
            )
            body.append(f'\\addlegendentry{{{_esc(_localize_label(label))}}}')
        return (
            '\\begin{tikzpicture}\\begin{axis}[cixi,xbar stacked,xmin=0,xmax=100,'
            'width=15cm,height=' + f'{1.1 + len(items) * 0.62:.2f}' + 'cm,'
            'symbolic y coords={' + _sym(names) + '},ytick=data,y dir=reverse,'
            'yticklabel style={font=\\scriptsize},xmajorgrids=true,ymajorgrids=false,'
            'xlabel={占比（\\%）},'
            'legend style={font=\\scriptsize,draw=none,at={(0.5,1.02)},anchor=south,legend columns='
            + str(max(1, len(labels)))
            + '}]\n'
            + '\n'.join(body)
            + '\n\\end{axis}\\end{tikzpicture}'
            + (
                f'\n\\par{{\\footnotesize\\textcolor{{black!60}}{{另有 {skipped} 个节点无情感标签，未画出。}}}}\n'
                if skipped
                else ''
            )
        )

    @classmethod
    def _biblio_topic(cls, df) -> str:
        """Node × topic grid of shares, drawn like the cluster heatmap.

        A cell states the node's share of its labelled documents in that topic (percent), not a
        raw count: with counts, one heavily mentioned node makes every other row look empty."""
        items, skipped = cls._overlay_items(df, '话题分布', 'chart.biblio_no_topics')
        totals = {}
        for _name, counts in items:
            for topic, count in counts.items():
                totals[topic] = totals.get(topic, 0) + count
        topics = sorted(totals, key=lambda topic: (-totals[topic], topic))[:OVERLAY_TOPIC_LIMIT]
        items = sorted(items, key=lambda item: (-sum(item[1].values()), item[0]))[:OVERLAY_ROW_LIMIT]
        body = []
        for row, (_name, counts) in enumerate(items):
            y = len(items) - row
            total = sum(counts.values())
            for column, topic in enumerate(topics):
                share = 100.0 * counts.get(topic, 0) / total if total else 0.0
                shade = int(10 + 80 * share / 100) if share > 0 else 0
                fill = f'cA!{shade}' if shade else 'black!3'
                body.append(
                    f'\\draw[fill={fill},draw=black!10] ({column:.2f},{y:.2f})rectangle ({column + 1:.2f},{y + 1:.2f});'
                )
                if share > 0:
                    color = 'white' if shade > 55 else 'black'
                    body.append(
                        f'\\node[font=\\scriptsize,text={color}] at ({column + 0.5:.2f},{y + 0.5:.2f}) '
                        f'{{{_num(round(share, 1))}}};'
                    )
        for row, (name, _counts) in enumerate(items):
            label = _fold_label(name, 10)
            y = len(items) - row + 0.5
            body.append(f'\\node[font=\\scriptsize,text=black,anchor=east] at (-0.15,{y:.2f}) {{{label}}};')
        for column, topic in enumerate(topics):
            body.append(
                f'\\node[font=\\scriptsize,rotate=45,anchor=north west] at ({column + 0.5:.2f},0) '
                f'{{{_esc(_localize_label(topic))}}};'
            )
        return (
            '\\begin{tikzpicture}[x=0.86cm,y=0.62cm]\n'
            + '\n'.join(body)
            + '\n\\end{tikzpicture}'
            + (
                f'\n\\par{{\\footnotesize\\textcolor{{black!60}}{{另有 {skipped} 个节点无话题标签，未画出。}}}}\n'
                if skipped
                else ''
            )
        )

    @classmethod
    def _biblio_graph3d(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', 'x', 'y', '连接', '频次'))
        links = cls._biblio_links(rows, names)
        max_freq = max((cls._biblio_float(rows[name]['频次'], 0.0) for name in names), default=1.0) or 1.0
        xs = [cls._biblio_float(rows[name]['x'], 0.0) for name in names]
        ys = [cls._biblio_float(rows[name]['y'], 0.0) for name in names]
        zs = (
            [cls._biblio_float(rows[name].get('中介中心性'), 0.0) for name in names]
            if '中介中心性' in df.columns
            else []
        )
        if not any(zs):
            zs = [cls._biblio_float(rows[name]['频次'], 0.0) / max_freq for name in names]
        min_x, max_x, min_y, max_y, min_z, max_z = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
        span_x = max_x - min_x or 1.0
        span_y = max_y - min_y or 1.0
        span_z = max_z - min_z or 1.0
        positions = {}
        for i, name in enumerate(names):
            x = (xs[i] - min_x) / span_x * 100
            y = (ys[i] - min_y) / span_y * 100
            z = (zs[i] - min_z) / span_z * 100
            positions[name] = ((x - y) * 0.07 + 7.5, (x + y) * 0.035 - z * 0.055 + 5.5, z)
        ranked = sorted(names, key=lambda name: (-cls._biblio_float(rows[name]['频次'], 0.0), name))
        labelled = set(ranked[:80])
        max_weight = max((link['value'] for link in links), default=1.0) or 1.0
        out = []
        for link in links[:180]:
            x1, y1, _z1 = positions[link['source']]
            x2, y2, _z2 = positions[link['target']]
            width = 0.2 + 2.2 * math.sqrt(max(0.0, link['value'] / max_weight))
            out.append(f'\\draw[black!14,line width={width:.2f}pt] ({x1:.2f},{y1:.2f}) -- ({x2:.2f},{y2:.2f});')
        for name in names:
            x, y, z = positions[name]
            frequency = cls._biblio_float(rows[name]['频次'], 0.0)
            radius = 0.06 + 0.34 * math.sqrt(max(0.0, frequency / max_freq))
            shade = int(35 + 45 * z / 100)
            out.append(f'\\draw[fill=cA!{shade},draw=cA,line width=0.55pt] ({x:.2f},{y:.2f}) circle ({radius:.2f});')
            if name in labelled:
                label_x = x + radius + 0.1
                out.append(f'\\node[lblbox,anchor=west,font=\\scriptsize] at ({label_x:.2f},{y:.2f}) {{{_esc(name)}}};')
        out.append(
            '\\node[font=\\scriptsize,text=black!60,anchor=south west] at (0,0)'
            '{等轴投影：z 轴为中介中心性（无该列时使用频次）；完整三维交互见 ECharts 图。};'
        )
        return '\\begin{tikzpicture}\n' + '\n'.join(out) + '\n\\end{tikzpicture}'

    @classmethod
    def _biblio_variation(cls, df) -> str:
        """Where each node's connection pattern moved, one marker per node × slice pair.

        Radius follows the square root of the divergence so equal CHANGES cover equal AREAS, and
        the fill darkens with it — the same two encodings the ECharts view uses, so a reader who
        saw the screen reads the paper. An empty cell is not zero: the node had no link in both
        slices of that pair, which is the case the algorithm refuses to score.

        Plain tikz coordinates, not a pgfplots axis with symbolic coords: the same lesson the
        heatmap figure learned, where ``xtick=data`` over an axis with no plotted series enumerates
        every coordinate again and the markers never land on the page."""
        cls._require_biblio(df, '节点', '起始年', '结束年', '结构变化')
        items = []
        for _, row in df.iterrows():
            name = cls._biblio_text(row.get('节点'))
            score = cls._biblio_float(row.get('结构变化'), 0.0)
            start = int(cls._biblio_float(row.get('起始年'), 0))
            end = int(cls._biblio_float(row.get('结束年'), 0))
            if not name or score <= 0 or not start or not end or end <= start:
                continue
            items.append((name, start, end, score))
        if not items:
            raise ChartConfigError(t('chart.biblio_no_variation'))
        pairs = sorted({(start, end) for _name, start, end, _score in items})
        strongest: dict[str, float] = {}
        for name, _start, _end, score in items:
            strongest[name] = max(score, strongest.get(name, 0.0))
        names = [name for name, _ in sorted(strongest.items(), key=lambda item: (-item[1], item[0]))][
            :VARIATION_ROW_LIMIT
        ]
        shown = set(names)
        max_score = max(score for name, *_rest, score in items if name in shown) or 1.0
        pair_at = {pair: index for index, pair in enumerate(pairs)}
        node_at = {name: index for index, name in enumerate(names)}
        cell_w = min(3.2, max(1.6, 12.0 / max(1, len(pairs))))
        cell_h = 0.85
        body = []
        for column in range(len(pairs) + 1):
            body.append(
                f'\\draw[black!8] ({column * cell_w:.2f},0) -- ({column * cell_w:.2f},{len(names) * cell_h:.2f});'
            )
        for row in range(len(names) + 1):
            body.append(f'\\draw[black!8] (0,{row * cell_h:.2f}) -- ({len(pairs) * cell_w:.2f},{row * cell_h:.2f});')
        for name, start, end, score in items:
            if name not in shown:
                continue
            ratio = min(1.0, score / max_score)
            center_x = (pair_at[(start, end)] + 0.5) * cell_w
            center_y = (len(names) - node_at[name] - 0.5) * cell_h
            radius = 0.06 + 0.17 * math.sqrt(ratio)
            shade = int(30 + 65 * ratio)
            body.append(
                f'\\fill[cA!{shade}] ({center_x:.2f},{center_y:.2f}) circle[radius={radius:.3f}cm];'
                f'\\node[font=\\tiny,text=black!70,anchor=west] at '
                f'({center_x + radius + 0.06:.2f},{center_y:.2f}) {{{_num(round(score, 3))}}};'
            )
        for index, name in enumerate(names):
            y = (len(names) - index - 0.5) * cell_h
            body.append(
                f'\\node[font=\\scriptsize,text=black,anchor=east] at (-0.12,{y:.2f}) {{{_fold_label(name, 11)}}};'
            )
        for index, (start, end) in enumerate(pairs):
            x = (index + 0.5) * cell_w
            body.append(
                f'\\node[font=\\scriptsize,rotate=35,anchor=north west,text=black!75] at ({x:.2f},-0.12) '
                f'{{{start}--{end}}};'
            )
        body.append(
            f'\\node[font=\\scriptsize,text=black!55,anchor=north] at '
            f'({len(pairs) * cell_w / 2:.2f},{-2.05 * cell_h:.2f}) {{{_esc(t("chart.biblio_pair"))}}};'
        )
        return '\\begin{tikzpicture}[x=1cm,y=1cm]\n' + '\n'.join(body) + '\n\\end{tikzpicture}'

    @classmethod
    def _biblio_dual_map(cls, df) -> str:
        cls._require_biblio(df, 'map', 'source', 'target', 'weight')
        edges = []
        seeded: dict[str, set[str]] = {'journal': set(), 'category': set()}
        for _, row in df.iterrows():
            side = cls._biblio_text(row.get('map')).lower()
            source = cls._biblio_text(row.get('source'))
            target = cls._biblio_text(row.get('target'))
            weight = cls._biblio_float(row.get('weight'), 0.0)
            if side not in ('journal', 'category', 'overlay') or not source:
                continue
            if not target:
                # The table lists its nodes too (empty 终点) so a journal with only overlay
                # links, or a category with only one, is still part of the figure.
                if side != 'overlay' and weight > 0:
                    seeded[side].add(source)
                continue
            if weight > 0:
                edges.append((side, source, target, weight))
        if not edges:
            raise ChartConfigError(t('chart.biblio_no_links'))
        # A same-side edge is undirected: both endpoints sit on that side's column.
        left = {source for side, source, _t, _w in edges if side in ('journal', 'overlay')}
        left |= {target for side, _s, target, _w in edges if side == 'journal'}
        right = {target for side, _s, target, _w in edges if side in ('category', 'overlay')}
        right |= {source for side, source, _t, _w in edges if side == 'category'}
        left |= seeded['journal']
        right |= seeded['category']
        left = sorted(left)[:60]
        right = sorted(right)[:60]
        if not left or not right:
            raise ChartConfigError(t('chart.biblio_no_nodes'))
        positions = {}
        for index, name in enumerate(left):
            positions[('journal', name)] = (2.0, 9.0 - index * (8.0 / max(1, len(left) - 1)))
        for index, name in enumerate(right):
            positions[('category', name)] = (14.0, 9.0 - index * (8.0 / max(1, len(right) - 1)))
        header = '\\node[font=\\small,text=black!65,anchor=south] at ({x},9.8) {{{label}}};'
        out = [
            header.format(x=2, label=_esc(t('chart.biblio_journal_map'))),
            header.format(x=14, label=_esc(t('chart.biblio_category_map'))),
            header.format(x=8, label=_esc(t('chart.biblio_overlay'))),
        ]
        max_weight = max(weight for *_rest, weight in edges) or 1.0
        for side, source, target, weight in edges:
            if side == 'overlay':
                a = positions.get(('journal', source))
                b = positions.get(('category', target))
                color = 'black!25'
            elif side == 'journal':
                a = positions.get(('journal', source))
                b = positions.get(('journal', target))
                color = 'cA!55'
            else:
                a = positions.get(('category', source))
                b = positions.get(('category', target))
                color = 'cB!55'
            if not a or not b:
                continue
            width = 0.2 + 2.5 * math.sqrt(max(0.0, weight / max_weight))
            out.append(
                f'\\draw[{color},line width={width:.2f}pt,opacity=0.55] '
                f'({a[0]:.2f},{a[1]:.2f}) -- ({b[0]:.2f},{b[1]:.2f});'
            )
        for (side, name), (x, y) in positions.items():
            color = 'cA' if side == 'journal' else 'cB'
            anchor = 'east' if side == 'journal' else 'west'
            offset = -0.25 if side == 'journal' else 0.25
            out.append(
                f'\\draw[fill={color}!55,draw={color},line width=0.55pt] ({x:.2f},{y:.2f}) circle (0.12);'
                f'\\node[lblbox,anchor={anchor},font=\\scriptsize] at ({x + offset:.2f},{y:.2f}) {{{_esc(name)}}};'
            )
        return '\\begin{tikzpicture}\n' + '\n'.join(out) + '\n\\end{tikzpicture}'

    @classmethod
    def _biblio_figure(cls, df, chart_type: str) -> str:
        if chart_type in ('knowledge_graph', 'circular', 'graph3d'):
            if chart_type == 'knowledge_graph':
                pic = cls._biblio_fixed_graph(df)
            elif chart_type == 'circular':
                pic = cls._biblio_circular(df)
            else:
                pic = cls._biblio_graph3d(df)
        elif chart_type == 'landscape':
            pic = cls._biblio_landscape(df)
        elif chart_type == 'cluster_timeline':
            pic = cls._biblio_timeline(df)
        elif chart_type == 'burst':
            pic = cls._biblio_burst(df)
        elif chart_type == 'timezone':
            pic = cls._biblio_timezone(df)
        elif chart_type == 'graph3d':
            pic = cls._biblio_graph3d(df)
        elif chart_type == 'dual_map':
            pic = cls._biblio_dual_map(df)
        elif chart_type == 'variation':
            pic = cls._biblio_variation(df)
        elif chart_type == 'geo_map':
            pic = cls._biblio_geo(df)
        elif chart_type == 'sentiment_overlay':
            pic = cls._biblio_sentiment(df)
        elif chart_type == 'topic_overlay':
            pic = cls._biblio_topic(df)
        elif chart_type == 'biblio_heatmap':
            pic = cls._biblio_heatmap(df)
        else:
            raise ChartConfigError(f'no bibliometric LaTeX figure for {chart_type}')
        return '\\begin{minipage}{17.5cm}\n' + pic + '\n' + cls._biblio_formulas(chart_type) + '\n\\end{minipage}'

    @classmethod
    def _biblio_table_data(cls, df, chart_type: str):
        if chart_type in ('knowledge_graph', 'circular', 'graph3d'):
            required = ['节点', '频次', '度', '中介中心性', '特征向量中心性', 'PageRank', 'Sigma']
            if '聚类标签' in df.columns:
                required.append('聚类标签')
            cls._require_biblio(df, *required)
            head = [_esc(column) for column in required]
            rows = []
            for _, row in df.iterrows():
                name = cls._biblio_text(row['节点'])
                if not name:
                    continue
                values = [_esc(name)]
                for column in required[1:]:
                    if column == '聚类标签':
                        values.append(_esc(cls._biblio_text(row.get(column))))
                    else:
                        values.append(_num(cls._biblio_float(row.get(column), 0.0)))
                rows.append(values)
            return head, rows
        if chart_type == 'sentiment_overlay':
            items, _skipped = cls._overlay_items(df, '情感分布', 'chart.biblio_no_sentiment')
            labels = cls._overlay_order(items)
            items = cls._overlay_ranked(items, set(labels) == set(POLARITY_LABELS))
            head = [_esc(t('biblio.col.节点')), _esc(t('biblio.col.情感倾向'))] + [
                _esc(_localize_label(label)) for label in labels
            ]
            table = []
            for name, counts in items[:OVERLAY_TABLE_LIMIT]:
                dominant = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
                table.append(
                    [_esc(name), _esc(_localize_label(dominant))] + [_num(counts.get(label, 0)) for label in labels]
                )
            return head, table
        if chart_type == 'topic_overlay':
            items, _skipped = cls._overlay_items(df, '话题分布', 'chart.biblio_no_topics')
            totals = {}
            for _name, counts in items:
                for topic, count in counts.items():
                    totals[topic] = totals.get(topic, 0) + count
            topics = sorted(totals, key=lambda topic: (-totals[topic], topic))[:OVERLAY_TOPIC_LIMIT]
            items = sorted(items, key=lambda item: (-sum(item[1].values()), item[0]))
            head = [_esc(t('biblio.col.节点'))] + [_esc(_localize_label(topic)) for topic in topics]
            table = [
                [_esc(name)] + [_num(counts.get(topic, 0)) for topic in topics]
                for name, counts in items[:OVERLAY_TABLE_LIMIT]
            ]
            return head, table
        if chart_type == 'variation':
            cls._require_biblio(df, '节点', '起始年', '结束年', '结构变化', '前邻居', '后邻居', '新增邻居', '消失邻居')
            items = []
            for _, row in df.iterrows():
                name = cls._biblio_text(row.get('节点'))
                score = cls._biblio_float(row.get('结构变化'), 0.0)
                if not name or score <= 0:
                    continue
                items.append(
                    (
                        name,
                        int(cls._biblio_float(row.get('起始年'), 0)),
                        int(cls._biblio_float(row.get('结束年'), 0)),
                        score,
                        int(cls._biblio_float(row.get('前邻居'), 0)),
                        int(cls._biblio_float(row.get('后邻居'), 0)),
                        cls._biblio_text(row.get('新增邻居')),
                        cls._biblio_text(row.get('消失邻居')),
                    )
                )
            items.sort(key=lambda item: (-item[3], item[0], item[1]))
            head = [
                _esc(t('biblio.col.节点')),
                _esc(t('biblio.col.起始年')),
                _esc(t('biblio.col.结束年')),
                _esc(t('biblio.col.结构变化')),
                _esc(t('biblio.col.前邻居')),
                _esc(t('biblio.col.后邻居')),
                _esc(t('biblio.col.新增邻居')),
                _esc(t('biblio.col.消失邻居')),
            ]
            rows = [
                [
                    _esc(name),
                    _num(start),
                    _num(end),
                    _num(round(score, 4)),
                    _num(before),
                    _num(after),
                    _esc(gained) or '—',
                    _esc(lost) or '—',
                ]
                for name, start, end, score, before, after, gained, lost in items
            ]
            return head, rows
        if chart_type == 'dual_map':
            cls._require_biblio(df, 'map', 'source', 'target', 'weight')
            # The table's own columns are machine tokens (a chart contract, not prose);
            # the paper table prints the same words the figure uses.
            sides = {
                'journal': t('chart.biblio_journal_map'),
                'category': t('chart.biblio_category_map'),
                'overlay': t('chart.biblio_overlay'),
            }
            rows = []
            for _, row in df.iterrows():
                side = cls._biblio_text(row.get('map')).lower()
                source = cls._biblio_text(row.get('source'))
                target = cls._biblio_text(row.get('target'))
                if not source or not target:
                    continue
                rows.append(
                    [
                        _esc(sides.get(side, side)),
                        _esc(source),
                        _esc(target),
                        _num(cls._biblio_float(row.get('weight'), 0.0)),
                    ]
                )
            return (
                [
                    _esc(t('chart.biblio_map_layer')),
                    _esc(t('chart.biblio_map_source')),
                    _esc(t('chart.biblio_map_target')),
                    _esc(t('chart.biblio_map_weight')),
                ],
                rows,
            )
        if chart_type == 'cluster_timeline':
            rows, names = cls._biblio_node_rows(df, ('节点', '聚类', '聚类标签', '首年', '末年', '频次'))
            groups = {}
            for name in names:
                cluster = cls._biblio_text(rows[name].get('聚类'))
                label = cls._biblio_text(rows[name].get('聚类标签')) or f'#{cluster}'
                key = f'#{cluster} {label}'
                first = int(cls._biblio_float(rows[name].get('首年'), 0))
                last = int(cls._biblio_float(rows[name].get('末年'), first))
                frequency = cls._biblio_float(rows[name].get('频次'), 0.0)
                group = groups.setdefault(key, {'nodes': 0, 'frequency': 0.0, 'years': []})
                group['nodes'] += 1
                group['frequency'] += frequency
                if first:
                    group['years'].extend([first, last])
            head = [_esc('聚类'), _esc('节点数'), _esc('首年'), _esc('末年'), _esc('总频次')]
            table = [
                [
                    _esc(key),
                    _num(group['nodes']),
                    _num(min(group['years']) if group['years'] else 0),
                    _num(max(group['years']) if group['years'] else 0),
                    _num(round(group['frequency'], 4)),
                ]
                for key, group in sorted(groups.items(), key=lambda item: (-item[1]['nodes'], item[0]))
            ]
            return head, table
        if chart_type == 'burst':
            rows, names = cls._biblio_node_rows(df, ('节点', '突现起始', '突现结束', '突现强度'))
            items = []
            for name in names:
                strength = cls._biblio_float(rows[name].get('突现强度'), 0.0)
                if strength <= 0:
                    continue
                items.append(
                    (
                        name,
                        int(cls._biblio_float(rows[name].get('突现起始'), 0)),
                        int(cls._biblio_float(rows[name].get('突现结束'), 0)),
                        strength,
                    )
                )
            items.sort(key=lambda item: (-item[3], item[0]))
            head = [_esc('节点'), _esc('起始'), _esc('结束'), _esc('强度 B')]
            return head, [[_esc(name), _num(start), _num(end), _num(strength)] for name, start, end, strength in items]
        if chart_type in ('timezone', 'biblio_heatmap'):
            rows, names = cls._biblio_node_rows(df, ('节点', '年份序列', '频次'))
            if chart_type == 'biblio_heatmap':
                cls._require_biblio(df, '聚类', '聚类标签')
            table = []
            years = set()
            for name in names:
                parsed = cls._biblio_parsed(rows[name].get('年份序列'), '年份序列')
                if not isinstance(parsed, dict):
                    continue
                counts = {int(float(year)): int(cls._biblio_float(count, 0)) for year, count in parsed.items()}
                years.update(counts)
                table.append((name, counts, cls._biblio_float(rows[name].get('频次'), 0.0)))
            if not years:
                raise ChartConfigError(t('chart.biblio_no_years'))
            year_list = sorted(years)
            if chart_type == 'biblio_heatmap':
                groups = {}
                for name, counts, _frequency in table:
                    cluster = cls._biblio_text(rows[name].get('聚类'))
                    label = cls._biblio_text(rows[name].get('聚类标签')) or f'#{cluster}'
                    key = f'#{cluster} {label}'
                    group = groups.setdefault(key, {year: 0 for year in year_list})
                    for year, count in counts.items():
                        group[year] += count
                ordered = sorted(groups.items(), key=lambda item: (-sum(item[1].values()), item[0]))[:40]
                head = [_esc('聚类')] + [_esc(str(year)) for year in year_list]
                return head, [[_esc(key)] + [_num(group[year]) for year in year_list] for key, group in ordered]
            head = [_esc('节点'), _esc('年份区间'), _esc('总频次')]
            rows_out = []
            for name, counts, frequency in sorted(table, key=lambda item: (-item[2], item[0]))[:80]:
                span = f'{min(counts)}--{max(counts)}' if counts else ''
                rows_out.append([_esc(name), _esc(span), _num(frequency)])
            return head, rows_out
        if chart_type == 'landscape':
            rows, names = cls._biblio_node_rows(df, ('节点', '聚类', '聚类标签', '频次'))
            groups = {}
            for name in names:
                cluster = cls._biblio_text(rows[name].get('聚类'))
                label = cls._biblio_text(rows[name].get('聚类标签')) or f'#{cluster}'
                key = f'#{cluster} {label}'
                group = groups.setdefault(key, {'nodes': [], 'frequency': 0.0})
                group['nodes'].append(name)
                group['frequency'] += cls._biblio_float(rows[name].get('频次'), 0.0)
            head = [_esc('聚类'), _esc('节点数'), _esc('总频次'), _esc('代表节点')]
            table = []
            for key, group in sorted(groups.items(), key=lambda item: (-item[1]['frequency'], item[0])):
                representatives = '、'.join(
                    sorted(group['nodes'], key=lambda x: (-cls._biblio_float(rows[x].get('频次'), 0), x))[:5]
                )
                table.append(
                    [_esc(key), _num(len(group['nodes'])), _num(round(group['frequency'], 4)), _esc(representatives)]
                )
            return head, table
        if chart_type == 'geo_map':
            cls._require_biblio(df, '节点', '频次')
            result = geo_aggregate(df.to_dict('records'))
            total = sum(value for _iso, value, _names in result['regions']) or 1.0
            head = [_esc(t('chart.biblio_geo')), _esc('频次'), _esc('占比'), _esc('并入的写法')]
            rows = [
                [
                    _esc(display(iso, 'zh') or iso),
                    _num(round(value, 4)),
                    _num(round(value / total * 100, 2)),
                    _esc('、'.join(names)) if names else '—',
                ]
                for iso, value, names in result['regions']
            ]
            if result['unknown']:
                # A row for what the map could not place: dropping it would make the table's total
                # look like the whole corpus when part of it simply has no region.
                rows.append(
                    [
                        _esc(
                            t(
                                'chart.biblio_geo_unknown',
                                n=len(result['unknown']),
                                names='、'.join(result['unknown'][:5]),
                            )
                        ),
                        _num(0),
                        _num(0),
                        '—',
                    ]
                )
            return head, rows
        raise ChartConfigError(f'no bibliometric LaTeX table for {chart_type}')

    # ── booktabs three-line table ─────────────────────────────────────

    @classmethod
    def _table_data(cls, df, chart_type, *, x, y, value_field, agg, y2, label_field, stack_fields, tokenize):
        if chart_type in BIBLIO_CHART_TYPES:
            return cls._biblio_table_data(df, chart_type)
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
