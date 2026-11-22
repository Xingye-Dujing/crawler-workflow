"""The compile capability: turn visualize parents' LaTeX into one PDF.

It reads the parents' DICT results, never rows. Every parent must be a visualize with at least one
LaTeX box on; a both-off chart gives the compiler nothing, so validation refuses it before a run.
"""

from capabilities_kernel.manifest import (
    Ai,
    Docs,
    Execution,
    Identity,
    Manifest,
    Ports,
    Tests,
    Ui,
)

MANIFEST = Manifest(
    identity=Identity(
        id='compile',
        kind='node',
        version='1.0.0',
        title_key='nodeType.compile',
        category='visualize',
        order=14,
        description='Assemble the LaTeX from visualize parents and compile it to a PDF.',
        when_to_use='When several charts/tables should become one PDF; a single chart can be saved directly.',
    ),
    ports=Ports(rows='pdf', inputs=-1),
    execution=Execution(handler='nodes.executors.compile:run'),
    validators=('nodes.executors.compile:validate_node',),
    ui=Ui(hint_key='settings.compileHint'),
    ai=Ai(
        summary=(
            'PDF 编译 collects the LaTeX emitted by visualize parents and compiles one document. It reads '
            'parent artifacts, not rows, and refuses an empty source instead of producing a blank PDF.'
        ),
        steps=(
            'Turn on 输出 LaTeX and/or LaTeX 表格 on every visualize parent.',
            'Wire those visualize nodes into PDF 编译.',
            'Wire the compile node into 保存 when the PDF needs a user-chosen filename.',
        ),
        examples=({'type': 'compile', 'params': {}},),
        failures=(
            'No parent: engine.compile_no_upstream.',
            'A parent is not a visualize node: engine.compile_bad_parent names it.',
            'A visualize parent has both LaTeX boxes off: engine.compile_source_both_off names it.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_compile_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/compile.md'),
)
