"""Cookie and device routes — ``/api/cookies/*``, ``/api/profiles/delete`` and ``/api/browser/profiles*``.

All of it lives in the login-state domain because a cookie and the browser directory that carries
it are one thing to the user: saving a jar plants it into that account's profile, deleting a jar is
not signing the device out, and renaming an account moves both halves or neither. The panel's
generation and verification workers are here too — they open the very browser this domain owns.

Two dependencies are worth keeping straight. ``cookie_manager`` is the one instance ``state``
creates at import and never rebinds (a per-test jar is the same object with its directory
redirected), and the workers pin their own language with ``set_lang`` because a daemon thread
starts with a fresh thread-local — without it their lines were Chinese in an English interface.

Paths and behaviour are unchanged from the ``app.py`` routes they replace (2026-10-28); app-level
``before_request`` / CORS still wrap them because the Blueprint is registered on the same app.
"""

import logging
import os
import threading
import time

from api.http import _bad_body, _json_body, _safe_int
from core.config import Config
from core.refs import as_bool, flag_or_none
from flask import Blueprint, jsonify
from state import add_log, cookie_manager, execution_state

import crawl_capabilities as capabilities
from crawlers import cookie_hosts, crawler_class, get_crawler
from i18n import get_lang, set_lang, t
from services.crawler_lifecycle import close_login_browser as _close_login_browser
from sessions import preflight, profiles
from sessions.cookies import CookieManager
from sessions.flow import crawler_hosts, flow_for, normalize_entry_url, retain_for_platform
from sessions.template import ensure_profile_template

logger = logging.getLogger(__name__)

bp = Blueprint('sessions', __name__)


# ─── Cookie API ────────────────────────────────────────────────

# One list, so a platform can never be half-wired: status, flows, generation and
# verification all walk the same tuple, which is the crawler registry's order.
# Derived from the cookie store's own list, so a platform added there cannot be
# left out of the panel, the flows or the status endpoint.
COOKIE_PLATFORMS = CookieManager.PLATFORMS


@bp.route('/api/cookies/status', methods=['GET'])
def cookie_status():
    """What the panel is allowed to know about saved logins: which accounts exist, and how fresh.

    ``cookies[platform]`` used to be ``cookie_manager.exists(platform)`` — the BLANK account's
    file only. A user who keeps every login under a name therefore saw 「没有 Cookie」 for a
    platform he crawls with daily, and the status line could not answer the question he was
    actually asking, which is about the account in the box.

    ``rows`` answers it per ``(platform, account)``: how many entries, how many of them will
    not outlive a window, when it was saved, and what that account's own browser directory
    knows. Labels travel as catalogue keys because 默认账号 / 默认账号2 are words this program
    generated, while ``work`` is a word the user typed and must be shown exactly as typed —
    so the row carries ``label_key`` (empty for a typed name) plus its arguments, and the
    browser translates one and prints the other.

    **No cookie value ever leaves this endpoint**, and the sentence is worth stating because
    the panel is the one surface a stranger could stand in front of on a cloud deploy: the
    counts are lengths, the date is a ``stat``, the profile half is one marker file, and the
    directory walk that would cost real time is switched off here (``size=False``) — a
    management row is not worth reading a browser's cache index.
    """
    accounts = {platform: cookie_manager.accounts_in_order(platform) for platform in COOKIE_PLATFORMS}
    rows = []
    for platform, names in accounts.items():
        for account in names:
            path = cookie_manager.path_for(platform, account)
            profile = profiles.status(platform, has_cookie=True, cookie_path=path, account=account, size=False)
            label_key, label_args = cookie_manager.account_label_key(account)
            rows.append(
                {
                    'platform': platform,
                    'account': account,
                    'entry_key': preflight.entry_key(platform, account),
                    'label_key': label_key or '',
                    'label_args': label_args,
                    'entries': cookie_manager.entry_count(platform, account),
                    'session_only': cookie_manager.session_only_count(platform, account),
                    'saved_at': cookie_manager.saved_at(platform, account),
                    'profiles_on': profile['enabled'],
                    'profile_exists': profile['exists'],
                    'profile_used': bool(profile['used_at']),
                    'profile_imported': profile['imported'],
                    'needs_refresh': profile['needs_refresh'],
                }
            )
    return jsonify(
        {
            'ok': True,
            # 「this platform has a login somewhere」 — not "the blank file exists".
            'cookies': {platform: bool(names) for platform, names in accounts.items()},
            'accounts': accounts,
            'rows': rows,
        }
    )


@bp.route('/api/cookies/flow', methods=['GET'])
def cookie_flow():
    """What each cookie is for and how to get it, for the panel to render.

    The guidance lives in the message catalogue and the host list on the
    crawler, never in the frontend: a translated panel and a per-platform
    "which page do I log in on" answer are the same feature. Only the platforms
    in ``CookieManager.PLATFORMS`` appear here — WeChat is not one of them,
    because its article bodies are served without a session.
    """
    flows = []
    for platform in COOKIE_PLATFORMS:
        cls = crawler_class(platform)
        flows.append(
            flow_for(
                platform,
                allowed_hosts=cookie_hosts(platform),
                login_url=getattr(cls, 'login_url', '') if cls else '',
            )
        )
    return jsonify({'ok': True, 'flows': flows})


