"""The upload capability: publish a stored dataset as ordinary rows.

The file is looked up by id, then by name plus row count, so re-uploading after a lost row hands
back something usable. A missing dataset is a named refusal, never an empty table.
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
        id='upload',
        kind='node',
        version='1.0.0',
        title_key='nodeType.upload',
        category='data',
        order=2,
        description='Publish a stored dataset (upload/paste/import) as rows for downstream nodes.',
        when_to_use='When the corpus is a file rather than a crawl: the one place a file enters a workflow.',
    ),
    params=(
        ParamSpec(name='dataset_id', type='string', default='', required=True, widget='dataset'),
        ParamSpec(name='dataset_name', type='string', default='', widget='text'),
        ParamSpec(name='row_count', type='string', default='', widget='text'),
    ),
    ports=Ports(rows='table', inputs=0, emit_columns='nodes.executors.upload:emit_columns'),
    execution=Execution(handler='nodes.executors.upload:run', quiet=True),
    rules=(
        Rule(
            kind='required_param',
            code='engine.upload_no_file',
            message_key='engine.upload_no_file',
            param='dataset_id',
        ),
    ),
    ui=Ui(form='custom', custom_renderer='upload'),
    ai=Ai(
        summary=(
            '文件上传 turns one stored dataset into the same row table a crawl produces. Downstream nodes '
            'never know the difference; the dataset id is the binding.'
        ),
        when_not_to_use=(
            'A crawl belongs on node.source; a file outside the dataset store belongs on workspace_import first.',
        ),
        prerequisites=('A stored dataset id (upload, paste or import in the data panel).',),
        steps=(
            'Upload or paste a file in the data panel and note its dataset id.',
            'Create 文件上传 and pick the dataset.',
            'Wire it into 清洗/分词/分析 as if it were a crawl.',
        ),
        examples=(
            {'type': 'upload', 'params': {'dataset_id': 'ds_123', 'dataset_name': 'comments.csv', 'row_count': ''}},
        ),
        template={
            'type': 'upload',
            'params': {'dataset_id': 'ds_example', 'dataset_name': 'comments.csv'},
        },
        failures=(
            'No dataset_id: refused with engine.upload_no_file before the run.',
            'The dataset was deleted and no name/row-count replacement exists: the executor refuses '
            'instead of returning [].',
        ),
        acceptance=(
            'The node emits as many rows as the dataset holds.',
            'A missing dataset settles with a named refusal, not an empty table.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_upload_manifest.py',)),
    docs=Docs(
        page='docs/capabilities/nodes/upload.md',
        skill='docs/capabilities/skills/nodes/upload.md',
    ),
)
