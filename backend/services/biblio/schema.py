"""Contracts for the bibliometric (CiteSpace-style) node.

One table, one row per entity. ``连接`` and ``年份序列`` are canonical JSON
text so the rows survive the run store, a CSV export and a resume unchanged;
charts parse them back. The tuple functions here are the single definition of
what a ``biblio`` node emits, shared by the engine, node-schema diagnostics and
the chart builders.

The parameter defaults and option lists are NOT declared here: they are read from
``capabilities_kernel/nodes/biblio/manifest.py``, so one edit reaches the validator,
the served catalogue and the run.
"""

from capabilities_kernel.nodes.biblio.manifest import MANIFEST
from core.refs import as_bool

from i18n import t


def _options(name: str) -> tuple[str, ...]:
    """The option list a parameter declares. The manifest is its one declaration."""
    spec = MANIFEST.param(name)
    return tuple(spec.enum) if spec is not None else ()


ENTITY_TYPES = _options('entity_type')

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

OUTPUT_SHAPES = _options('output_shape')

#: Shapes whose rows are NOT one row per entity: ``variation`` repeats a node once per slice pair,
#: ``clusters``/``bursts`` are per-cluster or per-burst rows. A cross-run monitor captures an
#: entity table, so filing one of these would store a graph whose node count is a multiple of the
#: real one and make every later comparison a comparison of two different questions.
WATCH_UNSHAPED = ('variation', 'clusters', 'bursts')

SELECTION_MODES = _options('selection')
LINK_MEASURES = _options('link_measure')
COUNTING_MODES = _options('counting')
PRUNING_MODES = _options('pruning')
PRUNING_SCOPES = _options('pruning_scope')
PATHFINDER_R = _options('pathfinder_r')
LABEL_METHODS = _options('label_method')
LABEL_SOURCES = _options('label_source')

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

#: The seed values a new node starts from, declared once in the manifest (``params`` section).
#: ``nodes/defaults.py`` merges the same answer from the kernel, so the canvas, the panel and the
#: executor cannot seed three different shapes.
DEFAULTS = MANIFEST.defaults()

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


def _problem(message_key: str, **context) -> dict:
    """One refusal as data: the console and the canvas badge word it from ``i18n``."""
    return {'code': message_key, 'message_key': message_key, 'context': context}


def _sentence(nid: str, problem: dict) -> str:
    """A problem's sentence for a direct caller (``normalize_params`` raises the first one)."""
    return t(problem['message_key'], nid=nid or '(biblio)', **problem['context'])


def _range_problem(param: str, value, low, high, whole: bool = True) -> dict | None:
    """The parameter's range problem, or None. ``whole`` reads the value the way the run does."""
    try:
        number = int(float(value)) if whole else float(value)
    except (TypeError, ValueError):
        return _problem('biblio.bad_option', param=param, value=value, allowed=f'{low}..{high}')
    if number < low or number > high:
        return _problem('biblio.bad_option', param=param, value=value, allowed=f'{low}..{high}')
    return None


def _whole(nid: str, param: str, value, low: int, high: int) -> int:
    problem = _range_problem(param, value, low, high)
    if problem:
        raise ValueError(_sentence(nid, problem))
    return int(float(value))


def _optional_whole(nid: str, param: str, value) -> int | None:
    text = str(value if value is not None else '').strip()
    return None if not text else _whole(nid, param, text, 0, 1000000000)


def _number(nid: str, param: str, value, low: float, high: float) -> float:
    problem = _range_problem(param, value, low, high, whole=False)
    if problem:
        raise ValueError(_sentence(nid, problem))
    return float(value)


#: Every numeric parameter and its inclusive range, in the order problems are reported.
#: ``whole`` marks the ones the run normalises with ``int(float(...))``; ``optional`` ones are
#: skipped while blank (a blank box is "not set", not a bad number).
RANGE_CHECKS = (
    ('slice_years', True, 1, 50, False),
    ('look_back_years', True, 0, 50, False),
    ('threshold_c', True, 0, 100000, False),
    ('threshold_cc', True, 0, 100000, False),
    ('threshold_ccv', False, 0.0, 1.0, False),
    ('min_tc', True, 0, 1000000000, True),
    ('min_usage', True, 0, 1000000000, True),
    ('top_n', True, 1, 5000, False),
    ('top_pct', True, 1, 100, False),
    ('g_index', True, 1, 1000, False),
    ('min_count', True, 1, 100000, False),
    ('max_links_per_node', True, 1, 200, False),
    ('citation_expansion', True, 0, 2, False),
    ('lrf', False, 1.0, 100.0, False),
    ('pathfinder_lmax', True, 0, 50, False),
    ('pathfinder_dmax', False, 0.05, 1.0, False),
    ('top_terms', True, 1, 20, False),
    ('burst_gamma', False, 0.01, 100.0, False),
    ('burst_min_duration', True, 1, 50, False),
    ('burst_weight', False, 1.0001, 100.0, False),
    ('burst_top', True, 1, 500, False),
    ('variation_min', False, 0.0, 1.0, False),
    ('cluster_count', True, 2, 50, True),
)

