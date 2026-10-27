"""Contracts for the bibliometric (CiteSpace-style) node.

One table, one row per entity. ``连接`` and ``年份序列`` are canonical JSON
text so the rows survive the run store, a CSV export and a resume unchanged;
charts parse them back. The tuple functions here are the single definition of
what a ``biblio`` node emits, shared by the engine, node-schema diagnostics and
the chart builders.
"""

from core.refs import as_bool

from i18n import t

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

OUTPUT_SHAPES = ('nodes', 'edges', 'clusters', 'bursts', 'variation', 'dual_map')

#: Shapes whose rows are NOT one row per entity: ``variation`` repeats a node once per slice pair,
#: ``clusters``/``bursts`` are per-cluster or per-burst rows. A cross-run monitor captures an
#: entity table, so filing one of these would store a graph whose node count is a multiple of the
#: real one and make every later comparison a comparison of two different questions.
WATCH_UNSHAPED = ('variation', 'clusters', 'bursts')

SELECTION_MODES = ('top_n', 'top_pct', 'g_index', 'threshold')
LINK_MEASURES = ('cosine', 'dice', 'jaccard', 'association')
#: How much a mediating document contributes to a link. ``full`` counts it once per pair it
#: contains; ``fractional`` divides its credit across the entries it carries, so one article
#: with 150 references stops outranking one with 12 — the standard full-vs-fractional
#: counting distinction in bibliometrics. Applied where a THIRD document mediates the link
#: (co-occurrence inside a document, co-citation inside a citing document).
COUNTING_MODES = ('full', 'fractional')
PRUNING_MODES = ('none', 'mst', 'pathfinder')
PRUNING_SCOPES = ('slices', 'merged')
#: Mantel's r-norm exponent for the Pathfinder reduction. ``inf`` is the classic PFNET
#: (a path is as long as its weakest link, i.e. the maximin path), ``1`` sums the link
#: distances, ``2`` takes their Euclidean norm. Stored as a string because the setting is
#: a select; ``inf`` never becomes a float in a JSON canvas.
PATHFINDER_R = ('1', '2', 'inf')
LABEL_METHODS = ('llr', 'lsi', 'mi', 'tfidf')
#: Which fields a cluster label draws its words from. ``all`` is the node's historical mix
#: (title + abstract + the graph's own keyword/entity values) — authors are deliberately NOT
#: folded into it, because an author name inside a keyword-cluster label is a claim the user did
#: not ask for; ``author`` is its own choice.
LABEL_SOURCES = ('all', 'title', 'abstract', 'keywords', 'author')

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
    # Optional overlays of a label column an upstream step already wrote (sentiment/emotion/
    # tendency, or a per-document topic). Blank = the node behaves exactly as it did before
    # these parameters existed; a NAMED column that is absent is refused by name at the run.
    'sentiment_column': '',
    'topic_column': '',
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
    'counting': 'full',
    'citation_expansion': 0,
    'max_links_per_node': 10,
    'lrf': 2.5,
    'pruning': 'none',
    'pruning_scope': 'slices',
    # Pathfinder only. r is the Mantel exponent; lmax the longest indirect path considered
    # (0 = every path, i.e. n-1 links); dmax the fraction of the surviving links to keep,
    # strongest first (1.0 keeps all of them).
    'pathfinder_r': 'inf',
    'pathfinder_lmax': 0,
    'pathfinder_dmax': 1.0,
    'cluster': True,
    'cluster_count': '',
    'label_method': 'llr',
    'label_source': 'all',
    'top_terms': 5,
    'burst': True,
    'burst_gamma': 1.0,
    'burst_min_duration': 2,
    'burst_weight': 2.0,
    'burst_top': 20,
    # Structural variation: how far a node's connection pattern moves between two
    # consecutive slices. ``variation_min`` is the divergence (in bits) a row must reach
    # to be reported at all — 0 would list every node that merely gained a neighbour.
    'variation': False,
    'variation_min': 0.05,
    'aliases': '',
    'exclude_values': '',
    'cluster_labels': '',
    'basemap_dataset_id': '',
    # Cross-run monitoring (定时任务 + 快照): each run files its own capture into this project
    # and diffs it against the previous one. Blank project = the node behaves exactly as before
    # the parameter existed.
    'watch_project': '',
    'watch_baseline': '',
    'watch_label': '',
    'output_shape': 'nodes',
    'export_files': True,
}

