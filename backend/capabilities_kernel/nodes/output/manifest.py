"""The save capability: merge/export rows or compile a PDF, then pass the result onward.

A save node is the canvas's merge point: every incoming table becomes one file, and a PDF save
consumes visualize/compile artifacts instead. Both shapes are validated before a run, because
"nothing to save here" used to pass silently.
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
        id='output',
        kind='node',
        version='1.0.0',
        title_key='nodeType.output',
        category='output',
        order=15,
        description='Merge incoming tables (or a PDF source) into one exported file.',
        when_to_use='At the end of a chain when the rows or the PDF need a file on disk.',
    ),
    params=(
        ParamSpec(name='operation', type='string', default='save', widget='select'),
        ParamSpec(name='format', type='string', default='csv', widget='text'),
        ParamSpec(name='filename', type='string', default='export.csv', widget='text'),
    ),
    ports=Ports(rows='table', inputs=-1),
    execution=Execution(handler='nodes.executors.output:run'),
    validators=('nodes.executors.output:validate_node',),
    ui=Ui(form='custom', custom_renderer='output'),
    ai=Ai(
        summary=(
            '保存 merges every incoming table into one file, or saves a PDF from visualize/compile parents. '
            'Column sets must match; the executor refuses a merge rather than exporting only the first table.'
        ),
        when_not_to_use=(
            'Intermediate results stay on the canvas; a reusable growing table belongs on node.accumulate.',
        ),
        prerequisites=(
            'Table parents with matching columns, or visualize/compile parents for a PDF.',
            'A filename; the exporter appends the extension.',
        ),
        steps=(
            'Wire one or more table producers into 保存 for a tabular export.',
            'For a PDF, choose format=pdf (or a .pdf filename) and wire visualize/compile parents only.',
            'Set the filename; the exporter appends the format extension when it is missing.',
        ),
        examples=({'type': 'output', 'params': {'operation': 'save', 'format': 'csv', 'filename': 'comments.csv'}},),
        template={
            'type': 'output',
            'params': {'operation': 'save', 'format': 'csv', 'filename': 'export.csv'},
        },
        failures=(
            'No parent: engine.output_no_upstream.',
            'A PDF save mixed with table parents: engine.output_pdf_mixed.',
            'A PDF save with no visualize/compile parent: engine.output_pdf_only_pdfable.',
            'Both a visualize and a compile PDF source: engine.output_pdf_two_sources.',
            'A table save fed only by a PDF source: engine.output_needs_pdf.',
        ),
        acceptance=(
            'The exported file exists and its row count matches the merged input.',
            'Mixed table and PDF parents are refused by name.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_output_manifest.py',)),
    docs=Docs(
        page='docs/capabilities/nodes/output.md',
        skill='docs/capabilities/skills/nodes/output.md',
    ),
)
