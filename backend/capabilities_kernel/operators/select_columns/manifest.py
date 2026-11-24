"""Keep only the named columns, in the order given."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMNS

MANIFEST = operator_manifest(
    'select_columns',
    title_key='op.select_columns',
    category='clean',
    order=80,
    summary='只保留列出的列（按此顺序），其余列丢弃。',
    when_to_use='导出或画图前把表收窄到需要的几列。',
    when_not_to_use=('要改列名用 rename_columns；要新增计算列用 column_calc。',),
    handler='services.analysis.ops.select_columns:select_columns',
    params=(ParamSpec(name='columns', type='array', default=[], widget='column'),),
    reads=Reads(some=('columns',)),
    writes=Writes(mode='select'),
    panel=(COLUMNS,),
)
