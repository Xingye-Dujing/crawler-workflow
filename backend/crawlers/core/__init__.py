"""The machinery every crawler shares, and no site's facts.

``crawler.py`` is the abstract ``Crawler``: browser session, cookie plant, navigation and arrival
judgement, the row sink / cursor / watermark contract, the throttle, and the end-reason gate that
refuses to let a short table settle clean. ``video.py`` adds the one shape two platforms share
(Bilibili and Douyin both emit one row per video).

Nothing here knows what a 微博 or a 视频 is: selectors, endpoints, column names and per-site
verdicts live in ``crawlers/platforms/<id>/``, and what a platform *offers* — its modes and fields —
is declared in ``capabilities/``, which must stay importable without selenium. That separation is
what keeps a DAG parse from loading a browser (``tests/unit/test_boot_import_budget.py``).
"""
