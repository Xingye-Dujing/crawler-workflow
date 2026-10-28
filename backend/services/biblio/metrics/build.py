"""The public build: records → documents → network → rows → JSON links.

One function per stage is called in publication order, and every cap (node count,
edge count, link JSON size) refuses by name before a table is returned.
"""

from collections import Counter, defaultdict
from itertools import combinations

import networkx as nx
import pandas as pd

from i18n import t
from services.biblio import cluster as clustering
from services.biblio.metrics.measures import (
    _bursts,
    _layout,
    _metrics,
    _node_citation_stats,
    _node_sources,
    _node_usage_stats,
    _overlay_stats,
)
from services.biblio.metrics.network import (
    _max_links,
    _normalized_edges,
    _prune,
    _slice_graphs,
    _structural_variation,
    _threshold_edges,
)
from services.biblio.metrics.records import (
    ENTITY_LABEL_KEYS,
    BiblioError,
    _apply_cluster_overrides,
    _apply_label_rules,
    _document_references,
    _documents,
    _json,
    _node_metadata,
    _ref_key,
    _reference_nodes,
    _require_columns,
    _split,
    _unique_labels,
)
from services.biblio.schema import LIMITS, normalize_params

# ─── Public build ───────────────────────────────────────────────


def _basemap_lookup(basemap_df: pd.DataFrame, nid: str = '') -> dict[str, list[str]]:
    """The journal → categories table a dual-map reads, or the refusal that names the node."""
    if basemap_df is None or basemap_df.empty:
        raise BiblioError(t('biblio.dual_map_needs_basemap', nid=nid or '(biblio)'))
    journal_column = next(
        (c for c in basemap_df.columns if _ref_key(c) in {'期刊', 'journal', 'source', '来源期刊'}), ''
    )
    category_column = next(
        (c for c in basemap_df.columns if _ref_key(c) in {'学科', 'category', 'subject', 'wc', 'sc'}), ''
    )
    if not journal_column or not category_column:
        raise BiblioError(
            t(
                'biblio.dual_map_columns',
                journal=journal_column or '期刊/journal',
                category=category_column or '学科/category',
            )
        )
    mapping: dict[str, list[str]] = defaultdict(list)
    for _, row in basemap_df.iterrows():
        journal = str(row.get(journal_column) or '').strip()
        categories = _split(row.get(category_column))
        if not journal or not categories:
            continue
        for category in categories:
            if category not in mapping[journal]:
                mapping[journal].append(category)
    return dict(mapping)


def build_dual_map(df: pd.DataFrame, params: dict, basemap_df: pd.DataFrame | None, nid: str = '') -> dict:
    """Build the journal/category dual-map table from records plus a basemap."""
    columns = _require_columns(df, params)
    mapping = _basemap_lookup(basemap_df, nid)
    cited_edges: Counter = Counter()
    category_edges: Counter = Counter()
    overlay: Counter = Counter()
    cited_labels: dict[str, str] = {}
    for _, row in df.iterrows():
        record = row.to_dict()
        raw_refs, structured = _document_references(record, columns)
        nodes, _, _ = _reference_nodes(raw_refs, 'journal_cocitation', structured)
        cited = []
        for key, info in nodes.items():
            label = str(info.get('label') or key).strip()
            if label:
                cited.append(label)
                cited_labels.setdefault(label, label)
        cited = sorted(set(cited))
        for left, right in combinations(cited, 2):
            cited_edges[(left, right)] += 1
        source_journal = (
            str(record.get(columns['entity']) or '').strip()
            if params['entity_type'] in ('journal', 'source')
            else str(record.get('来源期刊') or '').strip()
        )
        record_categories = _split(record.get('学科'))
        if not record_categories and source_journal:
            record_categories = mapping.get(source_journal, [])
        record_categories = sorted(set(record_categories))
        for left, right in combinations(record_categories, 2):
            category_edges[(left, right)] += 1
        for journal in cited:
            for category in record_categories:
                overlay[(journal, category)] += 1
    rows: list[dict] = []
    left_nodes = sorted({name for pair in cited_edges for name in pair} | {name for name, _ in overlay})
    right_nodes = sorted({name for pair in category_edges for name in pair} | {name for _, name in overlay})
    for index, name in enumerate(left_nodes[:120]):
        rows.append(
            {
                'map': 'journal',
                'source': name,
                'target': '',
                'weight': sum(value for pair, value in cited_edges.items() if name in pair),
                'label': name,
                'x': 150,
                # Rounded because this column is also a table cell the workspace and the CSV
                # show: 「97.36842105263159」 is a layout artifact, not a measurement.
                'y': round(50 + index * (900 / max(1, min(len(left_nodes), 120) - 1)), 2),
            }
        )
    for index, name in enumerate(right_nodes[:120]):
        rows.append(
            {
                'map': 'category',
                'source': name,
                'target': '',
                'weight': sum(value for pair, value in category_edges.items() if name in pair),
                'label': name,
                'x': 850,
                'y': round(50 + index * (900 / max(1, min(len(right_nodes), 120) - 1)), 2),
            }
        )
    for (left, right), weight in cited_edges.items():
        rows.append(
            {'map': 'journal', 'source': left, 'target': right, 'weight': weight, 'label': '', 'x': '', 'y': ''}
        )
    for (left, right), weight in category_edges.items():
        rows.append(
            {'map': 'category', 'source': left, 'target': right, 'weight': weight, 'label': '', 'x': '', 'y': ''}
        )
    for (left, right), weight in overlay.items():
        rows.append(
            {'map': 'overlay', 'source': left, 'target': right, 'weight': weight, 'label': '', 'x': '', 'y': ''}
        )
    if not any(row['source'] and row['target'] for row in rows):
        raise BiblioError(t('biblio.no_edges', start='', end=''))
    summary = {
        'entity_type': params['entity_type'],
        'window': {},
        'slices': 0,
        'nodes': len(left_nodes) + len(right_nodes),
        'edges': len(cited_edges) + len(category_edges) + len(overlay),
        'pruning': params['pruning'],
        'link_measure': params['link_measure'],
        'clusters': None,
        'bursts': 0,
        'variation': 0,
        'output_shape': 'dual_map',
        'notes': [t('biblio.dual_map_done', journals=len(left_nodes), categories=len(right_nodes))],
    }
    return {
        'rows': rows,
        'edges': rows,
        'bursts': [],
        'clusters': [],
        'variation': [],
        'graph': None,
        'summary': summary,
        'notes': summary['notes'],
    }


