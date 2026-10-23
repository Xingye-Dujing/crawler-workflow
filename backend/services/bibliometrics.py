"""Bibliometric network construction, metrics, bursts and citation graphs.

The input is the normalized record table produced by
:mod:`services.biblio_import`; the output is one row per entity with a JSON
adjacency column. Everything a chart needs is in that one table, so a resume,
a CSV export and a chart preview all see the same numbers.

The algorithms are published ones reimplemented here (co-occurrence and
co-citation counting, cosine/dice/Jaccard/association strengths, maximum
spanning tree, per-slice PFNET, Kleinberg's two-state burst detection,
spectral clustering). No CiteSpace code or bundled data is used.
"""

import json
import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from analyzers.keyword import KeywordExtractor
from i18n import t
from services import biblio_cluster
from services.biblio_refs import normalize_reference, parse_reference, references_from_json
from services.biblio_schema import (
    CITATION_TYPES,
    COUPLING_TYPES,
    LIMITS,
    normalize_params,
    read_columns,
)

_YEAR = re.compile(r'(?:19|20)\d{2}')
_LIST_SPLIT = re.compile(r'[;；,，、]+')
_TERM_POS = frozenset({'n', 'nz', 'vn', 'v', 'eng'})
_MAX_TERMS_PER_DOC = 30
_MAX_LABEL_TERMS = 40
_MAX_DOCS_PER_REF = 200
_MAX_EXPANDED_REFS = 500
_REF_RATE = 0.6

ENTITY_LABEL_KEYS = {
    'keyword': 'biblio.entity.keyword',
    'author': 'biblio.entity.author',
    'institution': 'biblio.entity.institution',
    'country': 'biblio.entity.country',
    'term': 'biblio.entity.term',
    'category': 'biblio.entity.category',
    'journal': 'biblio.entity.journal',
    'source': 'biblio.entity.source',
    'funder': 'biblio.entity.funder',
    'grant': 'biblio.entity.grant',
    'document_cocitation': 'biblio.entity.document_cocitation',
    'author_cocitation': 'biblio.entity.author_cocitation',
    'journal_cocitation': 'biblio.entity.journal_cocitation',
    'article': 'biblio.entity.article',
    'document': 'biblio.entity.document',
    'bibliographic_coupling': 'biblio.entity.bibliographic_coupling',
}


class BiblioError(ValueError):
    """A named refusal from the bibliometric pipeline."""


# ─── Shared parsing helpers ─────────────────────────────────────


def _split(value) -> list[str]:
    seen: list[str] = []
    for part in _LIST_SPLIT.split(str(value or '')):
        item = part.strip().strip('.')
        if item and item not in seen:
            seen.append(item)
    return seen


def _year(value) -> int | None:
    match = _YEAR.search(str(value or ''))
    return int(match.group(0)) if match else None


def _numeric(value) -> float:
    text = str(value if value is not None else '').replace(',', '').strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _unique_labels(labels: dict[str, str]) -> dict[str, str]:
    """A display label per node key, made unique.

    A chart addresses nodes by name, so two cited works that share a title
    must not collapse into one bubble. The key stays internal; the label gets
    a year suffix only when the plain label is already taken.
    """
    used: dict[str, int] = Counter()
    display: dict[str, str] = {}
    for key in sorted(labels):
        base = labels[key] or key
        count = used[base]
        used[base] += 1
        display[key] = base if count == 0 else f'{base}（{count + 1}）'
    return display


def _ref_key(text: str) -> str:
    return re.sub(r'[\s\.。；;,，:：\-—_（）()\[\]【】]', '', text or '').lower()


def _reference_nodes(
    raw_refs: list[str],
    entity: str,
    structured: list[dict] | None = None,
) -> tuple[dict, list[dict], int]:
    """Ref key → metadata, and the parsed refs. Returns (nodes, parsed, total)."""
    items = _direct_reference_items(raw_refs, structured or [])
    return _reference_nodes_from_items(items, entity)


def _document_references(record: dict, columns: dict) -> tuple[list[str], list[dict]]:
    """The raw and structured references a document carries."""
    raw_text = str(record.get(columns['reference']) or '')
    raw_refs = [line.strip() for line in raw_text.splitlines() if line.strip()]
    structured = references_from_json(record.get('引文')) if '引文' in record else []
    return raw_refs, structured


