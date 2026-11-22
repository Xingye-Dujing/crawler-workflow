"""The verify capability: compare a promised post list with a crawl result.

It reads exactly two data tables — the list (链接 + 评论数) and the result (文章URL) — and emits a
report table with the status, expected/actual/gap counts and completion. ``gaps`` is the actionable
feed; ``all`` is the full audit.
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
        id='verify',
        kind='node',
        version='1.0.0',
        title_key='nodeType.verify',
        category='process',
        order=10,
        description='Compare a promised list with a crawl result and report missing/short items.',
        when_to_use='After a comment crawl, when the list says how many comments each post should have.',
    ),
    params=(
        ParamSpec(name='input_key_column', type='string', default='链接', required=True, widget='column'),
        ParamSpec(name='result_key_column', type='string', default='文章URL', required=True, widget='column'),
        ParamSpec(name='expected_count_column', type='string', default='评论数', widget='column'),
        ParamSpec(name='match_mode', type='string', default='url', widget='select'),
        ParamSpec(name='tolerance', type='integer', default=0, minimum=0, widget='number'),
        ParamSpec(name='per_link_limit', type='string', default='', widget='text'),
        ParamSpec(name='output_mode', type='string', default='gaps', enum=('gaps', 'all'), widget='select'),
        ParamSpec(name='swap_tables', type='boolean', default=False, widget='switch'),
        ParamSpec(name='ignore_case', type='boolean', default=False, widget='switch'),
    ),
    ports=Ports(rows='table', inputs=2, read_columns='nodes.executors.verify:read_columns'),
    execution=Execution(handler='nodes.executors.verify:run'),
    validators=('nodes.executors.verify:validate_node',),
    ui=Ui(),
    ai=Ai(
        summary=(
            '采集校验 reads two tables: the promised list and the crawled result. It matches keys, compares the '
            'expected count (评论数) with the actual rows, and emits 采集状态/期望条数/实际条数/缺失条数/完成度.'
        ),
        steps=(
            'Wire the promised list in first and the crawl result in second (or set swap_tables).',
            'Name the list key, the result key and the expected-count column.',
            'Choose gaps for the re-crawl feed or all for the audit.',
        ),
        examples=(
            {
                'type': 'verify',
                'params': {
                    'input_key_column': '链接',
                    'result_key_column': '文章URL',
                    'expected_count_column': '评论数',
                    'output_mode': 'gaps',
                },
            },
        ),
        failures=(
            'Not exactly two data parents: engine.verify_two_inputs.',
            'Missing list/result key: engine.verify_need_list_col/result_col.',
            'A key column absent from its table: the executor names the column.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_verify_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/verify.md'),
)
