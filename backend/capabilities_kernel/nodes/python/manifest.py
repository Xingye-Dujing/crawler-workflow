"""The python capability: run a saved script over the upstream rows.

The node stores a script id, never inline code: the same script library feeds the AI's Python tools
and the canvas node. Cloud mode refuses it by name; local mode runs the JSONL contract.
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
        id='python',
        kind='node',
        version='1.0.0',
        title_key='nodeType.python',
        category='process',
        order=6,
        description='Run a saved Python script over the upstream rows (local/desktop only).',
        when_to_use='When a transformation is not one of the built-in operations and should be reused as a script.',
    ),
    params=(
        ParamSpec(name='script_id', type='string', default='', widget='select'),
        ParamSpec(name='args', type='string', default='{}', widget='json'),
        ParamSpec(name='timeout', type='integer', default=120, minimum=1, maximum=3600, widget='number'),
        ParamSpec(name='max_rows', type='integer', default=200000, minimum=1, widget='number'),
    ),
    ports=Ports(rows='table', inputs=1),
    execution=Execution(handler='nodes.executors.python_node:run'),
    ui=Ui(form='custom', custom_renderer='python'),
    ai=Ai(
        summary=(
            'Python 节点 runs one saved script from the account’s script library over the upstream rows. '
            'The script reads CIXI_INPUT and writes CIXI_OUTPUT (JSON Lines); the node stores its id, not code.'
        ),
        when_not_to_use=(
            'When a built-in operation exists, use node.process first (capability-first policy).',
            'Cloud mode has no Python and refuses this node by name.',
        ),
        prerequisites=(
            'A script saved in the account script library.',
            'Local or desktop mode with ai_allow_python on.',
            'Upstream rows in the CIXI_INPUT JSONL contract.',
        ),
        steps=(
            'Save or pick a script in the Python panel.',
            'Wire the rows in and set args (a JSON object the script reads from CIXI_ARGS).',
            'Keep timeout/max_rows within the script’s needs; the runtime caps the output rows.',
        ),
        examples=(
            {
                'type': 'python',
                'params': {
                    'script_id': 'clean_links',
                    'args': '{"drop_empty": true}',
                    'timeout': 120,
                    'max_rows': 200000,
                },
            },
        ),
        template={
            'type': 'python',
            'params': {'script_id': 'clean_links', 'args': '{}', 'timeout': 120},
        },
        failures=(
            'Cloud mode: refused by name (ai.pythonCloud).',
            'No/unknown script: refused with ai.pythonUnknown.',
            'Bad args JSON: ai.pythonArgs; bad timeout/max_rows: ai.pythonBadNumber.',
        ),
        acceptance=(
            'The node returns rows written to CIXI_OUTPUT and a zero exit code.',
            'A failed script names its stderr instead of settling an empty table.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_python_manifest.py',)),
    docs=Docs(
        page='docs/capabilities/nodes/python.md',
        skill='docs/capabilities/skills/nodes/python.md',
    ),
)
