"""Analysis node: a deterministic cleaning pipeline, plus the one step that needs a model.

A two-table step (``join_tables`` / ``anti_join``) reads the table of the node's *second*
incoming connection — the old design asked for an opaque dataset id that was shown nowhere, so a
join silently joined nothing. Because the roles are decided by connection ORDER, the console
prints which parent fills which role on every run (``wf.anti_join_roles*``): "the first wire is
the table being filtered, the second is the basis" is a fact the user must be able to check
against the canvas without opening the panel.

A step in ``LLM_OPS`` (主题概括 / 聚类命名 / 簇综述) is the one case this node is not
deterministic, so it borrows the process node's client builder rather than inventing a second
reading of the LLM settings: refusing for want of a model happens HERE, before any call is paid
for.
"""

import pandas as pd
from core.refs import as_bool
from runtime.state import add_log, execution_state
from runtime.stores import get_run_store

from i18n import t
from nodes.context import NodeCall, node_params, split_panel_columns
from nodes.labels import node_label, parent_label
from services.analysis.llm import build_llm_run_ctx
from services.analysis.matching import STEP_TWO_TABLE
from services.analysis.params import (
    STEP_ADD_MAYBE,
    STEP_ADD_ONE,
    STEP_DYNAMIC_REPLACE,
    STEP_PASSTHROUGH,
    STEP_REPLACE,
    STEP_UNKNOWN,
    normalize_analysis_params,
    replaced_columns,
)
from services.analysis.pipeline import LLM_OPS, STEP_PARAMS, DataAnalysisService, UnknownOperationError

NODE_TYPE = 'analysis'


# ─── Column contract ─── the op tables are this node's own; the lineage view asks rather than
# keeping a second copy. ``None`` from any of these means "unknown", never "empty".


def _normalized_kwargs(op: str, params: dict) -> dict:
    """The executor's own kwargs for one panel's flat params, or the params themselves.

    A canvas stores each field FLAT beside ``operation`` under the *panel's* name
    (``phase_new_col``, ``label_summary_col``); the executor reads a *canonical* name
    (``new_col``, ``summary_col``). ``services.analysis.params`` is the only authority on that
    mapping, so it is asked here rather than duplicated — the old ``[{'op': op}]`` threw
    every sibling away and the model computed the DEFAULT column name for a node the user
    had given a new one, hiding the very column downstream steps read.
    """
    try:
        normalized = normalize_analysis_params(op, params)
    except Exception:  # a preview must degrade to "read what is there", never crash
        normalized = {}
    return {**params, **normalized} if isinstance(normalized, dict) else dict(params)


def _step_kwargs(step: dict) -> dict:
    """One entry of a ``steps`` list, with its column kwargs resolved to canonical names.

    A step already carrying a ``params`` dict is an executor-shaped step (``/api/analysis``
    hands these) and its names are canonical; a flat step is panel-shaped and goes through
    the same translator.
    """
    nested = step.get('params')
    if isinstance(nested, dict):
        return {**step, **nested}
    op = str(step.get('op') or step.get('operation') or '')
    if not op:
        return dict(step)
    return _normalized_kwargs(op, step)


def _steps_of(params: dict) -> list[dict]:
    """The (op, canonical kwargs) pairs one analysis node will run, in order.

    Two shapes reach this function: the canvas's single flat ``operation`` with its panel
    fields beside it, and an API caller's ``steps`` list. Each is normalised through the
    executor's own translator so the column model can key on canonical names.
    """
    steps = params.get('steps')
    if isinstance(steps, list):
        return [_step_kwargs(s) for s in steps if isinstance(s, dict)]
    op = params.get('operation')
    if not op:
        return []
    return [{'op': op, **_normalized_kwargs(str(op), params)}]


def _step_with_params(step: dict) -> dict:
    """Give a flat (panel-shaped) step the nested ``params`` ``run_pipeline`` reads.

    ``_steps_of``/``_step_kwargs`` exists for the column model; the EXECUTION path used to
    pass the raw list, so a step like ``{'op': 'drop_null', 'columns': '标题'}`` reached
    ``run_pipeline`` with ``params == {}``. It then ran the operation's defaults: ``drop_null``
    deleted rows from a column the user never named, ``fill_null`` filled nothing, and
    ``select_columns`` raised a bare TypeError. A step that already carries ``params`` is an
    executor-shaped step and is left untouched.
    """
    if isinstance(step.get('params'), dict):
        return step
    op = str(step.get('op') or step.get('operation') or '')
    if not op:
        return step
    try:
        normalized = normalize_analysis_params(op, step)
    except Exception:
        # An unknown op still has to reach run_pipeline's own named refusal; an empty params
        # dict lets it raise `UnknownOperationError` instead of a translation error here.
        normalized = {}
    return {**step, 'params': normalized if isinstance(normalized, dict) else {}}


