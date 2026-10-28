"""Per-node metrics, Kleinberg bursts and the graph layout.

A row's citation counts, h-index, usage and overlay statistics are all computed from
the same node → document map, so they cannot disagree about which documents carry a
node. Bursts are the published two-state model, reimplemented without its toolkit.
"""

import math
from collections import Counter

import networkx as nx
import numpy as np

from i18n import t

# ─── Metrics, bursts and layout ─────────────────────────────────


def _node_citation_stats(nodes: list[str], node_docs: dict[str, set[int]], docs: list[dict]) -> dict[str, dict]:
    """Per-node TC totals and h-index, counted over the documents carrying the node."""
    stats: dict[str, dict] = {}
    for name in nodes:
        values = []
        for index in node_docs.get(name, set()):
            if 0 <= index < len(docs):
                value = docs[index].get('tc')
                if value is not None:
                    values.append(max(0.0, float(value)))
        values.sort(reverse=True)
        h = 0
        for rank, value in enumerate(values, start=1):
            if value >= rank:
                h = rank
            else:
                break
        stats[name] = {'总被引': round(sum(values), 4), 'H指数': h}
    return stats


def _node_usage_stats(nodes: list[str], node_docs: dict[str, set[int]], docs: list[dict]) -> dict[str, float]:
    stats: dict[str, float] = {}
    for name in nodes:
        total = 0.0
        for index in node_docs.get(name, set()):
            if 0 <= index < len(docs):
                value = docs[index].get('usage')
                if value is not None:
                    total += max(0.0, float(value))
        stats[name] = round(total, 4)
    return stats


def _overlay_stats(
    nodes: list[str], node_docs: dict[str, set[int]], docs: list[dict], label_key: str
) -> dict[str, dict]:
    """{node: dominant label + per-label document counts} for one mapped label column.

    A document labels every entity it mentions once, so ``counts`` is a count of DOCUMENTS. A
    document whose cell is blank contributes to none: 「没有判断」 is not a category, and folding
    it into the neutral one would change the share the figure claims. Ties on the dominant label
    break by label text, so two runs over the same table name the same winner.
    """
    stats: dict[str, dict] = {}
    for name in nodes:
        counts = Counter(label for index in node_docs.get(name, ()) if (label := docs[index].get(label_key) or ''))
        if not counts:
            continue
        dominant = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        stats[name] = {'dominant': dominant, 'counts': dict(sorted(counts.items()))}
    return stats


def _node_sources(nodes: list[str], node_docs: dict[str, set[int]], docs: list[dict]) -> dict[str, list[str]]:
    """Which corpora each entity actually appears in — the reading a fused graph exists for.

    A term that shows up in the papers and in the posts is the interesting one, and the graph
    cannot say so unless the provenance of the documents behind the node is kept. Empty when no
    document named a source, which is what keeps the column off a plain literature run's output.
    """
    found: dict[str, list[str]] = {}
    for name in nodes:
        labels = {
            docs[index]['source']
            for index in node_docs.get(name, set())
            if 0 <= index < len(docs) and docs[index].get('source')
        }
        found[name] = sorted(labels)
    return found


def _normalized_degree(graph: nx.Graph) -> dict[str, float]:
    """A 0..1 fallback for a failed eigenvector solve, not a raw weighted degree."""
    values = dict(graph.degree(weight='weight'))
    top = max(values.values(), default=0.0) or 1.0
    return {name: float(value) / top for name, value in values.items()}


def _metrics(graph: nx.Graph, nodes: list[str], notes: list[str]) -> dict[str, dict]:
    degree = dict(graph.degree(weight='weight'))
    distances = nx.Graph()
    for left, right, data in graph.edges(data=True):
        weight = float(data.get('weight') or 0.0)
        distances.add_edge(left, right, distance=(1.0 / weight) if weight > 0 else 1.0)
    sample = None
    if len(nodes) > 2000:
        sample = 500
        notes.append(t('biblio.betweenness_sampled', n=len(nodes), k=sample))
    betweenness = (
        nx.betweenness_centrality(distances, k=sample, weight='distance', seed=42, normalized=True) if nodes else {}
    )
    eigen: dict[str, float] = {}
    failed = False
    for component in nx.connected_components(graph):
        sub = graph.subgraph(component)
        if len(sub) <= 1:
            eigen.update({name: 0.0 for name in sub})
            continue
        if len(sub) <= 2000:
            # The principal eigenvector of a symmetric adjacency matrix is the
            # undirected eigenvector centrality. Computing it directly avoids
            # networkx's sparse eigensolver warning on a small component
            # ("k >= N-1"), which a test would otherwise have to mute.
            try:
                ordered = list(sub.nodes())
                # Only the LAST column is read (the principal vector, since ``eigh`` returns an
                # ascending spectrum); the eigenvalues themselves are centrality's, not needed here.
                _, vectors = np.linalg.eigh(nx.to_numpy_array(sub, nodelist=ordered, weight='weight'))
                principal = np.abs(vectors[:, -1])
                norm = float(np.linalg.norm(principal))
                if norm <= 0:
                    raise ValueError('zero eigenvector')
                eigen.update({name: float(principal[index] / norm) for index, name in enumerate(ordered)})
            except Exception:
                failed = True
                eigen.update(_normalized_degree(sub))
        else:
            try:
                eigen.update(nx.eigenvector_centrality(sub, weight='weight', max_iter=500))
            except Exception:
                failed = True
                eigen.update(_normalized_degree(sub))
    if failed:
        notes.append(t('biblio.eigen_failed'))
    pagerank = nx.pagerank(graph, weight='weight') if graph.number_of_edges() else {}
    return {
        name: {
            '度': round(float(degree.get(name, 0.0)), 6),
            '中介中心性': round(float(betweenness.get(name, 0.0)), 6),
            '特征向量中心性': round(float(eigen.get(name, 0.0)), 6),
            'PageRank': round(float(pagerank.get(name, 0.0)), 6),
        }
        for name in nodes
    }


