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
import re
import threading
import time

from config import Config
from settings_store import get_setting

#: Written inside a platform's directory the first time it is used. Its presence is
#: the whole difference between "import the saved cookie file" and "leave this
#: profile's own session alone".
MARKER = '.crawler-profile.json'

#: An account label nests a sub-directory, so it is held to the same shape as the
#: cookie filename uses (see ``CookieManager``): a lowercase word that can never be a
#: path escape or a separator. The blank account is the platform's default device and
#: keeps the historical ``<root>/<platform>`` directory byte-for-byte.
_ACCOUNT_RE = re.compile(r'^[a-z0-9_]{1,24}$')


def _account_part(account: str) -> str:
    """The validated account segment, or ``''`` for the default (no nesting).

    Raises on a label that is neither blank nor a safe word — the same refusal the
    cookie file makes, so a profile directory can never be walked out of the root.
    """
    account = str(account or '').strip()
    if not account:
        return ''
    if not _ACCOUNT_RE.match(account):
        raise ValueError(f'Invalid account: {account}')
    return account


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


def platform_dir(platform: str, account: str = '') -> str:
    """The profile directory for a platform, or for one of its accounts.

    The blank account is the platform's default device and keeps the historical
    ``<root>/<platform>`` path byte-for-byte; a named account nests one level
    (``<root>/<platform>/<account>``) so each account gets its own browser, its own
    rotated cookies and — because ``lock_for`` keys on the directory path — its own
    concurrency lane. That is the whole point of the feature: two accounts of one
    platform are two devices to the site, so they can crawl at the same time.
    """
    base = str(platform or '').strip()
    if base == TEMPLATE_NAME:
        # The template lives at ``<root>/_template``; a platform with that name would
        # collide with it, and seeding would then hand a new account the account's own
        # directory as its source. No such platform exists in the matrix — this is the
        # refusal that keeps it from becoming a silent alias.
        raise ValueError(f'Reserved profile name: {base}')
    part = _account_part(account)
    return os.path.join(root_dir(), base, part) if part else os.path.join(root_dir(), base)


def profile_dir_for(platform: str, enabled: bool = None, account: str = '') -> str | None:
    """The directory *platform* should run in, or None when profiles are switched off.

    ``enabled`` overrides the setting for one browser: a parallel canvas can be run
    without profiles, on purpose, after the user was told what each side costs (see
    the pre-run dialog in workflow.js). None means "ask the setting".

    Creating it here is deliberate: the panel's "is this platform set up?" question is
    answered from the filesystem, and a directory that exists but was never used is a
    different state from one that has the marker (see :func:`is_imported`).

    When **this call** is the one that brought the directory into the world, it is seeded
    from the pristine template first (see :func:`seed_new_profile`) — which is how a new
    account on a cloud server gets a device without anyone pressing 「浏览器生成」。The
    ``exist_ok=False`` below is what makes "I created it" answerable: with
    ``exist_ok=True`` a directory two threads found at once looks identical to one this
    thread just made, and seeding the loser's directory would race the winner's browser.
    """
    active = is_enabled() if enabled is None else bool(enabled)
    if not active or not str(platform or '').strip():
        return None
    path = platform_dir(platform, account)
    try:
        os.makedirs(path, exist_ok=False)
        seed_new_profile(path)
    except FileExistsError:
        pass
    except OSError:
        # An unreadable root is the historical behaviour: hand the path back and let the
        # browser fail on it visibly, rather than swapping a Chrome error for a mkdir one.
        pass
    return path


def marker_path(platform: str, account: str = '') -> str:
    return os.path.join(platform_dir(platform, account), MARKER)


# ─── The pristine template ─────────────────────────────────────
#
# On a cloud deploy there is no 「浏览器生成」 button: nobody is standing at a screen to
# log into a window, so the only way an account gets a device directory is the program
# making one. Chrome builds a user-data-dir from nothing when it is pointed at one, so a
# brand-new directory already works — what the template adds is a *known* start: one
# directory that this program created and verified, that every new account is seeded
# from, instead of a first-run whose contents nobody has looked at.
#
# It is generated by launching a blank headless browser, never copied out of anyone's
# real Chrome. That is the difference between "pristine" and "someone's life with the
# obvious files removed": the strip-the-private-stuff route has to be right about every
# one of a profile's stores (``Login Data``, ``History``, ``Local Storage``,
# ``Web Data``, the OS-bound cookie key in ``Local State``…), and one miss ships a
# person's session to a server. A directory that was never logged into has nothing to
# miss, and :func:`verify_pristine` refuses to use one that changed its mind.

#: The reserved name of the template directory, under the profile root.
TEMPLATE_NAME = '_template'

