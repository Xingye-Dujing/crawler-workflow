"""The message catalogue, by domain.

``backend/i18n.py`` is the only surface anything imports; this package is its data. A message
belongs to the module that owns the question it answers, so a new feature adds a line in one
small file instead of a 4,600-line one — and a missing word can be audited per domain.

``MODULES`` is ordered: the merge walks it, so a key claimed by two domains is refused at
import time rather than silently kept from whichever module came last.
"""

from i18n_catalog import accounts, analysis, api, biblio, charts, collect, cookie, crawl, run, sched, settings

MODULES = (
    crawl,
    collect,
    cookie,
    sched,
    run,
    analysis,
    biblio,
    charts,
    api,
    settings,
    accounts,
)
