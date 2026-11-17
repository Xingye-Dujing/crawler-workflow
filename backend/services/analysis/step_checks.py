"""Design-time parameter checks for one analysis step — the truth behind a node's badge.

``contracts.validate_step`` refuses a step when a table is finally handed to it. That is one
run too late for a box the user simply left empty: the node fails after the crawl above it has
been paid for. This module asks the SAME question without a table, so the canvas can flag the
node while it is being drawn.

It reads the one ``STEP_PARAMS`` contract rather than keeping a second copy, and it is fed
the *canonical* kwargs ``services.analysis.params`` resolved the panel's boxes into — the same
values ``validate_step`` compares, so a name that passes here is a name that resolves there.

The two-table steps are the exception the table cannot express: their keys name columns of two
DIFFERENT tables, so ``one`` (checked against the left table) would refuse the right-hand name
and ``some`` would accept a composite key on only one side. They are declared here, and
``join_tables`` only needs them when the join is not ``cross`` — the one join with no key.

The answer is data, never prose: ``code`` names the problem and ``param`` the box, while
``field`` is the label key the panel already shows, so wording stays the browser catalogue's
job. Whether a named column EXISTS is a question about a table and stays with the lineage view
(``referenced_columns``), which hands the columns to ``validate_step`` at run time.
"""

from services.analysis.contracts import NO_DEFAULT, STEP_PARAMS
from services.analysis.kernels import _blank

#: The words the analysis panel puts on each canonical parameter, as label keys the browser
#: catalogue declares. A badge that printed ``words_col`` would name a box the user has never
#: seen; where the same key is drawn from differently-labelled boxes the op-specific table
#: below answers first.
PARAM_LABELS = {
    'column': 'settings.column',
    'columns': 'settings.columns',
    'group_col': 'settings.groupCol',
    'agg_col': 'settings.aggCol',
    'stage_col': 'settings.stageColumn',
    'words_col': 'settings.labelWordsColumn',
    'summary_col': 'settings.labelSummaryColumn',
    'text_col': 'settings.clusterTextColumn',
    'name_col': 'settings.reviewNameColumn',
    'value_col': 'settings.compareValueColumn',
    'index_col': 'settings.alertIndexColumn',
    'author_col': 'settings.replyAuthorColumn',
    'floor_col': 'settings.replyFloorColumn',
    'parent_floor_col': 'settings.replyParentColumn',
    'platform_col': 'settings.comparePlatformColumn',
    'size_col': 'settings.timelineSizeColumn',
    'topic_col': 'settings.timelineTopicColumn',
    'weights_col': 'settings.flowWeightsColumn',
    'topics': 'settings.stageTopicCounts',
    'new_col': 'settings.newCol',
    'expr': 'settings.expr',
    'edges': 'settings.phaseEdges',
    'labels': 'settings.phaseLabels',
    'left_on': 'settings.leftOn',
    'right_on': 'settings.rightOn',
    'rename_from': 'settings.renameFrom',
    'rename_to': 'settings.renameTo',
}

_OP_PARAM_LABELS = {
    ('drop_duplicates', 'mode'): 'settings.dedupeMode',
    ('anti_join', 'mode'): 'settings.matchMode',
    ('drop_null', 'how'): 'settings.dropHow',
    ('join_tables', 'how'): 'settings.joinHow',
    ('fill_null', 'method'): 'settings.fillMethod',
    ('forecast', 'method'): 'settings.forecastMethod',
    ('filter_rows', 'op'): 'settings.filterOp',
    ('convert_type', 'dtype'): 'settings.dtype',
    ('topic_by_stage', 'word_source'): 'settings.topicWordSource',
    ('topic_label', 'on_fail'): 'settings.labelOnFail',
    ('cluster_label', 'on_fail'): 'settings.clusterOnFail',
    ('cluster_review', 'on_fail'): 'settings.clusterOnFail',
    ('forecast', 'value_col'): 'settings.forecastValueColumn',
    ('topic_timeline', 'stage_col'): 'settings.timelineStageColumn',
    ('topic_timeline', 'words_col'): 'settings.timelineWordsColumn',
    ('topic_timeline', 'topic_col'): 'settings.timelineTopicColumn',
    ('topic_timeline', 'size_col'): 'settings.timelineSizeColumn',
    ('topic_flow', 'stage_col'): 'settings.flowStageColumn',
    ('topic_flow', 'topic_col'): 'settings.flowTopicColumn',
    ('topic_flow', 'words_col'): 'settings.flowWordsColumn',
    ('topic_flow', 'weights_col'): 'settings.flowWeightsColumn',
}

