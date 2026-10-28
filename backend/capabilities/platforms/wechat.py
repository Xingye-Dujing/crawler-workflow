"""公众号: the article-URL crawl — the one platform with no login to ask about."""

from capabilities.fields import INPUT_COLUMN, RECOLLECT
from capabilities.model import Capability, Field, Mode

CAPABILITY = Capability(
    platform='wechat',
    modes=(
        Mode(
            key='posts',
            label_key='settings.articleUrls',
            # The article bodies are served anonymously by mp.weixin.qq.com (the crawler says
            # so, and wechat has never been in ``CookieManager.PLATFORMS``, so the panel holds no
            # row for it): there is no login this crawl can be asked for. Leaving the flag True
            # made the pre-run gate buy a browser to test a session that does not exist and then
            # refuse a crawl that needs no cookie at all.
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
                # An article URL already collected is skipped here too — the ledger is
                # the source path's, not a per-platform choice — so the way back has to
                # be on this form as well. It was missing because this mode is the one
                # that does not come from ``_posts_mode``, which is how a rule that
                # looks "shared" ends up holding for 26 of 27 forms; the matrix test
                # ``test_every_crawl_mode_offers_to_forget_what_it_deduped`` now walks
                # all of them instead of the helpers.
                RECOLLECT,
            ),
            note_key='settings.wechatLimitsNote',
            action_key='settings.wechatLimitsBtn',
            action_js='explainWechatLimits',
            collects='page_per_row',
        ),
    ),
)
