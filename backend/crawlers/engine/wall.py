"""Telling "this session is not allowed to see it" from "there is nothing here".

The distinction is the difference between an honest failure and a table of
nothing that looks like a finished crawl. Every platform parks a dead session
somewhere else, announces it in a different word, and — in two measured cases —
says it in the tab *title* rather than in the URL, so one shared classifier
replaces the per-platform guesses that used to live in :mod:`crawlers.base` and
:mod:`crawlers.comments`.

Measured shapes this module has to catch, all of them real observations:

* weibo/zhihu send the browser to a ``passport`` host;
* X uses a path with no query string (``/i/flow/login``) and, when it merely
  wants a re-verification, ``/i/jf/onboarding/web``;
* Instagram uses ``/accounts/login/`` *and* a subtler bounce: the router
  collapses a profile request to ``https://www.instagram.com/#`` with no login
  form at all, which reads as an empty page rather than as a refusal;
* douyin answers a headless browser with 验证码中间页 announced in the **title**.

``blocked`` and ``login`` are kept apart because the user's next action differs:
re-save the cookie, or back off and wait. A crawl that reports the wrong one
sends them off doing the wrong thing.

``unreachable`` is kept apart from both because it is not a statement about the
site at all. Measured 2026-09-25 (``backend/test_arrival_evidence.py``, Chrome
148): when the browser itself refuses a navigation it commits *its own* document —
``documentURI`` and ``location.href`` both ``chrome-error://chromewebdata``,
``readyState`` complete, navigation ``responseStatus`` 0, the title the bare host
and a ``net::ERR_…`` token in the body — while ``driver.current_url`` keeps
reporting the address that was asked for. The same three shapes (dead DNS,
refused port, black-holed address) differ only in the token. Reading that document
as an ordinary page is how a network failure gets filed as "this keyword has no
results", which is the lie this whole module exists to prevent.
"""

import re

# ─── the vocabulary the platforms actually use ───────────────────────

#: URL fragments that are, on their own, a wall.
LOGIN_URL_MARKERS = (
    'passport.weibo.com/sso',
    'passport.zhihu.com',
    '/login?',
    '/signin',
    'accounts.google.com',
    # X parks a logged-out visitor on a path segment with no query string and
    # Instagram on a trailing slash; neither matches the patterns above. Without
    # them, "验证 Cookie" answered "可用" to a dead session — worse than no check.
    '/flow/login',
    '/accounts/login/',
    # X's re-verification interstitial: the URL still says x.com, so only the
    # onboarding route gives it away.
    '/i/jf/onboarding',
)

#: Phrases a wall puts near the *top* of the page. Two are required (see
#: :func:`looks_like_login_page`) because one appears inside ordinary content.
#: The Instagram pair is load-bearing: its login form does not use any of the
#: Chinese phrases above, and without these two the page read as an account with
#: no posts (measured — the router serves the form at ``/#`` with no URL clue).
LOGIN_TEXTS = (
    '扫描二维码登录',
    '手机号登录',
    '请先登录',
    '登录后查看',
    '扫码登录',
    '创建新账户',
    '忘记密码',
    # X and Instagram answer a logged-out (or refused) request with their own
    # English form. Measured: X's ``/search`` for a headless browser renders
    # "See what's happening / Continue with phone / Forgot password?" and zero
    # tweets, and Instagram redirects a hashtag to ``/accounts/login/`` whose
    # inputs match no ``name="username"`` selector — so the *words* are the only
    # reliable signal on either site.
    'create new account',
    'forgot password?',
    'continue with phone',
    'log into instagram',
    "see what's happening",
)

#: Risk-control refusals. Not a login problem: the session may be perfect.
#: Two of these phrases ('扫码登录', '登录后查看') are also login wording — they
#: earn their place here because the comment adapters treat *any* interception of
#: a comment panel as ``blocked``, and that is the vocabulary those panels answer
#: with when the session behind them stops being trusted.
BLOCK_TEXTS = (
    '暂时限制',
    '当前请求存在异常',
    '访问频繁',
    '操作频繁',
    '请配合完成验证',
    '40362',  # zhihu's headless content-page code, seen in page text and URLs
    '验证码中间页',
    '滑动验证',
    '安全验证',
    '扫码登录',
    '登录后查看',
    # X answers a browser it does not like with a bare Cloudflare-style 403
    # page — measured in headless mode on ``/OpenAI``: "Access to x.com was
    # denied … HTTP ERROR 403". It is not a login wall (no form, no redirect),
    # and calling it one would send the user to re-save a cookie that is fine.
    'access to x.com was denied',
    'http error 403',
)

#: A tab title that says the platform's own captcha page (douyin, measured).
CAPTCHA_TITLES = ('验证码', '安全验证', '滑动验证')

#: Schemes the browser owns, not the site. A crawl that ends up here after
#: ``driver.get`` never reached the page it asked for: measured 2026-09-25 on an
#: over-throttled xiaohongshu session, a VISIBLE window stayed on ``chrome://new-tab-page``
#: (its body read 「新标签页 / 自定义 Chrome」, no wall text), so the classifier saw
#: 'ok' and the search filed an empty grid as if the keyword had no results. No site
#: can redirect into these schemes, so arriving here is purely a navigation that did
#: not happen — a refusal to back off from, never a "found nothing".
INTERNAL_PAGE_PREFIXES = (
    'chrome://',
    'chrome-search://',
    'edge://',
    'about:',
    'data:',
    'devtools://',
)


#: The document Chrome commits when **it** refused the navigation. Measured on three
#: shapes (unresolvable host, refused port, black-holed address) and identical in all
#: three; the address bar — and ``driver.current_url`` — still shows the URL that was
#: asked for, so this string is only ever found in the document's own URI.
ERROR_PAGE_PREFIX = 'chrome-error://'

