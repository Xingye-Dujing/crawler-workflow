"""Contracts for the bibliometric (CiteSpace-style) node.

One table, one row per entity. ``连接`` and ``年份序列`` are canonical JSON
text so the rows survive the run store, a CSV export and a resume unchanged;
charts parse them back. The tuple functions here are the single definition of
what a ``biblio`` node emits, shared by the engine, node-schema diagnostics and
the chart builders.
"""

from i18n import t
from utils.helpers import as_bool

ENTITY_TYPES = (
    'keyword',
    'author',
    'institution',
    'country',
    'term',
    'category',
    'document_cocitation',
    'author_cocitation',
    'journal_cocitation',
    'bibliographic_coupling',
)

CITATION_TYPES = (
    'document_cocitation',
    'author_cocitation',
    'journal_cocitation',
)

COUPLING_TYPE = 'bibliographic_coupling'

SELECTION_MODES = ('top_n', 'top_pct', 'g_index', 'threshold')
LINK_MEASURES = ('cosine', 'dice', 'jaccard', 'association')
PRUNING_MODES = ('none', 'mst', 'pathfinder')
LABEL_METHODS = ('llr', 'lsi', 'mi', 'tfidf')

#: The canonical input column each entity kind reads. ``term`` reads two columns
#: and the citation kinds read ``参考文献``; see :data:`ENTITY_REQUIRED`.
ENTITY_COLUMNS = {
    'keyword': '关键词',
    'author': '作者',
    'institution': '作者单位',
    'country': '国家',
    'term': '题名',
    'category': '学科',
    'document_cocitation': '参考文献',
    'author_cocitation': '参考文献',
    'journal_cocitation': '参考文献',
    'bibliographic_coupling': '参考文献',
}

#: Columns a node needs before it can count anything, including the year every
#: slice boundary is cut on.
ENTITY_REQUIRED = {
    'keyword': ('关键词', '年份'),
    'author': ('作者', '年份'),
    'institution': ('作者单位', '年份'),
    'country': ('国家', '年份'),
    'term': ('题名', '年份'),
    'category': ('学科', '年份'),
    'document_cocitation': ('参考文献', '年份'),
    'author_cocitation': ('参考文献', '年份'),
    'journal_cocitation': ('参考文献', '年份'),
    'bibliographic_coupling': ('参考文献', '题名', '年份'),
}

DEFAULTS = {
    'entity_type': 'keyword',
    # Column mapping. Blank entity_column means "the canonical column for this
    # entity kind" (关键词 / 作者 / 作者单位 / …); every other blank means its
    # canonical name. A crawled table can map 话题 / 用户名 / 发布时间 here.
    'entity_column': '',
    'year_column': '年份',
    'title_column': '题名',
    'abstract_column': '摘要',
    'reference_column': '参考文献',
    'time_start': '',
    'time_end': '',
    'slice_years': 1,
    'selection': 'top_n',
    'top_n': 50,
    'top_pct': 10,
    'g_index': 25,
    'min_count': 2,
    'link_measure': 'cosine',
    'max_links_per_node': 10,
    'lrf': 2.5,
    'pruning': 'none',
    'cluster': True,
    'cluster_count': '',
    'label_method': 'llr',
    'top_terms': 5,
    'burst': True,
    'burst_gamma': 1.0,
    'burst_min_duration': 2,
    'burst_weight': 2.0,
    'burst_top': 20,
    'export_files': True,
}

LIMITS = {
    'max_nodes': 5000,
    'max_edges': 100000,
    'max_links_json': 200000,
}

BASE_COLUMNS = (
    '节点',
    '类型',
    '频次',
    '首年',
    '末年',
    '年份序列',
    '度',
    '中介中心性',
    '特征向量中心性',
    'PageRank',
    'Sigma',
    'x',
    'y',
    '连接',
)

CLUSTER_COLUMNS = ('聚类', '聚类标签', '轮廓值')
BURST_COLUMNS = ('突现强度', '突现起始', '突现结束')


def read_columns(params: dict) -> dict[str, str]:
    """The actual table columns this node reads, after the user's mapping.

    ``entity_column`` is blank by default on purpose: the canonical column is a
    function of ``entity_type``, so one box cannot silently mean 关键词 for a
    keyword graph and 作者 for an author graph. A blank year/title/abstract/
    reference box is its canonical column, which is what CNKI/CSSCI and the
    sample workflows carry.
    """
    entity = str(params.get('entity_type') or DEFAULTS['entity_type'])
    return {
        'entity': str(params.get('entity_column') or '').strip() or ENTITY_COLUMNS.get(entity, ''),
        'year': str(params.get('year_column') or DEFAULTS['year_column']).strip() or DEFAULTS['year_column'],
        'title': str(params.get('title_column') or DEFAULTS['title_column']).strip() or DEFAULTS['title_column'],
        'abstract': str(params.get('abstract_column') or DEFAULTS['abstract_column']).strip()
        or DEFAULTS['abstract_column'],
        'reference': str(params.get('reference_column') or DEFAULTS['reference_column']).strip()
        or DEFAULTS['reference_column'],
    }


