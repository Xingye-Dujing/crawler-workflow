"""Login for a shared (cloud) host: one password, a signed session cookie, and a request gate.

The server is a local single-user tool by design, so the login exists for the one shape that is
not local: ``python app.py cloud`` puts the same state — saved crawl sessions, every dataset, the
run ledger — behind a public address. Without a login a stranger holding that address could read
all of it and could start crawls on the owner's accounts.

Why a session cookie rather than HTTP Basic: the page needs a visible way out (the 退出登录 button
in the top menu), and a Basic credential cannot be forgotten by the page — the browser re-sends it
until it is closed. The session is non-permanent on purpose: closing the browser ends it, which is
the right default for a shared host.

Named refusals, never guesses:

* no password configured → no login at all (the local default). Cloud mode is the exception:
  ``app.py`` refuses to start without one, because a public server that quietly serves everyone is
  the exact bug this module exists to prevent.
* cloud mode also refuses the built-in ``SECRET_KEY``: the session cookie is signed with it, and a
  published key lets anyone mint a logged-in session.
* a missing or expired session answers 401 to ``/api/*`` (with ``X-Auth-Required: 1``, so the page
  can tell this 401 from a node refusal) and a redirect to ``/login`` for a page.
"""

import hashlib
import hmac
import html
import secrets
import threading
import time
from urllib.parse import quote, urlsplit

from core.config import Config
from flask import Blueprint, Response, jsonify, redirect, request, session

from i18n import get_lang, normalize, set_lang, t

bp = Blueprint('auth', __name__)

#: Where a request goes after login when it named no (safe) destination.
DEFAULT_NEXT = '/'

#: A failed attempt waits this long. Not a lockout — just enough that an online guesser pays for
#: each try at the same rate a slow network would impose anyway on a shared server.
FAILED_ATTEMPT_DELAY = 0.3

_LOGIN_PAGE = """<!doctype html>
<html lang="@@LANG@@">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@ · 采析绘</title>
<style>
  :root { color-scheme: light dark; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    font: 15px/1.55 system-ui, -apple-system, 'Segoe UI', 'Noto Sans CJK SC', sans-serif;
    background: #f4f5f7; color: #1c1e21;
  }
  @media (prefers-color-scheme: dark) { body { background: #16181c; color: #e8eaed; } }
  form {
    width: min(340px, calc(100vw - 32px)); padding: 28px 26px 24px; border-radius: 12px;
    background: #fff; box-shadow: 0 8px 30px rgba(0, 0, 0, .08);
  }
  @media (prefers-color-scheme: dark) { form { background: #212429; box-shadow: none; border: 1px solid #2e3238; } }
  h1 { margin: 0 0 6px; font-size: 19px; font-weight: 650; }
  p.hint { margin: 0 0 18px; font-size: 13px; opacity: .72; }
  label { display: block; margin: 0 0 12px; font-size: 13px; }
  input {
    display: block; width: 100%; box-sizing: border-box; margin-top: 5px; padding: 8px 10px;
    border: 1px solid #c9ccd1; border-radius: 7px; font: inherit; background: transparent; color: inherit;
  }
  @media (prefers-color-scheme: dark) { input { border-color: #3a3f46; } }
  button {
    width: 100%; margin-top: 6px; padding: 9px 10px; border: 0; border-radius: 7px; cursor: pointer;
    font: inherit; font-weight: 600; background: #2f6fed; color: #fff;
  }
  button:hover { background: #2a63d4; }
  p.err {
    margin: 0 0 14px; padding: 8px 10px; border-radius: 7px; font-size: 13px;
    background: #fdecec; color: #a12a2a;
  }
  @media (prefers-color-scheme: dark) { p.err { background: #3a2325; color: #f0a8a8; } }
</style>
</head>
<body>
<form method="post" action="/login">
  <h1>@@TITLE@@</h1>
  <p class="hint">@@HINT@@</p>
  @@ERROR@@
  <input type="hidden" name="next" value="@@NEXT@@">
  <label>@@USER_LABEL@@
    <input name="username" autocomplete="username" required autofocus value="@@USER_VALUE@@">
  </label>
  <label>@@PASSWORD_LABEL@@
    <input name="password" type="password" autocomplete="current-password" required>
  </label>
  <button type="submit">@@SIGN_IN@@</button>
</form>
</body>
</html>
"""


# ─── Configuration questions ───────────────────────────────────


def auth_enabled() -> bool:
    """Whether this process asks for a login. A password is the only switch, read at request time."""
    return bool(str(Config.AUTH_PASSWORD or '').strip())


def startup_error() -> str | None:
    """The named refusal ``app.py`` raises at import time, or ``None`` when the shape is safe.

    Cloud mode is the only shape that reaches strangers, so it is the only one that requires a
    login. Any host that DOES have a login — cloud or a LAN box with a password — must sign its
    session cookie with a key of its own: the shipped default is public, and a published key lets
    anyone mint a logged-in session.
    """
    if not Config.CLOUD_MODE:
        if auth_enabled() and Config.SECRET_KEY == Config.DEFAULT_SECRET_KEY:
            return t('auth.loginNeedsSecretKey')
        return None
    if not auth_enabled():
        return t('auth.cloudNeedsPassword')
    if Config.SECRET_KEY == Config.DEFAULT_SECRET_KEY:
        return t('auth.loginNeedsSecretKey')
    return None


# ─── Credentials and the gate ──────────────────────────────────


def _same(left, right) -> bool:
    return hmac.compare_digest(str(left).encode('utf-8'), str(right).encode('utf-8'))


def check_credentials(user, password) -> bool:
    """Both halves compared every time — a short circuit on the username would say which was right."""
    if not auth_enabled():
        return False
    user_ok = _same(user or '', Config.AUTH_USER or '')
    password_ok = _same(password or '', Config.AUTH_PASSWORD or '')
    return user_ok and password_ok


