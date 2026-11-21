"""The 100 %-stacked shape, computed once for every projection.

A chart is drawn three times — the ECharts option the panel paints, the matplotlib PNG a report
embeds, and the booktabs table the paper prints — and all three must agree on the same numbers.
The stacked-share branch is the one place they drifted: ECharts coerced each field with
``pd.to_numeric``, refused a text-only field by name and left an unmeasured category as a GAP, while
the PNG summed the raw cells (concatenating text strings) and filled a missing group with 0, and the
LaTeX table did the same and could raise ``TypeError`` on a numeric-string column.

So the arithmetic lives here, once. Callers keep their own projection rules (a gap in ECharts, a
skipped segment in matplotlib, an empty cell in booktabs) but no caller re-derives what a share is.
"""

from __future__ import annotations

import pandas as pd

from i18n import t

from .contracts import ChartConfigError


def stacked_shares(df: pd.DataFrame, category: str, fields: list[str]) -> tuple[list[str], dict, list[float]]:
    """``(labels, columns, totals)`` for one 100 %-stacked chart.

    ``columns[field][i]`` is the field's numeric sum for category *i*, or NaN when the category held
    no measurement for it. ``totals[i]`` is the sum of the fields that WERE measured, so a caller
    can tell "0 of 0" (nothing measured) from "0 of 100" (a real zero share).

    A field that holds text everywhere is refused BY NAME — a stacked share has to divide numbers,
    and raw ``sum`` on strings either concatenates them (then the division raises) or silently
    treats blanks as zero. A field missing EVERYWHERE is not a mistake: it sums to nothing and the
    chart still serialises.
    """
    for field in (category, *fields):
        if field not in df.columns:
            raise ChartConfigError(t('chart.field_missing', col=field))
    work = df[[category, *fields]]
    keys = list(work.groupby(category, sort=False).groups.keys())
    columns: dict[str, list] = {}
    for field in fields:
        numeric = pd.to_numeric(work[field], errors='coerce')
        if work[field].notna().any() and not numeric.notna().any():
            raise ChartConfigError(t('chart.y_not_numeric', col=field))
        columns[field] = numeric.groupby(work[category], sort=False).sum(min_count=1).reindex(keys).tolist()
    totals = [
        float(sum(value for value in (columns[field][index] for field in fields) if pd.notna(value)))
        for index in range(len(keys))
    ]
    return [str(key) for key in keys], columns, totals


def share_percent(columns: dict, totals: list[float], field: str, index: int):
    """One cell's share as a percentage, or ``None`` when that category never measured the field."""
    value = columns[field][index]
    if not totals[index] or pd.isna(value):
        return None
    return round(value / totals[index] * 100, 2)
