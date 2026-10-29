"""Visualize node: build the chart spec a workflow's preview panel renders.

The node has no data source of its own on purpose: files enter a workflow through the Upload
node, so a chart is always "whatever upstream produced", crawl or file alike. The spec is an
ECharts option or a base64 matplotlib image — the same two engines ``/api/visualize/render``
offers — plus the LaTeX figure/table add-ons both callers share.
"""

import pandas as pd
from core.refs import as_bool
from runtime.state import add_log

from i18n import t
from nodes.context import NodeCall, columns_from_params, node_params, split_panel_columns
from services.charts.contracts import BIBLIO_CHART_READS
from services.charts.outputs import build_latex_outputs
from services.charts.visualizer import ChartConfigError, VisualizationService, chart_engine
from services.runs.files import record_file

NODE_TYPE = 'visualize'

#: The columns a chart reads from its upstream table (``stack_fields`` is split like a list by
#: the lineage model; a biblio chart adds its own contract through ``chart_contracts``).
READ_PARAMS = ('x_field', 'y_field', 'y2_field', 'label_field', 'value_field')


def read_columns(node: dict) -> list[str]:
    """The fields this chart reads from its input table, plus the biblio view's fixed columns."""
    params = node_params(node)
    found = columns_from_params(params, READ_PARAMS)
    found += split_panel_columns(params.get('stack_fields'))
    chart = str(params.get('chart_type') or '')
    found += list(BIBLIO_CHART_READS.get(chart, ()))
    return [c for c in found if c]


def execute_visualize_node(node: dict, current_input: list, ctx: dict = None):
    """Visualize node: builds a chart from the upstream data and returns a
    chart spec dict the frontend renders — either an ECharts option or a
    base64 image — so this node works identically to /api/visualize/render.

    It has no data source of its own on purpose: files enter a workflow
    through the Upload node, so a chart is always "whatever upstream
    produced", crawl or file alike.
    """
    params = node.get('params', {})
    chart_type = params.get('chart_type', 'bar')
    x_field = params.get('x_field')
    y_field = params.get('y_field')
    value_field = params.get('value_field')
    agg = params.get('agg', 'sum')
    # The right-hand scale of 双轴折线. Read like ``value_field`` — the service owns the
    # refusal when a type needs it and does not have it.
    y2_field = params.get('y2_field')
    agg2_field = params.get('agg2')
    # The column that NAMES each bubble in the intertopic map (the topic label). Read like
    # ``value_field``: the builder owns the refusal when a type needs it and does not have it.
    label_field = params.get('label_field')
    # The columns a 100% stacked-share figure lays on top of each other (e.g. the sentiment
    # evolution's positive_pct/neutral_pct/negative_pct). Forwarded to both engines.
    stack_fields = params.get('stack_fields')
    # The one word a 关系图 centres on: it + its directly co-occurring words only (an
    # ego-network), not a hover hint. Blank = the full candidate graph. It chooses which
    # rows reach the figure, so it feeds the node fingerprint (never a volatile label).
    center_node = params.get('center_node')
    # The three columns 模型一致率 reads from the tidy multi-model table: which column names a
    # model, which holds its label, and which aligns the same text across models. Forwarded like
    # the other optional fields; the builder owns the refusal when they name a missing column.
    model_field = params.get('model_field')
    agreement_label_field = params.get('agreement_label_field')
    id_field = params.get('id_field')
    # Dated event markers for 折线/柱状/双轴折线. Forwarded to both engines: the matplotlib
    # renderer refuses it by name, which is the honest answer when a figure would lose its dates.
    annotations = params.get('annotations')
    title = params.get('title', '')
    tokenize = as_bool(params.get('tokenize'))
    wordcloud_style = params.get('wordcloud_style')

    if not current_input:
        # A refused export answers as data, not as a console line: run_node_durable turns this
        # {'error': …} into the single attributed wf.node_failed line, so printing the bare
        # sentence here too was the second console line for one failure.
        return {'error': t('wf.visualize_no_input')}
    df = pd.DataFrame(current_input)

    try:
        # ``chart_engine`` refuses an off-list renderer by name; branching on the raw
        # value here (as both paths used to) handed 'mpl' / 'Matplotlib' to the browser
        # library and reported it as if the user had chosen it.
        engine = chart_engine(params.get('engine'))
        if engine == 'matplotlib':
            image = VisualizationService.render_image(
                df,
                chart_type,
                x=x_field,
                y=y_field,
                value_field=value_field,
                agg=agg,
                title=title,
                annotations=annotations,
                stack_fields=stack_fields,
            )
            spec = {'engine': 'matplotlib', 'image': image}
        else:
            kw = {'tokenize': tokenize}
            if wordcloud_style:
                kw['wordcloud_style'] = wordcloud_style
            option = VisualizationService.to_echarts_option(
                df,
                chart_type,
                x=x_field,
                y=y_field,
                value_field=value_field,
                agg=agg,
                y2=y2_field,
                agg2=agg2_field,
                label_field=label_field,
                annotations=annotations,
                title=title,
                stack_fields=stack_fields,
                center_node=center_node,
                model_field=model_field,
                agreement_label_field=agreement_label_field,
                id_field=id_field,
                **kw,
            )
            spec = {'engine': 'echarts', 'option': option}
    except ChartConfigError as e:
        # The reason travels as the node's own error; the executor prints it once,
        # with the node's label. Printing it here too gave two lines for one
        # failure, the first of them undiagnosable because it named no node.
        return {'error': str(e)}

    # Both LaTeX add-ons default ON: a chart a user drops on the canvas also owes them the
    # figure source and the three-line table, since the point of the whole node is a
    # paper-ready figure. Either box can be turned off on its own.
    emit_latex = as_bool(params.get('emit_latex', True))
    emit_latex_table = as_bool(params.get('emit_latex_table', True))
    if emit_latex or emit_latex_table:
        spec.update(
            build_latex_outputs(
                df,
                chart_type=chart_type,
                x_field=x_field,
                y_field=y_field,
                value_field=value_field,
                agg=agg,
                y2_field=y2_field,
                agg2_field=agg2_field,
                label_field=label_field,
                stack_fields=stack_fields,
                title=title,
                tokenize=tokenize,
                emit_latex=emit_latex,
                emit_latex_table=emit_latex_table,
                base_name=node.get('title') or node.get('id') or chart_type,
                log=True,
            )
        )
        # The LaTeX add-ons are real files in the export folder (the figure source and the
        # three-line table); the chart itself lives only in the returned spec. Register the
        # written files so a run's paper artifacts are clearable and listed with its record.
        nid = str(node.get('id') or '')
        for _key, _kind in (('latex_file', 'latex'), ('latex_table_file', 'latex_table')):
            if spec.get(_key):
                record_file(ctx, nid, spec[_key], _kind)

    add_log(t('wf.visualize_done', chart=chart_type, engine=engine, n=len(df)))
    return spec


def run(node: dict, call: NodeCall):
    return execute_visualize_node(node, call.current_input, ctx=call.ctx)