def output_columns(params: dict) -> list[str]:
    """The exact columns a node emits, conditional on its own switches."""
    cols = list(BASE_COLUMNS)
    if as_bool(params.get('cluster'), DEFAULTS['cluster']):
        cols += list(CLUSTER_COLUMNS)
    entity = str(params.get('entity_type') or DEFAULTS['entity_type'])
    burst_default = False if entity == COUPLING_TYPE else DEFAULTS['burst']
    if as_bool(params.get('burst'), burst_default):
        cols += list(BURST_COLUMNS)
    return cols


def _bad(nid: str, param: str, value, allowed) -> str:
    return t('biblio.bad_option', nid=nid or '(biblio)', param=param, value=value, allowed=allowed)


def _whole(nid: str, param: str, value, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(_bad(nid, param, value, f'{low}..{high}')) from None
    if number < low or number > high:
        raise ValueError(_bad(nid, param, value, f'{low}..{high}'))
    return number


def _number(nid: str, param: str, value, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(_bad(nid, param, value, f'{low}..{high}')) from None
    if number < low or number > high:
        raise ValueError(_bad(nid, param, value, f'{low}..{high}'))
    return number


def collect_errors(params: dict, nid: str = '') -> list[str]:
    """Every parameter problem, in order. One body answers validate and run.

    The engine asks this before a run is paid for; :func:`normalize_params`
    raises the first message when a direct caller skips validation. Both read
    the same rules, so a hand-edited workflow cannot be refused by one and run
    by the other.
    """
    params = params or {}
    errors: list[str] = []

    def check(fn):
        try:
            fn()
        except ValueError as exc:
            errors.append(str(exc))

    entity = str(params.get('entity_type') or DEFAULTS['entity_type']).strip()
    if entity not in ENTITY_TYPES:
        errors.append(_bad(nid, 'entity_type', entity, ', '.join(ENTITY_TYPES)))

    selection = str(params.get('selection') or DEFAULTS['selection']).strip()
    if selection not in SELECTION_MODES:
        errors.append(_bad(nid, 'selection', selection, ', '.join(SELECTION_MODES)))

    measure = str(params.get('link_measure') or DEFAULTS['link_measure']).strip()
    if measure not in LINK_MEASURES:
        errors.append(_bad(nid, 'link_measure', measure, ', '.join(LINK_MEASURES)))

    pruning = str(params.get('pruning') or DEFAULTS['pruning']).strip()
    if pruning not in PRUNING_MODES:
        errors.append(_bad(nid, 'pruning', pruning, ', '.join(PRUNING_MODES)))

    label_method = str(params.get('label_method') or DEFAULTS['label_method']).strip()
    if label_method not in LABEL_METHODS:
        errors.append(_bad(nid, 'label_method', label_method, ', '.join(LABEL_METHODS)))

    check(lambda: _whole(nid, 'slice_years', params.get('slice_years', DEFAULTS['slice_years']), 1, 50))
    check(lambda: _whole(nid, 'top_n', params.get('top_n', DEFAULTS['top_n']), 1, 5000))
    check(lambda: _whole(nid, 'top_pct', params.get('top_pct', DEFAULTS['top_pct']), 1, 100))
    check(lambda: _whole(nid, 'g_index', params.get('g_index', DEFAULTS['g_index']), 1, 1000))
    check(lambda: _whole(nid, 'min_count', params.get('min_count', DEFAULTS['min_count']), 1, 100000))
    check(
        lambda: _whole(
            nid, 'max_links_per_node', params.get('max_links_per_node', DEFAULTS['max_links_per_node']), 1, 200
        )
    )
    check(lambda: _number(nid, 'lrf', params.get('lrf', DEFAULTS['lrf']), 1.0, 100.0))
    check(lambda: _whole(nid, 'top_terms', params.get('top_terms', DEFAULTS['top_terms']), 1, 20))
    check(lambda: _number(nid, 'burst_gamma', params.get('burst_gamma', DEFAULTS['burst_gamma']), 0.01, 100.0))
    check(
        lambda: _whole(
            nid, 'burst_min_duration', params.get('burst_min_duration', DEFAULTS['burst_min_duration']), 1, 50
        )
    )
    check(lambda: _number(nid, 'burst_weight', params.get('burst_weight', DEFAULTS['burst_weight']), 1.0001, 100.0))
    check(lambda: _whole(nid, 'burst_top', params.get('burst_top', DEFAULTS['burst_top']), 1, 500))

    raw_count = params.get('cluster_count', DEFAULTS['cluster_count'])
    if raw_count not in (None, ''):
        check(lambda: _whole(nid, 'cluster_count', raw_count, 2, 50))

    try:
        start, end = _year_pair(params, nid)
    except ValueError as exc:
        errors.append(str(exc))
        start = end = None
    if start is not None and end is not None and start > end:
        errors.append(t('biblio.time_range', nid=nid or '(biblio)', start=start, end=end))

    if entity == COUPLING_TYPE and as_bool(params.get('burst'), False):
        errors.append(t('biblio.coupling_no_burst', nid=nid or '(biblio)'))
    return errors


def _year_pair(params: dict, nid: str) -> tuple[int | None, int | None]:
    def year(value, name):
        text = str(value if value is not None else '').strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            raise ValueError(_bad(nid, name, value, 'a four-digit year or blank')) from None

    return (
        year(params.get('time_start', DEFAULTS['time_start']), 'time_start'),
        year(params.get('time_end', DEFAULTS['time_end']), 'time_end'),
    )


def normalize_params(params: dict, nid: str = '') -> dict:
    """Typed parameters, with every refusal named after the box that caused it."""
    errors = collect_errors(params, nid)
    if errors:
        raise ValueError(errors[0])

    params = params or {}
    entity = str(params.get('entity_type') or DEFAULTS['entity_type']).strip()
    start, end = _year_pair(params, nid)
    raw_count = params.get('cluster_count', DEFAULTS['cluster_count'])
    count = None if raw_count in (None, '') else _whole(nid, 'cluster_count', raw_count, 2, 50)
    return {
        'entity_type': entity,
        'entity_column': str(params.get('entity_column') or '').strip(),
        'year_column': str(params.get('year_column') or DEFAULTS['year_column']).strip() or DEFAULTS['year_column'],
        'title_column': str(params.get('title_column') or DEFAULTS['title_column']).strip() or DEFAULTS['title_column'],
        'abstract_column': str(params.get('abstract_column') or DEFAULTS['abstract_column']).strip()
        or DEFAULTS['abstract_column'],
        'reference_column': str(params.get('reference_column') or DEFAULTS['reference_column']).strip()
        or DEFAULTS['reference_column'],
        'time_start': start,
        'time_end': end,
        'slice_years': _whole(nid, 'slice_years', params.get('slice_years', 1), 1, 50),
        'selection': str(params.get('selection') or DEFAULTS['selection']).strip(),
        'top_n': _whole(nid, 'top_n', params.get('top_n', DEFAULTS['top_n']), 1, 5000),
        'top_pct': _whole(nid, 'top_pct', params.get('top_pct', DEFAULTS['top_pct']), 1, 100),
        'g_index': _whole(nid, 'g_index', params.get('g_index', DEFAULTS['g_index']), 1, 1000),
        'min_count': _whole(nid, 'min_count', params.get('min_count', DEFAULTS['min_count']), 1, 100000),
        'link_measure': str(params.get('link_measure') or DEFAULTS['link_measure']).strip(),
        'max_links_per_node': _whole(
            nid, 'max_links_per_node', params.get('max_links_per_node', DEFAULTS['max_links_per_node']), 1, 200
        ),
        'lrf': _number(nid, 'lrf', params.get('lrf', DEFAULTS['lrf']), 1.0, 100.0),
        'pruning': str(params.get('pruning') or DEFAULTS['pruning']).strip(),
        'cluster': as_bool(params.get('cluster'), DEFAULTS['cluster']),
        'cluster_count': count,
        'label_method': str(params.get('label_method') or DEFAULTS['label_method']).strip(),
        'top_terms': _whole(nid, 'top_terms', params.get('top_terms', DEFAULTS['top_terms']), 1, 20),
        'burst': as_bool(params.get('burst'), False if entity == COUPLING_TYPE else DEFAULTS['burst']),
        'burst_gamma': _number(nid, 'burst_gamma', params.get('burst_gamma', DEFAULTS['burst_gamma']), 0.01, 100.0),
        'burst_min_duration': _whole(
            nid, 'burst_min_duration', params.get('burst_min_duration', DEFAULTS['burst_min_duration']), 1, 50
        ),
        'burst_weight': _number(
            nid, 'burst_weight', params.get('burst_weight', DEFAULTS['burst_weight']), 1.0001, 100.0
        ),
        'burst_top': _whole(nid, 'burst_top', params.get('burst_top', DEFAULTS['burst_top']), 1, 500),
        'export_files': as_bool(params.get('export_files'), DEFAULTS['export_files']),
    }
