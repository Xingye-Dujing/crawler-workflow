"""Take a random sample of rows, by count or fraction."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Writes, operator_manifest

MANIFEST = operator_manifest(
    'sample_rows',
    title_key='op.sample_rows',
    category='clean',
    order=130,
    summary='随机抽取 n 行或比例的样本（可固定随机种子）。',
    when_to_use='大表先抽样看效果，或做对照实验时取固定样本。',
    when_not_to_use=('要按条件挑行用 filter_rows。',),
    handler='services.analysis.ops.sample_rows:sample_rows',
    params=(
        ParamSpec(name='n', type='integer', default=None, minimum=1),
        ParamSpec(name='frac', type='number', default=None, minimum=0, maximum=1),
        ParamSpec(name='seed', type='integer', default=None),
    ),
    writes=Writes(mode='passthrough'),
)
