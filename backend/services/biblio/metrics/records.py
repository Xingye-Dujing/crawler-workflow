"""Reading the normalized record table into documents and entity labels.

The importer's fixed columns are the only input; every helper here answers one
question about a cell (what years does it carry, which terms does it name, which
reference keys does it point at). Refusals name the column that made the question
unanswerable.
"""

import json
import math
import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from analyzers.keyword import KeywordExtractor
from i18n import t
from services.biblio.refs import normalize_reference, parse_reference, references_from_json
from services.biblio.schema import (
    CITATION_TYPES,
    COUPLING_TYPES,
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


def _label_columns(df: pd.DataFrame, params: dict, columns: dict) -> dict:
    """The columns the chosen cluster-label source reads, refusing a missing one by name.

    ``all`` is the node's historical mix and stays LENIENT: a crawled table without 摘要 still
    labels from its keywords, exactly as it did before the selector existed. An EXPLICIT source
    is a hard read — "label from the abstract" against a table with no abstract column is a
    misconfiguration, not a licence to fall back to the title.
    """
    entity = params['entity_type']
    source = str(params.get('label_source') or 'all')
    resolved = {
        'title': columns['title'],
        'abstract': columns['abstract'],
        # A keyword graph's own entity column is its author-supplied tags; any other graph's
        # keyword source is the canonical 关键词 column (CiteSpace's DE).
        'keywords': columns['entity'] if entity == 'keyword' else '关键词',
        # Same rule for AU: an author graph's entity column, otherwise the canonical 作者.
        'author': columns['entity'] if entity == 'author' else '作者',
    }
    if source != 'all':
        column = resolved.get(source, '')
        if not column or column not in df.columns:
            raise BiblioError(t('biblio.column_missing', col=column or source, entity=entity))
    return resolved


def _doc_terms(
    row: dict, columns: dict, _entity: str, source: str = 'all', label_columns: dict | None = None
) -> list[str]:
    """Terms one document offers to the cluster-labelling methods.

    ``source`` chooses the fields: ``all`` = keywords + title + abstract (the behaviour this node
    always had), or exactly one of title / abstract / keywords / author. A keyword or author
    source is split, not tokenised — those cells already hold terms.

    ``_entity`` is the entity type the graph is built on. Nothing here reads it: the fields to
    pull are already resolved in ``columns``, and it sits in the signature so this stays the
    positional twin of :func:`_document_reference_nodes` beside it.
    """
    label_columns = label_columns or {}
    keywords = []
    if source in ('all', 'keywords'):
        keywords = _split(row.get(label_columns.get('keywords', columns['entity'])))
    if source == 'author':
        return _split(row.get(label_columns.get('author', '作者')))[:_MAX_LABEL_TERMS]
    parts = []
    if source in ('all', 'title'):
        parts.append(str(row.get(label_columns.get('title', columns['title'])) or ''))
    if source in ('all', 'abstract'):
        parts.append(str(row.get(label_columns.get('abstract', columns['abstract'])) or ''))
    text = ' '.join(parts)
    try:
        tokens = KeywordExtractor.tokenize(text, _TERM_POS)
    except Exception:
        tokens = []
    counts = Counter(tokens)
    ranked = [token for token, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    merged = keywords + [term for term in ranked if term not in keywords]
    return merged[:_MAX_LABEL_TERMS]


def _term_entities(row: dict, columns: dict) -> list[str]:
    text = ' '.join(str(row.get(columns[name]) or '') for name in ('title', 'abstract'))
    try:
        tokens = KeywordExtractor.tokenize(text, _TERM_POS)
    except Exception:
        tokens = []
    counts = Counter(tokens)
    return [token for token, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))][:_MAX_TERMS_PER_DOC]


def _label_value(value) -> str:
    """One upstream label cell as a graph-ready string, or '' for "no label".

    A missing cell is '' — 「没有判断」 is not a category, and the text ``nan`` must never become a
    label called nan. An integral float (a cluster id that survived a CSV round trip as ``2.0``)
    loses its ``.0``, so the same document does not land in two categories across a resume.
    """
    try:
        if pd.isna(value):
            return ''
    except (TypeError, ValueError):
        pass
    if isinstance(value, (float, np.floating)) and math.isfinite(float(value)) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    return '' if text.lower() in ('nan', 'none', 'nat', '<na>') else text


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
    # A named overlay column is a hard read for the same reason a named entity column is: a typo
    # silently ignored would produce a complete-looking graph whose overlay columns are all empty.
    for param in ('sentiment_column', 'topic_column'):
        column = str(params.get(param) or '').strip()
        if column and column not in df.columns:
            raise BiblioError(t('biblio.column_missing', col=column, entity=entity))
    return columns


# ─── Documents and slices ───────────────────────────────────────