def _direct_reference_items(raw_refs: list[str], structured: list[dict]) -> list[dict]:
    items = structured or raw_refs
    parsed = []
    for value in items:
        item = normalize_reference(value) if isinstance(value, dict) else parse_reference(value)
        if item is not None:
            parsed.append(item)
    return parsed


def _reference_nodes_from_items(items: list[dict], entity: str) -> tuple[dict, list[dict], int]:
    nodes: dict[str, dict] = {}
    for item in items:
        if entity == 'author_cocitation':
            if not item.get('authors'):
                continue
            label = item['authors'][0]
            key = _ref_key(label)
        elif entity == 'journal_cocitation':
            if not item.get('journal'):
                continue
            label = item['journal']
            key = _ref_key(label)
        else:
            label = item.get('title') or item.get('raw')
            title_key = _ref_key(item.get('title') or item.get('raw'))
            key = f'{title_key}|{item["year"]}' if item.get('year') else title_key
        if not key:
            continue
        nodes.setdefault(key, {'label': label[:160], 'year': item.get('year')})
    return nodes, items, len(items)


def _citation_source_index(df: pd.DataFrame, columns: dict) -> dict[str, list[dict]]:
    """Map a source record to its direct references so expansion can find it."""
    index: dict[str, list[dict]] = {}

    def add(key: str, items: list[dict]):
        if key:
            index.setdefault(key, items)

    for _, row in df.iterrows():
        record = row.to_dict()
        raw_refs, structured = _document_references(record, columns)
        items = _direct_reference_items(raw_refs, structured)
        if not items:
            continue
        doi = _ref_key(record.get('DOI'))
        title = _ref_key(record.get(columns['title']))
        year = _year(record.get(columns['year']))
        if doi:
            add(f'doi:{doi}', items)
        if title:
            add(f'title:{title}|{year or ""}', items)
            add(f'title:{title}', items)
    return index


def _expand_reference_items(items: list[dict], depth: int, source_index: dict[str, list[dict]]) -> list[dict]:
    """CiteSpace-style citation expansion through records already in the table."""
    if depth <= 0 or not source_index:
        return items
    result = list(items)
    seen = {_ref_key(item.get('doi') or '') or _ref_key(item.get('title') or '') for item in items}
    queue = [(item, 0) for item in items]
    while queue and len(result) < _MAX_EXPANDED_REFS:
        item, level = queue.pop(0)
        if level >= depth:
            continue
        candidates = []
        if item.get('doi'):
            candidates.append(f'doi:{_ref_key(item["doi"])}')
        title = _ref_key(item.get('title'))
        if title:
            candidates.append(f'title:{title}|{item.get("year") or ""}')
            candidates.append(f'title:{title}')
        for key in candidates:
            for child in source_index.get(key) or []:
                child_key = _ref_key(child.get('doi') or '') or _ref_key(child.get('title') or '')
                if not child_key or child_key in seen:
                    continue
                seen.add(child_key)
                result.append(child)
                queue.append((child, level + 1))
                if len(result) >= _MAX_EXPANDED_REFS:
                    break
    return result


def _document_reference_nodes(
    record: dict,
    columns: dict,
    entity: str,
    params: dict,
    source_index: dict[str, list[dict]],
) -> tuple[dict, list[dict], int]:
    raw_refs, structured = _document_references(record, columns)
    direct = _direct_reference_items(raw_refs, structured)
    expanded = _expand_reference_items(direct, params.get('citation_expansion') or 0, source_index)
    nodes, _, _ = _reference_nodes_from_items(expanded, entity)
    return nodes, direct, len(raw_refs) if raw_refs else len(direct)


def _doc_terms(row: dict, columns: dict, entity: str) -> list[str]:
    keywords = _split(row.get(columns['entity'])) if entity == 'keyword' else []
    text = ' '.join(str(row.get(columns[name]) or '') for name in ('title', 'abstract'))
    try:
        tokens = KeywordExtractor._tokenize(text, _TERM_POS)
    except Exception:
        tokens = []
    counts = Counter(tokens)
    ranked = [token for token, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    merged = keywords + [term for term in ranked if term not in keywords]
    return merged[:_MAX_LABEL_TERMS]


def _term_entities(row: dict, columns: dict) -> list[str]:
    text = ' '.join(str(row.get(columns[name]) or '') for name in ('title', 'abstract'))
    try:
        tokens = KeywordExtractor._tokenize(text, _TERM_POS)
    except Exception:
        tokens = []
    counts = Counter(tokens)
    return [token for token, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))][:_MAX_TERMS_PER_DOC]


