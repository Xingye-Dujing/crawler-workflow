"""Rename one column, refusing a rename that erases a name."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'rename_columns',
    title_key='op.rename_columns',
    category='clean',
    order=90,
    summary='把一列改名为另一个名字（旧列 -> 新列）。',
    when_to_use='上游列名与下游图表/算子约定的列名不一致时对齐一次。',
    when_not_to_use=('要移动/挑选列的集合用 select_columns。',),
    handler='services.analysis.ops.rename_columns:rename_columns',
    params=(ParamSpec(name='mapping', type='object', default={}),),
    reads=Reads(mapping=True),
    writes=Writes(mode='unknown'),
    template_values={'mapping': {'正文': '文本'}},
)
