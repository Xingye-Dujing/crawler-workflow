"""The visualize capability: build a chart spec from the upstream table.

One node type serves every chart (bar/line/pie/word cloud/topic map/…). The chart TYPE's own
contract — which fields it reads, which are required, what each must hold — is declared once in
``services.charts.registry``; this manifest only says the node exists and hands the registry the
node's parameters.
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
    preflight='nodes.executors.visualize:preflight',
    ui=Ui(form='custom', custom_renderer='visualize'),
    ai=Ai(
        summary=(
            '可视化 builds one chart from the upstream rows: an ECharts option or a matplotlib image, plus '
            'optional LaTeX figure/table. The chart type decides which fields it reads; the fields it '
            'requires are refused before a run.'
        ),
        when_not_to_use=(
            'Several charts into one PDF belong on node.compile.',
            'A table export belongs on node.output; a chart is not a file save.',
        ),
        prerequisites=(
            'An upstream table.',
            'The fields the chosen chart declares; validate names a blank required box.',
            'The engine this build serves (echarts or matplotlib).',
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
        template={
            'type': 'visualize',
            'params': {'chart_type': 'bar', 'x_field': 'word', 'y_field': 'frequency', 'engine': 'echarts'},
        },
        failures=(
            'A required field is blank: engine.chart_field_missing names the chart and the box.',
            'A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).',
            'A box plot with neither x nor y: engine.chart_field_group_missing.',
        ),
        acceptance=(
            'The chart option or image exists for the run and the LaTeX switches match the request.',
            'A missing required field is named before the run.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_visualize_manifest.py',)),
    docs=Docs(
        page='docs/capabilities/nodes/visualize.md',
        skill='docs/capabilities/skills/nodes/visualize.md',
    ),
)
