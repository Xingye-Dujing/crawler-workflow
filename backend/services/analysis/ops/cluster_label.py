"""The ``cluster_label`` step, one module of the analysis op registry (see ops/__init__.py)."""

import hashlib
import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import _label_from

logger = logging.getLogger(__name__)


def cluster_label(
    df: pd.DataFrame,
    llm=None,
    cancel=None,
    store=None,
    group_col: str = 'cluster',
    text_col: str = '正文',
    summary_col: str = '摘要',
    on_fail: str = 'abort',
    max_groups: int = 60,
    sample_n: int = 8,
) -> pd.DataFrame:
    """One paragraph per cluster of the raw documents — what the cluster is *about*.

    :meth:`topic_label` names a topic from the WEIGHTED WORDS ``topic_by_stage`` already
    reduced a corpus to; this is the other reading. The ``cluster`` process op labels rows
    by embedding similarity and writes nothing else, so a cluster number on its own says
    nothing about its meaning. Here the model reads the cluster's OWN texts (up to
    ``sample_n``, the ones that actually exist, not a word list) and writes a paragraph, so
    the cluster column becomes an interpretable table one row per cluster.

    Same discipline as :meth:`topic_label` because the failure modes are the same: a
    missing model is a refusal (not a silent empty column), Stop marks the not-yet-summarised
    groups ``ABORT_MARK`` so the node settles PARTIAL, and a table with more clusters than
    ``max_groups`` is a mis-wired pipeline (one paid call per group), not a run to bank.
    """
    from analyzers.llm_client import ABORT_MARK, LLMError

    if group_col not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='cluster_label', col=group_col))
    if text_col not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='cluster_label', col=text_col))
    if not str(summary_col or '').strip():
        raise UnknownOperationError(t('analysis.need_param', op='cluster_label', param='summary_col'))
    if llm is None and on_fail != 'fallback':
        raise UnknownOperationError(t('analysis.label_no_llm', op='cluster_label'))
    groups = df.copy()
    groups['_grp'] = pd.to_numeric(groups[group_col], errors='coerce')
    groups = groups[groups['_grp'].notna()]
    order = sorted(int(k) for k in groups['_grp'].unique())
    limit = int(max_groups)
    if len(order) > limit:
        raise UnknownOperationError(t('analysis.label_too_many', rows=len(order), limit=limit))

    scope = f'cluster_label:{getattr(llm, "label", "") or "model"}'
    rows = []
    summarised = 0
    asked = 0
    replayed = 0
    for idx, key in enumerate(order):
        if cancel is not None and cancel.is_set():
            for rest in order[idx:]:
                rows.append({group_col: rest, 'n_docs': int((groups['_grp'] == rest).sum()), summary_col: ABORT_MARK})
            logger.warning(t('analysis.cluster_cancelled', n=len(order) - idx))
            return pd.DataFrame(rows)
        texts = [tx for tx in groups.loc[groups['_grp'] == key, text_col].dropna().astype(str) if tx.strip()]
        n_docs = len(texts)
        if not texts:
            raise UnknownOperationError(t('analysis.cluster_no_texts', group=key))
        take = max(1, int(sample_n))
        sample = '\n'.join(texts[:take])
        prompt = t('analysis.cluster_prompt', group=key, size=n_docs, texts=sample)
        cache_key = hashlib.sha1(prompt.encode('utf-8')).hexdigest()
        answer = store.cache_get(scope, cache_key) if store is not None else None
        if answer is not None:
            replayed += 1
        else:
            asked += 1
            try:
                answer = llm.chat(prompt)
            except LLMError as e:
                if on_fail == 'fallback':
                    answer = texts[0][:40]
                    logger.warning(t('analysis.cluster_failed', group=key, err=e))
                elif on_fail != 'blank':
                    raise UnknownOperationError(t('analysis.cluster_failed', group=key, err=e)) from e
                else:
                    answer = ''
                    logger.warning(t('analysis.cluster_failed', group=key, err=e))
                rows.append({group_col: key, 'n_docs': n_docs, summary_col: answer})
                if answer:
                    summarised += 1
                continue
            if store is not None:
                store.cache_put(scope, cache_key, answer)
        summary = _label_from(answer)
        if not summary:
            if on_fail == 'fallback':
                summary = texts[0][:40]
            elif on_fail != 'blank':
                raise UnknownOperationError(t('analysis.cluster_empty', group=key))
            else:
                logger.warning(t('analysis.cluster_empty', group=key))
        rows.append({group_col: key, 'n_docs': n_docs, summary_col: summary})
        if summary:
            summarised += 1
    logger.info(t('analysis.cluster_done', n=summarised, model=getattr(llm, 'label', '')))
    if store is not None:
        logger.info(t('analysis.label_cached', asked=asked, replayed=replayed))
    return pd.DataFrame(rows)
