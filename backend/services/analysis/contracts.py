"""What a step is allowed to say: the select-shaped vocabularies, the per-op parameter contract,
and the coercion/refusal every entry into ``run_pipeline`` passes through.

Moved out of ``pipeline.py`` (Stage 9) so an operation module can read the contract without
importing the service that dispatches it. ``pipeline`` imports these names back, so
``from services.analysis.pipeline import STEP_PARAMS`` keeps working.
"""

import pandas as pd
from core.refs import split_names

from i18n import t
from services.analysis.kernels import (
    CONVERT_TYPES,
    DEDUPE_MODES,
    DROP_HOW,
    FILL_METHODS,
    FILTER_OPS,
    UnknownOperationError,
    _blank,
)

JOIN_HOW = ('left', 'right', 'inner', 'outer', 'cross')

#: Where a topic's 特征词 come from. ``tfidf`` is what the study says it used (TF-IDF over the
#: words LDA put in a document), and it inherits jieba's candidate rule of two characters or
#: more — so a single-character word like 捞, which is in the paper's own table, can only come
#: out of ``lda`` (the topic-word distribution reads the vectoriser's vocabulary directly).
#: That difference is why the switch is visible on the panel instead of being one behaviour.
WORD_SOURCES = ('tfidf', 'lda')

#: What :meth:`DataAnalysisService.topic_label` does when the model refuses one topic.
#: ``abort`` is the default: a table whose 主题概括 column is quietly half empty is the paper's
#: table with holes in it, and the export cannot tell an empty cell from a topic the model
#: was never asked about. ``blank`` is the opt-in for a long run the user does not want to
#: restart, and it logs one line per topic it gave up on.
ON_FAIL = ('abort', 'blank', 'fallback')

#: Steps that need the run's LLM client, and so are handed it by :func:`run_pipeline`.
#: Kept out of the step's own ``params`` because the pipeline report — which the console
#: prints and the run record keeps — echoes every parameter it is given.
LLM_OPS = frozenset({'topic_label', 'cluster_label', 'cluster_review'})

#: What :meth:`DataAnalysisService.forecast` extrapolates with. Both are computed in this
#: module: statsmodels is not a dependency of this project, and a two-parameter smoothing
#: written out is short enough to read next to the numbers it produced.
FORECAST_METHODS = ('moving_average', 'holt', 'seasonal_naive', 'holt_winters')

#: The stage part of a topic id: 表 1 numbers its topics TopicⅠ-1 … TopicⅤ-4, and the numeral
#: is the stage's POSITION in the lifecycle — which is why the order has to be declared rather
#: than read off the code points of Chinese names ('二次爆发期' sorts before '发酵期').
STAGE_NUMERALS = ('Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ', 'Ⅺ', 'Ⅻ')

#: Sentinel for a select with no fallback: leaving it blank is a missing choice, and
#: guessing one is the bug this table exists to stop. ``filter_rows`` uses it — defaulting
#: a blank comparison to ``eq`` would answer a mistyped filter with "the data was already
#: clean", which is the sentence this repo refuses to print.
NO_DEFAULT = object()

