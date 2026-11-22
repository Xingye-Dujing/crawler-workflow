"""The process capability: text cleaning and the analyzer-backed operations.

One node type serves every processing operation (clean, tokenize, word frequency, sentiment, …).
The operation-specific parameters are validated at the executor boundary; the manifest declares the
shared seed shape, the operation/tokenize pre-run checks, and that the node emits per-operation
columns through its own hooks.
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
        id='process',
        kind='node',
        version='1.0.0',
        title_key='nodeType.process',
        category='process',
        order=5,
        description='Clean, tokenize or analyze a text column; emits per-operation columns.',
        when_to_use='After a crawl/upload when the rows need cleaning or one text/algorithm operation.',
    ),
    params=(
        ParamSpec(
            name='operation',
            type='string',
            default='clean',
            widget='select',
            enum=(
                'clean',
                'tokenize',
                'emotion',
                'tendency',
                'sentiment',
                'keyword',
                'cluster',
                'ner',
                'zero_shot',
                'qualitative_code',
                'content_analysis',
                'aggression',
                'bot',
                'anomaly',
                'correlation',
                'significance',
            ),
        ),
        ParamSpec(name='text_column', type='string', default='正文', widget='column'),
        ParamSpec(name='topic', type='string', default='', widget='text'),
        ParamSpec(name='live_export', type='boolean', default=False, widget='switch'),
        ParamSpec(name='format', type='string', default='csv', widget='text'),
    ),
    ports=Ports(
        rows='table',
        inputs=1,
        emit_columns='nodes.executors.process:emit_columns',
        read_columns='nodes.executors.process:read_columns',
    ),
    execution=Execution(handler='nodes.executors.process:run'),
    validators=('nodes.executors.process:validate_node',),
    ui=Ui(form='custom', custom_renderer='process'),
    ai=Ai(
        summary=(
            '处理 runs one operation over the upstream text column: cleaning, tokenize, word frequency, '
            'TF-IDF/TextRank, sentiment/emotion/tendency, NER, clustering, correlation and the qualitative '
            'coding operations. The operation selects both the result columns and the required inputs.'
        ),
        steps=(
            'Pick the operation; the panel shows only that operation’s fields.',
            'Pick the text column (正文 is the usual crawl column).',
            'For BERT operations choose one model, or several for the comparison table.',
        ),
        examples=(
            {'type': 'process', 'params': {'operation': 'clean', 'text_column': '正文', 'format': 'csv'}},
            {'type': 'process', 'params': {'operation': 'tokenize', 'text_column': '正文', 'output_mode': 'word_freq'}},
        ),
        failures=(
            'No operation: engine.process_no_op.',
            'Tokenize without a text column: engine.tokenize_no_column.',
            'An unknown operation/param value: the executor refuses with analysis.bad_option and the allowed values.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_process_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/process.md'),
)
