"""DataFrame → transport helpers shared by the routes and the node executors.

These three used to live in ``core/refs.py``, which made every importer of ``platform_for`` or
``as_bool`` — the crawler parsers included — pay for ``import pandas``. They are about a *table*
leaving the program (a CSV, a JSON preview), so they belong beside the dataset layer, and ``core``
goes back to meaning "pure helpers, standard library".

The NaN rule is the reason this is one module instead of three copies: raw ``NaN`` is not valid
JSON and breaks ``JSON.parse()`` in the browser, so every preview, export and artifact goes through
:func:`json_safe_records`.
"""

from __future__ import annotations

import io

import pandas as pd


def df_to_csv_string(df: pd.DataFrame) -> str:
    """Convert DataFrame to CSV string (UTF-8 with BOM, which Excel needs to read Chinese)."""
    output = io.StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    return output.getvalue()


def merge_results(results: list, _key: str = 'platform') -> pd.DataFrame:
    """Merge multiple result lists into a single DataFrame; junk entries are skipped."""
    all_items = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)
        elif isinstance(r, dict):
            all_items.append(r)
    return pd.DataFrame(all_items)


def json_safe_records(df: pd.DataFrame, limit: int = None) -> list:
    """Convert a DataFrame slice to JSON-safe records: NaN/NaT become None."""
    page = df.head(limit) if limit is not None else df
    return page.astype(object).where(pd.notna(page), None).to_dict('records')
