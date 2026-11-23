"""What a step is allowed to say: the select-shaped vocabularies, the per-op parameter contract,
and the coercion/refusal every entry into ``run_pipeline`` passes through.

Moved out of ``pipeline.py`` (Stage 9) so an operation module can read the contract without
importing the service that dispatches it. ``pipeline`` imports these names back, so
``from services.analysis.pipeline import STEP_PARAMS`` keeps working.
"""

import pandas as pd
from capabilities_kernel import registry
from capabilities_kernel.operator import NO_DEFAULT, enum_of
from core.refs import split_names

from i18n import t
from services.analysis.kernels import UnknownOperationError, _blank

#: The join styles ``join_tables`` accepts, declared by that operator's manifest.
JOIN_HOW = enum_of('join_tables', 'how')

#: Where a topic's 特征词 come from. ``tfidf`` is what the study says it used (TF-IDF over the
#: words LDA put in a document), and it inherits jieba's candidate rule of two characters or
#: more — so a single-character word like 捞, which is in the paper's own table, can only come
#: out of ``lda`` (the topic-word distribution reads the vectoriser's vocabulary directly).
#: That difference is why the switch is visible on the panel instead of being one behaviour.
WORD_SOURCES = enum_of('topic_by_stage', 'word_source')

#: What :meth:`DataAnalysisService.topic_label` does when the model refuses one topic.
#: ``abort`` is the default: a table whose 主题概括 column is quietly half empty is the paper's
#: table with holes in it, and the export cannot tell an empty cell from a topic the model
#: was never asked about. ``blank`` is the opt-in for a long run the user does not want to
#: restart, and it logs one line per topic it gave up on.
ON_FAIL = enum_of('topic_label', 'on_fail')

#: Steps that need the run's LLM client, and so are handed it by :func:`run_pipeline`.
#: Kept out of the step's own ``params`` because the pipeline report — which the console
#: prints and the run record keeps — echoes every parameter it is given.
LLM_OPS = frozenset(manifest.identity.id for manifest in registry.manifests('operator') if manifest.needs_llm)

#: What :meth:`DataAnalysisService.forecast` extrapolates with, declared by its manifest. Both are
#: computed in this project: statsmodels is not a dependency, and a two-parameter smoothing written
#: out is short enough to read next to the numbers it produced.
FORECAST_METHODS = enum_of('forecast', 'method')

#: The stage part of a topic id: 表 1 numbers its topics TopicⅠ-1 … TopicⅤ-4, and the numeral
#: is the stage's POSITION in the lifecycle — which is why the order has to be declared rather
#: than read off the code points of Chinese names ('二次爆发期' sorts before '发酵期').
STAGE_NUMERALS = ('Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ', 'Ⅺ', 'Ⅻ')

#: Sentinel for a select with no fallback: leaving it blank is a missing choice, and guessing one is
#: the bug this contract exists to stop. ``filter_rows`` uses it — defaulting a blank comparison to
#: ``eq`` would answer a mistyped filter with "the data was already clean", which is the sentence
#: this repo refuses to print. It is declared once, in ``capabilities_kernel.operator``.
#
#: What each step needs from the table it is handed, checked before it runs.
#:
#: ``one`` names exactly one column, so a blank or an absent name is a mistake the user can fix — it
#: is NOT read as "every column". ``some`` names a subset where an empty list legitimately means
#: "every column" (the panel's 留空=全部 behaviour, which several saved pipelines rely on). ``enums``
#: maps each select to ``(its fallback, the names it accepts)``, the fallback being
#: :data:`NO_DEFAULT` when a blank has to be refused. ``nonblank`` is a parameter that names a *new*
#: column or an expression: writing it blank used to "succeed" by adding a header the CSV export
#: shows as an empty cell.
#:
#: Projected from the operator manifests (``capabilities_kernel/operators/<op>/manifest.py``): one
#: declaration per step, so a new operator or a changed column contract never edits this file.
#:
#: Applied in :meth:`DataAnalysisService.run_pipeline`, which both the analysis node and
#: ``/api/analysis/run`` go through, so one table guards every entry point — and after
#: :func:`normalize_step_params`, which is what makes each check a question about the value the
#: operation really receives.
STEP_PARAMS: dict = {manifest.identity.id: manifest.contract() for manifest in registry.manifests('operator')}


#: The timestamp shape THIS PROJECT'S OWN weibo crawler writes is handled by
#: ``kernels._to_datetime`` (moved with the other shared guards).


