"""Browser-profile template ownership — the one pristine device directory every new account copies.

Moved out of ``app.py`` so both the ``POST /api/browser/profiles/template`` Blueprint route and
the cookie-save path (``_plant_saved_cookie_into_profile`` in ``app.py``) call the same function
without a cycle. A build is process-serialised: two blank Chromes on one ``user-data-dir`` is the
crash the profile module documents. Tests that need to stub the launcher patch ``profiles.warm_profile_dir``.
"""

import threading

import browser_profiles

from crawlers.base import warm_profile_dir

_TEMPLATE_BUILD_LOCK = threading.Lock()


def ensure_profile_template(force: bool = False) -> dict:
    """Make the pristine device directory, unless a clean one already exists.

    One process at a time, because two blank Chromes pointed at the same
    ``user-data-dir`` is the crash the profile module documents (Chrome pre-writes that
    directory's preference file), and the answer the second caller wants is the same
    directory, not a second one.

    An existing-but-dirty template is rebuilt rather than trusted: :func:`build_template`
    destroys it first, because copying a directory that someone logged into would hand
    that session to every account created afterwards — which is the one outcome this
    feature exists to avoid.
    """
    with _TEMPLATE_BUILD_LOCK:
        if browser_profiles.template_exists() and not force and not browser_profiles.verify_pristine():
            return {'ok': True, 'built': False, 'existed': True}
        return browser_profiles.build_template(launch=warm_profile_dir)
