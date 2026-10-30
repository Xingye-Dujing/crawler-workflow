"""中国知网: keyword search, row selection and the site's own RefWorks export.

One mode, because CNKI offers one useful question here: "search this topic and
hand me the records". The rows are the importer's normalized literature table, so
they feed the Bibliometrics node exactly like an uploaded export does.
"""

from dataclasses import replace

from capabilities.fields import ACCOUNT, KEYWORD, RECOLLECT, TARGET
from capabilities.model import Capability, Mode

CAPABILITY = Capability(
    platform='cnki',
    # Measured 2026-10-30: a fresh headless *and* a fresh visible Chrome are both
    # sent to /verify/home (Tencent slider). The profile is what keeps the solved
    # session, so a throwaway browser pays the challenge on every crawl.
    profile_recommended=True,
    modes=(
        Mode(
            key='posts',
            label_key='settings.collectLiterature',
            handler='search',
            fields=(KEYWORD, replace(TARGET, default=50), ACCOUNT, RECOLLECT),
            note_key='settings.cnkiNote',
            # The result list is a document: the crawl types into it, ticks each
            # page's 全选 (the site accumulates across pages) and downloads the
            # Refworks export — it never scrolls a feed, and a visible window shows
            # the search page doing exactly that.
            collects='dom_read',
        ),
    ),
)