def _require_columns(df: pd.DataFrame, params: dict) -> dict:
    """Resolve the mapped columns and refuse a missing one by its real name."""
    entity = params['entity_type']
    columns = read_columns(params)
    required: list[str] = []
    if entity in CITATION_TYPES or entity in COUPLING_TYPES:
        required = [columns['year']]
        if columns['reference'] not in df.columns and '引文' not in df.columns:
            required.insert(0, columns['reference'])
        if entity in ('document', 'bibliographic_coupling'):
            required.append(columns['title'])
        if entity in ('journal', 'source'):
            required.append(columns['entity'])
    elif entity == 'term':
        if columns['title'] not in df.columns and columns['abstract'] not in df.columns:
            missing = f'{columns["title"]}/{columns["abstract"]}'
            raise BiblioError(t('biblio.column_missing', col=missing, entity=entity))
        required = [columns['year']]
    else:
        required = [columns['entity'], columns['year']]
    for column in required:
        if column and column not in df.columns:
            raise BiblioError(t('biblio.column_missing', col=column, entity=entity))
    return columns


# ─── Documents and slices ───────────────────────────────────────


def _documents(df: pd.DataFrame, params: dict) -> tuple[list[dict], dict, dict, list[str]]:
    entity = params['entity_type']
    columns = _require_columns(df, params)
    notes: list[str] = []
    docs: list[dict] = []
    ref_nodes: dict[str, dict] = {}
    dropped_year = 0
    skipped = 0

    source_index = _citation_source_index(df, columns) if params.get('citation_expansion') else {}
    if entity in CITATION_TYPES or entity in COUPLING_TYPES:
        total_refs = 0
        parsed_refs = 0
        field_refs = 0
        expanded_refs = 0
        for _, row in df.iterrows():
            nodes, direct, total = _document_reference_nodes(row.to_dict(), columns, entity, params, source_index)
            total_refs += total
            parsed_refs += len(direct)
            expanded_refs += max(0, len(nodes) - len(direct))
            if entity == 'author_cocitation':
                field_refs += sum(1 for item in direct if item['authors'])
            elif entity == 'journal_cocitation':
                field_refs += sum(1 for item in direct if item['journal'])
            for key, info in nodes.items():
                ref_nodes.setdefault(key, info)
        if total_refs < 2:
            raise BiblioError(t('biblio.refs_missing', type=entity))
        usable = parsed_refs / total_refs if total_refs else 0.0
        if usable < _REF_RATE:
            raise BiblioError(t('biblio.refs_low_rate', rate=f'{usable:.0%}', floor=f'{_REF_RATE:.0%}'))
        if entity in ('author_cocitation', 'journal_cocitation'):
            field = 'authors' if entity == 'author_cocitation' else 'journal'
            usable = field_refs / total_refs
            if usable < _REF_RATE:
                raise BiblioError(
                    t('biblio.refs_field_low', field=field, rate=f'{usable:.0%}', floor=f'{_REF_RATE:.0%}')
                )
        if expanded_refs:
            notes.append(t('biblio.citation_expansion_done', added=expanded_refs, depth=params['citation_expansion']))

    seen_doc_names: set[str] = set()
    for _, row in df.iterrows():
        year = _year(row.get(columns['year']))
        if year is None:
            dropped_year += 1
            continue
        if params['time_start'] is not None and year < params['time_start']:
            continue
        if params['time_end'] is not None and year > params['time_end']:
            continue

        record = row.to_dict()
        filtered = False
        for column, param in (
            (params['tc_column'], 'min_tc'),
            (params['usage_column'], 'min_usage'),
        ):
            if params.get(param) is None:
                continue
            if column not in df.columns:
                raise BiblioError(t('biblio.column_missing', col=column, entity=entity))
            if _numeric(record.get(column)) < params[param]:
                filtered = True
                break
        if filtered:
            skipped += 1
            continue

        if entity in CITATION_TYPES or entity in COUPLING_TYPES:
            nodes, _, _ = _document_reference_nodes(record, columns, entity, params, source_index)
            entities = list(nodes)
        elif entity == 'term':
            entities = _term_entities(record, columns)
        else:
            entities = _split(record.get(columns['entity']))

        if not entities:
            skipped += 1
            continue

        if entity in COUPLING_TYPES:
            if entity in ('journal', 'source'):
                name = str(record.get(columns['entity']) or '').strip()
            else:
                title = str(record.get(columns['title']) or '').strip()
                record_id = str(record.get('记录ID') or '').strip()
                name = title or record_id or f'record-{len(docs) + 1}'
                if name in seen_doc_names:
                    name = f'{name}（{record_id[:6] or len(docs) + 1}）'
                seen_doc_names.add(name)
            if not name:
                skipped += 1
                continue
        else:
            name = ''

        docs.append(
            {
                'index': len(docs),
                'year': year,
                'entities': list(dict.fromkeys(entities)),
                'terms': _doc_terms(record, columns, entity),
                'name': name,
                'tc': _numeric(record.get(columns['tc'])) if columns['tc'] in df.columns else None,
                'usage': _numeric(record.get(columns['usage'])) if columns['usage'] in df.columns else None,
            }
        )

    if not docs:
        raise BiblioError(t('biblio.no_records'))
    if dropped_year:
        notes.append(t('biblio.year_missing', n=dropped_year))
    if skipped:
        notes.append(t('biblio.records_skipped', n=skipped))

    start = params['time_start'] if params['time_start'] is not None else min(doc['year'] for doc in docs)
    end = params['time_end'] if params['time_end'] is not None else max(doc['year'] for doc in docs)
    if start > end:
        raise BiblioError(t('biblio.time_range', nid='(biblio)', start=start, end=end))
    docs = [doc for doc in docs if start <= doc['year'] <= end]
    if not docs:
        raise BiblioError(t('biblio.no_records_in_range', start=start, end=end))
    return docs, ref_nodes, {'start': start, 'end': end}, notes