#: The keys a two-table step joins on, per step. Shared by ``join_tables`` and ``anti_join``;
#: ``anti_join``'s two sides may each be a comma-separated COMPOSITE key, which is exactly why
#: neither name can live in ``STEP_PARAMS['one']`` (the left name is not a column of the right
#: table).
TWO_TABLE_KEYS = {
    'join_tables': ('left_on', 'right_on'),
    'anti_join': ('left_on', 'right_on'),
}


def param_label(op: str, param: str) -> str | None:
    """The browser label key for one parameter, or None when no box on the panel names it."""
    return _OP_PARAM_LABELS.get((str(op), str(param))) or PARAM_LABELS.get(str(param))


def _problem(op: str, code: str, param: str, **slots) -> dict:
    problem = {'code': code, 'op': str(op), 'param': str(param)}
    field = param_label(op, param)
    if field:
        problem['field'] = field
    problem.update(slots)
    return problem


def _required_keys(op: str, params: dict) -> tuple[str, ...]:
    """The two-table keys this step needs, once the join's own exception is honoured."""
    keys = TWO_TABLE_KEYS.get(op, ())
    if op == 'join_tables' and str(params.get('how') or '').strip() == 'cross':
        return ()
    return keys


def _rename_problems(op: str, mapping) -> list[dict]:
    """A rename with no source or no target name is a mistake, exactly as the run decides."""
    if not isinstance(mapping, dict) or not mapping:
        return [_problem(op, 'need_param', 'rename_from')]
    blank_target = [str(source) for source, target in mapping.items() if _blank(target)]
    if blank_target:
        return [_problem(op, 'rename_blank', 'rename_to', cols=blank_target)]
    return []


def _shape_problems(op: str, params: dict) -> list[dict]:
    """Requirements a step enforces itself because they are about SHAPE, not a column name.

    ``bin_time`` cuts a timestamp at named boundaries: the edge list is required, and its N
    edges describe exactly N-1 phases, so the name list has to hold that many. Neither box is
    a column of the table, so ``STEP_PARAMS`` cannot express them — and leaving both to the
    run would refuse the node only after the crawl above it was paid for.
    """
    if op != 'bin_time':
        return []
    edges = [edge for edge in (params.get('edges') or []) if not _blank(edge)]
    if not edges:
        return [_problem(op, 'need_param', 'edges')]
    labels = [label for label in (params.get('labels') or []) if not _blank(label)]
    if len(labels) != len(edges) - 1:
        return [_problem(op, 'labels_mismatch', 'labels', edges=len(edges), expected=len(edges) - 1, given=len(labels))]
    return []


def param_problems(op: str, params: dict) -> list[dict]:
    """Every parameter this step cannot run without, as data (no wording).

    Mirrors the refusals in ``validate_step``: a blank required name (``need_param``), a
    select whose value is outside its declared list (``bad_option``), and a rename with no
    new name (``rename_blank``). Columns are not checked here — that needs a table.
    """
    op = str(op)
    spec = STEP_PARAMS.get(op)
    if spec is None:
        return []
    params = params if isinstance(params, dict) else {}
    found: list[dict] = []
    for key in spec.get('one', ()):
        if _blank(params.get(key)):
            found.append(_problem(op, 'need_param', key))
    for key, (default, allowed) in (spec.get('enums') or {}).items():
        if key not in params or params[key] is None:
            continue
        value = str(params[key])
        if not value.strip():
            # A blank survived ``normalize_step_params``, so this select has no fallback.
            if default is NO_DEFAULT:
                found.append(_problem(op, 'need_param', key))
            continue
        if value not in allowed:
            found.append(_problem(op, 'bad_option', key, value=value, allowed=list(allowed)))
    for key in spec.get('nonblank', ()):
        if _blank(params.get(key)):
            found.append(_problem(op, 'need_param', key))
    for key in _required_keys(op, params):
        if _blank(params.get(key)):
            found.append(_problem(op, 'need_param', key))
    if spec.get('mapping'):
        found.extend(_rename_problems(op, params.get('mapping')))
    found.extend(_shape_problems(op, params))
    return found
