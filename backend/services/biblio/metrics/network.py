"""Selecting entities, building edges and pruning the network.

Selection is the frequency rule the panel names; edges are the normalized co-occurrence
or citation strengths; pruning is MST or per-slice PFNET. Each function answers one
stage and returns a new table, never mutating its input.
"""

import math
from collections import Counter, defaultdict
from itertools import combinations

import networkx as nx
import numpy as np

from i18n import t
from services.biblio.schema import COUPLING_TYPES

from .records import _MAX_DOCS_PER_REF, BiblioError

# ─── Selection, edges and pruning ───────────────────────────────


def _select(freq: Counter, params: dict) -> set[str]:
    mode = params['selection']
    names = sorted(freq, key=lambda name: (-freq[name], name))
    if mode == 'top_n':
        return set(names[: params['top_n']])
    if mode == 'top_pct':
        keep = max(1, math.ceil(len(names) * params['top_pct'] / 100.0))
        return set(names[:keep])
    if mode == 'g_index':
        total = 0
        g = 0
        for position, name in enumerate(names, start=1):
            total += freq[name]
            if total >= position * position:
                g = position
        return set(names[: max(1, g)])
    floor = params.get('threshold_c') or params['min_count']
    return {name for name in names if freq[name] >= floor}


def _slice_graphs(docs: list[dict], params: dict, node_meta) -> tuple[Counter, Counter, Counter, dict, dict]:
    # A slice re-derives everything it labels from the documents in it, so the display labels and
    # the per-node years (both whole-corpus answers the caller already holds) are not read here.
    _labels, year_counts, node_docs, _node_years = node_meta
    entity = params['entity_type']
    start = params['start']
    width = params['slice_years']
    slices: dict[int, list[dict]] = defaultdict(list)
    for doc in docs:
        slices[(doc['year'] - start) // width].append(doc)

    merged_edges: Counter = Counter()
    # The numerator the link measure reads: identical to the raw count under full counting, one
    # unit per document spread over its pairs under fractional counting.
    merged_weights: Counter = Counter()
    edge_slices: dict[tuple[str, str], set[int]] = defaultdict(set)
    total_freq: Counter = Counter()
    for name, counts in year_counts.items():
        total_freq[name] = sum(counts.values())

    if entity in COUPLING_TYPES:
        if params['variation']:
            # A coupling link belongs to two CITING papers, not to the year one event happened
            # in; assigning it a slice is a convention, so "how its pattern moved between slices"
            # has no referent here. Refuse rather than score a made-up timeline.
            raise BiblioError(t('biblio.variation_no_coupling', entity=entity))
        # Coupling is a relation between citing units, not between two events inside
        # one year: a 2021 paper and a 2022 paper that share references are
        # coupled. Counting pairs inside a slice missed exactly that case.
        strength: Counter = Counter()
        pairs: Counter = Counter()
        ref_to_docs: dict[str, list[str]] = defaultdict(list)
        for doc in docs:
            for ref in doc['entities']:
                ref_to_docs[ref].append(doc['name'])
        skipped = 0
        for _ref, names in ref_to_docs.items():
            unique = sorted(set(names))
            if len(unique) < 2:
                continue
            if len(unique) > _MAX_DOCS_PER_REF:
                skipped += 1
                continue
            for left, right in combinations(unique, 2):
                pairs[(left, right)] += 1
        if skipped:
            params.setdefault('_notes', []).append(t('biblio.wide_ref_skipped', n=skipped, cap=_MAX_DOCS_PER_REF))
        for (left, right), count in pairs.items():
            strength[left] += count
            strength[right] += count
        selected = _select(strength, params)
        slice_of = {doc['name']: (doc['year'] - start) // width for doc in docs}
        for key, count in pairs.items():
            left, right = key
            if left in selected and right in selected:
                merged_edges[key] += count
                edge_slices[key].add(min(slice_of.get(left, 0), slice_of.get(right, 0)))
        # A coupling node's weight is how many references it shares, not the
        # constant 1 document that carries its own year. This is what the node
        # size and the selection threshold read.
        total_freq = Counter(strength)
        # Coupling refuses fractional counting, so the numerator IS the raw count here.
        return (
            total_freq,
            merged_edges,
            merged_edges,
            edge_slices,
            {
                'slices': len(slices),
                'node_docs': node_docs,
            },
        )

    look_back = params.get('look_back_years') or 0
    # Structural variation reads one network per slice, so it needs the pair counts and the
    # node frequencies SEPARATELY per slice; the merged totals cannot answer "what moved".
    # Collected only when asked: a 20-slice run over 100k edges would otherwise carry 20 copies.
    counts_by_slice: dict[int, Counter] = {}
    freqs_by_slice: dict[int, Counter] = {}
    keep_slices = bool(params['variation'])
    for slice_id, members in sorted(slices.items()):
        slice_freq: Counter = Counter()
        for doc in members:
            for name in doc['entities']:
                slice_freq[name] += 1
        if look_back:
            look_slices = max(0, look_back // width)
            selection_freq: Counter = Counter()
            for prior in range(max(0, slice_id - look_slices), slice_id + 1):
                for doc in slices.get(prior, []):
                    for name in doc['entities']:
                        selection_freq[name] += 1
            selected = _select(selection_freq, params)
        else:
            selected = _select(slice_freq, params)
        slice_counts: Counter = Counter()
        # Fractional counting spreads ONE unit of credit per document over the pairs it carries,
        # so a citing article with 150 references contributes no more to the network than one
        # with 12. The RAW count is kept alongside it: `threshold_cc` and the displayed 次数
        # answer "how often did these two actually meet", which normalization must not rewrite.
        fractional = params['counting'] == 'fractional'
        divided = 0
        for doc in members:
            chosen = sorted(name for name in doc['entities'] if name in selected)
            pairs = len(chosen) * (len(chosen) - 1) / 2
            weight = (1.0 / pairs) if (fractional and pairs > 0) else 1.0
            if fractional and pairs > 1:
                divided += 1
            for left, right in combinations(chosen, 2):
                key = (left, right) if left < right else (right, left)
                merged_edges[key] += 1
                merged_weights[key] += weight
                edge_slices[key].add(slice_id)
                slice_counts[key] += weight
        if fractional and divided:
            params.setdefault('_notes', []).append(t('biblio.counting_fractional', docs=divided))
        if keep_slices:
            counts_by_slice[slice_id] = slice_counts
            freqs_by_slice[slice_id] = Counter(slice_freq)

    return (
        total_freq,
        merged_edges,
        merged_weights,
        edge_slices,
        {
            'slices': len(slices),
            'node_docs': node_docs,
            'counts': counts_by_slice,
            'freqs': freqs_by_slice,
        },
    )


def _normalized_edges(
    merged: Counter,
    total_freq: Counter,
    measure: str,
    numerators: Counter | None = None,
) -> dict[tuple[str, str], dict]:
    """Strength is read off the numerator (the raw count, or its fractional-counting version)
    while ``count`` stays the raw number of times the two met — the threshold and the table both
    answer that question, and normalization must not rewrite it."""
    numerators = merged if numerators is None else numerators
    edges = {}
    for (left, right), count in merged.items():
        c = float(numerators.get((left, right), count))
        fi = float(total_freq.get(left, 0))
        fj = float(total_freq.get(right, 0))
        if not fi or not fj:
            continue
        if measure == 'cosine':
            weight = c / math.sqrt(fi * fj)
        elif measure == 'dice':
            weight = 2.0 * c / (fi + fj)
        elif measure == 'jaccard':
            denominator = fi + fj - c
            weight = count / denominator if denominator > 0 else 0.0
        else:
            weight = c / (fi * fj)
        if weight <= 0:
            continue
        edges[(left, right)] = {'weight': weight, 'count': count}
    return edges


def _threshold_edges(edges: dict, total_freq: Counter, params: dict) -> dict:
    """Apply the (c, cc, ccv) analogue of CiteSpace's threshold selection.

    ``threshold_c`` picks nodes (handled by :func:`_select`), ``threshold_cc``
    is the minimum raw co-occurrence/citation count, and ``threshold_ccv`` is
    the minimum share of the union of the two endpoints' occurrences. Applying
    both to the merged edge table keeps a high-count edge between two very
    common nodes from being mistaken for a strong relation.
    """
    floor = params.get('threshold_cc') or 0
    share = params.get('threshold_ccv') or 0.0
    kept = {}
    for key, info in edges.items():
        if info['count'] < floor:
            continue
        if share:
            union = total_freq.get(key[0], 0) + total_freq.get(key[1], 0) - info['count']
            if union <= 0 or info['count'] / union < share:
                continue
        kept[key] = info
    return kept


def _max_links(edges: dict, params: dict) -> dict:
    """Keep each node's strongest links, symmetrically.

    ``lrf`` is the reading this implementation uses: a link survives a node's
    own cut only if it is at least ``strongest / lrf``. An edge must survive
    at BOTH endpoints, which keeps the graph undirected and every degree
    bounded by ``max_links_per_node``.
    """
    incident: dict[str, list] = defaultdict(list)
    for (left, right), info in edges.items():
        incident[left].append((right, info['weight'], (left, right)))
        incident[right].append((left, info['weight'], (left, right)))
    allowed: dict[str, set[tuple[str, str]]] = {}
    for node, items in incident.items():
        strongest = max((item[1] for item in items), default=0.0)
        floor = strongest / params['lrf']
        ranked = sorted(items, key=lambda item: (-item[1], item[0]))
        allowed[node] = {key for _, weight, key in ranked[: params['max_links_per_node']] if weight >= floor}
    return {
        key: info
        for key, info in edges.items()
        if key in allowed.get(key[0], set()) and key in allowed.get(key[1], set())
    }


def _edges_by_slice(edges: dict, edge_slices: dict) -> dict:
    """``{slice_id: {edge_key: info}}`` — the same network seen one slice at a time."""
    out: dict[int, dict] = defaultdict(dict)
    for key, ids in edge_slices.items():
        info = edges.get(key)
        if info is None:
            continue
        for slice_id in ids:
            out[slice_id][key] = info
    return {slice_id: out[slice_id] for slice_id in sorted(out)}


def _slice_mst_keys(edges: dict, edge_slices: dict) -> tuple[set[tuple[str, str]], int]:
    keep_keys: set[tuple[str, str]] = set()
    slices_seen = 0
    for slice_edges in _edges_by_slice(edges, edge_slices).values():
        graph = nx.Graph()
        for (left, right), info in slice_edges.items():
            graph.add_edge(left, right, weight=info['weight'])
        if graph.number_of_edges() == 0:
            continue
        slices_seen += 1
        tree = nx.maximum_spanning_tree(graph, weight='weight')
        for left, right in tree.edges():
            keep_keys.add((left, right) if left < right else (right, left))
    return keep_keys, slices_seen


def _global_mst_keys(edges: dict) -> set[tuple[str, str]]:
    graph = nx.Graph()
    for (left, right), info in edges.items():
        graph.add_edge(left, right, weight=info['weight'])
    return {
        (left, right) if left < right else (right, left)
        for left, right in nx.maximum_spanning_tree(graph, weight='weight').edges()
    }


#: One DP level of the general Pathfinder reduction costs ``n³`` dense element operations, so
#: the whole reduction is capped at roughly this many. A network above it refuses BY NAME with
#: the numbers it measured — a run that appears to hang is worse than a named refusal, and the
#: classic r=∞ / full-depth case never reaches the DP at all (it is a maximum spanning forest).
_PFNET_WORK_BUDGET = 400_000_000


def _pfnet_combine(r: str):
    """How two consecutive link distances become one path distance (Mantel's r-norm)."""
    if r == '1':
        return lambda left, right: left + right
    if r == '2':
        return lambda left, right: np.sqrt(left * left + right * right)
    return np.maximum


def _pfnet_keys(edges: dict, params: dict) -> set[tuple[str, str]]:
    """The Pathfinder reduction of one network (Mantel 1990; Chen & Lewens 2007).

    Similarity is read as distance ``d = 1 - s``. A link survives iff its own distance is no
    longer than the best *indirect* path between its endpoints, where a path's length is the
    Mantel r-norm of its links (``inf`` = its longest single link, ``1`` = their sum, ``2`` =
    their Euclidean norm) using at most ``pathfinder_lmax`` links (0 = as many as the network
    allows). ``pathfinder_dmax`` then keeps only that fraction of the survivors, strongest
    first — 1.0 keeps every link the reduction justified.

    With r=∞ and unlimited depth the two definitions coincide, so that case is answered by the
    maximum spanning forest instead of the DP; that is the same graph, not a weaker one.
    """
    names = sorted({node for key in edges for node in key})
    size = len(names)
    if size < 3:
        return set(edges)
    r = params['pathfinder_r']
    levels = params['pathfinder_lmax'] or (size - 1)
    levels = max(2, min(levels, size - 1))
    if r == 'inf' and levels >= size - 1:
        return _global_mst_keys(edges)
    work = size**3 * (levels - 1)
    if work > _PFNET_WORK_BUDGET:
        raise ValueError(t('biblio.pfnet_refused', nodes=size, levels=levels, work=work, limit=_PFNET_WORK_BUDGET))

    index = {name: position for position, name in enumerate(names)}
    direct = np.full((size, size), np.inf)
    np.fill_diagonal(direct, 0.0)
    for (left, right), info in edges.items():
        i, j = index[left], index[right]
        distance = max(0.0, 1.0 - float(info['weight']))
        if distance < direct[i, j]:
            direct[i, j] = direct[j, i] = distance
    # A path step is a real link: the zero diagonal would let a path "return" through its own
    # start for free and dominate every link it touches.
    step = direct.copy()
    np.fill_diagonal(step, np.inf)
    combine = _pfnet_combine(r)

    best = np.full((size, size), np.inf)
    for hop in range(2, levels + 1):
        current = best.copy()
        for middle in range(size):
            reached = step[:, middle] if hop == 2 else best[:, middle]
            current = np.minimum(current, combine(reached[:, None], step[middle, :][None, :]))
        np.fill_diagonal(current, np.inf)
        if np.array_equal(current, best):
            break
        best = current

    tolerance = 1e-9
    kept = []
    for key in edges:
        i, j = index[key[0]], index[key[1]]
        if direct[i, j] <= best[i, j] + tolerance:
            kept.append(key)
    dmax = float(params['pathfinder_dmax'])
    if dmax < 1.0 and len(kept) > 1:
        ranked = sorted(kept, key=lambda key: (-float(edges[key]['weight']), key))
        kept = ranked[: max(1, math.ceil(len(ranked) * dmax))]
    return set(kept)


def _pruning_scope_word(scope: str) -> str:
    """The scope as the reader sees it: a raw ``slices`` inside a Chinese console line is a
    token, not a word, and the line is the only place the user learns what was pruned."""
    return t('biblio.pruning_scope.slices' if scope == 'slices' else 'biblio.pruning_scope.merged')


def _neighbor_distributions(edges: dict) -> dict[str, dict[str, float]]:
    """``{node: {neighbor: weight}}`` — the connection pattern one slice shows."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for (left, right), info in edges.items():
        weight = float(info['weight'])
        out[left][right] = weight
        out[right][left] = weight
    return out


def _jsd(left: dict[str, float], right: dict[str, float]) -> float:
    """Jensen–Shannon divergence in bits between two link-strength distributions.

    Chosen over raw KL because a neighbour that appears or disappears makes KL infinite, and an
    infinite score is not something a table can rank. Both inputs are normalized over their
    union, so the result is bounded by 1 bit: 0 = the same pattern, 1 = nothing in common."""
    keys = set(left) | set(right)
    total_left = sum(left.values())
    total_right = sum(right.values())
    if total_left <= 0 or total_right <= 0:
        return 0.0
    p = {key: left.get(key, 0.0) / total_left for key in keys}
    q = {key: right.get(key, 0.0) / total_right for key in keys}
    mixed = {key: (p[key] + q[key]) / 2.0 for key in keys}

    def _kl(a: dict[str, float]) -> float:
        return sum(value * math.log2(value / mixed[key]) for key, value in a.items() if value > 0)

    return 0.5 * _kl(p) + 0.5 * _kl(q)


def _structural_variation(slice_counts: dict, slice_freqs: dict, params: dict) -> tuple[list[dict], list[str]]:
    """How far each node's connection pattern moves between CONSECUTIVE slices.

    A node is scored only where it has links in both slices of a pair: "it had a pattern and
    then had none" is a disappearance, not a measurable change of shape, and inventing a score
    for it would rank an absence above a restructuring. Gaps in the slicing (a year range with
    no records) are not treated as consecutive.
    """
    notes: list[str] = []
    measure = params['link_measure']
    width = params['slice_years']
    start = params['start']
    ids = sorted(slice_counts)
    patterns = {
        slice_id: _neighbor_distributions(_normalized_edges(slice_counts[slice_id], slice_freqs[slice_id], measure))
        for slice_id in ids
    }
    rows: list[dict] = []
    # Consecutive PAIRS, so the tail slice has no partner — the short end is the point.
    for left_id, right_id in zip(ids, ids[1:], strict=False):
        if right_id - left_id != 1:
            continue
        left_map, right_map = patterns[left_id], patterns[right_id]
        for name in sorted(set(left_map) & set(right_map)):
            left, right = left_map[name], right_map[name]
            score = _jsd(left, right)
            if score + 1e-12 < params['variation_min']:
                continue
            rows.append(
                {
                    '节点': name,
                    '起始年': start + left_id * width,
                    '结束年': start + right_id * width,
                    '结构变化': round(score, 6),
                    '前邻居': len(left),
                    '后邻居': len(right),
                    '新增邻居': '；'.join(sorted(set(right) - set(left))),
                    '消失邻居': '；'.join(sorted(set(left) - set(right))),
                }
            )
    rows.sort(key=lambda row: (-row['结构变化'], row['节点'], row['起始年']))
    if rows:
        top = rows[0]
        notes.append(
            t(
                'biblio.variation_done',
                rows=len(rows),
                node=top['节点'],
                pair=f'{top["起始年"]}→{top["结束年"]}',
                score=top['结构变化'],
                floor=params['variation_min'],
            )
        )
    else:
        notes.append(t('biblio.variation_empty', floor=params['variation_min']))
    return rows, notes


def _prune(edges: dict, edge_slices: dict, params: dict, notes: list[str]) -> dict:
    mode = params['pruning']
    if mode == 'none':
        return edges
    scope = params.get('pruning_scope') or 'slices'

    if mode == 'mst':
        keep_keys = _slice_mst_keys(edges, edge_slices)[0] if scope == 'slices' else _global_mst_keys(edges)
        kept = {key: info for key, info in edges.items() if key in keep_keys}
        notes.append(
            t(
                'biblio.mst_done',
                before=len(edges),
                after=len(kept),
                scope=_pruning_scope_word(scope),
            )
        )
        return kept

    # Pathfinder: every link is compared against the best INDIRECT path between its endpoints,
    # so which network is being reduced matters — per slice the union of the slice reductions
    # keeps more links than one reduction of the merged network. The parameters actually used
    # are printed, because r=∞ at full depth is a spanning forest and a reader may want to know
    # which of the two ran.
    if scope == 'merged':
        keep_keys = _pfnet_keys(edges, params)
        units = 1
    else:
        networks = _edges_by_slice(edges, edge_slices)
        keep_keys = set()
        for slice_edges in networks.values():
            keep_keys |= _pfnet_keys(slice_edges, params)
        units = len(networks)
    kept = {key: info for key, info in edges.items() if key in keep_keys}
    depth = params['pathfinder_lmax']
    notes.append(
        t(
            'biblio.pfnet_done',
            before=len(edges),
            after=len(kept),
            r='∞' if params['pathfinder_r'] == 'inf' else params['pathfinder_r'],
            lmax=str(depth) if depth else t('biblio.pfnet_depth_all'),
            dmax=params['pathfinder_dmax'],
            scope=_pruning_scope_word(scope),
            units=units,
        )
    )
    return kept