def _output_of(params: dict, upstream: list[str] | None) -> list[str] | None:
    """Walk the node's steps and say what columns come out — or None when a step is unmodelled."""
    cols = upstream
    for step in _steps_of(params):
        op = str(step.get('op') or '')
        if op in STEP_UNKNOWN:
            return None
        if op in STEP_DYNAMIC_REPLACE:
            derived = replaced_columns(op, step)
            if derived is None:
                return None
            cols = derived
            continue
        if op in STEP_REPLACE:
            cols = list(STEP_REPLACE[op])
            continue
        if op == 'select_columns':
            chosen = split_panel_columns(step.get('columns'))
            cols = chosen or cols
            continue
        if op in STEP_ADD_ONE:
            if cols is None:
                return None
            param, default = STEP_ADD_ONE[op]
            new_col = str(step.get(param) or default or '').strip()
            if not new_col and op == 'bin_column':
                # The executor writes f"{column}_bin" when the name box is blank, so the
                # lineage has to say the same thing rather than drop the column entirely.
                column = str(step.get('column') or '').strip()
                new_col = f'{column}_bin' if column else ''
            if new_col:
                cols = cols + [new_col]
            # `bin_time` is the one step that may add a SECOND column; every other single-add
            # step ends here, so the extra read below is skipped rather than falling through
            # (falling through would reach `return None` and call a known op unknown).
            if op not in STEP_ADD_MAYBE:
                continue
        if op in STEP_ADD_MAYBE:
            if cols is None:
                return None
            for param, default in STEP_ADD_MAYBE[op]:
                added = str(step.get(param) or default or '').strip()
                if added and added not in cols:
                    cols = cols + [added]
            continue
        if op in STEP_PASSTHROUGH:
            continue
        return None  # an op the model has not enumerated → unknown, never a guess
    return cols


def emit_columns(node: dict, merged: list[str] | None) -> list[str] | None:
    return _output_of(node_params(node), merged)


def read_columns(node: dict) -> list[str]:
    found: list[str] = []
    for step in _steps_of(node_params(node)):
        op = str(step.get('op') or '')
        spec = STEP_PARAMS.get(op, {})
        for key in ('one', 'some'):
            for pname in spec.get(key, ()):
                found += split_panel_columns(step.get(pname))
        if op == 'anti_join':
            # Both sides are read from the merged fan-in, so the lineage view can flag a
            # name neither table supplies; ``STEP_PARAMS`` cannot hold them because
            # ``one``/``some`` are checked against the LEFT table only.
            found += split_panel_columns(step.get('left_on'))
            found += split_panel_columns(step.get('right_on'))
    return [c for c in found if c]


def _two_table_params(step: dict) -> dict:
    """A flat panel-shaped step's fields, or the nested ``params`` a pipeline step carries."""
    if isinstance(step.get('params'), dict):
        return dict(step.get('params'))
    # A flat step keeps its fields BESIDE ``op``; those are the kwargs.
    return {key: value for key, value in step.items() if key != 'op'}


