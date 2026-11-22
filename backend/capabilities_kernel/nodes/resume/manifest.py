"""The resume capability: adopt a stored node output from an earlier run.

The original source may be logged out, blocked or expensive; its rows are already in runs.db. A
blank run/node lets the executor pick the newest unfinished run of this canvas's shape and its
fullest node — the same fallback the 继续 banner uses.
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
        id='resume',
        kind='node',
        version='1.0.0',
        title_key='nodeType.resume',
        category='data',
        order=3,
        description='Adopt a stored node output from an earlier run as this node’s rows.',
        when_to_use='When the original source cannot run again but its rows are already paid for.',
    ),
    params=(
        ParamSpec(name='resume_run_id', type='string', default='', widget='text'),
        ParamSpec(name='resume_node_id', type='string', default='', widget='text'),
        ParamSpec(name='resume_limit', type='integer', default=0, minimum=0, widget='number'),
    ),
    ports=Ports(rows='table', inputs=0),
    execution=Execution(handler='nodes.executors.resume:run'),
    ui=Ui(form='custom', custom_renderer='resume'),
    ai=Ai(
        summary=(
            '断点续采 adopts rows an earlier run already stored. Blank ids mean “newest unfinished run of '
            'this workflow shape, fullest node”; a limit truncates the adopted table.'
        ),
        steps=(
            'Pick a resumable run and node, or leave both blank for the automatic choice.',
            'Optionally set a row limit.',
            'Wire the adopted rows into the rest of the chain.',
        ),
        examples=({'type': 'resume', 'params': {'resume_run_id': '', 'resume_node_id': '', 'resume_limit': 0}},),
        failures=(
            'No resumable run: the executor logs resume.no_run and returns no rows.',
            'The picked node holds nothing and no node has rows: resume.empty.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_resume_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/resume.md'),
)
