"""Snapshots and file export for a bibliometric build.

A snapshot keeps the two halves a comparison reads (rows and links) without holding
the same edge twice; the Pajek export is the one graph dialect the field exchanges.
"""

import json
from pathlib import Path

import networkx as nx
import pandas as pd


def snapshot_capture(rows: list[dict]) -> dict:
    """Split a stored bibliometrics table into the two things a comparison reads.

    ``nodes`` keeps one row per entity WITHOUT its adjacency — ``连接``/``年份序列`` are
    re-derived into ``edges`` here, and holding the same links in two places is how a snapshot
    starts disagreeing with itself. An edge is stored once per unordered pair, at its strongest
    weight, because a node table lists each undirected link from both ends.
    """
    nodes: list[dict] = []
    edges: dict[tuple, dict] = {}

    def remember(source: str, target: str, weight, count):
        if not source or not target:
            return
        key = (source, target) if source <= target else (target, source)
        value = _as_float(weight, 0.0)
        best = edges.get(key)
        if best is None or value > best['weight']:
            edges[key] = {'source': key[0], 'target': key[1], 'weight': value, 'count': _as_int(count)}

    for row in rows or ():
        source = str(row.get('source') or '').strip()
        target = str(row.get('target') or '').strip()
        name = str(row.get('节点') or '').strip()
        if source and target:
            remember(source, target, row.get('weight'), row.get('count'))
            continue
        # A dual-map table has no `节点` column: it names its entities in `source` and marks the
        # node rows by an empty `target`. Reading only `节点` captured none of them, so a
        # dual-map snapshot stored its links and lost its nodes.
        if not name:
            name = source
        if not name:
            continue
        nodes.append(
            {key: (value if key != '节点' else name) for key, value in row.items() if key not in ('连接', '年份序列')}
        )
        if '节点' not in row:
            nodes[-1]['节点'] = name
        for link in _as_list(row.get('连接')):
            remember(name, str(link.get('target') or ''), link.get('value'), link.get('count'))

    return {'nodes': nodes, 'edges': sorted(edges.values(), key=lambda e: (e['source'], e['target']))}


def _as_float(value, default: float = 0.0) -> float:
    try:
        text = str(value).strip()
        return default if text == '' else float(text)
    except (TypeError, ValueError):
        return default


def _as_int(value) -> int:
    return int(_as_float(value, 0.0))


def _as_list(value) -> list[dict]:
    """A JSON-text adjacency cell, already parsed by the caller or raw from the table."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _pajek_label(name: str) -> str:
    """One node name as a Pajek label: always quoted, inner quotes and line breaks folded."""
    text = ' '.join(str(name).split()) or 'node'
    return '"' + text.replace('"', "'") + '"'


def _pajek_text(graph) -> str:
    """The network as Pajek ``.net``: vertices in a stable order, then weighted edges.

    Written here rather than through ``networkx.write_pajek`` because that writer emits a
    ``UserWarning`` for every non-string edge attribute (ours carries ``count``) — a warning is
    a defect this project fixes, never mutes — and its trailing coordinate columns are noise in
    a file someone opens in Pajek.
    """
    names = sorted(str(name) for name in graph.nodes())
    index = {name: position + 1 for position, name in enumerate(names)}
    lines = [f'*Vertices {len(names)}']
    lines += [f'{index[name]} {_pajek_label(name)}' for name in names]
    lines.append('*Edges')
    edges = []
    for left, right, data in graph.edges(data=True):
        a, b = index[str(left)], index[str(right)]
        edges.append((min(a, b), max(a, b), float(data.get('weight') or 0.0)))
    lines += [f'{a} {b} {weight:.6f}' for a, b, weight in sorted(edges)]
    return '\n'.join(lines) + '\n'


def export_result(result: dict, out_dir: str, base_name: str) -> dict[str, str]:
    """Write GraphML + CSV summaries; return {kind: path} for the run ledger."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    safe = __import__('re').sub(r'[\\/:*?"<>|\s]+', '_', base_name or 'biblio').strip('._') or 'biblio'
    files: dict[str, str] = {}
    graph = result.get('graph')
    if graph is not None:
        graph_path = target / f'{safe}_graph.graphml'
        nx.write_graphml(graph, graph_path)
        files['biblio_graphml'] = str(graph_path)

        gml_path = target / f'{safe}_graph.gml'
        nx.write_gml(graph, gml_path)
        files['biblio_gml'] = str(gml_path)

        pajek_path = target / f'{safe}_graph.net'
        pajek_path.write_text(_pajek_text(graph), encoding='utf-8')
        files['biblio_pajek'] = str(pajek_path)

    json_path = target / f'{safe}_graph.json'
    snapshot = {
        'summary': result.get('summary') or {},
        'nodes': result.get('rows') or [],
        'edges': result.get('edges') or [],
        'clusters': result.get('clusters') or [],
        'bursts': result.get('bursts') or [],
        'variation': result.get('variation') or [],
    }
    json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    files['biblio_json'] = str(json_path)

    nodes_path = target / f'{safe}_nodes.csv'
    pd.DataFrame(result['rows']).to_csv(nodes_path, index=False, encoding='utf-8-sig')
    files['biblio_nodes'] = str(nodes_path)

    edges_path = target / f'{safe}_edges.csv'
    pd.DataFrame(result['edges']).to_csv(edges_path, index=False, encoding='utf-8-sig')
    files['biblio_edges'] = str(edges_path)

    if result.get('clusters'):
        clusters_path = target / f'{safe}_clusters.csv'
        pd.DataFrame(result['clusters']).to_csv(clusters_path, index=False, encoding='utf-8-sig')
        files['biblio_clusters'] = str(clusters_path)
    if result.get('bursts'):
        bursts_path = target / f'{safe}_bursts.csv'
        pd.DataFrame(result['bursts']).to_csv(bursts_path, index=False, encoding='utf-8-sig')
        files['biblio_bursts'] = str(bursts_path)
    if result.get('variation'):
        variation_path = target / f'{safe}_variation.csv'
        pd.DataFrame(result['variation']).to_csv(variation_path, index=False, encoding='utf-8-sig')
        files['biblio_variation'] = str(variation_path)
    return files