#: Never copied, wherever it appears in the tree: anything that can carry a session, an
#: account, a browsing history, a restored tab, or a machine-local encryption key. The
#: list is a denylist because a Chrome profile's *shape* is Chrome's business — the safe
#: statement is "these names are what a login looks like", not "this is the whole tree".
UNSAFE_NAMES = frozenset(
    {
        'Cookies',
        'Cookies-journal',
        'Login Data',
        'Login Data For Account',
        'Login Data-journal',
        'Web Data',
        'Web Data-journal',
        'History',
        'History-journal',
        'History Provider Cache',
        'Favicons',
        'Favicons-journal',
        'Top Sites',
        'Top Sites-journal',
        'Shortcuts',
        'Visited Links',
        'Bookmarks',
        'Bookmarks.bak',
        'Preferences',
        'Secure Preferences',
        # Machine-level, not per-profile: it wraps the cookie-store key to *this* Windows
        # logon. A template built on one machine and copied into a container on another
        # would hand out a key nothing can unwrap, and Chrome rebuilds the file anyway.
        'Local State',
        'Local Storage',
        'Session Storage',
        'Session Storage-wal',
        'IndexedDB',
        'blob_storage',
        'Service Worker',
        'Sync Data',
        'Network',
        'DIPS',
        'DIPS-wal',
        'trust tokens',
        'heavy_ad_intervention_opt_out.db',
        'ServerCertificate',
        'ServerKeybindings',
        'AntiFraudMetadata',
        'Web Applications',
        'Web Applications 2024',
        'Key Storage',
        'KWL Metadata',
    }
)

#: Cache trees: they hold no login, and copying a hundred megabytes of shader cache into
#: every new account directory would make the seeding slower than the first run it saves.
UNSAFE_PREFIXES = ('LOCK', 'LOG', 'old_', 'Singleton', 'running', 'Crashpad')


def _is_unsafe(name: str) -> bool:
    """Whether one directory entry must never cross from the template into an account.

    Our own marker goes with them: a profile that inherits 「this device already holds a
    planted session」 would skip the import that gives it its cookie (#28's
    import-once rule reads this marker), which is a login silently missing on a server
    where nobody can open a window to fix it.
    """
    if name == MARKER:
        return True
    if name in UNSAFE_NAMES:
        return True
    return name.startswith(UNSAFE_PREFIXES)


#: Each Chrome store, and the table whose rows would mean a person has been here.
#:
#: The names alone prove nothing, and that is a measured fact, not an assumption: a
#: **blank** first run of Chrome creates ``Cookies``, ``Login Data``, ``History``,
#: ``Web Data``, ``Favicons`` and ``Preferences`` as empty stores (observed in
#: ``tests/integration/test_profile_template.py``, which prints the tree of a directory
#: no site was ever loaded in). A check on filenames therefore fails on the clean case —
#: it would refuse every template the program ever builds. What distinguishes an empty
#: store from somebody's login is the row count, so that is what is read.
_SESSION_TABLES = {
    'Cookies': 'cookies',
    'Safe Browsing Cookies': 'cookies',
    'Login Data': 'logins',
    'Login Data For Account': 'logins',
    'History': 'visits',
    'Web Data': 'autofill',
    'Favicons': 'favicons',
    'Top Sites': 'urls',
    'Device Bound Sessions': 'sessions',
}


