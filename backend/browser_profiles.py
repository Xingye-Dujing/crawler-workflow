"""Per-platform persistent Chrome profiles, and what the panel needs to know about them.

Every crawler browser used to start from an empty temporary directory, which tells a
site "this is a brand-new device" on each run. The consequence is measured, not
theorised: weibo re-issues ``SUB``/``SUBP`` on the first logged-in page load (so a
saved snapshot is stale the second time it is replayed — and replaying the rotated
values into a third browser is bounced straight back to ``/newlogin``), and
xiaohongshu walls a search session that the user's *own* browser keeps working in,
minutes apart. A site that rotates a credential needs a browser that keeps it, and a
temporary profile keeps nothing.

So the crawl browser and the cookie-login browser are given the **same directory per
platform**. The device identity, the rotated cookies and the site's own local state
then live in one place that outlives the run, which is exactly what the user's browser
does and what a snapshot cannot imitate.

Two rules this module exists to keep honest:

* **A profile that has been used owns its cookies.** The first time a platform's
  profile is created, the saved ``data/cookies/<platform>_cookies.json`` is imported
  into it (so an existing session is not wasted); afterwards nothing is planted,
  because planting an old snapshot over a live profile would overwrite the rotated
  credential with the stale one — the exact harm measured on weibo.
* **The user's daily Chrome profile is not an option, and saying so is part of the
  feature.** Chrome refuses a second process on a ``user-data-dir`` that is in use,
  its cookie store is exclusively locked while the browser runs, and (measured on
  Chrome 148) its cookies are app-bound-encrypted, with remote debugging disabled on
  the default profile since Chrome 136. The directory here is therefore either the
  app-managed one or a profile the user created *for this tool*.
"""

import contextlib
import json
import os
import time

from config import Config
from settings_store import get_setting

#: Written inside a platform's directory the first time it is used. Its presence is
#: the whole difference between "import the saved cookie file" and "leave this
#: profile's own session alone".
MARKER = '.crawler-profile.json'


def root_dir() -> str:
    """Where the per-platform directories live (settings can move it)."""
    configured = str(get_setting('browser_profile_dir') or '').strip()
    return configured or Config.BROWSER_PROFILE_DIR


def is_enabled() -> bool:
    return bool(get_setting('use_browser_profile'))


def platform_dir(platform: str) -> str:
    return os.path.join(root_dir(), str(platform or '').strip())


def profile_dir_for(platform: str) -> str | None:
    """The directory *platform* should run in, or None when profiles are switched off.

    Creating it here is deliberate: the panel's "is this platform set up?" question is
    answered from the filesystem, and a directory that exists but was never used is a
    different state from one that has the marker (see :func:`is_imported`).
    """
    if not is_enabled() or not str(platform or '').strip():
        return None
    path = platform_dir(platform)
    with contextlib.suppress(OSError):
        os.makedirs(path, exist_ok=True)
    return path


def marker_path(platform: str) -> str:
    return os.path.join(platform_dir(platform), MARKER)


def _marker(platform: str) -> dict:
    """The marker document, or ``{}`` when it is missing or unreadable.

    An unparsable marker is treated as *no history at all*, which re-imports the
    cookie file — the safe direction: the alternative is a crawl that assumes a
    session this profile was never given.
    """
    try:
        with open(marker_path(platform), encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def is_used(platform: str) -> bool:
    """Has this profile ever been handed to a browser?

    Three states matter and they are not two, which is why this is separate from
    :func:`is_imported`: a profile can be used without any import (the user logged
    in *inside* it), and a fresh one can be ready to import the saved file.
    """
    return bool(_marker(platform).get('used_at'))


def is_imported(platform: str) -> bool:
    """Did the saved cookie file actually go into this profile?

    The panel says 已导入 vs 将首次导入 from this — and the answer comes from the
    marker's own field, not from the file existing, or every used profile would look
    like it holds a session it may never have been given.
    """
    return bool(_marker(platform).get('imported_at'))


def mark_used(platform: str, *, imported: bool = True) -> None:
    """Record that the profile was handed to a browser, and whether cookies went in.

    A failed write leaves the profile "new", which re-imports the cookie file next
    run — the safe direction of failure (a session refresh, not a silently frozen
    credential).
    """
    path = marker_path(platform)
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = _marker(platform)
        existing['used_at'] = stamp
        if imported and not existing.get('imported_at'):
            existing['imported_at'] = stamp
        existing.setdefault('imported_at', '')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(existing, handle, ensure_ascii=False, indent=1)


def _dir_size_mb(path: str) -> int:
    total = 0
    for walk_root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(walk_root, name))
    return total // (1024 * 1024)


def status(platform: str, *, recommended: bool = False, has_cookie: bool = False) -> dict:
    """One platform's profile state, shaped for the settings panel.

    ``imported`` is what the guidance sentence turns on: false with an existing
    directory means "it has been used but never given a session — log into it".
    """
    path = platform_dir(platform)
    exists = os.path.isdir(path)
    marker = _marker(platform)
    return {
        'platform': platform,
        'enabled': is_enabled(),
        'recommended': bool(recommended),
        'path': path,
        'exists': exists,
        'imported': bool(marker.get('imported_at')),
        'used_at': str(marker.get('used_at') or ''),
        'size_mb': _dir_size_mb(path) if exists else 0,
        'has_saved_cookie': bool(has_cookie),
    }