def build(df: pd.DataFrame, params: dict, nid: str = '', basemap_df: pd.DataFrame | None = None) -> dict:
    """Build the node table and every artifact the Visualize node may need."""
    params = normalize_params(params, nid)
    if params['output_shape'] == 'dual_map':
        return build_dual_map(df, params, basemap_df, nid)
    notes: list[str] = []
    docs, ref_nodes, window, doc_notes = _documents(df, params)
    notes += doc_notes
    params['start'] = window['start']
    labels, year_counts, node_docs, node_years = _node_metadata(docs, params, ref_nodes)
    labels, year_counts, node_docs, node_years, rule_notes = _apply_label_rules(
        labels, year_counts, node_docs, node_years, docs, params
    )
    notes += rule_notes
    if not labels:
        raise BiblioError(t('biblio.no_records'))

    # Charts address a node by its name, so the display label is the graph key.
    # A duplicate title (two cited works, same wording) gets a suffix instead
    # of collapsing two nodes into one bubble.
    display = _unique_labels(labels)
    if any(display[key] != key for key in labels):
        for doc in docs:
            doc['entities'] = [display[name] for name in doc['entities'] if name in display]
        labels = {display[key]: display[key] for key in display}
        year_counts = {display[key]: counts for key, counts in year_counts.items()}
        node_docs = {display[key]: indices for key, indices in node_docs.items()}
        node_years = {display[key]: year for key, year in node_years.items()}

    total_freq, merged_edges, merged_weights, edge_slices, slice_meta = _slice_graphs(
        docs, params, (labels, year_counts, node_docs, node_years)
    )
    notes += params.pop('_notes', [])
    variation_rows: list[dict] = []
    if params['variation']:
        if len(slice_meta['counts']) < 2:
            # Two slices are the minimum a "change between them" can be measured over; one
            # slice is a snapshot, and reporting zeros for every node would read as stability.
            raise BiblioError(t('biblio.variation_needs_slices', n=len(slice_meta['counts'])))
        rows, variation_notes = _structural_variation(slice_meta['counts'], slice_meta['freqs'], params)
        variation_rows += rows
        notes += variation_notes
    if not merged_edges:
        raise BiblioError(t('biblio.no_edges', start=window['start'], end=window['end']))
    edges = _normalized_edges(merged_edges, total_freq, params['link_measure'], merged_weights)
    if not edges:
        raise BiblioError(t('biblio.no_edges', start=window['start'], end=window['end']))
    edges = _threshold_edges(edges, total_freq, params)
    if not edges:
        raise BiblioError(t('biblio.no_edges_after_threshold'))
    edges = _max_links(edges, params)
    edges = _prune(edges, edge_slices, params, notes)
    if not edges:
        raise BiblioError(t('biblio.no_edges_after_prune', pruning=params['pruning']))

    final_nodes = sorted({name for key in edges for name in key})
    dropped = len(set(labels) - set(final_nodes))
    if dropped:
        notes.append(t('biblio.isolates_dropped', n=dropped))
    if not final_nodes:
        raise BiblioError(t('biblio.no_edges', start=window['start'], end=window['end']))
    if len(final_nodes) > LIMITS['max_nodes']:
        raise BiblioError(t('biblio.too_many_nodes', n=len(final_nodes), cap=LIMITS['max_nodes']))
    if len(edges) > LIMITS['max_edges']:
        raise BiblioError(t('biblio.too_many_edges', n=len(edges), cap=LIMITS['max_edges']))

    graph = nx.Graph()
    for name in final_nodes:
        graph.add_node(name)
    for (left, right), info in edges.items():
        graph.add_edge(left, right, weight=info['weight'], count=info['count'])

    if params['largest_component']:
        components = list(nx.connected_components(graph))
        if len(components) > 1:
            largest = sorted(components, key=lambda members: (-len(members), min(members)))[0]
            keep = set(largest)
            before = len(final_nodes)
            edges = {key: info for key, info in edges.items() if key[0] in keep and key[1] in keep}
            final_nodes = sorted({name for key in edges for name in key})
            if not edges:
                raise BiblioError(t('biblio.no_edges_after_component'))
            graph = nx.Graph()
            graph.add_nodes_from(final_nodes)
            for (left, right), info in edges.items():
                graph.add_edge(left, right, weight=info['weight'], count=info['count'])
            notes.append(t('biblio.largest_component', before=before, after=len(final_nodes)))

    metrics = _metrics(graph, final_nodes, notes)
    input_columns = set(df.columns)
    citation_stats = _node_citation_stats(final_nodes, node_docs, docs) if params['tc_column'] in input_columns else {}
    usage_stats = _node_usage_stats(final_nodes, node_docs, docs) if params['usage_column'] in input_columns else {}
    # Only a fused record table carries 来源, so only there does the node table grow the
    # provenance columns. A plain literature run must not gain an all-empty 来源 it cannot justify.
    source_stats = _node_sources(final_nodes, node_docs, docs) if '来源' in input_columns else {}
    sentiment_stats = {}
    topic_stats = {}
    for param, key, bucket in (
        ('sentiment_column', 'sentiment_label', sentiment_stats),
        ('topic_column', 'topic_label', topic_stats),
    ):
        column = params[param]
        if not column:
            continue
        bucket.update(_overlay_stats(final_nodes, node_docs, docs, key))
        if not bucket:
            # The column has labels (``_documents`` refused otherwise), but every labelled
            # document's entities were dropped by selection/thresholds. The graph is still valid;
            # the overlay is empty, and that is a fact about the run worth printing.
            notes.append(t('biblio.overlay_no_nodes', col=column))
    bursts: dict[str, dict] = {}
    burst_rows: list[dict] = []
    if params['burst']:
        bursts, burst_rows, burst_notes = _bursts(
            final_nodes,
            year_counts,
            Counter(doc['year'] for doc in docs),
            window['start'],
            window['end'],
            params,
        )
        notes += burst_notes
        if len(bursts) > params['burst_top']:
            keep = {
                name
                for name, _ in sorted(bursts.items(), key=lambda item: (-item[1]['strength'], item[0]))[
                    : params['burst_top']
                ]
            }
            notes.append(t('biblio.burst_truncated', kept=len(keep), total=len(bursts)))
            bursts = {name: info for name, info in bursts.items() if name in keep}

    clusters = None
    if params['cluster']:
        clusters = clustering.cluster_graph(
            graph,
            final_nodes,
            {name: node_docs.get(name, set()) for name in final_nodes},
            [doc['terms'] for doc in docs],
            params['cluster_count'],
            params['label_method'],
            params['top_terms'],
        )
        if clusters.get('fallback'):
            notes.append(
                t(
                    'biblio.label_fallback',
                    asked=params['label_method'],
                    used=clusters['summary']['method'],
                )
            )
        applied, unmatched = _apply_cluster_overrides(clusters, params.get('cluster_labels') or '')
        if applied:
            notes.append(t('biblio.cluster_labels_applied', n=applied))
        for key in unmatched:
            notes.append(t('biblio.cluster_label_unmatched', cluster=key))

    positions = _layout(graph, final_nodes)
    type_label = t(ENTITY_LABEL_KEYS[params['entity_type']])
    rows: list[dict] = []
    for name in sorted(final_nodes, key=lambda item: (-total_freq.get(item, 0), item)):
        counts = year_counts.get(name, Counter())
        years = sorted(counts)
        link_items = []
        for neighbor in graph.neighbors(name):
            data = graph.edges[name, neighbor]
            link_items.append(
                {
                    'target': neighbor,
                    'value': round(float(data.get('weight') or 0.0), 6),
                    'count': int(data.get('count') or 0),
                }
            )
        link_items.sort(key=lambda item: (-item['value'], item['target']))
        links = _json(link_items)
        if len(links.encode('utf-8')) > LIMITS['max_links_json']:
            raise BiblioError(t('biblio.links_too_large', node=name, cap=LIMITS['max_links_json']))
        burst = bursts.get(name, {})
        row = {
            '节点': labels.get(name) or name,
            '类型': type_label,
            '频次': int(total_freq.get(name, 0)),
            '首年': years[0] if years else '',
            '末年': years[-1] if years else '',
            '年份序列': _json({str(year): int(counts[year]) for year in years}),
            '度': metrics[name]['度'],
            '中介中心性': metrics[name]['中介中心性'],
            '特征向量中心性': metrics[name]['特征向量中心性'],
            'PageRank': metrics[name]['PageRank'],
            'Sigma': round((metrics[name]['中介中心性'] + 1.0) ** burst.get('strength', 0.0), 6),
            'x': positions[name][0],
            'y': positions[name][1],
            '连接': links,
        }
        if citation_stats:
            row.update(citation_stats.get(name, {'总被引': 0.0, 'H指数': 0}))
        if usage_stats:
            row['使用次数合计'] = usage_stats.get(name, 0.0)
        if source_stats:
            row['来源'] = ';'.join(source_stats.get(name) or [])
            row['跨源'] = len(source_stats.get(name) or ()) > 1
        if params['sentiment_column']:
            stat = sentiment_stats.get(name)
            row['情感倾向'] = stat['dominant'] if stat else ''
            row['情感分布'] = _json(stat['counts']) if stat else '{}'
        if params['topic_column']:
            stat = topic_stats.get(name)
            row['主导话题'] = stat['dominant'] if stat else ''
            row['话题分布'] = _json(stat['counts']) if stat else '{}'
        if clusters is not None:
            cluster = clusters['members'].get(name, {})
            row['聚类'] = int(cluster.get('cluster', 0))
            row['聚类标签'] = cluster.get('cluster_label', '')
            row['轮廓值'] = cluster.get('silhouette', 0.0)
        if params['burst']:
            row['突现强度'] = round(burst.get('strength', 0.0), 6)
            row['突现起始'] = burst.get('start', '')
            row['突现结束'] = burst.get('end', '')
        rows.append(row)

    edge_rows = [
        {
            'source': left,
            'target': right,
            'weight': round(info['weight'], 6),
            'count': info['count'],
        }
        for (left, right), info in sorted(edges.items())
    ]
    cluster_rows = []
    if clusters is not None:
        by_cluster: dict[int, list[str]] = defaultdict(list)
        for name, info in clusters['members'].items():
            by_cluster[info['cluster']].append(labels.get(name) or name)
        for cluster_id, members in sorted(by_cluster.items()):
            cluster_rows.append(
                {
                    '聚类': cluster_id,
                    '聚类标签': clusters['members'][next(iter(members))]['cluster_label'] if members else '',
                    '节点数': len(members),
                    '节点': '；'.join(sorted(members)),
                    '轮廓值': clusters['cluster_silhouette'].get(cluster_id, 0.0),
                }
            )
    summary = {
        'entity_type': params['entity_type'],
        'window': window,
        'slices': slice_meta['slices'],
        'nodes': len(final_nodes),
        'edges': len(edges),
        'pruning': params['pruning'],
        'link_measure': params['link_measure'],
        'clusters': clusters['summary'] if clusters else None,
        'bursts': len(bursts),
        'variation': len(variation_rows),
        'output_shape': params['output_shape'],
        'notes': notes,
    }
    if params['sentiment_column'] or params['topic_column']:
        # Only when the node really overlaid something: an unconditional pair of blank strings
        # would make every summary claim it had an overlay of nothing.
        summary['overlay'] = {'sentiment': params['sentiment_column'], 'topic': params['topic_column']}
    return {
        'rows': rows,
        'edges': edge_rows,
        'bursts': burst_rows,
        'clusters': cluster_rows,
        'variation': variation_rows,
        'graph': graph,
        'summary': summary,
        'notes': notes,
    }