#: Every word :func:`classify` may answer, closed on purpose: a consumer that tests
#: ``== 'blocked'`` silently reads a word it has never seen as "not blocked", so a
#: new verdict has to be a deliberate edit here (pinned by tests/unit/test_login_wall.py).
VERDICTS = ('ok', 'login', 'blocked', 'unreachable')

#: Chrome's own machine token, printed inside its error page. Measured in three
#: spellings on a Chinese Chrome (``ERR_NAME_NOT_RESOLVED``, ``ERR_UNSAFE_PORT``,
#: ``ERR_CONNECTION_TIMED_OUT``), each on a line of its own and **without** the
#: ``net::`` prefix that the driver's exception message carries — so the prefix is
#: optional here rather than required, and a required one would name nothing at all.
#: Searched for **only** on a browser-written page anyway: a development article that
#: quotes ``net::ERR_CONNECTION_RESET`` is content, and mistaking it for a transport
#: death would discard a page that did arrive.
_ERROR_TOKEN = re.compile(r'\bERR_[A-Z0-9_]{2,}\b')


def _is_error_uri(value: str) -> bool:
    return (value or '').lower().startswith(ERROR_PAGE_PREFIX)


def unreachable_page(url: str = '', document_uri: str = '') -> bool:
    """True when what is on screen is the browser's own "I could not get there".

    ``url`` is accepted as well as ``document_uri`` because the two agree on this
    page and a caller may only reliably have one of them; the check is on the
    *document*, never on the address that was asked for, which is precisely the
    distinction that makes this word provable rather than a guess.
    """
    return _is_error_uri(document_uri) or _is_error_uri(url)


def error_token(body_text: str = '') -> str:
    """The machine's own name for the refusal (``ERR_NAME_NOT_RESOLVED``), or ``''``.

    ``''`` means the page did not say, which the caller must be able to tell from a
    token — inventing one would put a claim in the console that nothing measured.
    """
    match = _ERROR_TOKEN.search(body_text or '')
    return match.group(0) if match else ''


def never_arrived(url: str = '') -> bool:
    """True when the browser is on one of ITS OWN pages, not the site's.

    `about:blank` counts as not-arrived: it is the window a driver starts on and the
    state a failed navigation leaves behind, and no crawl's content page is a blank.
    """
    lowered = (url or '').lower()
    return lowered.startswith(INTERNAL_PAGE_PREFIXES)


def looks_like_login_page(url: str, body_text: str = '') -> bool:
    """True when a page is a login wall rather than the requested content.

    Crawlers used to read such a page as "no results" and log an empty crawl,
    which sent the user off to re-save cookies that were fine all along.
    """
    lowered = (url or '').lower()
    if any(marker in lowered for marker in LOGIN_URL_MARKERS):
        return True
    text = body_text or ''
    # Only the head is examined: a wall puts its phrases at the top, while an
    # article that merely mentions 登录 in its body must not read as a wall.
    # Casefolded, because the English phrases a Western-language session is
    # served ("Forgot password?") start with a capital and are sentences, not
    # keys — comparing them case-sensitively would miss every one of them.
    head = text[:400].casefold()
    return sum(1 for phrase in LOGIN_TEXTS if phrase in head) >= 2


def looks_blocked(body_text: str = '', url: str = '', title: str = '') -> bool:
    """True on a risk-control refusal (which may carry no login wording at all)."""
    head = (body_text or '')[:1200].casefold()
    tab = (title or '').casefold()
    if any(phrase in head for phrase in BLOCK_TEXTS):
        return True
    if any(phrase in (url or '').casefold() for phrase in BLOCK_TEXTS):
        return True
    return any(phrase in tab for phrase in CAPTCHA_TITLES)


def bounced_to_root(request_url: str, current_url: str, site_root: str) -> bool:
    """A request that came back at the site's root, having asked for a deeper path.

    Instagram does exactly this to a profile URL when the session is being
    challenged: ``/nasa/`` → ``https://www.instagram.com/#``. Nothing on that
    page says "login", so a crawler that only reads walls from URLs sees zero
    tiles and reports an account with no posts.

    Asking for the root and being served the root is not a bounce, and neither
    is a redirect to a *different* page — this catches the one shape where the
    router dropped the request on the floor.
    """

    def canonical(value: str) -> str:
        return (value or '').split('#')[0].rstrip('/')

    current, root, requested = canonical(current_url), canonical(site_root), canonical(request_url)
    if not root or current != root or requested == root:
        return False
    return requested.startswith(root)


def classify(url: str, body_text: str = '', title: str = '', document_uri: str = '') -> str:
    """One of :data:`VERDICTS`, decided in that order of urgency.

    A login marker wins over a block phrase: a risk page that also asks for a
    login is fixed by the cookie, and the resume path keys on that difference.
    A browser parked on one of its OWN pages (``chrome://new-tab-page``) is checked
    before anything else: it did not reach the site, so it is neither a login wall nor
    a real empty result — it is a refusal to back off from.

    ``unreachable`` is judged first of all, because it is the one word here that is
    not a reading of the page's *content* but of who wrote the page: a Chrome error
    document carries the site's address nowhere in itself, and a crawl that asked for
    an article and got a token back must say so rather than describe the token.
    ``document_uri`` is where that lives — measured, ``current_url`` still reports the
    address that was asked for. A caller that cannot read it passes nothing and gets
    the older judgement, which is the right way for a missing fact to degrade.
    """
    if unreachable_page(url, document_uri):
        return 'unreachable'
    if never_arrived(url):
        return 'blocked'
    if looks_like_login_page(url, body_text):
        return 'login'
    if looks_blocked(body_text, url=url, title=title):
        return 'blocked'
    return 'ok'
