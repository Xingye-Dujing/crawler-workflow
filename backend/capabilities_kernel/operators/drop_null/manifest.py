"""Drop rows that carry empty cells in the named columns."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMNS

MANIFEST = operator_manifest(
    'drop_null',
    title_key='op.drop_null',
    category='clean',
    order=10,
    summary='删除所选列中含空值的行（任一为空或全部为空）。',
    when_to_use='在分析前去掉缺字段的行，或只保留每一列都填写完整的行。',
    when_not_to_use=('只想填补空值而不是删除行时用 fill_null；要按列去重用 drop_duplicates。',),
    handler='services.analysis.ops.drop_null:drop_null',
    params=(
        ParamSpec(name='columns', type='array', default=[], widget='column'),
        ParamSpec(name='how', type='string', default='any', enum=('any', 'all'), widget='select'),
    ),
    reads=Reads(some=('columns',)),
    writes=Writes(mode='passthrough'),
    panel=(
        COLUMNS,
        PanelField(
            'how',
            'how',
            'settings.dropHow',
            control='select',
            default='any',
            options=(('any', 'settings.dropHowAny'), ('all', 'settings.dropHowAll')),
        ),
    ),
    labels=(('how', 'settings.dropHow'),),
)
