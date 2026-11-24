"""微信公众号：文章 URL 采集 —— 唯一不需要登录的平台。"""

from capabilities_kernel.platform import Field, Mode, platform_manifest
from capabilities_kernel.platforms._fields import INPUT_COLUMN, RECOLLECT

MANIFEST = platform_manifest(
    'wechat',
    order=40,
    modes=(
        Mode(
            key='posts',
            label_key='settings.articleUrls',
            # The article bodies are served anonymously by mp.weixin.qq.com (and wechat has never
            # been in ``CookieManager.PLATFORMS``): there is no login this crawl can be asked for.
            # Leaving the flag True made the pre-run gate buy a browser to test a session that does
            # not exist and then refuse a crawl that needs no cookie at all.
            needs_session=False,
            fields=(
                Field(
                    key='urls',
                    control='textarea',
                    label_key='settings.urls',
                    name_key='field.urls',
                    required=True,
                    hint_key='settings.urlsHint',
                    coerce='urls',
                    placeholder='https://mp.weixin.qq.com/s/...',
                    fed_by='input_column',
                ),
                INPUT_COLUMN,
                # An article URL already collected is skipped here too — the ledger is the source
                # path's, not a per-platform choice — so the way back has to be on this form as well.
                RECOLLECT,
            ),
            note_key='settings.wechatLimitsNote',
            action_key='settings.wechatLimitsBtn',
            action_js='explainWechatLimits',
            collects='page_per_row',
        ),
    ),
    crawler='crawlers.platforms.wechat.crawler:WechatCrawler',
    summary='微信公众号：粘贴文章链接，逐篇打开并保存正文。',
    when_to_use='已有公众号文章链接清单，需要正文语料时。',
    when_not_to_use=('它不搜索、不翻页、不需要登录；要发现文章请先用别的方式拿到链接。',),
)
