"""The ``topic_label`` step, one module of the analysis op registry (see ops/__init__.py)."""

import hashlib
import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import _fallback_topic_label, _label_from

logger = logging.getLogger(__name__)


def topic_label(
    df: pd.DataFrame,
    llm=None,
    cancel=None,
    store=None,
    words_col: str = 'feature_words',
    samples_col: str = 'sample_texts',
    summary_col: str = '主题概括',
    on_fail: str = 'abort',
    max_topics: int = 30,
) -> pd.DataFrame:
    """Ask the model for the 主题概括 column the study's authors wrote by hand.

    One prompt per topic row and nothing else: the evidence handed over is the phase, the
    topic's own number, its feature words and the sample posts :meth:`topic_by_stage`
    already picked — which is what a reader of 表 1 sees. The paper's summaries came from
    reading the corpus; these come from reading the same WORDS, so the column is data this
    project produced, not the authors' finding restated.

    The answer's language follows the run's own, because the prompt is an ``i18n`` string:
    a node that answers English into a Chinese interface would have to be re-run to be
    readable.

    ``llm`` is handed in by :func:`run_pipeline` for the ops in :data:`LLM_OPS`, and a
    missing one is a refusal rather than a skip — the column would come back empty and the
    node would settle DONE over work that did not happen. ``cancel`` is the run's Stop
    flag; a cut-short pass leaves :data:`ABORT_MARK` in the rows the model never saw, which
    is how the executor already learns an LLM node was interrupted instead of finished.
    """
    from analyzers.llm_client import ABORT_MARK, LLMError

    if words_col not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='topic_label', col=words_col))
    if llm is None and on_fail != 'fallback':
        raise UnknownOperationError(t('analysis.label_no_llm', op='topic_label'))
    if llm is None:
        # No model at all: name every topic from its OWN weighted words so the column is a
        # named topic, not a blank nobody can tell apart from a topic never asked about.
        work = df.copy()
        work[summary_col] = ''
        has_weights = 'weights' in work.columns
        for position in work.index:
            weights = str(work.at[position, 'weights'] or '') if has_weights else ''
            work.at[position, summary_col] = _fallback_topic_label(weights, str(work.at[position, words_col] or ''))
        logger.warning(t('analysis.label_fallback_all', n=len(work)))
        return work
    limit = int(max_topics)
    if limit < 1 or len(df) > limit:
        # One call per row, so a 5,000-row table is 5,000 paid questions nobody meant to
        # ask. 表 1 is 25 rows; the ceiling is there to catch the mis-wired pipeline.
        raise UnknownOperationError(t('analysis.label_too_many', rows=len(df), limit=limit))
    work = df.copy()
    work[summary_col] = ''
    has_stage = 'stage' in work.columns
    has_topic = 'topic' in work.columns
    positions = list(work.index)
    labelled = 0
    # Answers are replayed from runs.db's llm_cache, the way the analyzers' rows are: a re-run
    # of the same table must not re-pay 27 questions. The key is the prompt itself, so a changed
    # model, a different language, or an edited 特征词/样本帖 column all re-ask on their own —
    # a cache that survives the question it answers would be the bug this table exists to avoid.
    scope = f'topic_label:{getattr(llm, "label", "") or "model"}'
    asked = 0
    replayed = 0
    for offset, position in enumerate(positions):
        if cancel is not None and cancel.is_set():
            for rest in positions[offset:]:
                work.at[rest, summary_col] = ABORT_MARK
            logger.warning(t('analysis.label_cancelled', n=len(positions) - offset))
            return work
        name = str(work.at[position, 'topic']) if has_topic else f'#{offset + 1}'
        words = str(work.at[position, words_col] or '').strip()
        if not words:
            raise UnknownOperationError(t('analysis.label_no_words', topic=name, col=words_col))
        samples = ''
        if samples_col and samples_col in work.columns:
            samples = str(work.at[position, samples_col] or '').strip()
        prompt = t(
            'analysis.label_prompt',
            stage=str(work.at[position, 'stage']) if has_stage else '',
            topic=name,
            words=words,
            samples=samples or '—',
        )
        key = hashlib.sha1(prompt.encode('utf-8')).hexdigest()
        answer = store.cache_get(scope, key) if store is not None else None
        if answer is not None:
            replayed += 1
        else:
            asked += 1
            try:
                answer = llm.chat(prompt)
            except LLMError as e:
                if on_fail == 'fallback':
                    # Name the topic from its weighted words rather than dropping the row or
                    # aborting a long run the user asked to keep going.
                    work.at[position, summary_col] = _fallback_topic_label(
                        str(work.at[position, 'weights'] or '') if 'weights' in work.columns else '', words
                    )
                    labelled += 1
                    logger.warning(t('analysis.label_fallback', topic=name, reason='error'))
                    continue
                if on_fail != 'blank':
                    raise UnknownOperationError(t('analysis.label_failed', topic=name, err=e)) from e
                # One line per topic the model gave up on, and the cell stays empty: the user
                # asked for the run to continue, not for the gap to be invisible.
                logger.warning(t('analysis.label_failed', topic=name, err=e))
                continue
            if store is not None:
                store.cache_put(scope, key, answer)
        label = _label_from(answer)
        if not label:
            if on_fail == 'fallback':
                work.at[position, summary_col] = _fallback_topic_label(
                    str(work.at[position, 'weights'] or '') if 'weights' in work.columns else '', words
                )
                labelled += 1
                logger.warning(t('analysis.label_fallback', topic=name, reason='empty'))
                continue
            # An answer of punctuation, or of nothing: a blank cell would be
            # indistinguishable from a topic nobody asked the model about.
            if on_fail != 'blank':
                raise UnknownOperationError(t('analysis.label_empty', topic=name))
            logger.warning(t('analysis.label_empty', topic=name))
            continue
        work.at[position, summary_col] = label
        labelled += 1
    logger.info(t('analysis.label_done', n=labelled, model=getattr(llm, 'label', '')))
    if store is not None:
        logger.info(t('analysis.label_cached', asked=asked, replayed=replayed))
    return work
