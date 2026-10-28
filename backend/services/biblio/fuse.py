"""Cross-source fusion: several tables of records into ONE normalized record table.

Why a node and not the engine's fan-in merge: merging keeps each table's own column names, so a
literature file's ``关键词`` and a crawled ``话题`` sit in two different columns and no downstream
entity mapping can speak of both as one vocabulary. This node folds the candidate columns into
the canonical record shape and — the part a merge cannot do — keeps **which source every row came
from**, because a graph that mixes papers with posts is only readable if a term's provenance
travels with it.

A source is named, never guessed: a column that already says so (``平台``), a line the user
wrote for that parent, or the parent node's own title. A parent whose declared columns match
nothing is refused by name rather than contributing an empty slice of the graph.
"""

import re
from pathlib import Path

from i18n import t

#: The canonical record columns a ``biblio`` node reads with its default mapping, plus the
#: provenance column this node is the only producer of.
OUTPUT_COLUMNS = [
    '记录ID',
    '题名',
    '作者',
    '作者单位',
    '来源期刊',
    '年份',
    '关键词',
    '摘要',
    '参考文献',
    '来源',
]

#: Candidate columns per role, tried in order. A fusion node exists because different sources
#: name the same idea differently, so a role holds a list rather than one column.
DEFAULTS = {
    'entity_columns': '关键词,话题,主题,主题词,标签',
    'year_columns': '年份,发布时间,发表日期,日期',
    'title_columns': '题名,标题,内容,正文',
    'author_columns': '作者,用户名,昵称,发布者',
    'affiliation_columns': '作者单位,机构',
    'text_columns': '摘要,正文,内容',
    'reference_columns': '参考文献,引文',
    'source_columns': '平台,来源',
    'source_labels': '',
    'keep_undated': True,
}

_ROLES = (
    ('entity', 'entity_columns'),
    ('year', 'year_columns'),
    ('title', 'title_columns'),
    ('author', 'author_columns'),
    ('affiliation', 'affiliation_columns'),
    ('text', 'text_columns'),
    ('reference', 'reference_columns'),
)

#: The parameter names holding candidate column lists. ``nodes/schema.py`` reads them to report
#: which columns a fusion node depends on, so the list is part of the schema contract.
ROLE_PARAMS = tuple(key for _role, key in _ROLES) + ('source_columns',)

_LIST_SPLIT = re.compile(r'[;；,，、\n/|]+')
_YEAR = re.compile(r'(1[89]\d{2}|20\d{2})')


def normalize_params(params: dict) -> dict:
    """Typed parameters; every candidate list keeps its order, because order is the preference.

    The result is keyed by BOTH names — the parameter (``entity_columns``) for anyone reading the
    node's own settings back, and the role (``entity``) for the fold below.
    """
    params = params or {}
    out: dict = {}
    for key, default in DEFAULTS.items():
        raw = params.get(key, default)
        if key == 'source_labels':
            out[key] = _parse_source_labels(raw)
        elif key == 'keep_undated':
            out[key] = _as_bool(raw, True)
        else:
            out[key] = [part.strip() for part in str(raw or '').split(',') if part.strip()]
    for role, key in _ROLES:
        out[role] = out[key]
    out['source'] = out['source_columns']
    return out


def _as_bool(value, default: bool) -> bool:
    if value is None or str(value).strip() == '':
        return default
    return str(value).strip().lower() not in ('false', '0', 'no', 'off', '否', '关')


def _parse_source_labels(text: str) -> dict[str, str]:
    """``<父节点 id 或标题>=<来源名>`` lines, for a table that carries no source column."""
    mapping: dict[str, str] = {}
    for line in str(text or '').splitlines():
        if '=' not in line:
            continue
        key, _, label = line.partition('=')
        key, label = key.strip(), label.strip()
        if key and label:
            mapping[key] = label
    return mapping


def collect_errors(params: dict, nid: str = '') -> list[str]:
    """A fusion node with no entity role has nothing to build a graph from."""
    params = normalize_params(params)
    errors = []
    if not params['entity']:
        errors.append(t('fuse.needs_entity', nid=nid or '(fuse)'))
    return errors


def _candidates(columns, wanted: list[str]) -> str:
    """The first declared candidate this table really has, matched case- and space-insensitively."""
    lookup = {str(column).strip().lower(): column for column in columns}
    for name in wanted:
        found = lookup.get(str(name).strip().lower())
        if found is not None:
            return found
    return ''


def _values(value) -> list[str]:
    seen: list[str] = []
    for part in _LIST_SPLIT.split(str(value if value is not None else '')):
        item = part.strip().strip('.')
        if item and item not in seen:
            seen.append(item)
    return seen


def _year_of(value) -> str:
    """A four-digit year out of whatever the cell holds — a datetime string included.

    Social tables stamp 发布时间 as ``2026-03-04 11:02``, literature tables as ``2021`` or
    ``2021年``; the slicing downstream needs an integer year or nothing at all, never a
    half-parsed timestamp.
    """
    match = _YEAR.search(str(value if value is not None else ''))
    return match.group(1) if match else ''


