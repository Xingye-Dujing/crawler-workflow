"""The fuse capability: several source tables in, one canonical record table out.

Fusion reads the parents' DICT results (it needs to know which table a row came from), not the
flattened fan-in. It needs at least one entity role to build a graph from.
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
        id='fuse',
        kind='node',
        version='1.0.0',
        title_key='nodeType.fuse',
        category='biblio',
        order=11,
        description='Merge several source tables into ONE canonical bibliographic record table.',
        when_to_use='When CNKI/platform tables from different sources should become one record set.',
    ),
    params=(
        ParamSpec(name='entity_columns', type='string', default='关键词,话题,主题,主题词,标签', widget='text'),
        ParamSpec(name='year_columns', type='string', default='年份,发布时间,发表日期,日期', widget='text'),
        ParamSpec(name='title_columns', type='string', default='题名,标题,内容,正文', widget='text'),
        ParamSpec(name='author_columns', type='string', default='作者,用户名,昵称,发布者', widget='text'),
        ParamSpec(name='affiliation_columns', type='string', default='作者单位,机构', widget='text'),
        ParamSpec(name='text_columns', type='string', default='摘要,正文,内容', widget='text'),
        ParamSpec(name='reference_columns', type='string', default='参考文献,引文', widget='text'),
        ParamSpec(name='source_columns', type='string', default='平台,来源', widget='text'),
        ParamSpec(name='source_labels', type='string', default='', widget='text'),
        ParamSpec(name='keep_undated', type='boolean', default=True, widget='switch'),
        ParamSpec(name='export_files', type='boolean', default=False, widget='switch'),
    ),
    ports=Ports(
        rows='table',
        inputs=-1,
        emit_columns='nodes.executors.fuse:emit_columns',
        read_columns='nodes.executors.fuse:read_columns',
    ),
    execution=Execution(handler='nodes.executors.fuse:run'),
    rules=(Rule(kind='upstream_required', code='fuse.no_input', message_key='fuse.no_input'),),
    validators=('nodes.executors.fuse:validate_node',),
    ui=Ui(form='custom', custom_renderer='fuse'),
    ai=Ai(
        summary=(
            '文献融合 merges several source tables into one canonical record table: each role (entity, year, '
            'title, author, affiliation, text, reference, source) declares candidate column names, and the '
            'first candidate a source really has answers the role.'
        ),
        steps=(
            'Wire every source table in.',
            'Keep or edit the candidate column lists per role; at least the entity role must find a column.',
            'Choose whether undated records are kept and whether per-source files are exported.',
        ),
        examples=(
            {
                'type': 'fuse',
                'params': {
                    'entity_columns': '关键词,话题,主题,主题词,标签',
                    'title_columns': '题名,标题,内容,正文',
                    'keep_undated': True,
                },
            },
        ),
        failures=(
            'No input table: fuse.no_input.',
            'No entity candidate found: fuse.needs_entity names the node.',
            'Differing source columns are normalized per role; a missing role is left empty, never guessed.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_fuse_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/fuse.md'),
)