def _documents(df: pd.DataFrame, params: dict) -> tuple[list[dict], dict, dict, list[str]]:
    entity = params['entity_type']
    columns = _require_columns(df, params)
    label_columns = _label_columns(df, params, columns)
    label_source = str(params.get('label_source') or 'all')
    notes: list[str] = []
    overlay_columns = {
        'sentiment_label': str(params.get('sentiment_column') or '').strip(),
        'topic_label': str(params.get('topic_column') or '').strip(),
    }
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
                'terms': _doc_terms(record, columns, entity, label_source, label_columns),
                'name': name,
                # Only a fused table carries 来源; a plain literature or crawl table never does,
                # and then the node table grows neither column (an all-empty provenance column
                # would read as a claim that everything came from nowhere in particular).
                'source': str(record.get('来源') or '').strip() if '来源' in df.columns else '',
                'tc': _numeric(record.get(columns['tc'])) if columns['tc'] in df.columns else None,
                'usage': _numeric(record.get(columns['usage'])) if columns['usage'] in df.columns else None,
                # The overlay labels travel WITH the document, because a node's distribution is
                # aggregated over the documents that mentioned it — not over mentions, which would
                # let one chatty document outvote five quiet ones.
                'sentiment_label': _label_value(record.get(overlay_columns['sentiment_label']))
                if overlay_columns['sentiment_label']
                else '',
                'topic_label': _label_value(record.get(overlay_columns['topic_label']))
                if overlay_columns['topic_label']
                else '',
            }
        )

    if not docs:
        raise BiblioError(t('biblio.no_records'))
    for key, column in overlay_columns.items():
        if not column:
            continue
        labelled = sum(1 for doc in docs if doc[key])
        if not labelled:
            # An all-blank column is not "no overlay requested": the box named a column, so the
            # user believes labels are being aggregated. Say what happened instead of shipping
            # two empty columns the chart then refuses with a message about the wrong node.
            raise BiblioError(t('biblio.overlay_no_labels', col=column, n=len(docs)))
        if labelled < len(docs):
            notes.append(t('biblio.overlay_partial', col=column, n=len(docs) - labelled, total=len(docs)))
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


def _parse_alias_map(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in str(text or '').splitlines():
        if '=' not in line:
            continue
        canonical, _, aliases = line.partition('=')
        canonical = canonical.strip()
        if not canonical:
            continue
        mapping[canonical] = canonical
        for alias in re.split(r'[;；|]+', aliases):
            alias = alias.strip()
            if alias:
                mapping[alias] = canonical
    return mapping


def _parse_exclusion_set(text: str) -> set[str]:
    return {line.strip() for line in str(text or '').splitlines() if line.strip()}


def _parse_cluster_overrides(text: str) -> dict[str, str]:
    """``#<cluster>=<label>`` lines: a person, not LLR, decides what a cluster is called.

    The key keeps its ``#`` because that is how every surface here prints a cluster, and a
    bare ``0=…`` would read as a row index to whoever edits the box later.
    """
    overrides: dict[str, str] = {}
    for line in str(text or '').splitlines():
        if '=' not in line:
            continue
        key, _, label = line.partition('=')
        key = key.strip()
        label = label.strip()
        if key and label:
            overrides[key if key.startswith('#') else f'#{key}'] = label
    return overrides


def _apply_cluster_overrides(clusters: dict, text: str) -> tuple[int, list[str]]:
    """Rewrite the stored cluster labels; report how many landed and which named no cluster.

    An override for a cluster the run did not produce is a stale line from an earlier slicing,
    so it is named on the console rather than dropped in silence — and it is not a refusal: the
    labels that DO match are the ones the user asked for.
    """
    overrides = _parse_cluster_overrides(text)
    if not overrides:
        return 0, []
    present = {f'#{member.get("cluster")}' for member in clusters['members'].values()}
    applied = [key for key in overrides if key in present]
    for key in applied:
        for member in clusters['members'].values():
            if f'#{member.get("cluster")}' == key:
                member['cluster_label'] = overrides[key]
    summary = clusters.setdefault('summary', {})
    if applied and summary.get('method'):
        # The label a reader sees was produced by a person, not by the asked-for method, and the
        # summary has to say so — a count of lines that merely *exist* would overstate it.
        summary['method'] = f'{summary["method"]}+manual'
    return len(applied), sorted(set(overrides) - set(applied))


def _apply_label_rules(
    labels: dict[str, str],
    year_counts: dict[str, Counter],
    node_docs: dict[str, set[int]],
    node_years: dict[str, int | None],
    docs: list[dict],
    params: dict,
) -> tuple[dict, dict, dict, dict, list[str]]:
    aliases = _parse_alias_map(params.get('aliases') or '')
    exclusions = _parse_exclusion_set(params.get('exclude_values') or '')
    if not aliases and not exclusions:
        return labels, year_counts, node_docs, node_years, []

    mapping: dict[str, str] = {}
    new_labels: dict[str, str] = {}
    new_year_counts: dict[str, Counter] = defaultdict(Counter)
    new_node_docs: dict[str, set[int]] = defaultdict(set)
    new_node_years: dict[str, int | None] = {}
    excluded = aliased = 0
    for key, label in labels.items():
        canonical = aliases.get(label) or aliases.get(key) or label
        if canonical != label:
            aliased += 1
        if canonical in exclusions or label in exclusions:
            excluded += 1
            continue
        new_labels.setdefault(canonical, canonical)
        mapping[key] = canonical
        new_year_counts[canonical].update(year_counts.get(key, Counter()))
        new_node_docs[canonical].update(node_docs.get(key, set()))
        if new_node_years.get(canonical) is None:
            new_node_years[canonical] = node_years.get(key)

    for doc in docs:
        doc['entities'] = [mapping[name] for name in doc['entities'] if name in mapping]
        if doc.get('name') in mapping:
            doc['name'] = mapping[doc['name']]

    notes = []
    if aliased:
        notes.append(t('biblio.aliases_applied', n=aliased))
    if excluded:
        notes.append(t('biblio.exclusions_applied', n=excluded))
    return new_labels, new_year_counts, new_node_docs, new_node_years, notes