def safe_next(target) -> str:
    """Only a path on THIS server may be a post-login destination.

    ``//evil.example`` parses as a host, and ``/\\\\evil`` is read as a path by some clients — both
    would turn the login form into an open redirect.
    """
    text = str(target or '').strip()
    if not text.startswith('/') or text.startswith('//') or '\\' in text:
        return DEFAULT_NEXT
    parts = urlsplit(text)
    if parts.scheme or parts.netloc:
        return DEFAULT_NEXT
    return text


def session_ok() -> bool:
    """A live login for the credentials the server holds NOW.

    The cookie carries a random session id, not a claim; whether that id is still open is this
    process's answer. Two consequences are the point of doing it this way:

    * **logout really ends the login.** A signed cookie alone cannot be taken back — replaying it
      after 退出登录 would still open the app, which is what a copied cookie is.
    * **a password change revokes every session already handed out**: the id's stamp no longer
      matches the credential in force.

    The registry lives in this process (a local single-user server has one), so a restart signs
    everyone out — the cost of not adding a session table to ``runs.db`` for one login.
    """
    return session.get('auth') is True and _SESSIONS.valid(session.get('sid'))


def _credential_stamp() -> str:
    key = str(Config.SECRET_KEY or '').encode('utf-8')
    message = f'{Config.AUTH_USER or ""}\0{Config.AUTH_PASSWORD or ""}'.encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


class _SessionRegistry:
    """Open session ids, in insertion order, each stamped with the credential that opened it."""

    #: A cap nobody reaches by hand; it exists so a script cannot grow the dict forever.
    LIMIT = 1000

    def __init__(self):
        self._lock = threading.Lock()
        self._open: dict[str, str] = {}

    def _prune(self, stamp: str) -> None:
        """Drop ids opened under another credential, and the oldest beyond the cap. Caller holds the lock."""
        for sid in [key for key, value in self._open.items() if value != stamp]:
            del self._open[sid]
        while len(self._open) > self.LIMIT:
            del self._open[next(iter(self._open))]

    def open(self) -> str:
        stamp = _credential_stamp()
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._prune(stamp)
            self._open[sid] = stamp
        return sid

    def valid(self, sid) -> bool:
        stamp = _credential_stamp()
        with self._lock:
            return self._open.get(str(sid or '')) == stamp

    def close(self, sid) -> None:
        with self._lock:
            self._open.pop(str(sid or ''), None)


_SESSIONS = _SessionRegistry()


def gate():
    """The ``before_request`` answer: ``None`` to continue, or the refusal response."""
    if not auth_enabled() or session_ok() or request.endpoint == 'auth.login':
        return None
    if request.path.startswith('/api/'):
        response = jsonify({'ok': False, 'error': t('auth.required')})
        response.status_code = 401
    else:
        # A page keeps its address so the login lands back where it was asked for.
        target = request.full_path.rstrip('?') if request.method == 'GET' else DEFAULT_NEXT
        response = redirect('/login?next=' + quote(safe_next(target), safe=''))
    response.headers['X-Auth-Required'] = '1'
    response.headers['Cache-Control'] = 'no-store'
    return response


# ─── Routes ────────────────────────────────────────────────────


def _request_lang() -> str:
    """The page's language: an explicit choice first, then the browser's own preference."""
    if request.args.get('lang') or request.headers.get('X-Lang'):
        return get_lang()
    return normalize(request.accept_languages.best_match(('zh', 'en')))


def _page(nxt: str, error: str, user: str = '') -> str:
    def escape(value) -> str:
        return html.escape(str(value or ''), quote=True)

    fields = {
        '@@LANG@@': escape(_request_lang()),
        '@@TITLE@@': escape(t('auth.loginTitle')),
        '@@HINT@@': escape(t('auth.loginHint')),
        '@@USER_LABEL@@': escape(t('auth.username')),
        '@@PASSWORD_LABEL@@': escape(t('auth.password')),
        '@@SIGN_IN@@': escape(t('auth.signIn')),
        '@@NEXT@@': escape(nxt),
        '@@USER_VALUE@@': escape(user),
        '@@ERROR@@': f'<p class="err">{escape(error)}</p>' if error else '',
    }
    body = _LOGIN_PAGE
    for token, value in fields.items():
        body = body.replace(token, value)
    return body


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if not auth_enabled():
        return redirect(DEFAULT_NEXT)
    nxt = safe_next(request.values.get('next'))
    if session_ok():
        return redirect(nxt)
    error = ''
    user = ''
    if request.method == 'POST':
        user = str(request.form.get('username') or '')
        if check_credentials(user, request.form.get('password')):
            # A new session id for the new privilege, so a cookie planted before logging in is
            # not the one that carries the login.
            _SESSIONS.close(session.get('sid'))
            session.clear()
            session['auth'] = True
            session['sid'] = _SESSIONS.open()
            return redirect(nxt)
        time.sleep(FAILED_ATTEMPT_DELAY)
        error = t('auth.badCredentials')
    previous = get_lang()
    try:
        set_lang(_request_lang())
        body = _page(nxt, error, user)
    finally:
        set_lang(previous)
    return Response(
        body,
        status=401 if error else 200,
        mimetype='text/html',
        headers={'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer'},
    )


@bp.route('/logout', methods=['POST'])
def logout():
    """POST only: a cross-site image or link must not be able to end someone's session.

    The id is closed on the server, so the cookie stops working even if a copy of it is replayed —
    clearing only the browser's copy would leave a signed cookie that still opens the app.
    """
    _SESSIONS.close(session.get('sid'))
    session.clear()
    return redirect('/login' if auth_enabled() else DEFAULT_NEXT)
