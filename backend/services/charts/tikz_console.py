"""Console chart types: bars, lines, scatter, box, pie, heatmap, topics, relations,
word cloud, bubble map, and the booktabs table they share.

These are the figures the on-screen palette offers; the bibliometric views live in
``tikz_biblio``. Every builder reads the same helpers ``VisualizationService`` uses,
so the printed and drawn values cannot disagree.
"""

import math

import pandas as pd

from i18n import t
from services.charts.contracts import BIBLIO_CHART_TYPES
from services.charts.tikz_preamble import (
    _CHINA_LAT0,
    _CHINA_LAT1,
    _CHINA_LON0,
    _CHINA_LON1,
    _CYCLE_NAMES,
    _PROVINCE_CENTROIDS,
    GRAPH_BOX_CM,
    GRAPH_LINE_CM,
    _cat_axis,
    _esc,
    _fold_label,
    _num,
    _sym,
)
from services.charts.visualizer import (
    ChartConfigError,
    VisualizationService,
    _box_stats,
    _finite,
    _histogram_bins,
    _localize_label,
)


class ConsoleFigureMixin:
    @staticmethod
    def _require_pair(x, y, what):
        if not x or not y:
            raise ChartConfigError(f'{what} LaTeX requires both fields (x and y)')
        VisualizationService.require_columns(pd.DataFrame({x: [0], y: [0]}), x, y)

    # ── categorical bar / line ────────────────────────────────────────

    @classmethod
    def _bars_or_line(cls, df, chart_type, x, y, agg):
        if not x:
            raise ChartConfigError(f'{chart_type} LaTeX requires a category field (x)')
        labels, values = VisualizationService.aggregate(df, x, y, agg)
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
        labels, left = VisualizationService.aggregate(df, x, y, agg)
        _, right = VisualizationService.aggregate(df, x, y2, agg2 or 'mean')
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
        VisualizationService.require_columns(df, x, *fields)
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
        VisualizationService.require_columns(df, x, y)
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
        VisualizationService.require_columns(df, x)
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
        labels, values = VisualizationService.aggregate(df, x, y, agg)
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
        xcats, ycats, matrix = VisualizationService.pivot(df, x, y, value_field, agg)
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
        VisualizationService.require_columns(df, x, y)
        first = pd.to_numeric(df[x], errors='coerce')
        second = pd.to_numeric(df[y], errors='coerce')
        has_size = bool(value_field) and value_field in df.columns
        sizes = pd.to_numeric(df[value_field], errors='coerce').tolist() if has_size else [None] * len(df)
        # pd.to_numeric(errors='coerce') leaves NaN where a cell was not a number, and the
        # no-value-field branch fills None; both mean "no bubble size here".
        biggest = max((s for s in sizes if pd.notna(s)), default=0.0)
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
            if biggest and pd.notna(size):
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
        VisualizationService.require_columns(df, x, y, y2)
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
        _, links = VisualizationService.sankey_links(df, x, y, value_field, agg)
        if not links:
            raise ChartConfigError(f'{x}/{y} yields no {("sankey" if ribbons else "network")} edges to draw')
        return cls._sankey_tikz(links) if ribbons else cls._graph_tikz(links)

    @staticmethod
    def _incident(links):
        inc = {}
        for link in links:
            for name in (link['source'], link['target']):
                inc[name] = inc.get(name, 0.0) + link['value']
        return inc

    @classmethod
    def _sankey_tikz(cls, links) -> str:
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
    def _graph_tikz(cls, links) -> str:
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

        def _candidates() -> list:
            return [(name, spots[name][5], spots[name][3], spots[name][4], fonts[name]) for name in ranked]

        # Sized in two passes because the two quantities depend on each other: the scale is set by the
        # widest label, and which labels survive the de-collision is decided at that scale.
        scale = cls._picture_scale(2 * radius, 2 * radius, max(cls._label_cm(n, fonts[n]) for n in names))
        held = cls._fit_labels(_candidates(), scale)
        scale = cls._picture_scale(2 * radius, 2 * radius, max(cls._label_cm(n, fonts[n]) for n in held))
        held = cls._fit_labels(_candidates(), scale)
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
            labels, values = VisualizationService.aggregate(df, x, value_field, agg)
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
        labels, values = VisualizationService.aggregate(df, x, value_field, agg)
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

    @classmethod
    def _table_data(cls, df, chart_type, *, x, y, value_field, agg, y2, label_field, stack_fields):
        if chart_type in BIBLIO_CHART_TYPES:
            return cls._biblio_table_data(df, chart_type)
        if chart_type == 'stack_pct':
            fields = [s.strip() for s in str(stack_fields or '').replace('，', ',').split(',') if s.strip()]
            if not x or not fields:
                raise ChartConfigError('stack_pct LaTeX table requires a category field (x) and stacked fields')
            VisualizationService.require_columns(df, x, *fields)
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
            _, links = VisualizationService.sankey_links(df, x, y, value_field, agg)
            head = [_esc(_localize_label(x)), _esc(_localize_label(y)), _esc(value_field or t('chart.count'))]
            return head, [[_esc(lk['source']), _esc(lk['target']), _num(lk['value'])] for lk in links]
        if chart_type == 'topic_map':
            VisualizationService.require_columns(df, x, y)
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
            VisualizationService.require_columns(df, x, y, y2)
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
        labels, values = VisualizationService.aggregate(df, x, y, agg)
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