def _store_row_count(path: str, table: str) -> int:
    """How many rows one Chrome store holds; ``-1`` when it exists and cannot be read.

    Read-only and by URI, so this never takes a lock a running browser owns. A store
    that cannot be opened *while it is not empty* is reported as material rather than
    passed: an unreadable file is not evidence of an empty profile, and the conservative
    answer to "is somebody's login in here" is the one that protects the account.
    """
    if not re.fullmatch(r'[a-z_]{1,32}', table):
        return -1  # the table names above are this module's own; refuse a typo loudly
    try:
        if os.path.getsize(path) == 0:
            return 0
    except OSError:
        return -1
    import sqlite3

    db = None
    try:
        db = sqlite3.connect(f'file:{os.path.abspath(path).replace(os.sep, "/")}?mode=ro', uri=True)
        return int(db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
    except sqlite3.Error:
        # No such table means the store has not been created yet — a blank directory
        # that has not run Chrome at all — which is the cleanest answer there is.
        return 0
    except OSError:
        return -1
    finally:
        # Measured, not defensive: ``with sqlite3.connect(...)`` commits the transaction and
        # leaves the *handle* open, and an open handle on Windows makes the ``rmtree`` that
        # ``build_template`` runs a moment later on a dirty template fail silently. The dirty
        # directory then survives and is copied into every new account.
        if db is not None:
            db.close()


def template_dir() -> str:
    return os.path.join(root_dir(), TEMPLATE_NAME)


def template_exists() -> bool:
    return os.path.isdir(template_dir())


def find_session_material(path: str = '') -> list:
    """Where *path* keeps a login, a history or a site's data — empty when it keeps none.

    A walk, not a listing: Chrome puts the cookie store under ``Default/Network/`` and
    the local storage under ``Default/Local Storage/``, so checking the top level proves
    nothing. Two kinds of evidence count — a store with rows in it, and an ``IndexedDB``
    origin directory (a blank run creates none; a site that stored anything creates one
    named after itself, and that is a login's fingerprints even though no SQL store here
    holds it).
    """
    root = path or template_dir()
    hits = []
    for walk_root, dirs, files in os.walk(root):
        rel = os.path.relpath(walk_root, root)
        # The origin directories are the *children* of an IndexedDB tree, so the name to
        # match is the directory this walk step is standing in, not its parent.
        if os.path.basename(rel) == 'IndexedDB' and dirs:
            hits.append(os.path.normpath(os.path.join(rel, '<origin>')))
        for name in files:
            table = _SESSION_TABLES.get(name)
            if table is None:
                continue
            count = _store_row_count(os.path.join(walk_root, name), table)
            if count != 0:
                suffix = 'unreadable' if count < 0 else f'{count} rows'
                hits.append(f'{os.path.relpath(os.path.join(walk_root, name), root)} ({suffix})')
        if len(hits) > 8:
            break
    return sorted(hits)[:9]


def verify_pristine(path: str = '') -> str:
    """'' when *path* holds no session material, otherwise what it holds.

    The answer is a reason to show a person, never a silent no: 「模板脏了」 with the file
    names is actionable, and the alternative — seeding a new account from a directory
    that someone logged into — is how one account's session ends up in another's device.
    """
    hits = find_session_material(path)
    return '' if not hits else ', '.join(hits)


def _copy_template_into(source: str, target: str) -> int:
    """One-way copy of everything in *source* that is safe to carry into *target*.

    Returns the number of top-level entries landed. ``shutil.copy2`` keeps timestamps,
    which is what makes a seeded directory look like a Chrome first-run rather than a
    file dump.
    """
    import shutil

    copied = 0
    for name in sorted(os.listdir(source)):
        if _is_unsafe(name):
            continue
        src = os.path.join(source, name)
        dst = os.path.join(target, name)
        if os.path.islink(src):
            continue  # a link inside a profile can point outside the profile root
        if os.path.isdir(src):
            for walk_root, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if not _is_unsafe(d)]
                rel = os.path.relpath(walk_root, src)
                base = target if rel == '.' else os.path.join(target, rel)
                os.makedirs(base, exist_ok=True)
                for fname in files:
                    if _is_unsafe(fname):
                        continue
                    with contextlib.suppress(OSError):
                        shutil.copy2(os.path.join(walk_root, fname), os.path.join(base, fname))
            copied += 1
        else:
            with contextlib.suppress(OSError):
                shutil.copy2(src, dst)
                copied += 1
    return copied


def seed_new_profile(path: str) -> int:
    """Give a directory that was just created the template's contents. Returns the count.

    Two conditions, both about *who* this call is: the directory must have been created
    by the caller that is now seeding it, and it must still be empty. The first is
    handled by the caller (``os.makedirs`` with ``exist_ok=False`` answers it exactly —
    ``exist_ok=True`` cannot tell "I made this" from "someone made this"); the second is
    the guard against racing a browser that already started writing there.
    """
    source = template_dir()
    if not os.path.isdir(source) or os.path.abspath(source) == os.path.abspath(path):
        return 0
    if verify_pristine(source):
        return 0
    with contextlib.suppress(OSError):
        if os.listdir(path):
            return 0
        return _copy_template_into(source, path)
    return 0


def build_template(launch=None) -> dict:
    """Create the pristine device directory by starting one blank Chrome in it.

    *launch* is the browser seam — the caller passes something that starts a headless
    Chrome pointed at the directory and quits; ``None`` means "this build has no browser
    here", which is the honest answer for the fast tier and for a machine without Chrome,
    and it is why the caller's refusal is a report rather than an exception.

    No cookie path, no account, no login: the directory is empty of sessions because
    nothing was ever put into it, which is the property the whole feature rests on. The
    verification afterwards is not ceremony — a template that has since been used is
    destroyed and rebuilt rather than copied into new accounts.
    """
    path = template_dir()
    if launch is None:
        return {'ok': False, 'built': False, 'reason': 'no-launcher'}
    dirty = verify_pristine(path) if os.path.isdir(path) else ''
    if dirty:
        import shutil

        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    try:
        launch(path)
    except Exception as e:  # a browser that will not start is reported, not swallowed
        return {'ok': False, 'built': False, 'reason': str(e)[:200]}
    after = verify_pristine(path)
    if after:
        return {'ok': False, 'built': False, 'reason': f'template-not-pristine: {after}'}
    return {'ok': True, 'built': True, 'path': path}


