"""The tokenize capability: the P1 pilot for the manifest seam.

Every fact the server needs about 分词 is here. ``nodes.catalog``, ``nodes.defaults``,
``services.validation.engine`` and the lineage view read this declaration; the executor keeps the
behavior (jieba segmentation) and the per-mode column table it alone can know.
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
        id='tokenize',
        kind='node',
        version='1.0.0',
        title_key='nodeType.tokenize',
        category='process',
        # Between analysis and biblio: the slot this type occupied in the hand-written catalogue.
        order=8,
        description='Segment a text column into words and emit word frequencies or one word per row.',
        when_to_use=(
            'When a later step needs word frequencies or one word per row: word cloud, bar chart, '
            'corpus statistics. Use the process node for cleaning-only passes.'
        ),
    ),
    params=(
        ParamSpec(
            name='text_column',
            type='string',
            default='',
            required=True,
            widget='column',
            placeholder='正文',
        ),
        ParamSpec(
            name='top_n',
            type='string',
            default='',
            widget='text',
            placeholder='120',
        ),
        ParamSpec(
            name='output_mode',
            type='string',
            default='word_freq',
            enum=('word_freq', 'words_only', 'csv_line'),
            widget='select',
        ),
    ),
    ports=Ports(
        rows='table',
        inputs=1,
        emit_columns='nodes.executors.tokenize:emit_columns',
        read_columns='nodes.executors.tokenize:read_columns',
    ),
    execution=Execution(handler='nodes.executors.tokenize:run'),
    rules=(
        Rule(
            kind='required_param',
            code='engine.tokenize_no_column',
            message_key='engine.tokenize_no_column',
            param='text_column',
        ),
    ),
    ui=Ui(),
    ai=Ai(
        summary=(
            '分词 turns one text column into a word table: word/frequency pairs, bare words, or a single '
            'space-joined line. The upstream rows are the corpus; the node never reads a file itself.'
        ),
        steps=(
            'Wire a node that produces text rows into 分词.',
            'Pick the text column and an output mode.',
            'For word_freq, optionally cap the table with top_n (blank means the executor default).',
        ),
        examples=(
            {
                'type': 'tokenize',
                'params': {'text_column': '正文', 'top_n': '120', 'output_mode': 'word_freq'},
            },
        ),
        failures=(
            'No text column configured: refuses before the run with engine.tokenize_no_column.',
            'The column is absent from the upstream table: the executor names the column and the columns it saw.',
            'No upstream rows: the executor refuses instead of settling an empty table DONE.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_tokenize_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/tokenize.md'),
)
