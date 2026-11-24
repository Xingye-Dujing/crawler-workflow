"""Build the author-to-author reply graph of a comment table."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'reply_graph',
    title_key='op.reply_graph',
    category='social',
    order=270,
    summary='按评论者、楼层与父楼层还原“谁回复谁”的关系，输出带权重的边表。',
    when_to_use='要画互动网络、找关键传播者或社区结构时。',
    when_not_to_use=('表里没有楼层/父楼层字段时无法还原回复关系，请先确认采集列。',),
    handler='services.analysis.ops.reply_graph:reply_graph',
    params=(
        ParamSpec(name='author_col', type='string', default='评论者', widget='column'),
        ParamSpec(name='floor_col', type='string', default='楼层', widget='column'),
        ParamSpec(name='parent_floor_col', type='string', default='父楼层', widget='column'),
        ParamSpec(name='article_col', type='string', default='文章URL', widget='column'),
    ),
    reads=Reads(one=('author_col', 'floor_col', 'parent_floor_col')),
    writes=Writes(mode='replace', columns=('src_author', 'dst_author', 'weight')),
    panel=(
        PanelField('reply_author_col', 'author_col', 'settings.replyAuthorColumn', default='评论者'),
        PanelField('reply_floor_col', 'floor_col', 'settings.replyFloorColumn', default='楼层'),
        PanelField('reply_parent_col', 'parent_floor_col', 'settings.replyParentColumn', default='父楼层'),
        PanelField(
            'reply_article_col',
            'article_col',
            'settings.replyArticleColumn',
            default='文章URL',
            hint_key='settings.replyGraphHint',
        ),
    ),
    labels=(
        ('author_col', 'settings.replyAuthorColumn'),
        ('floor_col', 'settings.replyFloorColumn'),
        ('parent_floor_col', 'settings.replyParentColumn'),
        ('article_col', 'settings.replyArticleColumn'),
    ),
)
