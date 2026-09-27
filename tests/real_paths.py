"""The one answer to "where is the session the user really saved, and does it exist".

Every live tier needs these two facts and none of them may be re-derived per file:
:mod:`tests.conftest` redirects ``Config.COOKIE_DIR`` into a throwaway root *for every tier*,
which is right for the fast suites and would mean "nobody has a cookie" in a live run — a
run-level case would then crawl anonymous and read the login wall as a code failure. So the
real directory is named here, once, by absolute path, and every live file imports it.

The "does it exist" question is answered by the product's own
:class:`services.cookie_manager.CookieManager` rather than by a re-implementation of the file
format: that is what keeps a named-account jar (``zhihu@work_cookies.json``) understood the same
way in the tier and in the panel. AGENTS states the rule this file exists to honour — a second
list, or a second opinion about one storage path, is the thing that drifts.

``backend/`` is already on ``sys.path`` by the time any test module imports this one: the root
conftest puts it there at its own import, which is also how :mod:`run_wait` and
:mod:`live_run_harness` resolve their imports.
"""

from pathlib import Path

from services.cookie_manager import CookieManager

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The jar directory the user's own crawls and the cookie panel read and write.
COOKIE_DIR = REPO_ROOT / 'data' / 'cookies'

#: Built on first ask, never at import. ``CookieManager.__init__`` calls ``os.makedirs``, and
#: a module-level instance would mean *collecting* the test suite creates ``data/cookies/`` in
#: a fresh checkout — a directory the isolation guard does not watch (it fingerprints files), so
#: the write would be silent. Answering the question must not be a write.
_JAR: CookieManager | None = None


def _jar() -> CookieManager:
    global _JAR
    if _JAR is None:
        _JAR = CookieManager(str(COOKIE_DIR))
    return _JAR


def has_cookie(platform: str, account: str = '') -> bool:
    """Does the real jar hold a saved session for *platform*?

    Two conditions, both taken from the product: the panel recognises the platform at all
    (``wechat`` has no cookie row by design, so it never "has a session"), and the file holds a
    non-empty list. An empty JSON array is not a login — a crawl from it would be anonymous
    while looking configured.

    The account is part of the question, not a wildcard: ``account=''`` asks about the jar a
    crawl without an ``account`` field actually loads. A tier that crawls as a named login must
    ask with that name (``CookieManager.account_files`` lists what exists), or it would call a
    platform configured on a session it is never going to read.
    """
    jar = _jar()
    return bool(jar.exists(platform, account)) and bool(jar.load(platform, account))
