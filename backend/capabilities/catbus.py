"""The CatBus-only vocabulary: forms for the adapter's own parameters, plus its panel words.

CatBus's manifest declares parameter *names*; what each box looks like is this app's
declaration. The shared modes (posts/author/hot/comments) reuse the Selenium forms, so this
module holds only what exists solely on the second engine — and the platform/region words
for platforms no browser crawler covers.
"""

from capabilities.fields import AUTHOR, BACKEND_FIELDS, BOARD, COMMENT_LIMIT, KEYWORD, TARGET
from capabilities.model import Field

# ─── CatBus 独有模式的字段 ──────────────────────────────────────────────
# CatBus 清单只声明参数名（``room``/``folder``/``series``…），按钮长什么样是采析绘的事：
# 控件、标签、校验都在这里；服务端与面板读同一份。共享模式（posts/author/hot/comments）
# 复用 Selenium 的表单，不在这里重复声明。
_CATBUS_URLS = Field(
    key='urls',
    control='textarea',
    label_key='settings.urls',
    name_key='field.urls',
    required=True,
    coerce='urls',
    fed_by='input_column',
    placeholder='https://…',
    hint_key='settings.catbusUrlsHint',
)
_CATBUS_ROOM = Field(
    key='room', control='text', label_key='settings.catbusRoom', name_key='field.catbusRoom', required=True
)
_CATBUS_FOLDER = Field(
    key='folder', control='text', label_key='settings.catbusFolder', name_key='field.catbusFolder', required=True
)
_CATBUS_SERIES = Field(
    key='series', control='text', label_key='settings.catbusSeries', name_key='field.catbusSeries', required=True
)
_CATBUS_CONVERSATION = Field(
    key='conversation',
    control='text',
    label_key='settings.catbusConversation',
    name_key='field.catbusConversation',
    required=True,
)
_CATBUS_PRODUCT = Field(
    key='product',
    control='text',
    label_key='settings.catbusProduct',
    name_key='field.catbusProduct',
    required=True,
)
_CATBUS_COMMENT_ID = Field(
    key='comment_id',
    control='text',
    label_key='settings.catbusCommentId',
    name_key='field.catbusCommentId',
    required=True,
)
CATBUS_ACCOUNT = BACKEND_FIELDS[1]

#: 参数名 → 字段模板。清单里出现的参数都必须在这里有模板；没有就说明适配器加了新参数而
#: 采析绘还没有对应的框，模式会被拒绝而不是画一个填不了的输入。
CATBUS_FIELD_TEMPLATES = {
    'keyword': KEYWORD,
    'target_count': TARGET,
    'catbus_account': CATBUS_ACCOUNT,
    'author': AUTHOR,
    'urls': _CATBUS_URLS,
    'comment_limit': COMMENT_LIMIT,
    'board': BOARD,
    'room': _CATBUS_ROOM,
    'folder': _CATBUS_FOLDER,
    'series': _CATBUS_SERIES,
    'conversation': _CATBUS_CONVERSATION,
    'product': _CATBUS_PRODUCT,
    'comment_id': _CATBUS_COMMENT_ID,
}

#: CatBus 模式键 → 面板词。共享模式复用 Selenium 的词；独有模式各有自己的名字。
#: 拼出来的键是审计盲区（可达性扫描只问它看得见的键），所以这里逐个写全，并有契约测试
#: 用真实清单的每个模式键核对「有名字」。
CATBUS_MODE_LABELS = {
    'posts': 'settings.collectPosts',
    'author': 'settings.collectAuthor',
    'hot': 'settings.collectHot',
    'comments': 'settings.collectComments',
    'user.get': 'catbus.mode.userGet',
    'user.search': 'catbus.mode.userSearch',
    'user.followers': 'catbus.mode.userFollowers',
    'user.following': 'catbus.mode.userFollowing',
    'user.likes': 'catbus.mode.userLikes',
    'user.collects': 'catbus.mode.userCollects',
    'user.reposts': 'catbus.mode.userReposts',
    'item.get': 'catbus.mode.itemGet',
    'item.search': 'catbus.mode.itemSearch',
    'item.related': 'catbus.mode.itemRelated',
    'item.list': 'catbus.mode.itemList',
    'item.media': 'catbus.mode.itemMedia',
    'item.categories': 'catbus.mode.itemCategories',
    'comment.list': 'catbus.mode.commentList',
    'comment.replies': 'catbus.mode.commentReplies',
    'live.get': 'catbus.mode.liveGet',
    'live.list': 'catbus.mode.liveList',
    'live.search': 'catbus.mode.liveSearch',
    'live.categories': 'catbus.mode.liveCategories',
    'live.gifts': 'catbus.mode.liveGifts',
    'live.products': 'catbus.mode.liveProducts',
    'live.media': 'catbus.mode.liveMedia',
    'live.rank': 'catbus.mode.liveRank',
    'live.replays': 'catbus.mode.liveReplays',
    'keyword.hot': 'catbus.mode.keywordHot',
    'keyword.suggest': 'catbus.mode.keywordSuggest',
    'feed.list': 'catbus.mode.feedList',
    'feed.categories': 'catbus.mode.feedCategories',
    'folder.list': 'catbus.mode.folderList',
    'folder.items': 'catbus.mode.folderItems',
    'series.list': 'catbus.mode.seriesList',
    'series.items': 'catbus.mode.seriesItems',
    'history.list': 'catbus.mode.historyList',
    'topic.search': 'catbus.mode.topicSearch',
    'poi.search': 'catbus.mode.poiSearch',
    'notice.list': 'catbus.mode.noticeList',
    'product.get': 'catbus.mode.productGet',
    'danmaku.list': 'catbus.mode.danmakuList',
}

#: 只有 CatBus 能爬、采析绘没有 Selenium 版的平台，以及它们的词。
#: 平台是否真的出现、有哪些功能仍由适配器清单决定；这里只负责在清单不可用时也能
#: 把面板上的这一行画出来并说明「引擎不可用」，而不是让已保存的画布变成一个不存在的平台。
CATBUS_ONLY_PLATFORMS = {
    'kuaishou': 'platform.kuaishou',
    'tiktok': 'platform.tiktok',
    'jd': 'platform.jd',
    'taobao': 'platform.taobao',
    'xianyu': 'platform.xianyu',
}

#: 只有 CatBus 能爬的平台各自的内容来自哪里（网络分组，不是可用性）。
CATBUS_ONLY_REGIONS = {
    'kuaishou': 'cn',
    'tiktok': 'overseas',
    'jd': 'cn',
    'taobao': 'cn',
    'xianyu': 'cn',
}
