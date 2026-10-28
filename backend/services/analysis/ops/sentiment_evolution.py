"""The ``sentiment_evolution`` step, one module of the analysis op registry (see ops/__init__.py)."""

import logging

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError, _to_datetime

logger = logging.getLogger(__name__)


def sentiment_evolution(
    df: pd.DataFrame,
    column: str,
    label_col: str = 'sentiment',
    positive: str = 'positive',
    neutral: str = 'neutral',
    negative: str = 'negative',
    new_col: str = 'sentiment_index',
    score_col: str = '',
    order_col: str = '',
) -> pd.DataFrame:
    """Per-period sentiment shares and one signed intensity — the evolution curve.

    The number this exists for is ``sentiment_index`` = (positive − negative) / total,
    which is the paper's daily value: +1 means the period was wholly positive, −1
    wholly negative, and 0 means either everything was neutral or the two sides
    cancelled. It is deliberately NOT a mean of per-row scores: a mean over rows answers
    "how strong was the average opinion", while this answers "which way did the crowd
    lean", and a phase with a large silent neutral majority must read as moderate even
    when the few opinions are extreme. That distinction is the paper's central finding
    (爆发期 76% negative but a phase index near −0.56), so it is computed rather than
    approximated.

    Rows whose label is none of the three named values are counted in ``total`` and in
    none of the three buckets — a blank the polarity node could not judge is not a
    neutral opinion, and folding it into 中性 would report a finding the data does not
    contain. Their count is ``other_n``, so the difference is visible rather than lost.

    ``volume_pct`` is the other half of the figure the study is famous for: 舆情热度, the
    share of the corpus each period holds. It is taken over the rows that reached a
    period (a blank period belongs to none, so its share is not missing — it is
    undefined), which is what makes the column add up to 100.

    ``score_col`` adds the second curve the paper reads against 热度: 情感强度 =
    mean(|score − 0.5|) × 2 over the rows that carry a score, which is how far the
    crowd pushed, in either direction, from neutral. Signed means would answer "which
    way" a second time and collapse toward 0 in a period where both sides are loud —
    exactly the 二次爆发期 the paper says was COLDER in volume and HOTTER in intensity.
    A period with no scored rows gets ``None``, never 0.5: a half-way value would read
    as "measured and found neutral".

    ``order_col`` is how a 阶段 grouping keeps its lifecycle order. The rows come back
    sorted by PERIOD NAME, which is right for 'YYYY-MM-DD' days and wrong for Chinese
    phase labels: 二次爆发期 sorts before 发酵期 by code point, so 表 2 and 图 3 would
    present the case out of sequence while looking complete. The user names a column to
    order by — the NUMBER 按时间划分阶段's 序号列 writes, or a time — and a group whose
    rows hold none of it is refused by name rather than appended at the end.
    """
    if column not in df.columns:
        raise UnknownOperationError(t('analysis.step_col_missing', op='sentiment_evolution', col=column))
    if label_col not in df.columns:
        # The polarity column IS what this step counts. Handing the table back unchanged read
        # as a successful curve whose 极性 column had simply been renamed — and the step still
        # emits sentiment_index, so the downstream chart saw no gap at all.
        raise UnknownOperationError(t('analysis.step_col_missing', op='sentiment_evolution', col=label_col))
    if score_col and score_col not in df.columns:
        # The user asked for the intensity curve and named a column this table does not
        # hold. Answering with the shares only would ship a chart with one line and no
        # word about the missing one.
        raise UnknownOperationError(t('analysis.step_col_missing', op='sentiment_evolution', col=score_col))
    work = df.copy()
    labels = work[label_col].astype('string').fillna('').str.strip()
    work['_pos'] = (labels == positive).astype(int)
    work['_neu'] = (labels == neutral).astype(int)
    work['_neg'] = (labels == negative).astype(int)
    agg_map = {
        'positive_n': ('_pos', 'sum'),
        'neutral_n': ('_neu', 'sum'),
        'negative_n': ('_neg', 'sum'),
        'total': ('_pos', 'size'),
    }
    if score_col:
        scores = pd.to_numeric(work[score_col], errors='coerce')
        work['_deviation'] = (scores - 0.5).abs() * 2
        work['_scored'] = scores.notna().astype(int)
        agg_map['score_n'] = ('_scored', 'sum')
        # ``mean`` skips NaN, so an unscored row neither lifts nor drags the intensity —
        # it is simply absent from it, and ``score_n`` says how many rows were.
        agg_map['intensity'] = ('_deviation', 'mean')
    if order_col:
        if order_col not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='sentiment_evolution', col=order_col))
        # Numeric first (a 序号 column), then time (a 日期 column): the two ways this
        # project's own steps say "which phase came first".
        ranks = pd.to_numeric(work[order_col], errors='coerce')
        if not ranks.notna().any():
            ranks = _to_datetime(work[order_col]).astype('int64') / 1e9
            ranks = ranks.where(ranks.notna() & (ranks > 0) & (ranks < 2**62))
        work['_rank'] = ranks
        agg_map['_rank'] = ('_rank', 'min')
    grouped = work.groupby(column, dropna=True).agg(**agg_map)
    grouped = grouped.reset_index()
    grouped['other_n'] = grouped['total'] - grouped['positive_n'] - grouped['neutral_n'] - grouped['negative_n']
    # A zero total cannot happen (groupby only makes groups from rows) but the ratio is
    # written defensively: a division here would surface as an inf in a chart, not as
    # an error anyone could trace back to this line.
    totals = grouped['total'].replace(0, pd.NA)
    for name, source in (
        ('positive_pct', 'positive_n'),
        ('neutral_pct', 'neutral_n'),
        ('negative_pct', 'negative_n'),
    ):
        grouped[name] = (grouped[source] / totals * 100).round(2)
    grouped[new_col] = ((grouped['positive_n'] - grouped['negative_n']) / totals).round(4)
    heat = int(grouped['total'].sum())
    grouped['volume_pct'] = (grouped['total'] / max(1, heat) * 100).round(2)
    if score_col:
        # NaN would serialise as a bare ``NaN`` token, which the browser's JSON.parse
        # rejects for the WHOLE response, and writing None back into the float column
        # pandas already built just folds it back into NaN. An object column is the one
        # spelling that keeps an unjudged period an empty cell.
        grouped['intensity'] = pd.Series(
            [
                None if not count else round(float(value), 4)
                for count, value in zip(grouped['score_n'], grouped['intensity'], strict=True)
            ],
            index=grouped.index,
            dtype='object',
        )
    # Ascending by the period so a line chart draws left-to-right in time without the
    # user having to add a sort step — and 'YYYY-MM-DD' sorts chronologically as text,
    # which is why extract_time answers with text. With ``order_col`` the lifecycle order
    # comes from that column instead, because a phase NAME does not sort in time.
    if order_col:
        # ``grouped`` has already been reset_index()-ed above, so its index is 0..n-1 and
        # naming a row from it would report "4" where the user needs the phase's name.
        adrift = [str(name) for name, rank in zip(grouped[column], grouped['_rank'], strict=True) if pd.isna(rank)]
        if adrift:
            # A period with no rank has no position; putting it at the end would invent one.
            raise UnknownOperationError(
                t(
                    'analysis.stage_order_unranked',
                    op='sentiment_evolution',
                    col=order_col,
                    stages='、'.join(adrift),
                )
            )
        grouped = grouped.sort_values('_rank', kind='stable')
        grouped = grouped.drop(columns=['_rank'])
    else:
        grouped = grouped.sort_values(column, kind='stable')
    grouped = grouped.reset_index(drop=True)
    grouped = grouped.rename(columns={column: 'period'})
    logger.info(
        t(
            'analysis.evolution_done',
            n=len(grouped),
            periods=str(grouped['period'].iloc[0]) + ' … ' + str(grouped['period'].iloc[-1]) if len(grouped) else '',
        )
    )
    if score_col:
        unscored = [str(name) for name, count in zip(grouped['period'], grouped['score_n'], strict=True) if not count]
        if unscored:
            logger.warning(t('analysis.evolution_unscored', col=score_col, periods='、'.join(unscored)))
    return grouped


# ── Looking forward: the paper's 预测情感走向 and 提前干预 ─────
