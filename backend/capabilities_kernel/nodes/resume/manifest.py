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
    ports=Ports(
        rows='table',
        inputs=0,
        opaque="the adopted table's columns belong to the earlier run's node, not to this canvas",
    ),
    execution=Execution(handler='nodes.executors.resume:run'),
    ui=Ui(form='custom', custom_renderer='resume'),
    ai=Ai(
        summary=(
            '断点续采 adopts rows an earlier run already stored. Blank ids mean “newest unfinished run of '
            'this workflow shape, fullest node”; a limit truncates the adopted table.'
        ),
        when_not_to_use=(
            'Not a repair: a source that can run again is cheaper than adopting an older result.',
            'Not for copying one node between canvases.',
        ),
        prerequisites=(
            'An earlier run of this workflow shape that stored rows.',
            'Optionally the run id and node id to adopt; blank means the automatic choice.',
        ),
        steps=(
            'Pick a resumable run and node, or leave both blank for the automatic choice.',
            'Optionally set a row limit.',
            'Wire the adopted rows into the rest of the chain.',
        ),
        examples=({'type': 'resume', 'params': {'resume_run_id': '', 'resume_node_id': '', 'resume_limit': 0}},),
        template={
            'type': 'resume',
            'params': {'resume_run_id': '', 'resume_node_id': '', 'resume_limit': 0},
        },
        failures=(
            'No resumable run: the executor logs resume.no_run and returns no rows.',
            'The picked node holds nothing and no node has rows: resume.empty.',
        ),
        acceptance=(
            "The node emits the adopted rows and the run shows them as this node's output.",
            'A run without stored rows reports resume.empty instead of zero rows.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_resume_manifest.py',)),
    docs=Docs(
        page='docs/capabilities/nodes/resume.md',
        skill='docs/capabilities/skills/nodes/resume.md',
    ),
)