def _log_binom(k: int, n: int, p: float) -> float:
    if n <= 0:
        return 0.0
    if k < 0 or k > n:
        return -math.inf
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p)


def kleinberg_bursts(
    counts: list[int],
    totals: list[int],
    gamma: float,
    min_duration: int,
    burst_weight: float,
) -> list[dict]:
    """Two-state Kleinberg bursts, returning the strongest interval first.

    State 0 is the base rate; state 1 is ``base * burst_weight``. The Viterbi
    cost is the negative binomial log-likelihood plus ``gamma`` per state
    change, and strength is the log-likelihood ratio over a run. A burst shorter
    than ``min_duration`` is not an event.
    """
    total_events = sum(counts)
    total_docs = sum(totals)
    if total_events <= 0 or total_docs <= 0:
        return []
    p0 = total_events / total_docs
    p1 = min(0.999999, max(p0 * burst_weight, p0 + 1e-6))
    if p1 <= p0:
        return []
    emission = []
    for count, documents in zip(counts, totals, strict=True):
        emission.append((-_log_binom(count, documents, p0), -_log_binom(count, documents, p1)))
    steps = len(counts)
    if steps == 0:
        return []
    inf = float('inf')
    cost = [[inf, inf] for _ in range(steps)]
    back = [[0, 0] for _ in range(steps)]
    cost[0][0] = emission[0][0]
    cost[0][1] = emission[0][1] + gamma
    for step in range(1, steps):
        for state in (0, 1):
            stay = cost[step - 1][state]
            switch = cost[step - 1][1 - state] + gamma
            if stay <= switch:
                cost[step][state] = stay + emission[step][state]
                back[step][state] = state
            else:
                cost[step][state] = switch + emission[step][state]
                back[step][state] = 1 - state
    state = 0 if cost[-1][0] <= cost[-1][1] else 1
    states = [0] * steps
    for step in range(steps - 1, -1, -1):
        states[step] = state
        state = back[step][state]

    bursts = []
    index = 0
    while index < steps:
        if states[index] != 1:
            index += 1
            continue
        end = index
        while end + 1 < steps and states[end + 1] == 1:
            end += 1
        if end - index + 1 >= min_duration:
            strength = 0.0
            for position in range(index, end + 1):
                strength += emission[position][0] - emission[position][1]
            if strength > 0:
                bursts.append({'start': index, 'end': end, 'strength': strength})
        index = end + 1
    bursts.sort(key=lambda item: (-item['strength'], item['start']))
    return bursts


def _bursts(
    nodes: list[str],
    year_counts: dict[str, Counter],
    total_docs_by_year: Counter,
    start: int,
    end: int,
    params: dict,
) -> tuple[dict, list[dict], list[str]]:
    notes: list[str] = []
    years = list(range(start, end + 1))
    totals = [total_docs_by_year.get(year, 0) for year in years]
    found: dict[str, dict] = {}
    rows: list[dict] = []
    for name in nodes:
        counts = [year_counts.get(name, Counter()).get(year, 0) for year in years]
        bursts = kleinberg_bursts(
            counts,
            totals,
            params['burst_gamma'],
            params['burst_min_duration'],
            params['burst_weight'],
        )
        if not bursts:
            continue
        best = bursts[0]
        found[name] = {
            'strength': round(best['strength'], 6),
            'start': start + best['start'],
            'end': start + best['end'],
        }
        for burst in bursts:
            rows.append(
                {
                    '节点': name,
                    '突现起始': start + burst['start'],
                    '突现结束': start + burst['end'],
                    '突现强度': round(burst['strength'], 6),
                }
            )
    notes.append(t('biblio.burst_done', nodes=len(found), total=len(nodes)))
    return found, rows, notes


def _layout(graph: nx.Graph, nodes: list[str]) -> dict[str, tuple[float, float]]:
    if not nodes:
        return {}
    iterations = 100 if len(nodes) <= 1500 else 30
    positions = nx.spring_layout(graph, seed=42, weight='weight', iterations=iterations, k=None)
    xs = [positions[name][0] for name in nodes]
    ys = [positions[name][1] for name in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max_x - min_x or 1.0
    span_y = max_y - min_y or 1.0
    return {
        name: (
            round(50.0 + 900.0 * (positions[name][0] - min_x) / span_x, 3),
            round(50.0 + 900.0 * (positions[name][1] - min_y) / span_y, 3),
        )
        for name in nodes
    }