def execute_analysis_node(
    node: dict,
    current_input: list,
    upstream: list = None,
    ctx: dict = None,
    label_of=None,
):
    """Analysis node: runs a deterministic data-cleaning pipeline (null
    handling, de-duplication, filtering, renaming, ...) via
    DataAnalysisService. Supports either a single configured operation
    (as built by the Settings panel) or a full multi-step pipeline stored
    under params['steps'] for advanced use / API callers.

    A step in ``LLM_OPS`` (the 主题概括 labeler) is the one case this node is not
    deterministic, so it borrows the process node's client builder rather than
    inventing a second reading of the LLM settings: the per-node model override,
    the daemon address pinned at run start and the run's Stop event all come from
    there. Refusing for want of a model happens HERE, before any call is paid for.
    """
    params = node.get('params', {})
    if not current_input:
        return []

    df = pd.DataFrame(current_input)

    steps = params.get('steps')
    if isinstance(steps, dict):
        # ``pd.DataFrame`` above turns a dict-shaped ``steps`` into rows and ``.get`` then dies
        # with a TypeError, which the executor reports as an unexplained node failure. The
        # normalizer's door refuses this shape; this door has to as well.
        raise UnknownOperationError(t('wf.analysis_steps_shape'))
    if not steps:
        op = node.get('operation', params.get('operation', ''))
        steps = [{'op': op, 'params': normalize_analysis_params(op, params)}] if op else []

    # upstream[0] is the left table (already current_input); the SECOND connection is the
    # other table of a two-table step (join / anti-join). ``pairs`` keeps every id so the
    # console can say WHICH parent filled each role.
    pairs = [(str(pid), res) for pid, res in (upstream or ())]
    nid = str(node.get('id') or '')
    label = node_label(node, nid)

    steps = list(steps)
    # The execution path needs the canonical `params` dict, not only the lineage view. Do it
    # once, before the two-table loop, so that loop still sees the flat fields it reads.
    steps = [_step_with_params(step) for step in steps]
    for index, step in enumerate(steps):
        op = str(step.get('op') or '')
        if op not in STEP_TWO_TABLE:
            continue
        if len(pairs) < 2:
            # The step is handed the second table by this executor; with one wire there is
            # nothing to join with. Unlike a filter blank the user can fix in a box, this is
            # a missing CONNECTION, so it is refused before the pipeline starts.
            raise UnknownOperationError(t('wf.two_table_no_right', nid=label))
        right_result = pairs[1][1]
        if not isinstance(right_result, list):
            raise UnknownOperationError(
                t(
                    'wf.two_table_not_table',
                    nid=label,
                    up=parent_label(label_of, pairs[1][0]),
                )
            )
        if op == 'join_tables' and not right_result:
            raise UnknownOperationError(t('wf.join_no_right_table'))
        two_table = _two_table_params(step)
        steps[index] = {**step, 'params': {**two_table, 'other_df': pd.DataFrame(right_result)}}
        if op == 'anti_join' and as_bool(two_table.get('swap_tables'), False):
            # Printed on EVERY run, not only the swapped one: a console line that appears
            # only in one state makes the reader compare two runs to learn which table was
            # kept. ``swap`` names the two roles as the step will actually use them.
            add_log(
                t(
                    'wf.anti_join_roles_swapped',
                    nid=label,
                    keep=parent_label(label_of, pairs[1][0]),
                    basis=parent_label(label_of, pairs[0][0]),
                )
            )
        elif op == 'anti_join':
            add_log(
                t(
                    'wf.anti_join_roles',
                    nid=label,
                    keep=parent_label(label_of, pairs[0][0]),
                    basis=parent_label(label_of, pairs[1][0]),
                )
            )

    # An unknown/malformed step RAISES straight through: the executor turns it into
    # this node's failure and prints the reason with the node's label — one line,
    # attributed. Swallowing it into an empty list used to make a mistyped filter value
    # look like "the data was already clean": the run went green, the export wrote a
    # header row and nothing else, and downstream nodes reported "no upstream data" for
    # a table that was really refused. Same contract as `/api/analysis/clean`, which
    # answers these with a 400 and this exact message.
    # A labelling step is the one thing in this node that cannot answer without the model, so
    # the refusal is issued BEFORE any call is paid for. The client comes from the process
    # node's own builder, because that is where the per-node model override, the daemon address
    # pinned at run start and the run's Stop event are read: a second reader of those settings
    # here would be a second opinion about which model this run is using.
    llm = None
    cancel = None
    labelling = [str(step.get('op')) for step in steps if str(step.get('op')) in LLM_OPS]
    if labelling:
        cfg = execution_state.get('llm') or {}
        node_model = str((node.get('params') or {}).get('model') or '').strip()
        if not str(cfg.get('model') or '').strip() and not node_model:
            raise UnknownOperationError(t('wf.analysis_llm_no_model'))
        # Named by the step that needs it, not by whichever step was first: the context reads the
        # operation to size the answer, and a log line that says ``topic_label`` for a cluster
        # review is a second, wrong opinion about what this node is doing.
        run_ctx = build_llm_run_ctx(node, labelling[0], ctx)
        llm = run_ctx['client']
        cancel = run_ctx.get('cancel_event')

    # The store is the run ledger's own llm_cache: a summary the model already answered for this
    # exact prompt is replayed instead of paid for again. It is passed beside ``llm`` rather than
    # through params for the same reason the client is — the run record echoes params.
    cleaned, report = DataAnalysisService.run_pipeline(df, steps, llm=llm, cancel=cancel, store=get_run_store())

    for step in report:
        line = t('wf.analysis_step', op=step['op'], before=step['rows_before'], after=step['rows_after'])
        # A step that dropped nothing deserves saying so; printing "(-0)" looked
        # like a truncated number rather than an outcome.
        line += (
            t('wf.analysis_step_removed', removed=step['rows_removed'])
            if step['rows_removed']
            else t('wf.analysis_step_nochange')
        )
        add_log(line)
    return cleaned.to_dict('records')


def run(node: dict, call: NodeCall):
    return execute_analysis_node(
        node,
        call.current_input,
        upstream=call.upstream,
        ctx=call.ctx,
        label_of=call.label_of,
    )
