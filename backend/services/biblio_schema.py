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
    'journal',
    'source',
    'funder',
    'grant',
    'document_cocitation',
    'author_cocitation',
    'journal_cocitation',
    'article',
    'document',
    'bibliographic_coupling',
)

CITATION_TYPES = (
    'document_cocitation',
    'author_cocitation',
    'journal_cocitation',
    'article',
)

#: Document coupling and source-journal coupling read a paper's references and
#: connect the citing units that share them. ``document`` and
#: ``bibliographic_coupling`` are the same construction under the names used by
#: CiteSpace and by this project; keeping both is a compatibility choice.
COUPLING_TYPES = ('document', 'bibliographic_coupling', 'journal', 'source')

COUPLING_TYPE = 'bibliographic_coupling'

OUTPUT_SHAPES = ('nodes', 'edges', 'clusters', 'bursts')

SELECTION_MODES = ('top_n', 'top_pct', 'g_index', 'threshold')
LINK_MEASURES = ('cosine', 'dice', 'jaccard', 'association')
PRUNING_MODES = ('none', 'mst', 'pathfinder')
PRUNING_SCOPES = ('slices', 'merged')
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
    'journal': '来源期刊',
    'source': '来源期刊',
    'funder': '基金',
    'grant': '基金',
    'document_cocitation': '参考文献',
    'author_cocitation': '参考文献',
    'journal_cocitation': '参考文献',
    'article': '参考文献',
    'document': '题名',
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
    'journal': ('参考文献', '来源期刊', '年份'),
    'source': ('参考文献', '来源期刊', '年份'),
    'funder': ('基金', '年份'),
    'grant': ('基金', '年份'),
    'document_cocitation': ('参考文献', '年份'),
    'author_cocitation': ('参考文献', '年份'),
    'journal_cocitation': ('参考文献', '年份'),
    'article': ('参考文献', '年份'),
    'document': ('参考文献', '题名', '年份'),
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
    'tc_column': '引用次数',
    'usage_column': '使用次数',
    'time_start': '',
    'time_end': '',
    'slice_years': 1,
    'look_back_years': 0,
    'selection': 'top_n',
    'top_n': 50,
    'top_pct': 10,
    'g_index': 25,
    'min_count': 2,
    'threshold_c': 0,
    'threshold_cc': 1,
    'threshold_ccv': 0.0,
    'min_tc': '',
    'min_usage': '',
    'largest_component': False,
    'link_measure': 'cosine',
    'citation_expansion': 0,
    'max_links_per_node': 10,
    'lrf': 2.5,
    'pruning': 'none',
    'pruning_scope': 'slices',
    'cluster': True,
    'cluster_count': '',
    'label_method': 'llr',
    'top_terms': 5,
    'burst': True,
    'burst_gamma': 1.0,
    'burst_min_duration': 2,
    'burst_weight': 2.0,
    'burst_top': 20,
    'output_shape': 'nodes',
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

#: Data-dependent citation metrics. They are emitted only when the input table
#: really has the mapped times-cited/usage columns, so CNKI RefWorks does not
#: gain an all-zero H-index column it cannot justify.
CITATION_METRIC_COLUMNS = ('总被引', 'H指数')
USAGE_METRIC_COLUMNS = ('使用次数合计',)

EDGE_COLUMNS = ('source', 'target', 'weight', 'count')
CLUSTER_TABLE_COLUMNS = ('聚类', '聚类标签', '节点数', '节点', '轮廓值')
BURST_TABLE_COLUMNS = ('节点', '突现起始', '突现结束', '突现强度')


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
        'tc': str(params.get('tc_column') or DEFAULTS['tc_column']).strip() or DEFAULTS['tc_column'],
        'usage': str(params.get('usage_column') or DEFAULTS['usage_column']).strip() or DEFAULTS['usage_column'],
    }


def output_columns(params: dict, input_columns: list[str] | None = None) -> list[str]:
    """The exact columns a node emits, conditional on its own switches and input."""
    shape = str(params.get('output_shape') or DEFAULTS['output_shape'])
    if shape == 'edges':
        return list(EDGE_COLUMNS)
    if shape == 'clusters':
        return list(CLUSTER_TABLE_COLUMNS)
    if shape == 'bursts':
        return list(BURST_TABLE_COLUMNS)
    cols = list(BASE_COLUMNS)
    if as_bool(params.get('cluster'), DEFAULTS['cluster']):
        cols += list(CLUSTER_COLUMNS)
    entity = str(params.get('entity_type') or DEFAULTS['entity_type'])
    burst_default = False if entity in COUPLING_TYPES else DEFAULTS['burst']
    if as_bool(params.get('burst'), burst_default):
        cols += list(BURST_COLUMNS)
    available = set(input_columns or [])
    columns = read_columns(params)
    if columns['tc'] in available:
        cols += list(CITATION_METRIC_COLUMNS)
    if columns['usage'] in available:
        cols += list(USAGE_METRIC_COLUMNS)
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


