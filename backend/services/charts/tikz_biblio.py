"""Bibliometric LaTeX figures: the shared readers, the graph shapes and the dispatch.

The fixed graph, circular and concentric views are the shapes CiteSpace-style figures use;
every other bibliometric view lives in ``tikz_biblio_charts`` and the three-line tables in
``tikz_biblio_tables``. The three mixins are assembled into one service by ``tikz``.
"""

import json
import math

import pandas as pd

from i18n import t
from services.charts.contracts import (
    OVERLAY_ROW_LIMIT,
    OVERLAY_TABLE_LIMIT,
    OVERLAY_TOPIC_LIMIT,
)
from services.charts.visualizer import ChartConfigError, VisualizationService

from .tikz_preamble import (
    _CYCLE_NAMES,
    _esc,
)


class BiblioFigureMixin:
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
        VisualizationService.require_columns(df, *columns)

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
                # The layout's two numbers are geometry the reader cannot recover from the picture:
                # which ring a node sits on, and where inside the ring it was put.
                '\\medskip\\par{\\footnotesize\\textbf{同心环布局：}'
                r'第 $k$ 个环的半径 $r_k=r_0+k\,\Delta r$（$r_0=\Delta r$，内环为最早年份），'
                r'环内按频次降序排布，第 $i$ 个节点的角度 $\theta_i=\frac{2\pi i}{n_k}+0.35k$，'
                r'坐标为 $(r_k\cos\theta_i,\ r_k\sin\theta_i)$；'
                r'没有年份的节点单独成最外一环并标明。'
                '}\n'
                if chart_type == 'concentric'
                else ''
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

        def _candidates() -> list:
            return [(name, spots[name][0], spots[name][1], spots[name][2], fonts[name]) for name in ranked[:120]]

        labelled = cls._fit_labels(_candidates(), scale)
        scale = cls._picture_scale(14.1, 8.1, max(cls._label_cm(n, fonts[n]) for n in labelled))
        labelled = cls._fit_labels(_candidates(), scale)
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
        return cls._graph_tikz(links)

    @classmethod
    def _biblio_concentric(cls, df) -> str:
        rows, names = cls._biblio_node_rows(df, ('节点', '年份序列', '频次'))
        links = cls._biblio_links(rows, names)
        buckets: dict[int, list[str]] = {}
        unknown: list[str] = []
        for name in names:
            parsed = cls._biblio_parsed(rows[name].get('年份序列'), '年份序列')
            year = 0
            if isinstance(parsed, dict) and parsed:
                try:
                    year = min(int(key) for key in parsed)
                except (TypeError, ValueError):
                    year = 0
            if year:
                buckets.setdefault(year, []).append(name)
            else:
                unknown.append(name)
        if not buckets:
            raise ChartConfigError(t('chart.biblio_no_years'))
        rings = [(str(year), buckets[year]) for year in sorted(buckets)]
        if unknown:
            rings.append((t('chart.biblio_ring_unknown'), unknown))
        max_freq = max((cls._biblio_float(rows[name]['频次'], 0.0) for name in names), default=1.0) or 1.0
        pos: dict[str, tuple[float, float]] = {}
        colors: dict[str, str] = {}
        for ring, (_label, ring_names) in enumerate(rings):
            radius = 1.9 * (ring + 1)
            ordered = sorted(ring_names, key=lambda name: (-cls._biblio_float(rows[name]['频次'], 0.0), name))
            for index, name in enumerate(ordered):
                angle = 2.0 * math.pi * index / len(ordered) + 0.35 * ring
                pos[name] = (radius * math.cos(angle), radius * math.sin(angle))
                colors[name] = cls._biblio_color(ring)
        order = [name for _label, ring_names in rings for name in ring_names]
        index_of = {name: index for index, name in enumerate(order)}
        spots = {}
        for name in order:
            x, y = pos[name]
            radius = 0.12 + 0.42 * math.sqrt(max(0.0, cls._biblio_float(rows[name]['频次'], 0.0) / max_freq))
            norm = math.hypot(x, y) or 1.0
            ux, uy = x / norm, y / norm
            spots[name] = (
                x,
                y,
                radius,
                x + ux * (radius + 0.22),
                y + uy * (radius + 0.22),
                'east' if ux >= 0 else 'west',
            )
        font = {name: r'\scriptsize' for name in order}
        ranked = sorted(order, key=lambda name: (-cls._biblio_float(rows[name]['频次'], 0.0), name))

        def _candidates() -> list:
            return [(name, spots[name][5], spots[name][3], spots[name][4], font[name]) for name in ranked]

        outer = 1.9 * len(rings)
        scale = cls._picture_scale(2 * outer, 2 * outer, max(cls._label_cm(name, font[name]) for name in order))
        held = cls._fit_labels(_candidates(), scale)
        scale = cls._picture_scale(2 * outer, 2 * outer, max(cls._label_cm(name, font[name]) for name in held))
        held = cls._fit_labels(_candidates(), scale)
        out = [
            f'\\coordinate (n{index}) at ({pos[name][0]:.2f},{pos[name][1]:.2f});' for index, name in enumerate(order)
        ]
        for ring, (label, _ring_names) in enumerate(rings):
            radius = 1.9 * (ring + 1)
            out.append(f'\\draw[black!10,dashed,line width=0.4pt] (0,0) circle ({radius:.2f});')
            out.append(
                f'\\node[font=\\scriptsize,text=black!55,anchor=east] at ({-radius - 0.1:.2f},0) {{{_esc(label)}}};'
            )
        biggest = max(link['value'] for link in links) or 1.0
        for link in links:
            width = max(0.3, 3.2 * math.sqrt(link['value'] / biggest))
            out.append(
                f'\\draw[black!12,line width={width:.2f}pt] '
                f'(n{index_of[link["source"]]}) -- (n{index_of[link["target"]]});'
            )
        for name in order:
            x, y, radius, lx, ly, side = spots[name]
            draw = (
                f'\\draw[fill={colors[name]}!45,draw={colors[name]},line width=0.7pt] '
                f'(n{index_of[name]}) circle ({radius:.2f});'
            )
            if name in held:
                anchor = 'west' if side == 'east' else 'east'
                draw += (
                    f'\\draw[leadline] ({x + (lx - x) * 0.7:.2f},{y + (ly - y) * 0.7:.2f}) -- ({lx:.2f},{ly:.2f});'
                    f'\\node[font={font[name]},anchor={anchor},text=black] at ({lx:.2f},{ly:.2f}) {{{_esc(name)}}};'
                )
            out.append(draw)
        if len(held) < len(order):
            out.append(
                f'\\node[font=\\scriptsize,text=black!55,anchor=north] at (0,{-(outer + 1.0):.2f})'
                f'{{已省略 {len(order) - len(held)} 个会互相遮盖的节点标签；完整节点见三线表。}};'
            )
        return f'\\begin{{tikzpicture}}[x={scale:.3f}cm,y={scale:.3f}cm]\n' + '\n'.join(out) + '\n\\end{tikzpicture}'

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
        elif chart_type == 'concentric':
            pic = cls._biblio_concentric(df)
        else:
            raise ChartConfigError(f'no bibliometric LaTeX figure for {chart_type}')
        return '\\begin{minipage}{17.5cm}\n' + pic + '\n' + cls._biblio_formulas(chart_type) + '\n\\end{minipage}'