#: What each step needs from the table it is handed, checked before it runs.
#:
#: ``one`` names exactly one column, so a blank or an absent name is a mistake the user
#: can fix — it is NOT read as "every column". ``some`` names a subset where an empty
#: list legitimately means "every column" (the panel's 留空=全部 behaviour, which several
#: saved pipelines rely on). ``enums`` maps each select to ``(its fallback, the names it
#: accepts)``, the fallback being :data:`NO_DEFAULT` when a blank has to be refused.
#: ``nonblank`` is a parameter that names a *new* column or an expression: writing it
#: blank used to "succeed" by adding a header the CSV export shows as an empty cell.
#:
#: Applied in :meth:`DataAnalysisService.run_pipeline`, which both the analysis node and
#: ``/api/analysis/run`` go through, so one table guards every entry point — and after
#: :func:`normalize_step_params`, which is what makes each check a question about the
#: value the operation really receives.
STEP_PARAMS: dict = {
    'drop_null': {'some': ('columns',), 'enums': {'how': ('any', DROP_HOW)}},
    'fill_null': {'some': ('columns',), 'enums': {'method': (None, FILL_METHODS)}},
    'drop_duplicates': {'some': ('columns',), 'enums': {'mode': ('exact', DEDUPE_MODES)}},
    # SimHash near-duplicates read ONE column: the fingerprint is over a text, so a
    # multi-column ask would have to invent a concatenation order nobody chose.
    'dedupe_similar': {'one': ('column',)},
    'select_columns': {'some': ('columns',)},
    'strip_whitespace': {'some': ('columns',)},
    'filter_rows': {'one': ('column',), 'enums': {'op': (NO_DEFAULT, FILTER_OPS)}},
    'rename_columns': {'mapping': True},
    'convert_type': {'one': ('column',), 'enums': {'dtype': ('str', CONVERT_TYPES)}},
    'sort_rows': {'one': ('column',)},
    'groupby_agg': {'one': ('group_col', 'agg_col')},
    'join_tables': {'enums': {'how': ('left', JOIN_HOW)}},
    'column_calc': {'nonblank': ('new_col', 'expr')},
    'bin_column': {'one': ('column',)},
    'sample_rows': {},
    # ── the event-study steps ──
    # All four name ONE column: an unnamed timestamp is not "every timestamp", and a topic
    # model over a column nobody named has no corpus to read. A blank is refused by name
    # rather than defaulted to 正文, because comment crawls file their text under 评论内容 —
    # a default there would model the wrong column and report it as a result.
    'extract_time': {'one': ('column',)},
    'bin_time': {'one': ('column',)},
    # The boundary proposal reads one timestamp column and writes a table of its own, so a
    # column it cannot find is a refusal, not an empty suggestion.
    'suggest_stages': {'one': ('column',)},
    # Every topic step defaults to ``auto``: the encoder is used when its optional stack imports and
    # LDA otherwise, and :func:`_resolve_topic_method` PRINTS which one actually ran, so an auto result
    # is never mislabeled. An EXPLICIT ``embedding`` on a machine without the encoder still refuses BY
    # NAME (a model you asked for is never substituted); explicit ``lda`` runs LDA. The op signatures
    # keep ``method='lda'`` as the floor for a caller that bypasses this normalization (a direct unit
    # call) — which is why the default lives HERE, not in the signature.
    'topic_model': {'one': ('column',), 'enums': {'method': ('auto', ('lda', 'embedding', 'auto'))}},
    # The staged model needs BOTH columns named: a phase column it has to guess would decide
    # the paper's table by dict order. ``topics`` is nonblank because a blank stage-topic count
    # has no defensible default — 5 would be this project's choice, not the user's.
    'topic_by_stage': {
        'one': ('column', 'stage_col'),
        'nonblank': ('topics',),
        'enums': {'word_source': ('tfidf', WORD_SOURCES), 'method': ('auto', ('lda', 'embedding', 'auto'))},
    },
    # The two figure steps read a text column and fit their own model, so the column is the one
    # thing they cannot do without. Their topic count keeps the declared default the panel
    # shows, exactly as ``topic_model`` does.
    'topic_map': {'one': ('column',), 'enums': {'method': ('auto', ('lda', 'embedding', 'auto'))}},
    'topic_salience': {'one': ('column',), 'enums': {'method': ('auto', ('lda', 'embedding', 'auto'))}},
    # The labelling step reads the word cell and writes the summary cell; both are named, and
    # an unnamed 概括 column would "succeed" by adding a header the export shows as empty.
    'topic_label': {
        'one': ('words_col',),
        'nonblank': ('summary_col',),
        'enums': {'on_fail': ('abort', ON_FAIL)},
    },
    # The cluster summariser reads the cluster LABEL column the `cluster` op wrote and the raw
    # TEXT column beside it; both must exist, so each goes in ``one``. ``summary_col`` is the
    # column it writes — nonblank because an unnamed output column would "succeed" invisibly.
    'cluster_label': {
        'one': ('group_col', 'text_col'),
        'nonblank': ('summary_col',),
        'enums': {'on_fail': ('abort', ON_FAIL)},
    },
    # The frontier reviewer groups on the cluster column and names members through the node
    # column, so both are hard reads: a guessed "whichever column looks like a name" would write
    # a paragraph about the wrong set of entities and still print a full table.
    'cluster_review': {
        'one': ('group_col', 'name_col'),
        'nonblank': ('summary_col',),
        'enums': {'on_fail': ('abort', ON_FAIL)},
    },
    'sentiment_evolution': {'one': ('column', 'label_col')},
    # The three reads that follow the staged model all name the columns 分阶段 LDA writes: a
    # lifecycle built on a guessed word column is a story about the wrong cell, and these steps
    # would still print a complete-looking table. ``size_col`` for the timeline is gated for the
    # same reason — a peak taken from a column that holds text is a peak measured from zeros.
    'topic_timeline': {'one': ('stage_col', 'words_col', 'size_col')},
    'topic_flow': {'one': ('stage_col', 'topic_col', 'weights_col')},
    # The sweep and the co-occurrence graph both read one text column, exactly as the topic
    # steps do: neither has a defensible fallback corpus to pick.
    'topic_coherence': {'one': ('column',)},
    'cooccur': {'one': ('column',)},
    # The reply graph names all three columns it joins on; each must exist, so all go in ``one``.
    'reply_graph': {'one': ('author_col', 'floor_col', 'parent_floor_col')},
    # The comparison groups on ONE named column (the platform the merge stamped); the optional
    # value column is checked by the method itself (it is "" when the user asked for counts only).
    'compare_platform': {'one': ('platform_col',)},
    # Both look-forward steps read a CURVE, so the period column and the value column are each
    # named: a forecast of whichever numeric column was nearest in the table would put a line on
    # a chart nobody asked for and label it 预测情感走向.
    'forecast': {
        'one': ('column', 'value_col'),
        'enums': {'method': ('moving_average', FORECAST_METHODS)},
    },
    'alert': {'one': ('column', 'index_col')},
}


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
