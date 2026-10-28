"""The machinery every crawler shares, and no site's facts.

Four files, with a direction between them:

``browser.py`` is the lowest — how one Chrome is assembled on THIS machine (switches, fingerprint
masks, window metrics) and how its profile directory is claimed. It imports no driver-owning
session and no crawl state, which is what lets :func:`crawlers.core.crawler.warm_profile_dir` build
a browser to produce a *directory* without pretending to crawl a site.
``faults.py`` names the four outcomes that are not about a site — the user's 停止, a driver killed by
PID, a profile nobody can take, a page that never arrived — and imports nothing but the message
catalogue, so the CatBus backend, an analyzer and the live tier can all refuse without loading
selenium.
``crawler.py`` is the crawl contract that reads those two: navigation and arrival judgement, the
cookie plant, the row sink / cursor / watermark, and the end-reason gate that refuses to let a short
table settle clean. Pacing left it for ``crawlers/engine/pacing.py``, being site-independent.
``video.py`` adds the one shape two platforms share (Bilibili and Douyin both emit one row per
video).

Nothing here knows what a 微博 or a 视频 is: selectors, endpoints, column names and per-site
verdicts live in ``crawlers/platforms/<id>/``, and what a platform *offers* — its modes and fields —
is declared in ``capabilities/``, which must stay importable without selenium. That separation is
what keeps a DAG parse from loading a browser (``tests/unit/foundation/test_boot_import_budget.py``).
"""
