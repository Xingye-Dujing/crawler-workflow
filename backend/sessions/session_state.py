"""The one answer to "does this account hold a session at all?".

It lives in a leaf module because two features ask it from opposite sides: the pre-run gate
(:mod:`sessions.preflight`) and the account pool (:mod:`services.pool.selector`). The pool's
selector deciding candidates by a different rule than the gate that later refuses the run is
exactly how a healthy login gets called missing on one side and a dead one accepted on the
other — the reason :func:`preflight.has_session_to_test` was public in the first place.

The imports are deliberately only the cookie store and the profile markers: no crawler, no
pool, so either side may import this without a cycle.
"""

from runtime import paths

from sessions import profiles
from sessions.cookies import CookieManager


def has_session(platform: str, account: str = '', use_profile: bool = None) -> bool:
    """Whether anything could carry this platform's login for *account*.

    The saved file is the obvious source, but a *used profile* is a second one: since a
    profile imports the cookie file once and is never re-planted, a session lives in the
    directory from then on, and :mod:`sessions.profiles` ignores the file completely.
    Deleting a snapshot therefore does not log that device out — so this must not answer
    "nothing to test" while the profile is in play.

    Both halves are the *account's*: one account can hold a session while another has
    none, and asking the wrong one is how a valid login gets called missing.
    """
    if CookieManager(paths.active().cookie_dir).exists(platform, account):
        return True
    active = profiles.is_enabled() if use_profile is None else bool(use_profile)
    return bool(active and profiles.is_used(platform, account))
