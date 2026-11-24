"""The login-state domain: named cookies, the device directories that carry them, and the verdict.

One directory because one question lives here — *does this machine have a usable session for this
platform and account?* — and its modules answer different parts of it. Three of them hold the pure
decisions, so a rule can be asked without a disk, a clock or a browser:

``naming``      a (platform, account) pair to its cookie filename and profile directory, and the
                account list's order — the folds ``cookies`` and ``profiles`` both ask for;
``verdict``     what a probe's facts mean, which words block a run, and the cache slot (scope,
                platform, account, profile mode) a verdict lives in;
``lanes``       one ``Lock`` per profile directory, so two crawls of one device serialise.

``cookies``     the named cookie jar (``data/cookies/<platform>@<account>.json``), built on ``naming``;
``flow``        the per-platform "where do I copy a cookie from" guide the panel renders;
``profiles``    the Chrome ``user-data-dir`` per account: layout, freshness, and the template's
                bookkeeping, with its concurrency lane delegated to ``lanes``;
``template``    who may build that pristine device directory, with the browser launcher injected;
``preflight``   the answer to "run now?" — probe each canvas's platforms, cache a ``verdict`` per entry,
                and never block a run on a probe that could not be read.

The HTTP surface (``/api/cookies/*``, ``/api/profiles/delete`` and the ``/api/browser/profiles*``
pair) lives in ``api/sessions.py`` with every other route; this package never imports Flask.

The edge worth keeping straight: ``crawlers.core.browser`` asks ``profiles`` for a device directory and
``profiles`` never asks anything back — the path, the lane and the freshness rules are answerable without
buying a browser, which is what lets a session question be asked at page load. ``template`` and
``preflight`` do reach into the crawler layer (the launcher is a browser operation; "does this mode need
a session" is a crawl fact), and they are the only two that do.
"""
