"""Login for a shared (cloud) host: accounts in ``data/accounts.db``, a signed session cookie and
a request gate.

The server is a local single-user tool by design, so the login exists for the one shape that is
not local: ``python app.py cloud`` puts the same state — saved crawl sessions, every dataset, the
run ledger — behind a public address. Accounts isolate that state: each one owns
``data/users/<user_id>/`` (``runtime/paths.py``) and the gate is what binds the identity every
lower layer asks for (``runtime/account_context.py``).

Named refusals, never guesses:

* no account registry and no password → no login at all (the local default).
* cloud mode refuses to start without a way to seed the first administrator, and always refuses
  the built-in ``SECRET_KEY`` (``services.accounts.service.startup_error``).
* a missing or expired session answers 401 to ``/api/*`` (with ``X-Auth-Required: 1``, so the page
  can tell this 401 from a node refusal) and a redirect to ``/login`` for a page.
* a session that still owes a password change may read the shell and change the password, and is
  refused (403 + ``X-Password-Change-Required``) everywhere else.
* a mutating API call must carry the session's CSRF token in ``X-CSRF-Token``; the login form
  carries its own one-shot token, so a foreign page can neither act as a signed-in user nor sign
  someone into an account the caller controls.

This module is the ONLY place that imports ``flask.session`` (``tests/api/test_privacy_leaks.py``
pins that): every other module asks :func:`current_user` / :func:`current_sid`.
"""

import hmac
import html
import secrets
import time
from urllib.parse import quote, urlsplit

from flask import Blueprint, Response, jsonify, redirect, request, session
from runtime import account_context

from i18n import get_lang, normalize, set_lang, t
from services.accounts.errors import AccountError
from services.accounts.service import accounts_mode, get_account_service
from services.accounts.service import startup_error as _accounts_startup_error

bp = Blueprint('auth', __name__)

#: Where a request goes after login when it named no (safe) destination.
DEFAULT_NEXT = '/'

#: A failed attempt waits this long. The account registry's own lockout counts attempts; this
#: delay merely makes an online guesser pay the same rate a slow network would impose anyway.
FAILED_ATTEMPT_DELAY = 0.3

#: Methods that change state by definition; they must carry the CSRF token.
_MUTATING = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

#: What a session that still owes a password change may reach: the shell it needs to render the
#: dialog, and the endpoint that ends the debt.
_MUST_CHANGE_ALLOWED = frozenset(
    {
        '/login',
        '/logout',
        '/api/account/me',
        '/api/account/password',
        '/api/config',
    }
)

