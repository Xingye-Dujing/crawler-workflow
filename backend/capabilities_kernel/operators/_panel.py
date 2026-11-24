"""The analysis panel's shared boxes, declared once for every operator that shows them."""

from capabilities_kernel.operator import PanelField

#: The comma-separated column list several cleaning steps ask for (blank = every column).
COLUMNS = PanelField(
    'columns',
    'columns',
    'settings.columns',
    placeholder='col1, col2 (empty = all)',
)

#: One column name.
COLUMN = PanelField('column', 'column', 'settings.column')

#: The sentence encoder both model-backed similarity steps name.
MODEL = PanelField('model', 'model', 'settings.bertModel', default='BAAI/bge-small-zh-v1.5')