@bp.route('/api/cookies/preflight', methods=['POST'])
def preflight_cookies():
    """Ask every platform of this canvas, at once, whether its session still gets us in.

    One request for the whole canvas rather than one per platform: the page has to be
    able to name *which* source is dead in the dialog it shows before 执行, and it
    cannot do that if it has to wait on each probe in turn.

    This endpoint answers the question it is asked; it does not decide whether to ask
    it. That is ``cookie_preflight_before_run`` in the browser
    (``_preflightCookies`` in workflow.js), so the panel's own 验证 button, a hand-made
    request and a future caller all get the same facts from the same code.

    ``text`` is rendered here rather than keyed: the sentences live in the backend
    catalogue next to the crawler that decides them, and the panel already treats
    server-side wording as the single source (see ``/api/cookies/flow``).
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    raw = data.get('platforms')
    if raw is None:
        # Absent means "nothing on this canvas crawls anything", which is an answer,
        # not a mistake. A field that is there but is not a list is a different thing
        # and is refused below.
        raw = []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return jsonify({'ok': False, 'error': t('api.platformsRequired')}), 400
    # Each entry is a platform string (the shape before accounts existed, still
    # accepted) or a {platform, account[, backend]} pair. Only the PLATFORM is knowledge-checked —
    # an account is a filename segment the store validates, and a name nobody saved is
    # answered 「no cookie」 by the probe, not refused at the door. ``check`` normalizes
    # the same way, so the door and the probe never agree to disagree about what an entry is.
    #
    # The knowledge door is a COOKIE-STORE question, so it is not asked of an entry that will not
    # read the cookie store: a CatBus node's platform is judged by the adapter's manifest inside
    # ``probe``, and refusing a name the cookie list lacks would block a crawl that needs no cookie.
    refused = [
        plat
        for plat, _acct, backend in (preflight.entry_of(p) for p in raw)
        if backend != capabilities.BACKEND_CATBUS and not preflight.knows(plat)
    ]
    if refused:
        # The names arrive from the browser and each one would buy a Chrome, so an
        # unrecognised name is refused whole instead of being filtered out quietly — a
        # silent drop reads as "checked and fine" for the platform nobody checked.
        # A name a *crawler* knows but the cookie store does not (WeChat) passes: the
        # gate answers it 「不需要登录」 without opening anything.
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=refused[0])}), 400
    use_profile = flag_or_none(data.get('use_profile'))
    fresh = flag_or_none(data.get('fresh')) is True
    results = preflight.check(raw, use_profile=use_profile, fresh=fresh)
    for verdict in results.values():
        verdict['text'] = preflight.describe(verdict)
    blocked = [name for name, verdict in results.items() if verdict['blocking']]
    unclear = [name for name, verdict in results.items() if verdict['state'] == preflight.UNKNOWN]
    return jsonify(
        {
            'ok': True,
            'results': results,
            # Split server-side so the browser cannot invent its own reading of a
            # state it does not know: 「拦下来」 and 「没核得上」 are different answers.
            'blocked': blocked,
            'unclear': unclear,
            'probed': any(v['probed'] for v in results.values()),
        }
    )


#: One plant at a time: two browsers writing the same profile would each report a session
#: count that the other had already overwritten.
_PROFILE_REFRESH_LOCK = threading.Lock()


def _plant_saved_cookie_into_profile(platform: str, account: str) -> str | None:
    """Give this account's own browser the file that was just saved, and say what happened.

    The import-once rule is right for a crawl — planting an older snapshot over a live,
    rotating session is how weibo's ``SUB``/``SUBP`` get thrown away — but a paste in this
    panel is not an older snapshot: it is the newest login the user has, and the browser that
    will do the crawling is the only place it can still be used. Requiring a separate button
    for that made the user re-take a session, watch it get saved, and then get crawled with
    the previous one.

    ``None`` means nothing to do and nothing to say: profiles are switched off, and then every
    crawl is planted from the file in a throwaway browser, so buying one to change nothing would
    cost a browser and claim a thing that did not happen. Anything else gets a sentence, because
    「保存成功」 and 「这次没能进到 Profile」 look identical from a paste box otherwise.

    A profile that has never been opened is *created and planted now*, not left for the first
    crawl: one cookie, one profile, and a login sitting in a file its own browser has never read
    is exactly the state the panel used to leave behind (the directory comes from
    ``profile_dir_for``, which ``get_crawler`` calls before Chrome starts).

    On a cloud host the pristine template is made here first, before that directory exists:
    it is the one thing that has to precede a new account, and this is the one moment the
    user is present to ask for a device. It costs one extra blank browser — once per
    server, never again while the template stands — and on a machine with no
    「浏览器生成」 button that browser is how the directory gets made at all.
    """
    if not profiles.is_enabled():
        return None
    if Config.CLOUD_MODE:
        ensure_profile_template()
    profile = profiles.platform_dir(platform, account)
    if profiles.is_busy(profile) or execution_state['running']:
        # The file is newer than the session in that browser, and `needs_refresh` is what the
        # next crawl reads to decide — so this is a wait, not a lost update.
        return t('cookie.plant.deferred', platform=platform)
    if not _PROFILE_REFRESH_LOCK.acquire(blocking=False):
        return t('cookie.plant.deferred', platform=platform)
    try:
        try:
            crawler = get_crawler(
                platform,
                # The plant is one page load on that site, and a headless Chrome now carries the
                # desktop fingerprint (#148) so every platform — douyin and X included — serves it.
                headless=True,
                cookie_dir=Config.COOKIE_DIR,
                use_profile=True,
                refresh_cookies=True,
                account=account,
            )
        except Exception as e:
            logger.debug('the plant browser for %s did not come up: %s', platform, e)
            return t('cookie.refresh.failed', err=str(e)[:160])
        try:
            planted = int(getattr(crawler, 'cookies_loaded', 0))
        finally:
            _close_login_browser(crawler)
    finally:
        _PROFILE_REFRESH_LOCK.release()
    # The profile now holds a different session than the one the last probe looked at.
    preflight.invalidate(platform)
    # Measured on a real Chrome: a cookie without an expiry is not written to the profile store
    # at all, so it dies with the window that was opened to plant it. Saying only 「已更新」 would
    # promise a transfer that partly did not happen.
    fading = cookie_manager.session_only_count(platform, account)
    message = t('cookie.refresh.done', platform=platform, n=planted)
    return message + '\n' + t('cookie.refresh.sessionOnly', n=fading) if fading else message


@bp.route('/api/cookies/save', methods=['POST'])
def save_cookies():
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = data.get('platform', '')
    cookies = data.get('cookies', [])
    account = str(data.get('account') or '').strip()
    if not platform:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_supported(platform):
        # The platform becomes part of a filename — refuse anything else.
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if account and not cookie_manager.is_account(account):
        # The account is the OTHER filename segment that comes from a text box.
        return jsonify({'ok': False, 'error': t('api.badAccount', account=account)}), 400
    if not cookies:
        return jsonify({'ok': False, 'error': t('api.cookiesRequired')}), 400
    try:
        # The same rule the login browser follows: cookies from another site do
        # not belong in this platform's file, however they were pasted in.
        kept, dropped = retain_for_platform(cookies, cookie_hosts(platform))
        if dropped:
            add_log(t('cookie.droppedForeign', platform=platform, n=dropped))
        if not kept:
            return jsonify({'ok': False, 'error': t('cookie.allForeign', platform=platform)}), 400
        # 留空 = 「一个还没起名字的登录」：第一份是默认账号，第二份是默认账号2, never an overwrite.
        # A second blank paste cannot be told apart from re-pasting the first one (two logins of one
        # platform carry the same cookie *names*, and the value that would tell them apart is the one
        # that rotates), so the only reading that cannot destroy a paid-for login is "this is a new
        # one". Overwriting a specific account is what choosing that account in the box means.
        if not account and cookie_manager.exists(platform):
            account = cookie_manager.next_free_account(platform)
        cookie_manager.save(platform, kept, account)
        # The file this platform would be planted from just changed, so the cached
        # verdict about the previous one has to go with it.
        preflight.invalidate(platform)
        # No ``add_log`` beside this: ``CookieManager.save`` logs the same sentence and
        # ``LogBufferHandler`` forwards every logger call into the console, so the
        # narration the panel wanted was already there — twice, for one paste.
        # One cookie, one profile: the browser that will crawl with this login takes the
        # new file in now, instead of the user pressing a second button to say so.
        planted = _plant_saved_cookie_into_profile(platform, account)
        # 「已保存」 is not the whole answer any more: a blank name can have become 默认账号2, and
        # the panel has to say which login it just wrote — otherwise the user cannot tell whether
        # the account he meant is the one that changed.
        message = t('cookie.savedAccount', platform=platform, account=cookie_manager.label_of(account))
        return jsonify(
            {
                'ok': True,
                'message': f'{message}\n{planted}' if planted else message,
                'count': len(kept),
                'account': account,
                'account_label': cookie_manager.label_of(account),
                'profile_note': planted or '',
            }
        )
    except (OSError, ValueError) as e:
        # One line for one failure. ``LogBufferHandler`` forwards every logger call to
        # the console (its ``format`` is the message alone, so the traceback still goes
        # only to the log file) — the ``add_log`` beside it printed the same sentence a
        # second time, and the console showed 「保存 Cookie 失败」 twice in a row.
        # The reason travels as a catalogue parameter, the way every other console-level
        # logger call here speaks: no interpolation in the code (pylint W1201/W1203) and no
        # bare ``'%s'`` template for the untranslated-text guard to read as English prose.
        logger.exception(t('misc.cookie_save_failed', err=str(e)[:120]))
        return jsonify({'ok': False, 'error': str(e)}), 500


@bp.route('/api/cookies/rename', methods=['POST'])
def rename_cookie_account():
    """Give a saved login a new label — its cookie file AND that account's browser directory.

    Each refusal names what it refused, because the alternative is a panel that says
    「已重命名」 about a session still filed under the old name. The blank account is refused
    structurally: 默认账号 owns no directory of its own (it IS the platform's), so naming it
    would move the parent of every other account of that platform — and since the user is told
    an account and its profile are one thing, the two halves move together or nothing moves.
    """
    body = _json_body()
    if body is None:
        return _bad_body()
    platform = str(body.get('platform') or '').strip()
    # Folded through the manager's own key, so 「the default account」 has ONE meaning here:
    # a blank from an old caller and the name ``default`` are the same login, and the checks
    # below cannot be stepped around by spelling it the other way.
    account = CookieManager.key(body.get('account'))
    to = CookieManager.key(body.get('to'))
    if not CookieManager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if body.get('to') is None or str(body.get('to')).strip() == '':
        return jsonify({'ok': False, 'error': t('api.cookieRenameEmptyTarget')}), 400
    if not CookieManager.is_account(account) or not CookieManager.is_account(to):
        return jsonify({'ok': False, 'error': t('api.cookieRenameBadName')}), 400
    if account == CookieManager.DEFAULT_ACCOUNT:
        return jsonify({'ok': False, 'error': t('api.cookieRenameDefault')}), 400
    if to == CookieManager.DEFAULT_ACCOUNT:
        # Renaming ONTO the default name would aim a named account at the platform's own
        # file — the same topology problem as renaming the default away from it, seen from
        # the other side, and it must be said rather than quietly overwriting a login.
        return jsonify({'ok': False, 'error': t('api.cookieRenameTaken')}), 409
    if account == to:
        return jsonify({'ok': False, 'error': t('api.cookieRenameSameName')}), 400
    manager = CookieManager(Config.COOKIE_DIR)
    if not manager.exists(platform, account):
        return jsonify({'ok': False, 'error': t('api.cookieRenameNoSource')}), 404
    try:
        # The device first: a profile that will not move (a browser is inside it, or the name
        # is taken) must stop the file too — otherwise the new label is born pointing at a
        # directory that is still called the old one, and the next crawl opens a stranger.
        profile_moved = profiles.rename_account(platform, account, to)
        manager.rename(platform, account, to)
    except ValueError as e:
        return jsonify({'ok': False, 'error': _rename_refusal(e)}), 409
    except OSError as e:
        return jsonify({'ok': False, 'error': t('api.cookieRenameFailed', err=str(e)[:160])}), 500
    # A rename changes which file answers 「does this account have a login」, so a cached
    # verdict about the old name is now a statement about a file that is not there.
    preflight.invalidate(platform)
    return jsonify(
        {
            'ok': True,
            'platform': platform,
            'account': to,
            'profile_moved': profile_moved,
            # Which of the two sentences, by what actually moved: an account whose browser was
            # never opened has no directory to take along, and 「一起搬过去了」 would be a claim
            # about a device that does not exist.
            'message': t(
                'cookie.renamed' if profile_moved else 'cookie.renamedFileOnly',
                platform=platform,
                old=manager.label_of(account),
                new=manager.label_of(to),
            ),
        }
    )


def _rename_refusal(error: ValueError) -> str:
    """Say which refusal happened, because the three want three different actions.

    Waiting for a crawl, choosing another name and finding the file gone are not one
    「失败」 — and the ValueError text is this module's own (see ``CookieManager.rename`` and
    ``profiles.rename_account``), so matching it is matching code, not a site.
    """
    text = str(error)
    if 'in use' in text:
        return t('api.cookieRenameBusy')
    if 'already exists' in text:
        return t('api.cookieRenameTaken')
    if 'Invalid account' in text or 'cannot be renamed' in text:
        return t('api.cookieRenameBadName')
    return t('api.cookieRenameFailed', err=text[:160])


@bp.route('/api/cookies/delete', methods=['POST'])
def delete_cookies():
    """Throw away the saved cookie *file* for one platform.

    The honest scope matters here, and it is why the response carries
    ``profile_holds``: a file is only what a *throwaway* browser is planted from.
    A platform profile that has logged in keeps its own session in
    ``data/chrome_profile/<platform>``, and deleting the snapshot does not sign that
    device out (see :mod:`sessions.profiles`, where the file is imported once and
    never planted again). Saying 「已删除，已退出登录」 would send the user to re-login
    over a session that is still live, and hide the case that genuinely needs a
    profile reset.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform', ''))
    account = str(data.get('account') or '').strip()
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if account and not cookie_manager.is_account(account):
        return jsonify({'ok': False, 'error': t('api.badAccount', account=account)}), 400
    if not cookie_manager.exists(platform, account):
        # Not a silent success: the panel asked to remove something that is not
        # there, and 「已删除」 would leave the user believing a stale file was replaced.
        return jsonify({'ok': False, 'error': t('cookie.delete.none', platform=platform)}), 404
    try:
        cookie_manager.delete(platform, account)
    except OSError as e:
        logger.exception(t('cookie.delete.failed', err=str(e)[:120]))
        return jsonify({'ok': False, 'error': str(e)}), 500
    preflight.invalidate(platform)
    holds = bool(profiles.is_enabled() and profiles.is_used(platform, account))
    message = t('cookie.deleted', platform=platform)
    if holds:
        # ``CookieManager.delete`` already logged the deletion, and that line reaches
        # the console as well — so the handler adds only the fact that line cannot
        # carry, instead of narrating the whole answer a second time.
        extra = t('cookie.delete.profileHolds', platform=platform)
        message += '\n' + extra
        add_log(extra)
    return jsonify({'ok': True, 'message': message, 'profile_holds': holds})