def _marker(platform: str, account: str = '') -> dict:
    """The marker document, or ``{}`` when it is missing or unreadable.

    An unparsable marker is treated as *no history at all*, which re-imports the
    cookie file — the safe direction: the alternative is a crawl that assumes a
    session this profile was never given.
    """
    try:
        with open(marker_path(platform, account), encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def is_used(platform: str, account: str = '') -> bool:
    """Has this profile ever been handed to a browser?

    Three states matter and they are not two, which is why this is separate from
    :func:`is_imported`: a profile can be used without any import (the user logged
    in *inside* it), and a fresh one can be ready to import the saved file.
    """
    return bool(_marker(platform, account).get('used_at'))


def is_imported(platform: str, account: str = '') -> bool:
    """Did the saved cookie file actually go into this profile?

    The panel says 已导入 vs 将首次导入 from this — and the answer comes from the
    marker's own field, not from the file existing, or every used profile would look
    like it holds a session it may never have been given.
    """
    return bool(_marker(platform, account).get('imported_at'))


def mark_used(platform: str, *, imported: bool = True, cookie_stamp: str = '', account: str = '') -> None:
    """Record that the profile was handed to a browser, and whether cookies went in.

    A failed write leaves the profile "new", which re-imports the cookie file next
    run — the safe direction of failure (a session refresh, not a silently frozen
    credential).

    ``cookie_stamp`` is *which* file went in (see :func:`file_stamp`). It is what lets
    the panel answer "the saved Cookie is newer than what this profile holds" without
    re-reading the browser's own store, which no process but Chrome can do.
    """
    path = marker_path(platform, account)
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = _marker(platform, account)
        existing['used_at'] = stamp
        if imported and not existing.get('imported_at'):
            existing['imported_at'] = stamp
        existing.setdefault('imported_at', '')
        if imported:
            existing['cookie_stamp'] = cookie_stamp
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(existing, handle, ensure_ascii=False, indent=1)


def remember_cookie(platform: str, cookie_path: str, account: str = '') -> None:
    """Record that this file IS the profile's own session, without claiming a plant.

    The panel's 「把 Cookie 更新进 Profile」 hint answers one question: *did a different file go in
    last time?* A cookie captured **out of this very profile** (the panel's 浏览器生成 path logs in
    inside the profile browser and reads its jar) is not a different file — the profile already
    holds it. Leaving the old stamp there would advertise a button whose only effect is to
    overwrite a live session with a copy of itself, which is precisely what the import-once rule
    exists to prevent. ``imported_at`` stays where it is: nothing was imported.
    """
    path = marker_path(platform, account)
    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing = _marker(platform, account)
        existing['cookie_stamp'] = file_stamp(cookie_path)
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


def needs_refresh(platform: str, cookie_path: str, account: str = '') -> bool:
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
    if not cookie_path or not is_used(platform, account):
        return False
    recorded = str(_marker(platform, account).get('cookie_stamp') or '')
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


def status(
    platform: str,
    *,
    recommended: bool = False,
    has_cookie: bool = False,
    cookie_path: str = '',
    account: str = '',
    size: bool = True,
) -> dict:
    """One platform's profile state, shaped for the settings panel.

    ``imported`` is what the guidance sentence turns on: false with an existing
    directory means "it has been used but never given a session — log into it".
    ``needs_refresh`` is the other half of that story: the profile *was* given a
    session, and the file it came from has been saved over since, so the login the user
    just re-took is sitting in a file the browser will never look at again by itself.

    ``account`` scopes the whole answer to one account's device; the blank account is
    the platform's default device, unchanged from before multi-account existed.
    """
    path = platform_dir(platform, account)
    exists = os.path.isdir(path)
    marker = _marker(platform, account)
    return {
        'platform': platform,
        'account': str(account or '').strip(),
        'enabled': is_enabled(),
        'recommended': bool(recommended),
        'path': path,
        'exists': exists,
        'imported': bool(marker.get('imported_at')),
        'used_at': str(marker.get('used_at') or ''),
        'size_mb': _dir_size_mb(path) if exists else 0,
        'has_saved_cookie': bool(has_cookie),
        'needs_refresh': bool(cookie_path) and needs_refresh(platform, cookie_path, account),
    }
