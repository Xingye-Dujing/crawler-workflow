"""图表渲染 Blueprint — the ``/api/visualize/*`` cluster, split out of ``app.py``.

The standalone chart door: render any registered dataset / workflow result / inline table into
an ECharts option or a server-side PNG, with the optional LaTeX figure / three-line table
produced through the same ``services.latex_outputs`` the ``visualize`` node executor uses — so
the HTTP preview and the node can never drift apart. Every dependency is reachable without
importing ``app``. Path and behaviour are unchanged.
"""

import logging

from flask import Blueprint, jsonify

from api.http import _bad_body, _json_body
from api.resolution import NoRunDataError, _resolve_dataframe
from i18n import t
from services.latex_outputs import build_latex_outputs
from services.visualizer import ChartConfigError, VisualizationService, chart_engine
from utils.helpers import as_bool

logger = logging.getLogger(__name__)

bp = Blueprint('visualize', __name__)


@bp.route('/api/visualize/render', methods=['POST'])
def render_visualization():
    """Render a chart from any registered dataset / workflow result / inline
    data. Works for arbitrary tabular data, not just crawler output."""
    data = _json_body()
    if data is None:
        return _bad_body()
    try:
        df = _resolve_dataframe(data)
    except NoRunDataError as e:
        # A canvas nobody has run yet is expected, so answer 200 rather than a 400 the
        # browser dev console would flag red once per cell the dashboard rehydrates on a
        # cold load: ok:false + code + a localized reason the UI paints as a muted note.
        return jsonify({'ok': False, 'code': e.code, 'error': t('chart.noRunData')})
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    chart_type = data.get('chart_type', 'bar')
    x_field = data.get('x_field')
    y_field = data.get('y_field')
    value_field = data.get('value_field')
    agg = data.get('agg', 'sum')
    y2_field = data.get('y2_field')
    agg2_field = data.get('agg2')
    label_field = data.get('label_field')
    stack_fields = data.get('stack_fields')
    center_node = data.get('center_node')
    model_field = data.get('model_field')
    agreement_label_field = data.get('agreement_label_field')
    id_field = data.get('id_field')
    annotations = data.get('annotations')
    title = data.get('title', '')
    tokenize = as_bool(data.get('tokenize'))
    wordcloud_style = data.get('wordcloud_style')
    emit_latex = as_bool(data.get('emit_latex', True))
    emit_latex_table = as_bool(data.get('emit_latex_table', True))
    latex_extra = {}
    if emit_latex or emit_latex_table:
        # Computed outside the render ``try`` because ``build_latex_outputs`` guards each branch
        # itself: a bad TikZ body must annotate the response, not 400 a chart that already rendered.
        latex_extra = build_latex_outputs(
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
            base_name=title or chart_type,
            log=False,
        )

    try:
        engine = chart_engine(data.get('engine'))
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
            return jsonify({'ok': True, 'engine': 'matplotlib', 'image': image, **latex_extra})
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
            stack_fields=stack_fields,
            center_node=center_node,
            annotations=annotations,
            title=title,
            model_field=model_field,
            agreement_label_field=agreement_label_field,
            id_field=id_field,
            **kw,
        )
        return jsonify({'ok': True, 'engine': 'echarts', 'option': option, **latex_extra})
    except ChartConfigError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except (ValueError, KeyError, TypeError) as e:
        # e.g. matplotlib refusing a pie chart of negative values: report it as
        # a bad request instead of letting Flask return an HTML 500 (which the
        # caller cannot even json.parse()).
        logger.warning(t('misc.visualize_failed', err=e))
        return jsonify({'ok': False, 'error': str(e)}), 400