def _optional_whole(nid: str, param: str, value) -> int | None:
    text = str(value if value is not None else '').strip()
    return None if not text else _whole(nid, param, text, 0, 1000000000)


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

    scope = str(params.get('pruning_scope') or DEFAULTS['pruning_scope']).strip()
    if scope not in PRUNING_SCOPES:
        errors.append(_bad(nid, 'pruning_scope', scope, ', '.join(PRUNING_SCOPES)))

    label_method = str(params.get('label_method') or DEFAULTS['label_method']).strip()
    if label_method not in LABEL_METHODS:
        errors.append(_bad(nid, 'label_method', label_method, ', '.join(LABEL_METHODS)))

    shape = str(params.get('output_shape') or DEFAULTS['output_shape']).strip()
    if shape not in OUTPUT_SHAPES:
        errors.append(_bad(nid, 'output_shape', shape, ', '.join(OUTPUT_SHAPES)))

    check(lambda: _whole(nid, 'slice_years', params.get('slice_years', DEFAULTS['slice_years']), 1, 50))
    check(lambda: _whole(nid, 'look_back_years', params.get('look_back_years', DEFAULTS['look_back_years']), 0, 50))
    check(lambda: _whole(nid, 'threshold_c', params.get('threshold_c', DEFAULTS['threshold_c']), 0, 100000))
    check(lambda: _whole(nid, 'threshold_cc', params.get('threshold_cc', DEFAULTS['threshold_cc']), 0, 100000))
    check(lambda: _number(nid, 'threshold_ccv', params.get('threshold_ccv', DEFAULTS['threshold_ccv']), 0.0, 1.0))
    for name in ('min_tc', 'min_usage'):
        raw = params.get(name, DEFAULTS[name])
        if raw not in (None, ''):
            check(lambda raw=raw, name=name: _whole(nid, name, raw, 0, 1000000000))
    check(lambda: _whole(nid, 'top_n', params.get('top_n', DEFAULTS['top_n']), 1, 5000))
    check(lambda: _whole(nid, 'top_pct', params.get('top_pct', DEFAULTS['top_pct']), 1, 100))
    check(lambda: _whole(nid, 'g_index', params.get('g_index', DEFAULTS['g_index']), 1, 1000))
    check(lambda: _whole(nid, 'min_count', params.get('min_count', DEFAULTS['min_count']), 1, 100000))
    check(
        lambda: _whole(
            nid, 'max_links_per_node', params.get('max_links_per_node', DEFAULTS['max_links_per_node']), 1, 200
        )
    )
    check(lambda: _whole(nid, 'citation_expansion', params.get('citation_expansion', 0), 0, 2))
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

    burst_default = False if entity in COUPLING_TYPES else DEFAULTS['burst']
    if entity in COUPLING_TYPES and as_bool(params.get('burst'), False):
        errors.append(t('biblio.coupling_no_burst', nid=nid or '(biblio)'))
    if shape == 'clusters' and not as_bool(params.get('cluster'), DEFAULTS['cluster']):
        errors.append(t('biblio.shape_needs_cluster', nid=nid or '(biblio)'))
    if shape == 'bursts' and not as_bool(params.get('burst'), burst_default):
        errors.append(t('biblio.shape_needs_burst', nid=nid or '(biblio)'))
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
        'tc_column': str(params.get('tc_column') or DEFAULTS['tc_column']).strip() or DEFAULTS['tc_column'],
        'usage_column': str(params.get('usage_column') or DEFAULTS['usage_column']).strip() or DEFAULTS['usage_column'],
        'time_start': start,
        'time_end': end,
        'slice_years': _whole(nid, 'slice_years', params.get('slice_years', 1), 1, 50),
        'look_back_years': _whole(nid, 'look_back_years', params.get('look_back_years', 0), 0, 50),
        'selection': str(params.get('selection') or DEFAULTS['selection']).strip(),
        'top_n': _whole(nid, 'top_n', params.get('top_n', DEFAULTS['top_n']), 1, 5000),
        'top_pct': _whole(nid, 'top_pct', params.get('top_pct', DEFAULTS['top_pct']), 1, 100),
        'g_index': _whole(nid, 'g_index', params.get('g_index', DEFAULTS['g_index']), 1, 1000),
        'min_count': _whole(nid, 'min_count', params.get('min_count', DEFAULTS['min_count']), 1, 100000),
        'threshold_c': _whole(nid, 'threshold_c', params.get('threshold_c', DEFAULTS['threshold_c']), 0, 100000),
        'threshold_cc': _whole(nid, 'threshold_cc', params.get('threshold_cc', DEFAULTS['threshold_cc']), 0, 100000),
        'threshold_ccv': _number(
            nid, 'threshold_ccv', params.get('threshold_ccv', DEFAULTS['threshold_ccv']), 0.0, 1.0
        ),
        'min_tc': _optional_whole(nid, 'min_tc', params.get('min_tc', DEFAULTS['min_tc'])),
        'min_usage': _optional_whole(nid, 'min_usage', params.get('min_usage', DEFAULTS['min_usage'])),
        'largest_component': as_bool(params.get('largest_component'), DEFAULTS['largest_component']),
        'link_measure': str(params.get('link_measure') or DEFAULTS['link_measure']).strip(),
        'citation_expansion': _whole(nid, 'citation_expansion', params.get('citation_expansion', 0), 0, 2),
        'max_links_per_node': _whole(
            nid, 'max_links_per_node', params.get('max_links_per_node', DEFAULTS['max_links_per_node']), 1, 200
        ),
        'lrf': _number(nid, 'lrf', params.get('lrf', DEFAULTS['lrf']), 1.0, 100.0),
        'pruning': str(params.get('pruning') or DEFAULTS['pruning']).strip(),
        'pruning_scope': str(params.get('pruning_scope') or DEFAULTS['pruning_scope']).strip(),
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
        'output_shape': str(params.get('output_shape') or DEFAULTS['output_shape']).strip(),
        'export_files': as_bool(params.get('export_files'), DEFAULTS['export_files']),
    }