_LOGIN_PAGE = """<!doctype html>
<html lang="@@LANG@@">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@ · 采析绘</title>
<script>
(function () {
  /* The login page is served before /css is reachable, so the design tokens live here. The
     stored theme choice (Settings → 主题, same localStorage key app.js writes) still wins;
     "auto" falls back to the OS scheme, which is also how the rest of the app resolves it. */
  var choice = 'auto';
  try {
    var stored = JSON.parse(localStorage.getItem('crawler_settings') || '{}');
    choice = (stored && stored.theme) || 'auto';
  } catch (e) { /* a broken draft is not this page's problem */ }
  var dark = choice === 'dark' || (choice !== 'light' && window.matchMedia
    && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
</script>
<style>
  /* Mirrors css/base.css: paper ground, #1a1a1a ink (never black), Literata throughout,
     hairline borders and the app's single 2px corner. No blue, no filled primary button —
     "primary" is the inset ink underline the menu uses. */
  :root {
    color-scheme: light dark;
    --bg: #fff; --paper: #fff; --text: #1a1a1a;
    --text-dim: rgba(26, 26, 26, .55); --text-faint: rgba(26, 26, 26, .38);
    --line: rgba(26, 26, 26, .15); --ink: #1a1a1a;
    --hover: rgba(26, 26, 26, .06); --hover-strong: rgba(26, 26, 26, .12);
    --err: #a85454; --radius: 2px;
    --font: "Literata", "Georgia", "Times New Roman", "Songti SC", "SimSun", "宋体", serif;
  }
  :root[data-theme="dark"] {
    --bg: #14161b; --paper: #1c2027; --text: #e7e5df;
    --text-dim: rgba(231, 229, 223, .55); --text-faint: rgba(231, 229, 223, .38);
    --line: rgba(231, 229, 223, .18); --ink: #e7e5df;
    --hover: rgba(231, 229, 223, .08); --hover-strong: rgba(231, 229, 223, .16);
    --err: #cf7a7a;
  }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: var(--bg); color: var(--text); font: 15px/1.6 var(--font);
  }
  form {
    width: min(360px, calc(100vw - 32px)); padding: 26px 26px 24px;
    background: var(--paper); border: 1px solid var(--ink); border-radius: var(--radius);
    box-shadow: 0 10px 28px rgba(0, 0, 0, .08);
  }
  :root[data-theme="dark"] form { box-shadow: 0 10px 28px rgba(0, 0, 0, .55); }
  p.brand {
    margin: 0 0 18px; font-size: 9px; letter-spacing: 2.4px; text-transform: uppercase;
    color: var(--text-faint); font-weight: 500; white-space: nowrap;
  }
  h1 { margin: 0 0 6px; font-size: 21px; font-weight: 600; letter-spacing: .2px; }
  p.hint { margin: 0 0 20px; font-size: 12px; line-height: 1.6; color: var(--text-dim); }
  label {
    display: block; margin: 0 0 14px; font-size: 9px; letter-spacing: 1.7px;
    text-transform: uppercase; color: var(--text-faint); font-weight: 500;
  }
  input {
    display: block; width: 100%; box-sizing: border-box; margin-top: 6px; padding: 7px 9px;
    border: 1px solid var(--line); border-radius: var(--radius); background: transparent;
    color: var(--text); font: 13px/1.4 var(--font); outline: none; transition: border-color .15s;
  }
  input:focus { border-color: var(--ink); }
  button {
    width: 100%; margin-top: 8px; padding: 9px 10px; border: 1px solid var(--ink);
    border-radius: var(--radius); cursor: pointer; background: var(--hover); color: var(--text);
    font: 600 12px var(--font); letter-spacing: .6px; box-shadow: inset 0 -2px 0 var(--text);
    transition: background .15s;
  }
  button:hover { background: var(--hover-strong); }
  p.err {
    margin: 0 0 14px; padding: 8px 10px; border: 1px solid var(--err);
    border-radius: var(--radius); font-size: 12px; color: var(--err); background: transparent;
  }
  input:-webkit-autofill, input:-webkit-autofill:hover, input:-webkit-autofill:focus {
    -webkit-text-fill-color: var(--text);
    -webkit-box-shadow: 0 0 0 1000px var(--paper) inset;
    caret-color: var(--text);
  }
</style>
</head>
<body>
<form method="post" action="/login">
  <p class="brand">采析绘 · CRAWLER WORKFLOW</p>
  <h1>@@TITLE@@</h1>
  <p class="hint">@@HINT@@</p>
  @@ERROR@@
  <input type="hidden" name="next" value="@@NEXT@@">
  <input type="hidden" name="csrf" value="@@CSRF@@">
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
    """Whether this process asks for a login. The account registry is the switch."""
    return accounts_mode()


def startup_error() -> str | None:
    """The named refusal ``app.py`` raises at import time, or ``None`` when the shape is safe."""
    return _accounts_startup_error()


# ─── Identity accessors (the only way out of ``flask.session``) ───


def current_user():
    """The account bound to this request/worker, or ``None`` for the local owner."""
    return account_context.current()


def current_sid() -> str:
    """The raw session token from the signed cookie (needed to keep it on a password change)."""
    return str(session.get('sid') or '')


def is_admin() -> bool:
    account = current_user()
    return bool(account is not None and account.is_admin)


# ─── Credentials and the gate ──────────────────────────────────


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
    """Whether the cookie names a live server-side session."""
    return resolve_session() is not None


def resolve_session():
    """The account behind the cookie's session id, or ``None`` (and the stale cookie is dropped)."""
    token = current_sid()
    if not token:
        return None
    account = get_account_service().resolve(token)
    if account is None:
        session.pop('sid', None)
    return account


def csrf_ok(account) -> bool:
    given = str(request.headers.get('X-CSRF-Token') or '')
    return bool(given) and hmac.compare_digest(given, str(getattr(account, 'csrf_token', '') or ''))


def _bind(account) -> None:
    """Publish the identity for this request and remember the token that restores the previous."""
    request.environ['cixi_account'] = account
    request.environ['cixi_account_reset'] = account_context.bind(account)


