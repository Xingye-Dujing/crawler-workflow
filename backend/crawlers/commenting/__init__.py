"""The comment engine: one browser session, many articles, resumable per link.

Three files, three different kinds of thing:

* ``session.py`` — ``CommentSession``: the state that survives from one article to the next (the
  live driver, the log line, the pacing knob, the stop predicate) and the element reads every
  platform shares;
* ``walks.py`` — the registry: platform → the walk that reads that site, which is what
  ``CommentSession.walk`` dispatches through instead of a name built out of a string;
* ``protocol.py`` — the browser-free parts several platforms share: the OK/BLOCKED/DEAD verdicts,
  JSON/HTML/text normalisation and timestamp stamping.

The engine is deliberately not a ``Crawler``: it reads hundreds of pages per node, on a browser the
node handler owns and can have to stop mid-row, so it takes its own stop predicate and its own
cursor ledger. A platform's own DOM or endpoint knowledge — its walk, its in-page scripts, its
parsers — lives with that platform in ``crawlers/platforms/<id>/comments.py``, and nothing here
re-exports it: two names for one reader is how one of them falls behind.
"""
