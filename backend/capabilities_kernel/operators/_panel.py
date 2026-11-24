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

#: The topic family's shared boxes. The topic count, the method and its encoder are one vocabulary:
#: five steps ask the same three questions, and the per-step label differences ride on the boxes
#: that really differ (which value the ranking box writes).
N_TOPICS = PanelField('n_topics', 'n_topics', 'settings.nTopics', control='number', default=5)
TOPIC_METHOD = PanelField(
    'topic_method',
    'method',
    'settings.topicMethod',
    control='select',
    default='auto',
    options=(
        ('auto', 'settings.topicMethodAuto'),
        ('embedding', 'settings.topicMethodEmbed'),
        ('lda', 'settings.topicMethodLda'),
    ),
)
EMBEDDING_MODEL = PanelField(
    'embedding_model', 'embedding_model', 'settings.embeddingModel', default='BAAI/bge-small-zh-v1.5'
)
TOPIC_MAX_FEATURES = PanelField(
    'topic_max_features',
    'max_features',
    'settings.topicMaxFeatures',
    control='number',
    default=2000,
)
