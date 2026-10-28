"""The three-line (booktabs) tables that go beside the bibliometric figures.

A table lists every value the figure draws, so a figure with a hidden tail still has a
complete printed record.
"""

from i18n import t
from services.biblio.geo import aggregate as geo_aggregate
from services.biblio.geo import display
from services.charts.contracts import OVERLAY_TABLE_LIMIT, OVERLAY_TOPIC_LIMIT, POLARITY_LABELS
from services.charts.visualizer import ChartConfigError, _localize_label

from .tikz_preamble import _esc, _num


class BiblioTableMixin:
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
        if chart_type == 'concentric':
            cls._require_biblio(df, '节点', '年份序列', '频次')
            buckets: dict[int, list[tuple[float, str]]] = {}
            unknown: list[tuple[float, str]] = []
            for _, row in df.iterrows():
                name = cls._biblio_text(row['节点'])
                if not name:
                    continue
                frequency = cls._biblio_float(row.get('频次'), 0.0)
                parsed = cls._biblio_parsed(row.get('年份序列'), '年份序列')
                year = 0
                if isinstance(parsed, dict) and parsed:
                    try:
                        year = min(int(key) for key in parsed)
                    except (TypeError, ValueError):
                        year = 0
                if year:
                    buckets.setdefault(year, []).append((frequency, name))
                else:
                    unknown.append((frequency, name))
            if not buckets:
                raise ChartConfigError(t('chart.biblio_no_years'))
            rings = [(str(year), buckets[year]) for year in sorted(buckets)]
            if unknown:
                rings.append((t('chart.biblio_ring_unknown'), unknown))
            head = [
                _esc(t('biblio.col.年份')),
                _esc(t('chart.biblio_ring_nodes')),
                _esc(t('chart.biblio_ring_reps')),
                _esc(t('chart.biblio_ring_total')),
            ]
            table = []
            for label, items in rings:
                ranked = sorted(items, key=lambda item: (-item[0], item[1]))
                table.append(
                    [
                        _esc(label),
                        _num(len(ranked)),
                        _esc('、'.join(name for _frequency, name in ranked[:3])),
                        _num(sum(frequency for frequency, _name in ranked)),
                    ]
                )
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
