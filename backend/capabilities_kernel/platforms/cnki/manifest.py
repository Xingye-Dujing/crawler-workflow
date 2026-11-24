"""中国知网：关键词检索、勾选行并下载 RefWorks 导出。

One mode, because CNKI offers one useful question here: "search this topic and hand me the records".
The rows are the importer's normalized literature table, so they feed the Bibliometrics node exactly
like an uploaded export does.
"""

from dataclasses import replace

from capabilities_kernel.platform import Mode, platform_manifest
from capabilities_kernel.platforms._fields import ACCOUNT, KEYWORD, RECOLLECT, TARGET

MANIFEST = platform_manifest(
    'cnki',
    order=80,
    modes=(
        Mode(
            key='posts',
            label_key='settings.collectLiterature',
            handler='search',
            fields=(KEYWORD, replace(TARGET, default=50), ACCOUNT, RECOLLECT),
            note_key='settings.cnkiNote',
            # The result list is a document: the crawl types into it, ticks each page's 全选 (the site
            # accumulates across pages) and downloads the Refworks export — it never scrolls a feed.
            collects='dom_read',
        ),
    ),
    crawler='crawlers.platforms.cnki.crawler:CnkiCrawler',
    summary='中国知网：关键词检索，勾选结果并下载 RefWorks 导出，得到文献表。',
    when_to_use='文献计量分析的起点：用主题词把一批文献记录取回来。',
    when_not_to_use=('它不是通用网页采集；没有文献分析需求时用别的平台。',),
    # Measured 2026-10-30: a fresh headless *and* a fresh visible Chrome are both sent to
    # /verify/home (Tencent slider); the profile is what keeps the solved session.
    profile_recommended=True,
)
