"""The ``cluster_review`` step, one module of the analysis op registry (see ops/__init__.py)."""

import hashlib
import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError
from services.analysis.topic_kernels import _cluster_facts, _review_fallback, _review_language

logger = logging.getLogger(__name__)


def cluster_review(
    df: pd.DataFrame,
    llm=None,
    cancel=None,
    store=None,
    group_col: str = '聚类',
    label_col: str = '聚类标签',
    name_col: str = '节点',
    freq_col: str = '频次',
    first_col: str = '首年',
    last_col: str = '末年',
    summary_col: str = '簇综述',
    members: int = 12,
    on_fail: str = 'abort',
    max_groups: int = 60,
) -> pd.DataFrame:
    """One research-frontier paragraph per bibliometric cluster.

    :meth:`cluster_label` summarises what a cluster's TEXTS say. This reads what the GRAPH
    already measured — the LLR label, the size, the strongest members by frequency, the years
    they span — and asks the model for the one thing clustering cannot produce: what front
    this group forms and which way it is moving. Every number in the prompt comes from the
    table, the prose comes from the model, and the model's own name is logged with the result.

    Same discipline as the other paid steps, because the failure modes are identical: no
    model is a refusal BEFORE anything is spent, Stop marks the clusters not yet reached
    ``ABORT_MARK`` so the node settles PARTIAL rather than DONE, and each answer is cached
    under its prompt so a resume re-reads what it paid for instead of paying twice. A
    ``fallback`` answer is built from the table's own facts and says so in the console — never
    a paragraph that looks like the model wrote it.
    """
    from analyzers.llm_client import ABORT_MARK, LLMError

    for column in (group_col, name_col):
        if column not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='cluster_review', col=column))
    if not str(summary_col or '').strip():
        raise UnknownOperationError(t('analysis.need_param', op='cluster_review', param='summary_col'))
    if llm is None and on_fail != 'fallback':
        raise UnknownOperationError(t('analysis.label_no_llm', op='cluster_review'))

    work = df.copy()
    work['_grp'] = pd.to_numeric(work[group_col], errors='coerce')
    work = work[work['_grp'].notna()]
    order = sorted(int(key) for key in work['_grp'].unique())
    if not order:
        raise UnknownOperationError(t('analysis.review_no_groups', col=group_col))
    if len(order) > int(max_groups):
        raise UnknownOperationError(t('analysis.label_too_many', rows=len(order), limit=int(max_groups)))

    take = max(3, int(members))
    scope = f'cluster_review:{getattr(llm, "label", "") or "model"}'

    def row(key: int, facts: dict | None) -> dict:
        out: dict = {group_col: key}
        if facts:
            out['节点数'] = facts['size']
            out['代表节点'] = '；'.join(facts['names'])
            if facts.get('span'):
                out['年份跨度'] = facts['span']
        if label_col and label_col in work.columns:
            values = [str(v).strip() for v in work.loc[work['_grp'] == key, label_col].dropna().tolist()]
            out[label_col] = values[0] if values else ''
        return out

    rows: list[dict] = []
    written = 0
    asked = 0
    replayed = 0
    for position, key in enumerate(order):
        slice_ = work[work['_grp'] == key]
        facts = _cluster_facts(slice_, name_col, freq_col, first_col, last_col, label_col, take)
        if cancel is not None and cancel.is_set():
            for rest in order[position:]:
                rows.append(
                    row(
                        rest,
                        _cluster_facts(
                            work[work['_grp'] == rest], name_col, freq_col, first_col, last_col, label_col, take
                        ),
                    )
                    | {summary_col: ABORT_MARK}
                )
            logger.warning(t('analysis.review_cancelled', n=len(order) - position))
            return pd.DataFrame(rows)
        prompt = t('analysis.review_prompt', facts=facts['block'], language=_review_language())
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
                    answer = _review_fallback(facts)
                    logger.warning(t('analysis.review_failed_fallback', group=key, err=e))
                elif on_fail != 'blank':
                    raise UnknownOperationError(t('analysis.review_failed', group=key, err=e)) from e
                else:
                    answer = ''
                    logger.warning(t('analysis.review_failed_blank', group=key, err=e))
                rows.append(row(key, facts) | {summary_col: answer})
                if answer:
                    written += 1
                continue
            if store is not None:
                store.cache_put(scope, cache_key, answer)
        text = str(answer or '').strip()
        if not text:
            if on_fail == 'fallback':
                text = _review_fallback(facts)
            elif on_fail != 'blank':
                raise UnknownOperationError(t('analysis.review_empty', group=key))
            else:
                logger.warning(t('analysis.review_empty', group=key))
        rows.append(row(key, facts) | {summary_col: text})
        if text:
            written += 1
    logger.info(t('analysis.review_done', n=written, model=getattr(llm, 'label', '') or ''))
    if store is not None:
        logger.info(t('analysis.label_cached', asked=asked, replayed=replayed))
    return pd.DataFrame(rows)
