"""The parameters a freshly created node starts with, per node type.

One table for the whole product: the canvas seeds a new node from it, ``GET /api/node-types``
serves it, and ``tests/unit/analysis/test_node_plugins`` pins it against the catalogue. ``source`` has no
entry on purpose — its defaults depend on the crawl matrix the browser has just fetched (platform,
engine, mode), so the canvas derives them from that matrix instead of freezing one shape here.
"""

from services.biblio.schema import DEFAULTS as BIBLIO_DEFAULTS

#: Which types have static defaults. ``source`` and ``reusable`` are the documented exceptions:
#: the first is capability-shaped, the second carries a template snapshot chosen at creation.
NODE_DEFAULTS: dict[str, dict] = {
    'name': {'workflow_name': '', 'layout_order': ''},
    'upload': {'dataset_id': '', 'dataset_name': '', 'row_count': ''},
    'accumulate': {'lineage_name': '', 'identity': 'row', 'key_columns': ''},
    'process': {'operation': 'clean', 'text_column': '正文', 'topic': '', 'live_export': False, 'format': 'csv'},
    'analysis': {
        'operation': 'drop_null',
        'columns': '',
        'column': '',
        'value': '',
        'op': 'eq',
        'dtype': 'str',
        'rename_from': '',
        'rename_to': '',
    },
    'biblio': dict(BIBLIO_DEFAULTS),
    'visualize': {
        'chart_type': 'bar',
        'x_field': '',
        'y_field': '',
        'value_field': '',
        'agg': 'sum',
        'engine': 'echarts',
        'title': '',
        'tokenize': False,
        'emit_latex': True,
        'emit_latex_table': True,
    },
    'fuse': {
        'entity_columns': '关键词,话题,主题,主题词,标签',
        'year_columns': '年份,发布时间,发表日期,日期',
        'title_columns': '题名,标题,内容,正文',
        'author_columns': '作者,用户名,昵称,发布者',
        'affiliation_columns': '作者单位,机构',
        'text_columns': '摘要,正文,内容',
        'reference_columns': '参考文献,引文',
        'source_columns': '平台,来源',
        'source_labels': '',
        'keep_undated': True,
        'export_files': False,
    },
    'tokenize': {'text_column': '', 'top_n': '', 'output_mode': 'word_freq'},
    'resume': {'resume_run_id': '', 'resume_node_id': '', 'resume_limit': 0},
    'comment': {
        'urls': '',
        'comment_limit': 0,
        'part_size': 50,
        'per_article_file': True,
        'keep_parts': False,
        'recrawl': False,
        'format': 'csv',
    },
    'compile': {},
    'output': {'operation': 'save', 'format': 'csv', 'filename': 'export.csv'},
}

#: Types whose defaults are derived where the facts live, not frozen here. The API says so in
#: ``defaultsFrom`` so the client knows to ask its own source of truth.
DYNAMIC_DEFAULTS = {'source': 'capabilities'}