def teardown(_exc=None) -> None:
    """Undo :func:`_bind` on every exit path (``app.teardown_request`` calls this)."""
    token = (request.environ or {}).pop('cixi_account_reset', None)
    if token is not None:
        account_context.unbind(token)
    (request.environ or {}).pop('cixi_account', None)


def gate():
    """The ``before_request`` answer: ``None`` to continue, or the refusal response."""
    if not auth_enabled() or request.endpoint == 'auth.login':
        return None
    account = resolve_session()
    if account is None:
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
    _bind(account)
    if account.must_change_password and request.path.startswith('/api/') and request.path not in _MUST_CHANGE_ALLOWED:
        response = jsonify({'ok': False, 'error': t('accounts.mustChangePassword')})
        response.status_code = 403
        response.headers['X-Password-Change-Required'] = '1'
        response.headers['Cache-Control'] = 'no-store'
        return response
    if request.method in _MUTATING and _csrf_required_path(request.path) and not csrf_ok(account):
        response = jsonify({'ok': False, 'error': t('accounts.csrfRequired')})
        response.status_code = 403
        response.headers['Cache-Control'] = 'no-store'
        return response
    return None


def _csrf_required_path(path: str) -> bool:
    """Every API write, plus logout (a cross-site form must not end the session)."""
    return str(path or '').startswith('/api/') or str(path or '') == '/logout'


# ─── Routes ────────────────────────────────────────────────────


def _request_lang() -> str:
    """The page's language: an explicit choice first, then the browser's own preference."""
    if request.args.get('lang') or request.headers.get('X-Lang'):
        return get_lang()
    return normalize(request.accept_languages.best_match(('zh', 'en')))


def _page(nxt: str, error: str, user: str = '', csrf: str = '') -> str:
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
        '@@CSRF@@': escape(csrf),
        '@@USER_VALUE@@': escape(user),
        '@@ERROR@@': f'<p class="err">{escape(error)}</p>' if error else '',
    }
    body = _LOGIN_PAGE
    for token, value in fields.items():
        body = body.replace(token, value)
    return body


def _login_csrf() -> str:
    """The form's one-shot token: minted once, reused until a POST consumes it.

    It must NOT be regenerated on every GET. A browser follows the document with an automatic
    ``GET /login?next=/favicon.ico`` (Chromium does exactly this), so minting per request replaced
    the session's token after the page had already rendered the previous one — every real Chrome
    login then failed with 「CSRF 令牌错误」 while curl and the test client passed. Rotation happens
    where it belongs: the POST pops the token, and a refusal renders a fresh page with a fresh one.
    """
    token = str(session.get('login_csrf') or '')
    if not token:
        token = secrets.token_urlsafe(24)
        session['login_csrf'] = token
    return token


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
        expected = str(session.pop('login_csrf', '') or '')
        given = str(request.form.get('csrf') or '')
        if not expected or not hmac.compare_digest(given, expected):
            time.sleep(FAILED_ATTEMPT_DELAY)
            error = t('accounts.csrfRequired')
        else:
            try:
                ticket = get_account_service().authenticate(
                    user,
                    request.form.get('password'),
                    ip=request.remote_addr or '',
                    user_agent=request.user_agent.string,
                )
            except AccountError as exc:
                time.sleep(FAILED_ATTEMPT_DELAY)
                error = t(exc.key, **exc.params)
            else:
                # A new session id for the new privilege, so a cookie planted before logging in is
                # not the one that carries the login.
                session.clear()
                session['sid'] = ticket.token
                return redirect(nxt)
    csrf = _login_csrf()
    previous = get_lang()
    try:
        set_lang(_request_lang())
        body = _page(nxt, error, user, csrf)
    finally:
        set_lang(previous)
    return Response(
        body,
        status=401 if error else 200,
        mimetype='text/html',
        headers={'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'same-origin'},
    )


@bp.route('/logout', methods=['POST'])
def logout():
    """POST only: a cross-site image or link must not be able to end someone's session.

    The session row is revoked on the server, so a copy of the cookie stops working even if it is
    replayed — clearing only the browser's copy would leave a live session behind.
    """
    token = current_sid()
    if token:
        get_account_service().logout(token)
    account = current_user()
    if account is not None:
        get_account_service().audit_logout(account, request.remote_addr or '')
    session.clear()
    return redirect('/login' if auth_enabled() else DEFAULT_NEXT)