def normalize_step_params(op: str, params: dict) -> dict:
    """Coerce one step's parameters into the shape and spelling the operation reads.

    Two entry paths used to disagree about this and nothing told the caller. The node
    executor sends the *flat* panel fields through ``_normalize_analysis_params``, which
    splits ``columns: '名称, 城市'`` into two stripped names; ``/api/analysis/run`` and a
    workflow file's own ``steps`` handed the same params to ``run_pipeline`` as they were,
    so a string was iterated as its **characters** — seven "columns" that match nothing, a
    step that quietly did nothing, and a green node. Normalizing here, at the one place
    both doors pass through, makes them mean the same thing.

    Padding comes off the names and selects, matching what the crawl matrix does with a
    text field (``Field.value_from`` strips), and a blank select becomes its declared
    fallback: passing ``how=''`` on to pandas is a ``ValueError: invalid how option:``
    for a box the user simply left alone. A *value* is deliberately untouched —
    ``filter_rows(value=' ')`` searches for a space, which is a real answer rather than a
    missing one.
    """
    spec = STEP_PARAMS.get(op)
    if spec is None or not isinstance(params, dict):
        return params or {}
    out = dict(params)
    for key in spec.get('some', ()):
        if key in out:
            out[key] = split_names(out[key])
    for key in (*spec.get('one', ()), *spec.get('nonblank', ())):
        if isinstance(out.get(key), str):
            out[key] = out[key].strip()
    for key, (default, _allowed) in (spec.get('enums') or {}).items():
        if key not in out or default is NO_DEFAULT or isinstance(out[key], bool):
            continue
        out[key] = default if _blank(out[key]) else str(out[key]).strip()
    return out


def validate_step(df: pd.DataFrame, op: str, params: dict) -> None:
    """Refuse a step this table cannot carry out, naming the reason.

    The silent alternatives were each worse than an error: a mistyped entry in a column
    *list* was dropped, and when every entry missed, ``drop_null`` read the emptied subset
    as "all columns" and deleted rows the user never aimed at, while
    ``filter_rows``/``sort_rows``/``convert_type`` on a column that does not exist settled
    the node **done** and passed the untouched table downstream — so an export shipped
    unfiltered data with a green check on it.

    Call it with :func:`normalize_step_params` output: it compares the value the operation
    will receive, so a name that passes here is a name that resolves there.
    """
    spec = STEP_PARAMS.get(op)
    if spec is None:
        # An op with no entry here is a gap in this table, not a licence to skip the
        # check; `test_the_gate_knows_every_registered_step` fails the suite first.
        return
    params = params or {}
    columns = [str(col) for col in df.columns]
    for key in spec.get('one', ()):
        name = params.get(key)
        if _blank(name):
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
        if str(name) not in columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op=op, col=str(name)))
    for key in spec.get('some', ()):
        wanted = params.get(key) or []
        missing = [str(name) for name in wanted if str(name) not in columns]
        if wanted and missing:
            raise UnknownOperationError(t('analysis.step_cols_missing', op=op, cols=', '.join(missing)))
    for key, (_default, allowed) in (spec.get('enums') or {}).items():
        if key not in params or params[key] is None:
            continue  # absent: the operation's own signature default answers
        value = str(params[key])
        if not value.strip():
            # A blank here survived normalize_step_params, so this select has no
            # fallback to fall back on and the choice is simply missing.
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
        if value not in allowed:
            raise UnknownOperationError(
                t('analysis.bad_option', op=op, param=key, value=value, allowed=', '.join(allowed))
            )
    for key in spec.get('nonblank', ()):
        if _blank(params.get(key)):
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
    if spec.get('mapping'):
        _validate_renames(df, op, params.get('mapping'))


def _validate_renames(df: pd.DataFrame, op: str, mapping) -> None:
    """A rename that would erase a column's name is refused, not applied.

    ``{'标题': ''}`` used to rename the column to the empty string: every later step
    that named 标题 then found nothing, and the exported CSV carried a header cell
    with no word in it. A blank *source* name is the same mistake on the other side,
    and an empty mapping "succeeded" while changing nothing.
    """
    if not isinstance(mapping, dict) or not mapping:
        raise UnknownOperationError(t('analysis.need_param', op=op, param='rename_from'))
    columns = [str(col) for col in df.columns]
    missing, blank_target = [], []
    for source, target in mapping.items():
        name = str(source)
        if not name.strip() or name not in columns:
            missing.append(name.strip() or name)
        elif _blank(target):
            blank_target.append(name)
    if missing:
        raise UnknownOperationError(t('analysis.step_cols_missing', op=op, cols=', '.join(missing)))
    if blank_target:
        raise UnknownOperationError(t('analysis.rename_blank', op=op, cols=', '.join(blank_target)))
    # A target that is ALREADY a column (and is not itself being renamed away) produces two
    # columns with one name. ``df.rename`` allows that; the node boundary (``to_dict('records')``)
    # then keeps only one of them with a pandas warning, so the reader got the OLD values under
    # the requested name and the renamed column was gone. A source that is also a target is the
    # legal swap/chained case and stays allowed.
    taken = [
        f'{source} → {target}'
        for source, target in mapping.items()
        if not _blank(target)
        and str(target) in columns
        and str(target) != str(source)
        and str(target) not in map(str, mapping)
    ]
    if taken:
        raise UnknownOperationError(t('analysis.rename_target_exists', op=op, cols='、'.join(taken)))
