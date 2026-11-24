"""The field boxes a chart can ask for, declared once for the whole chart family.

A bar's x and a pie's x are the same box, so this vocabulary lives here and each chart manifest
picks the boxes it reads. The form labels are the ones the panel has always shown, carried by the
declaration instead of a JavaScript map.
"""

from capabilities_kernel.chart import FieldSpec

X_CATEGORY = FieldSpec(
    'x_field',
    'category',
    label_key='settings.xField',
    placeholder_key='settings.fieldPlaceholderCategory',
)
X_CATEGORY2 = FieldSpec(
    'x_field',
    'category2',
    label_key='settings.xFieldCat1',
    placeholder_key='settings.fieldPlaceholderCategory',
)
X_SOURCE = FieldSpec(
    'x_field',
    'source',
    label_key='settings.sourceField',
    placeholder_key='settings.fieldPlaceholderSource',
)
X_TEXT = FieldSpec(
    'x_field',
    'text',
    label_key='settings.textField',
    placeholder_key='settings.fieldPlaceholderText',
)
X_GEO = FieldSpec(
    'x_field',
    'geo',
    label_key='settings.regionField',
    placeholder_key='settings.fieldPlaceholderGeo',
)
X_COORDINATE = FieldSpec(
    'x_field',
    'coordinate',
    label_key='settings.xField',
    placeholder_key='settings.fieldPlaceholderNumeric',
)
X_VALUE = FieldSpec(
    'x_field',
    'value',
    label_key='settings.xField',
    placeholder_key='settings.fieldPlaceholderNumeric',
)
X_OPTIONAL = FieldSpec(
    'x_field',
    'category',
    required=False,
    label_key='settings.xField',
    placeholder_key='settings.fieldPlaceholderCategory',
    # A box plot's single numeric column lives in x with no y; naming a y makes this the grouping
    # axis, which the builder refuses to run without.
    required_when='y_field',
)
Y_VALUE = FieldSpec(
    'y_field',
    'value',
    required=False,
    label_key='settings.yField',
    placeholder_key='settings.fieldPlaceholderValue',
    control='agg',
)
Y_VALUE_REQUIRED = FieldSpec(
    'y_field',
    'value',
    label_key='settings.yField',
    placeholder_key='settings.fieldPlaceholderNumeric',
)
Y_COORDINATE = FieldSpec(
    'y_field',
    'coordinate',
    label_key='settings.yField',
    placeholder_key='settings.fieldPlaceholderNumeric',
)
Y_CATEGORY2 = FieldSpec(
    'y_field',
    'category2',
    label_key='settings.yFieldCat2',
    placeholder_key='settings.fieldPlaceholderCategory',
)
Y_TARGET = FieldSpec(
    'y_field',
    'target',
    label_key='settings.targetField',
    placeholder_key='settings.fieldPlaceholderTarget',
)
Y2_VALUE = FieldSpec(
    'y2_field',
    'value',
    label_key='settings.y2Field',
    placeholder_key='settings.fieldPlaceholderRightAxis',
    control='agg2',
)
VALUE_FIELD = FieldSpec(
    'value_field',
    'value',
    required=False,
    label_key='settings.valueField',
    placeholder_key='settings.fieldPlaceholderWeight',
)
#: The same box where the value is AGGREGATED per category/cell (heatmap, sankey, network): the
#: aggregation control belongs to the column it reduces, so it rides on the field.
VALUE_FIELD_AGG = FieldSpec(
    'value_field',
    'value',
    required=False,
    label_key='settings.valueField',
    placeholder_key='settings.fieldPlaceholderWeight',
    control='agg',
)
LABEL_FIELD = FieldSpec('label_field', 'label', required=False, label_key='settings.labelField')
STACK_FIELDS = FieldSpec(
    'stack_fields',
    'list',
    label_key='settings.stackFields',
    placeholder='积极占比, 中性占比, 消极占比',
    hint_key='hint.stackFields',
)
#: The agreement matrix reads a tidy multi-model table by its own columns. The two the analysis
#: step writes carry defaults, so a fresh chart needs no typing; a renamed column refuses by name.
MODEL_FIELD = FieldSpec('model_field', 'column', label_key='settings.modelField')
AGREEMENT_LABEL_FIELD = FieldSpec(
    'agreement_label_field',
    'column',
    required=False,
    label_key='settings.agreementLabelField',
    placeholder='emotion / tendency / sentiment',
)
ID_FIELD = FieldSpec('id_field', 'column', label_key='settings.idField')
