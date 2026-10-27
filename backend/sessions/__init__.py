"""The login-state domain: named cookies, the device directories that carry them, and the verdict.

One directory because one question lives here — *does this machine have a usable session for this
platform and account?* — and five modules answer different parts of it:

``cookies``     the named cookie jar (``data/cookies/<platform>@<account>.json``) and its folding rules;
``flow``        the per-platform "where do I copy a cookie from" guide the panel renders;
``profiles``    the Chrome ``user-data-dir`` per account: layout, freshness, the lock that keeps two
                crawls off one device, and the template's bookkeeping;
``template``    who may build that pristine device directory, with the browser launcher injected;
``preflight``   the answer to "run now?" — probe each canvas's platforms, cache a verdict per entry,
                and never block a run on a probe that could not be read;
``routes``      the panel's HTTP surface (``/api/cookies/*``, ``/api/profiles/delete`` and the
                ``/api/browser/profiles*`` pair), because the jar, the device and the verbs that
                move them are one question.

The edge worth keeping straight: ``crawlers.core.browser`` asks ``profiles`` for a device directory and
``profiles`` never asks anything back — the path, the lock and the freshness rules are answerable without
buying a browser, which is what lets a session question be asked at page load. ``template`` and
``preflight`` do reach into the crawler layer (the launcher is a browser operation; "does this mode need
a session" is a crawl fact), and they are the only two that do.
"""
