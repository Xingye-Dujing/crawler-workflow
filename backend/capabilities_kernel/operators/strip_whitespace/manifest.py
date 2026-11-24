"""Strip leading/trailing whitespace in the named columns."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMNS

MANIFEST = operator_manifest(
    'strip_whitespace',
    title_key='op.strip_whitespace',
    category='clean',
    order=100,
    summary='去掉所选列文本首尾的空白（含全角空格），行数不变。',
    when_to_use='采集文本带换行/缩进，导致去重、分词或图表标签不一致时。',
    when_not_to_use=('要改数据类型用 convert_type。',),
    handler='services.analysis.ops.strip_whitespace:strip_whitespace',
    params=(ParamSpec(name='columns', type='array', default=[], widget='column'),),
    reads=Reads(some=('columns',)),
    writes=Writes(mode='passthrough'),
    panel=(COLUMNS,),
)
