"""The visualize capability: build a chart spec from the upstream table.

One node type serves every chart (bar/line/pie/word cloud/topic map/…). The chart type selects the
fields and the required parameters; ``ChartSpec.required_params`` is checked before a run.
"""

from capabilities_kernel.manifest import (
    Ai,
    Docs,
    Execution,
    Identity,
    Manifest,
    ParamSpec,
    Ports,
    Tests,
    Ui,
)

MANIFEST = Manifest(
    identity=Identity(
        id='visualize',
        kind='node',
        version='1.0.0',
        title_key='nodeType.visualize',
        category='visualize',
        order=13,
        description='Build an ECharts/matplotlib chart (plus LaTeX) from the upstream table.',
        when_to_use='When rows should become a chart; a PDF document belongs on PDF 编译.',
    ),
    params=(
        ParamSpec(name='chart_type', type='string', default='bar', widget='select'),
        ParamSpec(name='x_field', type='string', default='', widget='column'),
        ParamSpec(name='y_field', type='string', default='', widget='column'),
        ParamSpec(name='value_field', type='string', default='', widget='column'),
        ParamSpec(name='agg', type='string', default='sum', widget='select'),
        ParamSpec(name='engine', type='string', default='echarts', widget='select'),
        ParamSpec(name='title', type='string', default='', widget='text'),
        ParamSpec(name='tokenize', type='boolean', default=False, widget='switch'),
        ParamSpec(name='emit_latex', type='boolean', default=True, widget='switch'),
        ParamSpec(name='emit_latex_table', type='boolean', default=True, widget='switch'),
    ),
    ports=Ports(rows='pdf', inputs=-1, read_columns='nodes.executors.visualize:read_columns'),
    execution=Execution(handler='nodes.executors.visualize:run'),
    validators=('nodes.executors.visualize:validate_node',),
    ui=Ui(),
    ai=Ai(
        summary=(
            '可视化 builds one chart from the upstream rows: an ECharts option or a matplotlib image, plus '
            'optional LaTeX figure/table. Chart type decides the fields; ChartSpec.required_params decides '
            'what must be filled before a run.'
        ),
        steps=(
            'Pick the chart type (词云, 柱状图, 主题距离图, 文献共现, …).',
            'Pick the x/y/value/label fields; a chart that needs no x says so.',
            'Turn on LaTeX outputs only when a PDF 编译/保存 will consume them.',
        ),
        examples=(
            {
                'type': 'visualize',
                'params': {'chart_type': 'bar', 'x_field': 'word', 'y_field': 'frequency', 'engine': 'echarts'},
            },
        ),
        failures=(
            'No chart type: engine.visualize_no_chart.',
            'No x field for a chart that needs one: engine.visualize_no_x.',
            'A chart-specific field missing (e.g. stack_fields): engine.chart_field_missing names the chart and field.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_visualize_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/visualize.md'),
)
