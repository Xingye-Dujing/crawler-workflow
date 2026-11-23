"""The accumulate capability: append this run's rows to a named lineage/dataset.

It passes the upstream schema through (unknown upstream = unknown output) and appends by row or by
key columns. Exactly one table parent feeds it; the lineage name is what later runs append to.
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
        id='accumulate',
        kind='node',
        version='1.0.0',
        title_key='nodeType.accumulate',
        category='data',
        order=12,
        description='Append the upstream rows to a named lineage (by whole row or by key columns).',
        when_to_use='When repeated runs should accumulate into one growing dataset instead of separate files.',
    ),
    params=(
        ParamSpec(name='lineage_name', type='string', default='', required=True, widget='text'),
        ParamSpec(name='identity', type='string', default='row', enum=('row', 'columns'), widget='select'),
        ParamSpec(name='key_columns', type='string', default='', widget='text'),
    ),
    ports=Ports(rows='table', inputs=1, emit_columns='nodes.executors.accumulate:emit_columns'),
    execution=Execution(handler='nodes.executors.accumulate:run'),
    validators=('nodes.executors.accumulate:validate_node',),
    ui=Ui(form='custom', custom_renderer='accumulate'),
    ai=Ai(
        summary=(
            '数据累积 appends the rows passing through it into a named lineage. ``identity=row`` appends every '
            'row; ``identity=columns`` appends only rows whose key columns are not already present.'
        ),
        when_not_to_use=('A standalone file belongs on node.output; a one-off result should not grow a lineage.',),
        prerequisites=(
            'Exactly one table producer upstream.',
            'A lineage name that stays the same across runs.',
            'Key columns when identity is columns.',
        ),
        steps=(
            'Name the lineage (the same name across runs accumulates together).',
            'Choose row identity or key columns; key columns are required for the column mode.',
            'Wire exactly one table producer in.',
        ),
        examples=(
            {'type': 'accumulate', 'params': {'lineage_name': '知乎评论', 'identity': 'row', 'key_columns': ''}},
        ),
        template={
            'type': 'accumulate',
            'params': {'lineage_name': 'example-lineage', 'identity': 'row', 'key_columns': ''},
        },
        failures=(
            'Blank lineage name: engine.accumulate_no_name.',
            'Unknown identity or column mode without keys: engine.accumulate_bad_identity/no_keys.',
            'Not exactly one parent, or a non-table parent: engine.accumulate_one_parent/bad_parent.',
        ),
        acceptance=(
            'The lineage grows by the rows (or the new keys) of this run.',
            'A non-table or second parent is refused by name.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_accumulate_manifest.py',)),
    docs=Docs(
        page='docs/capabilities/nodes/accumulate.md',
        skill='docs/capabilities/skills/nodes/accumulate.md',
    ),
)
