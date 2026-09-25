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
import threading
import time

from config import Config
from settings_store import get_setting

#: Written inside a platform's directory the first time it is used. Its presence is
#: the whole difference between "import the saved cookie file" and "leave this
#: profile's own session alone".
MARKER = '.crawler-profile.json'

# ─── one browser per profile ────────────────────────────────────
#
# chromedriver writes into ``<user-data-dir>/Default/Preferences`` *before* the
# browser starts, so two sessions created in the same profile at the same moment
# cannot both come up: one of them dies with ``session not created / failed to
# write prefs file`` (measured 2026-09: 2 failures in 8 barrier-synchronised
# attempts, and the failure is a race, not a schedule — it can pass ten times in a
# row then take down a node). A parallel canvas is exactly where this bites,
# because two workflows that crawl the same platform are started by the same
# thread pool.
#
# The profile is what makes the run "the same device" to a site, so the answer is
# not a second directory per consumer: it is one browser at a time per profile,
# which is also what the user's own browser does. Different platforms keep running
# in parallel — only the same profile serialises.

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _dir_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path or '')))


def lock_for(path: str) -> threading.Lock:
    """The lock that owns *path*, created on first use.

    A plain ``Lock``, deliberately **not** an ``RLock``: the browser is closed from a
    helper thread (``_close_login_browser`` gives ``quit()`` a bounded grace on a side
    thread so a hand-closed window cannot hang the run), and an RLock can only be
    released by the thread that took it — with one, every real crawl finished and left
    its profile claimed, so the next crawl of that platform waited out the whole
    timeout. The reentrancy an RLock would buy is not needed either: a workflow never
    holds two browsers for one platform at a time.
    """
    key = _dir_key(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def acquire_profile(path: str, timeout: float = None, abort=None):
    """Take exclusive use of *path*; return the lock, or None if it stayed busy.

    None is an answer the caller must not ignore: proceeding anyway is the crash
    this prevents. The timeout exists because a browser that was killed without
    closing would otherwise park every later run of that platform.

    ``abort`` makes the wait cancellable in half-second slices: a run the user
    stopped must not sit out the timeout behind a browser the stop has already
    closed — the wait ending on Stop is what lets the worker reach its finally
    and turn the record from 运行中 into its verdict. Without it the acquire
    stays the single blocking call it always was.
    """
    lock = lock_for(path)
    if abort is None:
        return lock if lock.acquire(timeout=timeout if timeout is not None else Config.PROFILE_LOCK_TIMEOUT) else None
    deadline = time.monotonic() + (timeout if timeout is not None else Config.PROFILE_LOCK_TIMEOUT)
    while True:
        if abort():
            return None
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        if lock.acquire(timeout=min(0.5, left)):
            return lock


def release_profile(lock) -> None:
    if lock is not None:
        with contextlib.suppress(RuntimeError):
            lock.release()


def is_busy(path: str) -> bool:
    """Whether some browser holds *path* at this instant.

    Advisory only — the answer is stale the moment it is returned, and a caller that
    *needed* ownership would take :func:`acquire_profile` instead. It exists for the
    pre-run cookie probe: opening a second browser into a profile a live crawl owns
    would park that probe behind ``PROFILE_LOCK_TIMEOUT`` (longer than any crawl) and
    tell the user nothing about their cookie they could act on.
    """
    lock = lock_for(path)
    if lock.acquire(blocking=False):
        release_profile(lock)
        return False
    return True


def root_dir() -> str:
    """Where the per-platform directories live (settings can move it)."""
    configured = str(get_setting('browser_profile_dir') or '').strip()
    return configured or Config.BROWSER_PROFILE_DIR


def is_enabled() -> bool:
    return bool(get_setting('use_browser_profile'))


def platform_dir(platform: str) -> str:
    return os.path.join(root_dir(), str(platform or '').strip())


def profile_dir_for(platform: str, enabled: bool = None) -> str | None:
    """The directory *platform* should run in, or None when profiles are switched off.

    ``enabled`` overrides the setting for one browser: a parallel canvas can be run
    without profiles, on purpose, after the user was told what each side costs (see
    the pre-run dialog in workflow.js). None means "ask the setting".

    Creating it here is deliberate: the panel's "is this platform set up?" question is
    answered from the filesystem, and a directory that exists but was never used is a
    different state from one that has the marker (see :func:`is_imported`).
    """
    active = is_enabled() if enabled is None else bool(enabled)
    if not active or not str(platform or '').strip():
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


def mark_used(platform: str, *, imported: bool = True, cookie_stamp: str = '') -> None:
    """Record that the profile was handed to a browser, and whether cookies went in.

    A failed write leaves the profile "new", which re-imports the cookie file next
    run — the safe direction of failure (a session refresh, not a silently frozen
    credential).

    ``cookie_stamp`` is *which* file went in (see :func:`file_stamp`). It is what lets
    the panel answer "the saved Cookie is newer than what this profile holds" without
    re-reading the browser's own store, which no process but Chrome can do.
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
        if imported:
            existing['cookie_stamp'] = cookie_stamp
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(existing, handle, ensure_ascii=False, indent=1)


def file_stamp(path: str) -> str:
    """A cheap identity for a cookie file: its mtime and size, not its contents.

    Contents would be the precise answer and also a read of the user's session values,
    which this module has no business holding in memory. A re-save changes the
    modification time, which is the event the panel cares about.
    """
    try:
        info = os.stat(path)
    except OSError:
        return ''
    return f'{int(info.st_mtime)}:{info.st_size}'


def needs_refresh(platform: str, cookie_path: str) -> bool:
    """Is the saved cookie file a *different* file than the one this profile was given?

    Three answers must stay separate, and two of them are "no":

    * a profile that has never been used will import the file on its own — nothing to
      refresh;
    * a profile whose marker predates this field answers "no" rather than nagging,
      because "I cannot tell what went in" is not evidence that something changed;
    * a platform with no saved file has nothing to plant.

    Only "it was planted, and the file has been saved since" is a real difference, and
    even then this is a hint and a button — never an automatic re-plant. Overwriting a
    live profile with an older snapshot is the harm the import-once rule exists to
    prevent; the user asking is the one thing that makes it a refresh.
    """
    if not cookie_path or not is_used(platform):
        return False
    recorded = str(_marker(platform).get('cookie_stamp') or '')
    if not recorded:
        return False
    return file_stamp(cookie_path) != recorded


def _dir_size_mb(path: str) -> int:
    total = 0
    for walk_root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(walk_root, name))
    return total // (1024 * 1024)


def status(platform: str, *, recommended: bool = False, has_cookie: bool = False, cookie_path: str = '') -> dict:
    """One platform's profile state, shaped for the settings panel.

    ``imported`` is what the guidance sentence turns on: false with an existing
    directory means "it has been used but never given a session — log into it".
    ``needs_refresh`` is the other half of that story: the profile *was* given a
    session, and the file it came from has been saved over since, so the login the user
    just re-took is sitting in a file the browser will never look at again by itself.
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
        'needs_refresh': bool(cookie_path) and needs_refresh(platform, cookie_path),
    }