@bp.route('/api/profiles/delete', methods=['POST'])
def delete_profile():
    """Throw away one account's browser PROFILE directory — the device, not the cookie file.

    This is the counterpart the cookie-delete cannot be: ``delete_cookies`` removes only the
    snapshot a throwaway browser is planted from, and a platform crawled inside its own profile
    keeps its live session in ``data/chrome_profile/<platform>[/<account>]`` — so signing that
    device out needs this separate action. The two stay independent by design: a user may retire
    the saved cookie and keep logging the profile in, or reset the device and keep the file.

    Every refusal names itself, and the **default** account is refused structurally (the panel
    disables it too): its browser data is the platform root that nests every named account, so
    「delete」 there would silently wipe them all — the same reason ``rename_cookie_account``
    refuses to rename it. A live browser holding the directory is refused so a running crawl is
    never pulled out from under.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform') or '').strip()
    account = CookieManager.key(data.get('account'))
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if not CookieManager.is_account(account):
        bad = str(data.get('account') or '')
        return jsonify({'ok': False, 'error': t('api.profileDeleteBadName', account=bad)}), 400
    if account == CookieManager.DEFAULT_ACCOUNT:
        return jsonify({'ok': False, 'error': t('api.profileDeleteDefault', platform=platform)}), 400
    try:
        result = profiles.delete(platform, account)
    except ValueError as e:
        text = str(e)
        if 'in use' in text:
            return jsonify({'ok': False, 'error': t('api.profileDeleteBusy', platform=platform, account=account)}), 409
        return jsonify({'ok': False, 'error': t('api.profileDeleteDefault', platform=platform)}), 400
    except OSError as e:
        logger.exception(t('cookie.delete.failed', err=str(e)[:120]))
        return jsonify({'ok': False, 'error': str(e)}), 500
    if result == 'absent':
        # Not a silent success: the panel asked to remove a device that is not there, and
        # 「已删除」 would report a reset that did not happen.
        return jsonify({'ok': False, 'error': t('cookie.profileDelete.none', platform=platform, account=account)}), 404
    # The device that held a live session is gone, so a cached "does this account have a login"
    # verdict about that profile is now a statement about a browser that no longer exists.
    preflight.invalidate(platform)
    add_log(t('cookie.profileDeleted', platform=platform, account=account))
    return jsonify(
        {
            'ok': True,
            'platform': platform,
            'account': account,
            'profile_deleted': True,
            'message': t('cookie.profileDeleted', platform=platform, account=account),
        }
    )


_COOKIE_JOB_LOCK = threading.Lock()
_COOKIE_JOB = {
    'active': False,
    # Which single-flight action owns the browser: a login (waits for the user
    # to press Done) or a verification (runs to completion by itself). The panel
    # shows its "Done — I logged in" button only for the first.
    'kind': '',
    'platform': '',
    # The account the live job owns its browser AS — carried so a second request
    # can be refused with the SESSION that is busy, not just the platform.
    'account': '',
    'phase': '',  # login: starting → waiting → saved | cancelled | error; verify: verifying → verified | error
    'error': '',
    'count': 0,
    'entry': '',  # the URL the browser was actually sent to
    'facts': {},  # verify: what the stored cookie unlocked
    'lines': [],  # verify: those facts, already in the user's language
    'cancel': threading.Event(),
    'confirm': threading.Event(),
}


def _cookie_login_worker(platform: str, wait_seconds: int, entry_url: str = '', lang: str = '', account: str = ''):
    """Drive one login window from the request thread to its own daemon.

    ``set_lang`` is the first thing it does: thread-locals are not inherited, so
    without it every line this worker wrote into the console panel was Chinese
    whatever language the interface was showing — the run worker pins its own
    language, and these two silently did not.

    The request thread used to sleep for the whole wait (up to 600 s), so any
    proxy or tab timeout turned a perfectly good login into a broken fetch and
    an orphaned browser. Progress lives in _COOKIE_JOB now; the panel polls it.

    *entry_url* overrides which page opens: some platforms only plant the
    cookies the crawler needs while sitting on a page the user picks (a note or
    video link), so the panel lets that link be pasted in — validated against
    the crawler's own host list before it is ever opened.

    *account* is which login of the platform this window captures: the browser
    opens that account's profile and the jar is saved to that account's file.
    Blank is the platform's default session — the only one that existed before
    multi-account.
    """
    job = _COOKIE_JOB
    crawler = None
    set_lang(lang)
    try:
        # ``for_login`` is the point of this window: a human reads it. The crawler
        # default blocks images to save seconds per navigation, and the QR code a
        # user must scan is an ``<img>`` — with the blocker on, the panel opened a
        # window that could not be completed at all.
        crawler = get_crawler(platform, headless=False, cookie_dir=Config.COOKIE_DIR, for_login=True, account=account)
        url = entry_url or crawler.login_url
        if not url:
            raise ValueError(t('api.unsupportedPlatform', platform=platform))
        crawler.driver.get(url)
        job['entry'] = url
        # One line for one event, carrying both facts it was split across: which
        # platform's window opened, how long it will wait, and the page it landed on
        # (the entry link is what a user checks when the window shows something
        # unexpected). Two consecutive console lines said one thing each.
        add_log(t('wf.browser_opened', platform=platform, n=wait_seconds, url=url))
        job['phase'] = 'waiting'
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if job['cancel'].is_set():
                job['phase'] = 'cancelled'
                add_log(t('cookie.jobCancelled', platform=platform))
                return
            if job['confirm'].is_set():
                break
            try:
                # Cheap liveness probe: the moment the user closes the window
                # every call raises, and waiting on would just burn the rest
                # of the deadline pretending a login can still happen.
                _ = crawler.driver.window_handles
            except Exception:
                job['phase'] = 'error'
                job['error'] = t('cookie.windowClosed')
                add_log(t('cookie.windowClosed'))
                return
            time.sleep(1.0)
        # Confirmed early, or the deadline passed: capture best-effort either
        # way — people log in and simply forget to press the button.
        # Pull the browser back to the platform's own page first. A login that
        # ended on the identity provider (accounts.google.com, facebook.com)
        # would otherwise be read *there*, which both misses the session the crawl
        # needs and stores someone else's cookies under this platform's name. A
        # dead window raises, which the outer handler reports as it always has.
        crawler.driver.get(crawler.login_url or url)
        cookies, dropped = retain_for_platform(crawler.driver.get_cookies(), crawler_hosts(crawler))
        if dropped:
            add_log(t('cookie.droppedForeign', platform=platform, n=dropped))
        if not cookies:
            job['phase'] = 'error'
            job['error'] = t('cookie.noCookies')
            add_log(t('cookie.noCookies'))
            return
        cookie_manager.save(platform, cookies, account)
        # This jar was read OUT OF the platform's own profile browser, so the profile is not behind
        # the file: without this line the panel would go on offering 「把 Cookie 更新进 Profile」,
        # a button that here would overwrite a live session with a copy of itself. Only when a
        # profile really exists — a run that chose 本次不用 Profile has no live session to spare.
        if profiles.is_enabled() and profiles.is_used(platform, account):
            profiles.remember_cookie(platform, cookie_manager.path_for(platform, account), account)
        # A capture replaces the session, so any verdict the pre-run gate cached about
        # the old one is now not just stale but wrong in the dangerous direction.
        preflight.invalidate(platform)
        job['count'] = len(cookies)
        job['phase'] = 'saved'
        add_log(t('wf.cookies_generated', platform=platform, n=len(cookies)))
    except Exception as e:
        job['phase'] = 'error'
        job['error'] = str(e)[:300]
        # One line, one reason: the logger call already reaches the console (see the
        # cookie-save handler above), so the extra add_log said 「生成 Cookie 失败」 twice.
        logger.exception(t('misc.cookie_gen_failed', err=str(e)[:120]))
    finally:
        _close_login_browser(crawler)
        with _COOKIE_JOB_LOCK:
            job['active'] = False


@bp.route('/api/cookies/generate', methods=['POST'])
def generate_cookies():
    """Open a login browser as a single-flight background job.

    One login at a time, machine-wide: two windows racing on the same profile
    (or on the user's attention) saved half-cookies and confusion. A second
    request is refused with the platform of the live one.

    Refused outright on a cloud host: this route opens a window **for a person to log
    into**, and there is nobody at this server's screen. The panel hides the button, but a
    stale tab or a hand-written POST still reaches here, and the answer they get has to
    say why rather than hang on a browser nobody can see.
    """
    if Config.CLOUD_MODE:
        return jsonify({'ok': False, 'error': t('api.cloudNoLoginWindow')}), 400
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform', ''))
    account = str(data.get('account') or '').strip()
    if not platform:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if account and not cookie_manager.is_account(account):
        # The window will one day SAVE under this name — it enters a filename.
        return jsonify({'ok': False, 'error': t('api.badAccount', account=account)}), 400
    wait_seconds = _safe_int(data.get('wait_seconds'), 120, minimum=10, maximum=600)
    # A cookie-only platform still needs a real login page; anything without one
    # would open a browser at about:blank and capture nothing.
    # A link the user pasted, if any. It has to belong to this platform: the
    # browser is driven with their real session, and cookies are saved per
    # platform file — opening some other site here would store that site's
    # session under, say, "zhihu" and the crawl would carry it to Zhihu.
    requested = str(data.get('url') or '').strip()
    entry_url = normalize_entry_url(requested, cookie_hosts(platform))
    entry_rejected = bool(requested) and not entry_url

    with _COOKIE_JOB_LOCK:
        if _COOKIE_JOB['active']:
            return (
                jsonify(
                    {
                        'ok': False,
                        'busy': True,
                        'platform': _COOKIE_JOB['platform'],
                        'account': _COOKIE_JOB['account'],
                        'error': t('api.cookieBusy', platform=_COOKIE_JOB['platform']),
                    }
                ),
                409,
            )
        _COOKIE_JOB.update(
            active=True, kind='login', platform=platform, account=account, phase='starting', error='', count=0
        )
        _COOKIE_JOB['entry'] = ''
        _COOKIE_JOB['facts'] = {}
        _COOKIE_JOB['lines'] = []
        _COOKIE_JOB['cancel'].clear()
        _COOKIE_JOB['confirm'].clear()
    threading.Thread(
        target=_cookie_login_worker, args=(platform, wait_seconds, entry_url, get_lang(), account), daemon=True
    ).start()
    payload = {'ok': True, 'message': t('cookie.started'), 'entry': entry_url or ''}
    if entry_rejected:
        # Say so instead of quietly opening somewhere else: the user believes
        # they are logging in for one purpose and the browser shows another.
        payload['entry_rejected'] = True
        payload['entry_note'] = t('cookie.entryRejected', platform=platform)
        add_log(payload['entry_note'])
    return jsonify(payload), 202


@bp.route('/api/cookies/generate/status', methods=['GET'])
def cookie_generate_status():
    return jsonify(
        {
            'ok': True,
            'active': _COOKIE_JOB['active'],
            'kind': _COOKIE_JOB['kind'],
            'platform': _COOKIE_JOB['platform'],
            'phase': _COOKIE_JOB['phase'],
            'error': _COOKIE_JOB['error'],
            'count': _COOKIE_JOB['count'],
            'entry': _COOKIE_JOB['entry'],
            'facts': _COOKIE_JOB['facts'],
            'lines': _COOKIE_JOB['lines'],
        }
    )


def _verify_lines(platform: str, facts: dict) -> list:
    """Turn one diagnosis into the lines the panel shows.

    Three answers, not the two this had. ``login_wall`` or 可用 called a risk-control
    page 可用 — the mirror image of the lie the pre-run gate refuses (see
    ``sessions.preflight``): a page that answered with a captcha says nothing about
    the cookie, in either direction.
    """
    state = preflight.classify_probe(facts)
    lines = [t('cookie.verify.checkedUrl', url=str(facts.get('url') or ''))]
    if facts.get('unreachable'):
        # Before the three states below, and as its own line: 「无法核对」 is true but
        # useless here, because what could not be checked was not the cookie — the page
        # the browser was asked to open never arrived.
        lines.append(t('cookie.verify.unreachable', platform=platform))
    elif state == preflight.EXPIRED:
        lines.append(t('cookie.verify.loginWall', platform=platform))
    elif state == preflight.VALID:
        lines.append(t('cookie.verify.ok', platform=platform))
    else:
        lines.append(t('cookie.verify.unclear', platform=platform))
    if Config.CLOUD_MODE:
        # The worker above asks for a visible window because a site's risk control treats the two
        # differently — and on a server there is no display to honour that ask (``get_crawler`` clamps
        # every cloud crawl to headless). Saying nothing would let a captcha page be read as a dead
        # cookie, which is the diagnosis this project refuses to guess at.
        lines.append(t('cookie.verify.cloudHeadless'))
    return lines


def _cookie_verify_worker(platform: str, url: str, lang: str = '', account: str = ''):
    """Probe the stored cookie against the live site and report what it unlocks.

    Visible by design: this machine's risk control treats a headless content
    page differently from a real window (Zhihu in particular), and a diagnosis
    that blamed the cookie for a headless block would send the user to log in
    again for nothing.

    ``lang`` is handed in by the request thread and pinned here for the same
    reason the run worker does it: a daemon thread starts with a fresh thread-local,
    so without this the probe's own lines and its failure were Chinese in an English
    interface.
    """
    job = _COOKIE_JOB
    crawler = None
    set_lang(lang)
    try:
        # Whatever this probe sees is newer than anything the pre-run gate cached, so
        # the stale verdict goes before the browser opens, not after.
        preflight.invalidate(platform)
        # ``for_login`` because this window is shown to a person, and a person can be
        # sent there by an expired cookie: the probe lands on the login page, whose QR
        # code is an ``<img>``. Blocked, the diagnosis 「cookie 已失效，去登录」 pointed at
        # a window where logging in was impossible.
        crawler = get_crawler(platform, headless=False, cookie_dir=Config.COOKIE_DIR, for_login=True, account=account)
        facts = crawler.diagnose(url)
        facts['risk_blocked'] = bool(getattr(crawler, 'risk_blocked', False))
        lines = _verify_lines(platform, facts)
        with _COOKIE_JOB_LOCK:
            job['facts'] = facts
            job['lines'] = lines
            job['entry'] = str(facts.get('url') or '')
            job['phase'] = 'verified'
        if not url:
            # A manual 验证 on the platform's own page is the same measurement the
            # pre-run gate would pay for, so it refreshes that answer: the user who
            # came here from the block dialog should not have to prove the fix twice.
            # With a pasted entry URL it does not — the verdict is about that page, not
            # about the address the gate would visit.
            preflight.record(platform, facts, account)
        for line in lines:
            add_log(line)
    except Exception as e:
        # A VERIFICATION failure, so it must not be announced as 「生成 Cookie 失败」 —
        # the user asked no cookie to be generated here, and the line beside it already
        # said 验证失败. One attributed line carries the reason; the logger call is what
        # reaches the console (and the traceback reaches the log file).
        logger.exception(t('cookie.verifyFailed', err=str(e)[:120]))
        with _COOKIE_JOB_LOCK:
            job['phase'] = 'error'
            job['error'] = str(e)[:300]
    finally:
        _close_login_browser(crawler)
        with _COOKIE_JOB_LOCK:
            job['active'] = False


@bp.route('/api/cookies/verify', methods=['POST'])
def verify_cookies():
    """Ask the platform, with the saved cookie, whether it still lets us in.

    Refused outright when no cookie is stored: opening a browser to discover
    that would only produce a wall that looks like a failed check.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform', ''))
    account = str(data.get('account') or '').strip()
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if account and not cookie_manager.is_account(account):
        return jsonify({'ok': False, 'error': t('api.badAccount', account=account)}), 400
    if not cookie_manager.exists(platform, account):
        return jsonify({'ok': False, 'error': t('cookie.verify.noCookie', platform=platform)}), 400
    requested = str(data.get('url') or '').strip()
    target = normalize_entry_url(requested, cookie_hosts(platform))
    if requested and not target:
        return jsonify({'ok': False, 'error': t('cookie.entryRejected', platform=platform)}), 400

    with _COOKIE_JOB_LOCK:
        if _COOKIE_JOB['active']:
            return (
                jsonify(
                    {
                        'ok': False,
                        'busy': True,
                        'platform': _COOKIE_JOB['platform'],
                        'account': _COOKIE_JOB['account'],
                        'error': t('api.cookieBusy', platform=_COOKIE_JOB['platform']),
                    }
                ),
                409,
            )
        _COOKIE_JOB.update(
            active=True, kind='verify', platform=platform, account=account, phase='verifying', error='', count=0
        )
        _COOKIE_JOB['entry'] = ''
        _COOKIE_JOB['facts'] = {}
        _COOKIE_JOB['lines'] = []
        _COOKIE_JOB['cancel'].clear()
        _COOKIE_JOB['confirm'].clear()
    threading.Thread(target=_cookie_verify_worker, args=(platform, target, get_lang(), account), daemon=True).start()
    return jsonify({'ok': True, 'message': t('cookie.verifying')}), 202


@bp.route('/api/cookies/generate/confirm', methods=['POST'])
def cookie_generate_confirm():
    """'I finished logging in' — capture and save the cookies now."""
    with _COOKIE_JOB_LOCK:
        if not _COOKIE_JOB['active'] or _COOKIE_JOB['kind'] != 'login':
            return jsonify({'ok': False, 'error': t('api.noCookieJob')}), 400
        _COOKIE_JOB['confirm'].set()
    return jsonify({'ok': True})


@bp.route('/api/cookies/generate/cancel', methods=['POST'])
def cookie_generate_cancel():
    with _COOKIE_JOB_LOCK:
        if not _COOKIE_JOB['active'] or _COOKIE_JOB['kind'] != 'login':
            return jsonify({'ok': False, 'error': t('api.noCookieJob')}), 400
        _COOKIE_JOB['cancel'].set()
    return jsonify({'ok': True})


@bp.route('/api/browser/profiles/template', methods=['POST'])
def build_profile_template():
    """One blank Chrome, once, to make the directory every new account starts from.

    On a cloud host this is how a device comes into the world at all: the button that
    used to create one by logging in is not offered there. The cookie-save path calls
    the same function by itself (see :func:`template.ensure_profile_template`), so this
    route exists for an operator who wants to rebuild it now — and for a machine where
    no cookie has been pasted yet.
    """
    body = _json_body()
    if body is None:
        return _bad_body()
    force = as_bool(body.get('force'))
    result = ensure_profile_template(force=force)
    # 502, not 200-with-a-lie: the directory was asked for and does not exist, and the
    # reason (no chromedriver, Chrome refused) is what the caller has to act on.
    return jsonify(result), (200 if result.get('ok') else 502)


@bp.route('/api/browser/profiles', methods=['GET'])
def get_browser_profiles():
    """One row per platform that has a login session at all.

    WeChat is deliberately absent: its article bodies need no login (there is no
    cookie row for it anywhere in this app), so a browser profile would be a
    directory of nothing — and a row in this table reads as "you should log in here".

    Three things can only be checked from the request side:

    * the payload covers **every platform the cookie panel can sign into**, in matrix
      order (a platform missing here is one whose state the user cannot see);
    * `recommended` is read off the crawl matrix, not from a second list this endpoint
      keeps by hand;
    * a directory is reported as *existing* only after something created it, and as
      *imported* only after a cookie actually went in. Those two booleans are the whole
      guidance sentence in the panel.
    """
    rows = {'ok': True, 'enabled': profiles.is_enabled(), 'root': profiles.root_dir()}
    # The template's own row, because "no new account can be made without it" is the
    # thing a cloud operator needs to see before they paste a cookie. The walk is over a
    # first-run skeleton (hundreds of files at most), not over a used profile — which is
    # why this may check the contents while the per-account rows below pass ``size=False``.
    rows['template'] = {
        'exists': profiles.template_exists(),
        'pristine': not profiles.find_session_material(),
    }
    rows['profiles'] = []
    for cap in capabilities.CAPABILITIES:
        platform = cap.platform
        if not CookieManager.is_supported(platform):
            continue
        # The ONE filename rule, from CookieManager — splicing ``{platform}_cookies.json`` here
        # was a second spelling of where a login lives, and it can only ever name the default
        # account: the panel would say 「no cookie」 about an account whose file it never looked at.
        saved = CookieManager(Config.COOKIE_DIR).path_for(platform, '')
        rows['profiles'].append(
            profiles.status(
                platform,
                recommended=cap.profile_recommended,
                has_cookie=os.path.isfile(saved),
                # The path, not the contents: this is what lets the panel say "the file you
                # saved is not the session this profile holds" without reading a cookie.
                cookie_path=saved,
            )
        )
    return jsonify(rows)
