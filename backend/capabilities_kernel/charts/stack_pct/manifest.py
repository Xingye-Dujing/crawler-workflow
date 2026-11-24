"""100% stacked bar: each category split into several share columns."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import STACK_FIELDS, X_CATEGORY

MANIFEST = chart_manifest(
    'stack_pct',
    order=40,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.series:build_stack_pct',
    summary='百分比堆叠柱：每个类别的几列占比堆成 100%，看构成变化。',
    when_to_use='正/中/负情感占比随时间或阶段的变化。',
    when_not_to_use=('没有被拆成几列占比时用普通柱状图；要看总量而不是构成时不适合。',),
    fields=(X_CATEGORY, STACK_FIELDS),
)