LIMITS = {
    'max_nodes': 5000,
    'max_edges': 100000,
    'max_links_json': 200000,
    # Pathfinder's guard is the WORK budget (``bibliometrics._PFNET_WORK_BUDGET``), not a node
    # count: the classic r=∞ / unlimited-depth case is a spanning forest at O(m log n) and must
    # not be refused for size, while a 500-node general DP is 6×10^10 element operations.
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

#: Emitted only when the input is a fused record table (``fuse`` node upstream): which corpora
#: an entity appears in, and whether that is more than one.
SOURCE_COLUMNS = ('来源', '跨源')

#: Emitted only when the node maps an upstream label column. ``情感分布`` / ``话题分布`` are
#: canonical JSON (label → number of mentioning documents), like ``年份序列``, so a stored row,
#: a CSV export and a resume all parse back to the same counts; ``情感倾向`` / ``主导话题`` are
#: the label the node's mentioning documents use most (ties broken by label, never by row order).
SENTIMENT_COLUMNS = ('情感倾向', '情感分布')
TOPIC_COLUMNS = ('主导话题', '话题分布')

EDGE_COLUMNS = ('source', 'target', 'weight', 'count')
DUAL_MAP_COLUMNS = ('map', 'source', 'target', 'weight', 'label', 'x', 'y')
CLUSTER_TABLE_COLUMNS = ('聚类', '聚类标签', '节点数', '节点', '轮廓值')
BURST_TABLE_COLUMNS = ('节点', '突现起始', '突现结束', '突现强度')
#: One row per node per pair of CONSECUTIVE slices: how far its connection pattern moved.
#: The score is the Jensen–Shannon divergence (bits) between the node's two link-strength
#: distributions, so it is bounded and symmetric — a neighbour that appears or disappears is a
#: real structural change, not an infinite KL term.
VARIATION_COLUMNS = (
    '节点',
    '起始年',
    '结束年',
    '结构变化',
    '前邻居',
    '后邻居',
    '新增邻居',
    '消失邻居',
)


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
    if shape == 'variation':
        return list(VARIATION_COLUMNS)
    if shape == 'dual_map':
        return list(DUAL_MAP_COLUMNS)
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
    # Provenance travels only from a fused record table.
    if '来源' in available:
        cols += list(SOURCE_COLUMNS)
    # The overlay columns exist only when the node maps a column AND the input carries it — the
    # same evidence rule the citation metrics follow, so diagnostics never promise a column the
    # run cannot fill.
    if str(params.get('sentiment_column') or '').strip() in available:
        cols += list(SENTIMENT_COLUMNS)
    if str(params.get('topic_column') or '').strip() in available:
        cols += list(TOPIC_COLUMNS)
    return cols


def classify_shape(columns) -> str:
    """The output shape a stored table was emitted as, read back off its own columns.

    ``output_columns`` is the forward direction; the workspace panel needs the reverse one
    because a run record stores rows, not the node's parameters. An unrecognised table answers
    ``''`` — the panel then says it cannot tell, which is the honest reading of a table whose
    shape the columns do not determine.
    """
    names = {str(column) for column in columns or ()}
    if 'map' in names:
        return 'dual_map'
    if {'source', 'target', 'weight', 'count'} <= names:
        return 'edges'
    if '节点数' in names:
        return 'clusters'
    if {'突现起始', '突现结束', '突现强度'} <= names and '频次' not in names:
        return 'bursts'
    if '结构变化' in names:
        return 'variation'
    if '节点' in names:
        return 'nodes'
    return ''


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

    counting = str(params.get('counting') or DEFAULTS['counting']).strip()
    if counting not in COUNTING_MODES:
        errors.append(_bad(nid, 'counting', counting, ', '.join(COUNTING_MODES)))
    elif counting == 'fractional' and entity in COUPLING_TYPES:
        # In a coupling network the two citing documents ARE the endpoints, so there is no third
        # document whose credit could be split: fractional counting has nothing to divide.
        errors.append(t('biblio.counting_no_coupling', nid=nid or '(biblio)', entity=entity))

    pruning = str(params.get('pruning') or DEFAULTS['pruning']).strip()
    if pruning not in PRUNING_MODES:
        errors.append(_bad(nid, 'pruning', pruning, ', '.join(PRUNING_MODES)))

    scope = str(params.get('pruning_scope') or DEFAULTS['pruning_scope']).strip()
    if scope not in PRUNING_SCOPES:
        errors.append(_bad(nid, 'pruning_scope', scope, ', '.join(PRUNING_SCOPES)))

    pf_r = str(params.get('pathfinder_r') or DEFAULTS['pathfinder_r']).strip()
    if pf_r not in PATHFINDER_R:
        errors.append(_bad(nid, 'pathfinder_r', pf_r, ', '.join(PATHFINDER_R)))

    label_method = str(params.get('label_method') or DEFAULTS['label_method']).strip()
    if label_method not in LABEL_METHODS:
        errors.append(_bad(nid, 'label_method', label_method, ', '.join(LABEL_METHODS)))

    label_source = str(params.get('label_source') or DEFAULTS['label_source']).strip()
    if label_source not in LABEL_SOURCES:
        errors.append(_bad(nid, 'label_source', label_source, ', '.join(LABEL_SOURCES)))

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
    check(lambda: _whole(nid, 'pathfinder_lmax', params.get('pathfinder_lmax', DEFAULTS['pathfinder_lmax']), 0, 50))
    check(
        lambda: _number(nid, 'pathfinder_dmax', params.get('pathfinder_dmax', DEFAULTS['pathfinder_dmax']), 0.05, 1.0)
    )
    check(lambda: _whole(nid, 'top_terms', params.get('top_terms', DEFAULTS['top_terms']), 1, 20))
    check(lambda: _number(nid, 'burst_gamma', params.get('burst_gamma', DEFAULTS['burst_gamma']), 0.01, 100.0))
    check(
        lambda: _whole(
            nid, 'burst_min_duration', params.get('burst_min_duration', DEFAULTS['burst_min_duration']), 1, 50
        )
    )
    check(lambda: _number(nid, 'burst_weight', params.get('burst_weight', DEFAULTS['burst_weight']), 1.0001, 100.0))
    check(lambda: _whole(nid, 'burst_top', params.get('burst_top', DEFAULTS['burst_top']), 1, 500))
    check(lambda: _number(nid, 'variation_min', params.get('variation_min', DEFAULTS['variation_min']), 0.0, 1.0))

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
    if entity in COUPLING_TYPES and as_bool(params.get('burst'), burst_default):
        errors.append(t('biblio.coupling_no_burst', nid=nid or '(biblio)'))
    if shape == 'clusters' and not as_bool(params.get('cluster'), DEFAULTS['cluster']):
        errors.append(t('biblio.shape_needs_cluster', nid=nid or '(biblio)'))
    if shape == 'bursts' and not as_bool(params.get('burst'), burst_default):
        errors.append(t('biblio.shape_needs_burst', nid=nid or '(biblio)'))
    if shape == 'variation' and not as_bool(params.get('variation'), DEFAULTS['variation']):
        # Asking for the variation table without the switch is a stale box, not a preference:
        # say which one is missing instead of emitting an empty table the charts then refuse.
        errors.append(t('biblio.shape_needs_variation', nid=nid or '(biblio)'))
    if shape == 'dual_map' and not str(params.get('basemap_dataset_id') or '').strip():
        errors.append(t('biblio.dual_map_needs_basemap', nid=nid or '(biblio)'))
    if str(params.get('cluster_labels') or '').strip() and not as_bool(params.get('cluster'), DEFAULTS['cluster']):
        # Naming clusters that will not exist is a stale box, not a preference: say which switch
        # is missing instead of quietly ignoring the labels the user typed.
        errors.append(t('biblio.cluster_labels_need_cluster', nid=nid or '(biblio)'))
    watch_project = str(params.get('watch_project') or '').strip()
    if not watch_project and (
        str(params.get('watch_baseline') or '').strip() or str(params.get('watch_label') or '').strip()
    ):
        # A baseline and a capture name belong to a project; filing them with none would let the
        # node look configured while it watches nothing at all.
        errors.append(t('biblio.watch_needs_project', nid=nid or '(biblio)'))
    if watch_project and shape in WATCH_UNSHAPED:
        errors.append(t('biblio.watch_needs_entity_table', nid=nid or '(biblio)', shape=shape))
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
        'sentiment_column': str(params.get('sentiment_column') or '').strip(),
        'topic_column': str(params.get('topic_column') or '').strip(),
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
        'counting': str(params.get('counting') or DEFAULTS['counting']).strip(),
        'citation_expansion': _whole(nid, 'citation_expansion', params.get('citation_expansion', 0), 0, 2),
        'max_links_per_node': _whole(
            nid, 'max_links_per_node', params.get('max_links_per_node', DEFAULTS['max_links_per_node']), 1, 200
        ),
        'lrf': _number(nid, 'lrf', params.get('lrf', DEFAULTS['lrf']), 1.0, 100.0),
        'pruning': str(params.get('pruning') or DEFAULTS['pruning']).strip(),
        'pruning_scope': str(params.get('pruning_scope') or DEFAULTS['pruning_scope']).strip(),
        'pathfinder_r': str(params.get('pathfinder_r') or DEFAULTS['pathfinder_r']).strip(),
        'pathfinder_lmax': _whole(
            nid, 'pathfinder_lmax', params.get('pathfinder_lmax', DEFAULTS['pathfinder_lmax']), 0, 50
        ),
        'pathfinder_dmax': _number(
            nid, 'pathfinder_dmax', params.get('pathfinder_dmax', DEFAULTS['pathfinder_dmax']), 0.05, 1.0
        ),
        'cluster': as_bool(params.get('cluster'), DEFAULTS['cluster']),
        'cluster_count': count,
        'label_method': str(params.get('label_method') or DEFAULTS['label_method']).strip(),
        'label_source': str(params.get('label_source') or DEFAULTS['label_source']).strip(),
        'top_terms': _whole(nid, 'top_terms', params.get('top_terms', DEFAULTS['top_terms']), 1, 20),
        'burst': as_bool(params.get('burst'), False if entity in COUPLING_TYPES else DEFAULTS['burst']),
        'burst_gamma': _number(nid, 'burst_gamma', params.get('burst_gamma', DEFAULTS['burst_gamma']), 0.01, 100.0),
        'burst_min_duration': _whole(
            nid, 'burst_min_duration', params.get('burst_min_duration', DEFAULTS['burst_min_duration']), 1, 50
        ),
        'burst_weight': _number(
            nid, 'burst_weight', params.get('burst_weight', DEFAULTS['burst_weight']), 1.0001, 100.0
        ),
        'burst_top': _whole(nid, 'burst_top', params.get('burst_top', DEFAULTS['burst_top']), 1, 500),
        'variation': as_bool(params.get('variation'), DEFAULTS['variation']),
        'variation_min': _number(
            nid, 'variation_min', params.get('variation_min', DEFAULTS['variation_min']), 0.0, 1.0
        ),
        'aliases': str(params.get('aliases') or '').strip(),
        'exclude_values': str(params.get('exclude_values') or '').strip(),
        'cluster_labels': str(params.get('cluster_labels') or '').strip(),
        'basemap_dataset_id': str(params.get('basemap_dataset_id') or '').strip(),
        'watch_project': str(params.get('watch_project') or '').strip(),
        'watch_baseline': str(params.get('watch_baseline') or '').strip(),
        'watch_label': str(params.get('watch_label') or '').strip(),
        'output_shape': str(params.get('output_shape') or DEFAULTS['output_shape']).strip(),
        'export_files': as_bool(params.get('export_files'), DEFAULTS['export_files']),
    }
