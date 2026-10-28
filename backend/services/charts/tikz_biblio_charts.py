"""Bibliometric LaTeX chart views: landscape, timeline, burst, geography, timezone,
heatmap, sentiment/topic overlays, variation and the dual map.
"""

import math

from i18n import t
from services.biblio.geo import aggregate as geo_aggregate
from services.biblio.geo import display
from services.charts.contracts import (
    OVERLAY_ROW_LIMIT,
    OVERLAY_TOPIC_LIMIT,
    POLARITY_LABELS,
    VARIATION_ROW_LIMIT,
)
from services.charts.visualizer import ChartConfigError, _localize_label

from .tikz_preamble import (
    _esc,
    _fold_label,
    _num,
    _sym,
)


class BiblioChartMixin:
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
