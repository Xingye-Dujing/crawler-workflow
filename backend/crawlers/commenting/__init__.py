"""The comment engine: one browser session, many articles, resumable per link.

``session.py`` holds ``CommentSession`` — the state that survives from one article to the next (the
scroll boxes, the per-thread cursors, the OK/BLOCKED/DEAD verdicts) — and the platform walks that
read them. ``protocol.py`` holds the browser-free parts several platforms share: the verdict
constants, JSON/HTML/text normalisation and timestamp stamping.

The engine is deliberately not a ``Crawler``: it reads hundreds of pages per node, on a browser the
node handler owns and can have to stop mid-row, so it takes its own stop predicate and its own
cursor ledger. The parsers each platform uses live with that platform, and are re-exported here for
callers that name them from the engine.
"""
