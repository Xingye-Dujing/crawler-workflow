"""The name capability: metadata only, never rows.

A name node labels a workflow for the history panel and produces nothing. That is why it must sit
at the head of a chain and wire into a real node: a label with nothing downstream groups no work.
"""

from capabilities_kernel.manifest import (
    Ai,
    Docs,
    Execution,
    Identity,
    Manifest,
    ParamSpec,
    Ports,
    Rule,
    Tests,
    Ui,
)

MANIFEST = Manifest(
    identity=Identity(
        id='name',
        kind='node',
        version='1.0.0',
        title_key='nodeType.name',
        category='meta',
        order=0,
        description='Name a workflow for the history panel; produces no rows.',
        when_to_use='At the head of a canvas whose runs should be grouped by a readable name.',
    ),
    params=(
        ParamSpec(
            name='workflow_name',
            type='string',
            default='',
            required=True,
            widget='text',
            placeholder_key='name.unnamed',
            label_key='settings.workflowName',
        ),
        ParamSpec(
            name='layout_order',
            type='string',
            default='',
            widget='number',
            description_key='settings.layoutOrderHint',
            label_key='settings.layoutOrder',
        ),
    ),
    ports=Ports(rows='none', inputs=0, emit_columns='nodes.executors.name:emit_columns'),
    execution=Execution(handler='nodes.executors.name:run', quiet=True),
    rules=(
        Rule(
            kind='required_param',
            code='engine.name_no_label',
            message_key='engine.name_no_label',
            param='workflow_name',
        ),
        Rule(kind='no_input', code='engine.name_not_head', message_key='engine.name_not_head'),
        Rule(kind='requires_output', code='engine.name_no_downstream', message_key='engine.name_no_downstream'),
    ),
    ui=Ui(hint_key='name.hint'),
    ai=Ai(
        summary='工作流命名 is pure metadata: it names the run and must feed a real node.',
        steps=(
            'Put 工作流命名 at the head of the canvas (no incoming wire).',
            'Type the run name; a blank name is refused before the run and in history grouping.',
            'Wire it into the node whose work the name describes.',
        ),
        examples=({'type': 'name', 'params': {'workflow_name': '知乎评论 · 10 月', 'layout_order': ''}},),
        failures=(
            'Blank workflow_name: refused with engine.name_no_label.',
            'An incoming wire: refused with engine.name_not_head.',
            'No outgoing wire: refused with engine.name_no_downstream.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_name_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/name.md'),
)