def _node_metadata(docs: list[dict], params: dict, ref_nodes: dict) -> tuple[dict, dict, dict, dict]:
    entity = params['entity_type']
    labels: dict[str, str] = {}
    year_counts: dict[str, Counter] = defaultdict(Counter)
    node_docs: dict[str, set[int]] = defaultdict(set)
    node_years: dict[str, int | None] = {}
    for doc in docs:
        if entity in COUPLING_TYPES:
            name = doc['name']
            labels[name] = name
            year_counts[name][doc['year']] += 1
            node_docs[name].add(doc['index'])
            node_years[name] = doc['year']
            continue
        for name in doc['entities']:
            info = ref_nodes.get(name) if entity in CITATION_TYPES else None
            labels.setdefault(name, (info or {}).get('label') or name)
            year_counts[name][doc['year']] += 1
            node_docs[name].add(doc['index'])
            node_years.setdefault(name, (info or {}).get('year'))
    return labels, year_counts, node_docs, node_years


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


def _slice_graphs(docs: list[dict], params: dict, node_meta) -> tuple[Counter, Counter, dict, dict]:
    labels, year_counts, node_docs, node_years = node_meta
    entity = params['entity_type']
    start = params['start']
    width = params['slice_years']
    slices: dict[int, list[dict]] = defaultdict(list)
    for doc in docs:
        slices[(doc['year'] - start) // width].append(doc)

    merged_edges: Counter = Counter()
    edge_slices: dict[tuple[str, str], set[int]] = defaultdict(set)
    total_freq: Counter = Counter()
    for name, counts in year_counts.items():
        total_freq[name] = sum(counts.values())

    if entity in COUPLING_TYPES:
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
        return total_freq, merged_edges, edge_slices, {'slices': len(slices), 'node_docs': node_docs}

    look_back = params.get('look_back_years') or 0
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
        for doc in members:
            chosen = sorted(name for name in doc['entities'] if name in selected)
            for left, right in combinations(chosen, 2):
                key = (left, right) if left < right else (right, left)
                merged_edges[key] += 1
                edge_slices[key].add(slice_id)

    return total_freq, merged_edges, edge_slices, {'slices': len(slices), 'node_docs': node_docs}


def _normalized_edges(merged: Counter, total_freq: Counter, measure: str) -> dict[tuple[str, str], dict]:
    edges = {}
    for (left, right), count in merged.items():
        fi = float(total_freq.get(left, 0))
        fj = float(total_freq.get(right, 0))
        if not fi or not fj:
            continue
        if measure == 'cosine':
            weight = count / math.sqrt(fi * fj)
        elif measure == 'dice':
            weight = 2.0 * count / (fi + fj)
        elif measure == 'jaccard':
            denominator = fi + fj - count
            weight = count / denominator if denominator > 0 else 0.0
        else:
            weight = count / (fi * fj)
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


def _slice_mst_keys(edges: dict, edge_slices: dict) -> tuple[set[tuple[str, str]], int]:
    keep_keys: set[tuple[str, str]] = set()
    slices_seen = 0
    for slice_id in sorted({sid for ids in edge_slices.values() for sid in ids}):
        graph = nx.Graph()
        for key, ids in edge_slices.items():
            if slice_id not in ids or key not in edges:
                continue
            left, right = key
            graph.add_edge(left, right, weight=edges[key]['weight'])
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


def _prune(edges: dict, edge_slices: dict, params: dict, notes: list[str]) -> dict:
    mode = params['pruning']
    if mode == 'none':
        return edges
    scope = params.get('pruning_scope') or 'slices'

    if mode == 'mst':
        keep_keys = _slice_mst_keys(edges, edge_slices)[0] if scope == 'slices' else _global_mst_keys(edges)
        kept = {key: info for key, info in edges.items() if key in keep_keys}
        notes.append(t('biblio.mst_done', before=len(edges), after=len(kept), scope=scope))
        return kept

    # Pathfinder: PFNET(r=∞, q=n−1) is a maximum spanning tree on one slice;
    # CiteSpace applies it per slice and merges, which is why the result can
    # keep more links than one global MST. The retained count is reported.
    if scope == 'merged':
        keep_keys = _global_mst_keys(edges)
        slices_seen = 1
        notes.append(t('biblio.pathfinder_merged_equals_mst'))
    else:
        keep_keys, slices_seen = _slice_mst_keys(edges, edge_slices)
    kept = {key: info for key, info in edges.items() if key in keep_keys}
    notes.append(t('biblio.pathfinder_done', before=len(edges), after=len(kept), slices=slices_seen))
    return kept


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
                values, vectors = np.linalg.eigh(nx.to_numpy_array(sub, nodelist=ordered, weight='weight'))
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


# ─── Public build ───────────────────────────────────────────────


def build(df: pd.DataFrame, params: dict, nid: str = '') -> dict:
    """Build the node table and every artifact the Visualize node may need."""
    params = normalize_params(params, nid)
    notes: list[str] = []
    docs, ref_nodes, window, doc_notes = _documents(df, params)
    notes += doc_notes
    params['start'] = window['start']
    labels, year_counts, node_docs, node_years = _node_metadata(docs, params, ref_nodes)
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

    total_freq, merged_edges, edge_slices, slice_meta = _slice_graphs(
        docs, params, (labels, year_counts, node_docs, node_years)
    )
    notes += params.pop('_notes', [])
    if not merged_edges:
        raise BiblioError(t('biblio.no_edges', start=window['start'], end=window['end']))
    edges = _normalized_edges(merged_edges, total_freq, params['link_measure'])
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
        clusters = biblio_cluster.cluster_graph(
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
        'output_shape': params['output_shape'],
        'notes': notes,
    }
    return {
        'rows': rows,
        'edges': edge_rows,
        'bursts': burst_rows,
        'clusters': cluster_rows,
        'graph': graph,
        'summary': summary,
        'notes': notes,
    }


def export_result(result: dict, out_dir: str, base_name: str) -> dict[str, str]:
    """Write GraphML + CSV summaries; return {kind: path} for the run ledger."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    safe = __import__('re').sub(r'[\\/:*?"<>|\s]+', '_', base_name or 'biblio').strip('._') or 'biblio'
    files: dict[str, str] = {}
    graph_path = target / f'{safe}_graph.graphml'
    nx.write_graphml(result['graph'], graph_path)
    files['biblio_graphml'] = str(graph_path)

    gml_path = target / f'{safe}_graph.gml'
    nx.write_gml(result['graph'], gml_path)
    files['biblio_gml'] = str(gml_path)

    json_path = target / f'{safe}_graph.json'
    snapshot = {
        'summary': result.get('summary') or {},
        'nodes': result.get('rows') or [],
        'edges': result.get('edges') or [],
        'clusters': result.get('clusters') or [],
        'bursts': result.get('bursts') or [],
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
    return files