#: The select-shaped parameters, in the order problems are reported.
OPTION_CHECKS = (
    ('selection', SELECTION_MODES),
    ('link_measure', LINK_MEASURES),
    ('counting', COUNTING_MODES),
    ('pruning', PRUNING_MODES),
    ('pruning_scope', PRUNING_SCOPES),
    ('pathfinder_r', PATHFINDER_R),
    ('label_method', LABEL_METHODS),
    ('label_source', LABEL_SOURCES),
    ('output_shape', OUTPUT_SHAPES),
)


def collect_problems(params: dict) -> list[dict]:
    """Every parameter problem, in order, as ``{code, message_key, context}`` data.

    The manifest validator and the canvas badge read this; :func:`collect_errors` words the same
    list for a direct caller (``normalize_params`` raises the first sentence). One body answers
    validate and run, so a hand-edited workflow cannot be refused by one and run by the other.
    """
    params = params or {}
    problems: list[dict] = []

    def bad(param, value, allowed):
        return _problem('biblio.bad_option', param=param, value=value, allowed=allowed)

    entity = str(params.get('entity_type') or DEFAULTS['entity_type']).strip()
    if entity not in ENTITY_TYPES:
        problems.append(bad('entity_type', entity, ', '.join(ENTITY_TYPES)))

    for param, allowed_options in OPTION_CHECKS:
        value = str(params.get(param) or DEFAULTS[param]).strip()
        if value not in allowed_options:
            problems.append(bad(param, value, ', '.join(allowed_options)))
        elif param == 'counting' and value == 'fractional' and entity in COUPLING_TYPES:
            # In a coupling network the two citing documents ARE the endpoints, so there is no
            # third document whose credit could be split: fractional counting has nothing to divide.
            problems.append(_problem('biblio.counting_no_coupling', entity=entity))

    for param, whole, low, high, optional in RANGE_CHECKS:
        value = params.get(param, DEFAULTS[param])
        if optional and value in (None, ''):
            continue
        problem = _range_problem(param, value, low, high, whole=whole)
        if problem:
            problems.append(problem)

    start, end, year_problem = _year_values(params)
    if year_problem:
        problems.append(year_problem)
        start = end = None
    if start is not None and end is not None and start > end:
        problems.append(_problem('biblio.time_range', start=start, end=end))

    shape = str(params.get('output_shape') or DEFAULTS['output_shape']).strip()
    burst_default = False if entity in COUPLING_TYPES else DEFAULTS['burst']
    if entity in COUPLING_TYPES and as_bool(params.get('burst'), burst_default):
        problems.append(_problem('biblio.coupling_no_burst'))
    if shape == 'clusters' and not as_bool(params.get('cluster'), DEFAULTS['cluster']):
        problems.append(_problem('biblio.shape_needs_cluster'))
    if shape == 'bursts' and not as_bool(params.get('burst'), burst_default):
        problems.append(_problem('biblio.shape_needs_burst'))
    if shape == 'variation' and not as_bool(params.get('variation'), DEFAULTS['variation']):
        # Asking for the variation table without the switch is a stale box, not a preference:
        # say which one is missing instead of emitting an empty table the charts then refuse.
        problems.append(_problem('biblio.shape_needs_variation'))
    if shape == 'dual_map' and not str(params.get('basemap_dataset_id') or '').strip():
        problems.append(_problem('biblio.dual_map_needs_basemap'))
    if str(params.get('cluster_labels') or '').strip() and not as_bool(params.get('cluster'), DEFAULTS['cluster']):
        # Naming clusters that will not exist is a stale box, not a preference: say which switch
        # is missing instead of quietly ignoring the labels the user typed.
        problems.append(_problem('biblio.cluster_labels_need_cluster'))
    watch_project = str(params.get('watch_project') or '').strip()
    if not watch_project and (
        str(params.get('watch_baseline') or '').strip() or str(params.get('watch_label') or '').strip()
    ):
        # A baseline and a capture name belong to a project; filing them with none would let the
        # node look configured while it watches nothing at all.
        problems.append(_problem('biblio.watch_needs_project'))
    if watch_project and shape in WATCH_UNSHAPED:
        problems.append(_problem('biblio.watch_needs_entity_table', shape=shape))
    return problems


def collect_errors(params: dict, nid: str = '') -> list[str]:
    """The problems worded for a direct caller; the validator reads :func:`collect_problems`."""
    return [_sentence(nid, problem) for problem in collect_problems(params)]


def _year_values(params: dict) -> tuple[int | None, int | None, dict | None]:
    """(start, end, first problem). A blank year is "not set"; a bad one is named once."""

    def year(name):
        raw = params.get(name, DEFAULTS[name])
        text = str(raw if raw is not None else '').strip()
        if not text:
            return None, None
        try:
            return int(text), None
        except ValueError:
            return None, _problem('biblio.bad_option', param=name, value=raw, allowed='a four-digit year or blank')

    start, start_problem = year('time_start')
    end, end_problem = year('time_end')
    return start, end, start_problem or end_problem


def _year_pair(params: dict, nid: str) -> tuple[int | None, int | None]:
    start, end, problem = _year_values(params)
    if problem:
        raise ValueError(_sentence(nid, problem))
    return start, end


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