def fuse(upstream, params: dict, nid: str = '') -> dict:
    """Fold every parent table into the canonical record table.

    Returns ``{'rows', 'columns', 'sources', 'summary', 'notes'}``. ``sources`` lists what each
    parent contributed and how it was named, so the console can show where every row came from.
    """
    parsed = normalize_params(params)
    rows: list[dict] = []
    sources: list[dict] = []
    notes: list[str] = []
    parents = list(upstream or ())
    if not parents:
        raise ValueError(t('fuse.no_input', nid=nid or '(fuse)'))

    for position, (pid, result) in enumerate(parents):
        records = result if isinstance(result, list) else []
        if not records:
            raise ValueError(t('fuse.empty_parent', nid=nid or '(fuse)', pid=str(pid)))
        columns = list(records[0].keys())
        found = {role: _candidates(columns, parsed[role]) for role, _key in _ROLES}
        if not found['entity']:
            raise ValueError(
                t(
                    'fuse.no_entity_column',
                    nid=nid or '(fuse)',
                    pid=str(pid),
                    wanted=', '.join(parsed['entity_columns'] or []),
                )
            )
        label, source_column = _source_label(records, columns, parsed, pid, position)
        contributed = 0
        for index, record in enumerate(records):
            terms = _values(record.get(found['entity']))
            if not terms:
                continue
            year = _year_of(record.get(found['year'])) if found['year'] else ''
            if not year and not parsed['keep_undated']:
                continue
            title = str(record.get(found['title']) or '').strip() if found['title'] else ''
            # A table that carries several platforms labels each row with its OWN one; the
            # table-level label is only the fallback for rows that do not say.
            origin = (str(record.get(source_column) or '').strip() if source_column else '') or label
            rows.append(
                {
                    '记录ID': f'{origin}#{position}-{index}',
                    '题名': title or f'{origin} {index + 1}',
                    '作者': str(record.get(found['author']) or '').strip() if found['author'] else '',
                    '作者单位': str(record.get(found['affiliation']) or '').strip() if found['affiliation'] else '',
                    # A post has no journal; the source name is the closest honest reading of
                    # "where this record came from", and it is what the dual map would key on.
                    '来源期刊': origin,
                    '年份': year,
                    '关键词': ';'.join(terms),
                    '摘要': str(record.get(found['text']) or '').strip() if found['text'] else '',
                    '参考文献': str(record.get(found['reference']) or '').strip() if found['reference'] else '',
                    '来源': origin,
                }
            )
            contributed += 1
        if not contributed:
            raise ValueError(t('fuse.no_rows', nid=nid or '(fuse)', pid=str(pid), column=found['entity']))
        sources.append(
            {
                'node_id': str(pid),
                'source': label,
                'rows': contributed,
                'entity_column': found['entity'],
                'year_column': found['year'],
            }
        )
        notes.append(t('fuse.source_named', source=label, pid=str(pid), rows=contributed))

    distinct = {row['来源'] for row in rows}
    return {
        'rows': rows,
        'columns': list(OUTPUT_COLUMNS),
        'sources': sources,
        'notes': notes,
        'summary': {
            'node_id': nid,
            'parents': len(parents),
            'sources': sorted(distinct),
            'rows': len(rows),
        },
    }


def _source_label(records, columns, parsed: dict, pid, position: int) -> tuple[str, str]:
    """Where this table's source name comes from, and the column that may override it per row.

    A column that already carries it wins (a crawled table knows its own 平台 per row), then the
    line written for this parent, then the parent's node id. Nothing here invents 「文献」 for a
    table that never said so.
    """
    source_column = _candidates(columns, parsed['source_columns'])
    if source_column:
        values = {str(record.get(source_column) or '').strip() for record in records}
        values.discard('')
        if len(values) == 1:
            return values.pop(), source_column
        if len(values) > 1:
            # One table, several platforms: the table has no single name, so each row keeps its
            # own and the summary lists the parent by id.
            return str(pid), source_column
    for key in (str(pid), f'#{position}'):
        if key in parsed['source_labels']:
            return parsed['source_labels'][key], source_column
    return str(pid), source_column


def export_records(rows: list[dict], out_dir: str, base_name: str) -> str:
    """Write the fused record table as a CSV next to the graph artifacts of the run.

    A fusion is the one place a person wants the intermediate table on disk: it is the file they
    hand to a colleague, and the only way to check that a term really did come from the corpus
    they think it came from.
    """
    import pandas as pd

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\/:*?"<>|\s]+', '_', str(base_name or 'fuse')).strip('._') or 'fuse'
    path = target / f'{safe}.csv'
    pd.DataFrame(rows, columns=list(OUTPUT_COLUMNS)).to_csv(path, index=False, encoding='utf-8-sig')
    return str(path)
