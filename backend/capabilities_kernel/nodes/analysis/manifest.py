"""The analysis capability: a pipeline of data-analysis steps over the upstream table.

``steps`` is a JSON array; each step names an operator and its parameters. The output columns follow
the steps, so the lineage view asks the executor's own hook. A node with neither steps nor an
operation would pass rows through doing nothing.
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
        id='analysis',
        kind='node',
        version='1.0.0',
        title_key='nodeType.analysis',
        category='analysis',
        order=7,
        description='Run a pipeline of data-analysis steps (filter, join, group, statistics, LDA, …).',
        when_to_use='When rows need a multi-step table transformation; a single text operation belongs on 处理.',
    ),
    params=(
        ParamSpec(name='operation', type='string', default='drop_null', widget='select'),
        ParamSpec(name='columns', type='string', default='', widget='text'),
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='value', type='string', default='', widget='text'),
        ParamSpec(name='op', type='string', default='eq', widget='select'),
        ParamSpec(name='dtype', type='string', default='str', widget='select'),
        ParamSpec(name='rename_from', type='string', default='', widget='column'),
        ParamSpec(name='rename_to', type='string', default='', widget='text'),
    ),
    ports=Ports(
        rows='table',
        inputs=1,
        emit_columns='nodes.executors.analysis:emit_columns',
        read_columns='nodes.executors.analysis:read_columns',
    ),
    execution=Execution(handler='nodes.executors.analysis:run'),
    validators=('nodes.executors.analysis:validate_node',),
    postcheck='nodes.executors.analysis:postcheck',
    ui=Ui(form='custom', custom_renderer='analysis'),
    ai=Ai(
        summary=(
            '数据分析 runs an ordered pipeline of operators over one table: filter/select/rename/join/group, '
            'statistics, text analysis (keyword/topic/LDA) and chart-ready aggregates. Each operator declares '
            'the columns it reads and the columns it emits.'
        ),
        when_not_to_use=('One text operation belongs on node.process; a chart belongs on node.visualize.',),
        prerequisites=(
            'An upstream table.',
            'Every column a step reads exists upstream; the step refuses by name otherwise.',
        ),
        steps=(
            'Add steps in order; each step is {op, ...params}.',
            'A step that reads a column refuses by name when the column is absent upstream.',
            'The analysis node emits the columns of the last step plus passthrough columns.',
        ),
        examples=(
            {
                'type': 'analysis',
                'params': {'operation': 'drop_null', 'steps': '[{"op": "drop_null", "columns": "正文"}]'},
            },
        ),
        template={
            'type': 'analysis',
            'params': {'operation': 'drop_null', 'steps': '[{"op": "drop_null", "columns": "正文"}]'},
        },
        failures=(
            'No steps and no operation: engine.analysis_no_op.',
            'An unknown operator/parameter: data_analysis.validate_step names it with the allowed values.',
            'A missing input column: the step refuses by name rather than guessing.',
        ),
        acceptance=(
            'The output carries the last step’s columns.',
            'A zero-row result from non-empty input is reported as engine.empty_output.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_analysis_manifest.py',)),
    docs=Docs(
        page='docs/capabilities/nodes/analysis.md',
        skill='docs/capabilities/skills/nodes/analysis.md',
    ),
)
