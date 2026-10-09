"""The optional LaTeX add-ons a visualize node / render route produces.

``app.py`` historically held both the HTTP render route and the ``visualize`` node
executor, and both generated the same TikZ figure source and three-line table on top of
the chart they drew. This module owns that web so the route can live in ``api/`` while the
executor stays where the other node executors are — both import the same two functions, so
neither re-implements (nor drifts from) the other.

``build_latex_outputs`` never touches the chart on failure: a broken TikZ branch is recorded
as ``latex_error`` / ``latex_table_error`` and named once on the console in a real run, so the
figure the node already drew and the run itself still succeed.
"""

import logging
import os

from state import add_log

from config import Config
from i18n import t
from services.latex_charts import LatexChartService
from services.visualizer import ECHARTS_ONLY_TYPES
from utils.helpers import as_bool, sanitize_filename

logger = logging.getLogger(__name__)


def write_latex_export(base: str, content: str, suffix: str) -> str:
    """File a LaTeX source as ``<base><suffix>.txt`` under EXPORT_DIR; return the stored name.

    ``.txt`` (not ``.tex``) is deliberate — the user copies the body into their paper and a plain
    text artifact is what the exports browser and download route already serve without a new type.
    """
    name = sanitize_filename(f'{base or "chart"}{suffix}.txt')
    os.makedirs(Config.EXPORT_DIR, exist_ok=True)
    with open(os.path.join(Config.EXPORT_DIR, name), 'w', encoding='utf-8') as handle:
        handle.write(content)
    return name


def build_latex_outputs(
    df,
    *,
    chart_type,
    x_field,
    y_field,
    value_field,
    agg,
    y2_field,
    agg2_field,
    label_field,
    stack_fields,
    title,
    tokenize,
    emit_latex,
    emit_latex_table,
    base_name,
    log,
) -> dict:
    """Generate the optional LaTeX figure / three-line table; never touch the chart on failure.

    Both are add-ons to a visualize node: a broken TikZ branch must not drop the figure the node
    already drew or fail the run, so any error is recorded as ``latex_error`` / ``latex_table_error``
    and named on the console once (in a real run, not a transient preview).
    """
    out: dict = {}
    if chart_type in ECHARTS_ONLY_TYPES:
        # An echarts-only figure (wordcloud/sankey/网络图/模型一致率…) has no LaTeX twin by
        # design; emitting would record a spurious latex_error for a chart that rendered fine.
        return {}
    common = dict(
        x=x_field,
        y=y_field,
        value_field=value_field,
        agg=agg,
        label_field=label_field,
        stack_fields=stack_fields,
        title=title,
        tokenize=tokenize,
    )
    if as_bool(emit_latex):
        try:
            tex = LatexChartService.to_latex_document(df, chart_type, y2=y2_field, agg2=agg2_field, **common)
            name = write_latex_export(base_name, tex, '')
            out['latex'] = tex
            out['latex_file'] = name
            if log:
                add_log(t('latex.done', file=name))
        except Exception as exc:  # a LaTeX defect must not sink the chart — record and name it
            out['latex_error'] = str(exc)
            logger.warning(t('latex.failed', reason=str(exc)))
    if as_bool(emit_latex_table):
        try:
            tex = LatexChartService.to_latex_table(df, chart_type, y2=y2_field, **common)
            name = write_latex_export(base_name, tex, '-表')
            out['latex_table'] = tex
            out['latex_table_file'] = name
            if log:
                add_log(t('latex.table_done', file=name))
        except Exception as exc:
            out['latex_table_error'] = str(exc)
            logger.warning(t('latex.failed', reason=str(exc)))
    return out
