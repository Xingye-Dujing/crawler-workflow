"""Model agreement matrix: where several analyzers agree or disagree."""

from capabilities_kernel.chart import FAMILY_CONSOLE, chart_manifest
from capabilities_kernel.charts._fields import AGREEMENT_LABEL_FIELD, ID_FIELD, MODEL_FIELD

MANIFEST = chart_manifest(
    'model_agreement',
    order=120,
    family=FAMILY_CONSOLE,
    handler='services.charts.options.relations:build_model_agreement',
    summary='模型一致性矩阵：每个模型对每条数据给出的标签是否一致。',
    when_to_use='多个情感/倾向模型对同一份语料比较，找出分歧样本。',
    when_not_to_use=('只用一个模型时没有“一致性”可看。',),
    fields=(MODEL_FIELD, AGREEMENT_LABEL_FIELD, ID_FIELD),
    defaults=(('model_field', '模型'), ('id_field', '原行')),
    hint_key='hint.modelAgreement',
    echarts_only=True,
    latex_buildable=False,
)
