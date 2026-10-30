"""Server-side message catalogue (zh / en) for everything the console shows.

Console output reaches the browser through three pipes — ``add_log()``,
``logging`` (via LogBufferHandler) and ``print()`` (via LogTee) — and it used
to be hardcoded, half in Chinese and half in English depending on which file
emitted it. Every user-visible line now goes through :func:`t`, which renders
it in the language of whoever triggered the run:

- HTTP requests carry ``X-Lang`` (the frontend patches ``fetch`` once, so
  every call gets it for free).
- A workflow runs in its own thread(s), and thread-locals are not inherited,
  so the language captured when the run starts is re-applied in each worker
  thread explicitly.

Unknown keys render as the key itself: a missing translation shows up loudly
in the console instead of silently falling back to a foreign language.
"""

import logging
import re
import threading

from i18n_catalog import MODULES

logger = logging.getLogger(__name__)

# printf-style placeholders ('%s', '%(name)d') that str.format cannot fill.
_BAD_PLACEHOLDER = re.compile(r'%(?:\(\w+\))?[#0-9+.-]*[sdfgrx]')

DEFAULT_LANG = 'zh'
LANGS = ('zh', 'en')

_local = threading.local()


# ─── Catalogue ──────────────────────────────────────────────────
# The messages themselves are data, one module per domain under ``backend/i18n_catalog/``, merged
# here so ``i18n`` stays the single surface every module imports. The merge is a function rather
# than ``{**a, **b}`` because dict expansion lets a key declared in two domains silently keep
# whichever came LAST — the same accident as a key typed twice in one table
# (``tests/unit/i18n/test_i18n.py::TestNoDuplicateKeys``), only spread over two files where parity
# cannot see it. Refusing at import time fails the suite on the wording nobody prints, instead of a
# run answering a stale one.
def _merge_domain_table(attribute: str) -> dict:
    merged = {}
    for module in MODULES:
        for key, value in getattr(module, attribute).items():
            if key in merged:
                raise RuntimeError(f'i18n: {key!r} is declared by two catalogue domains')
            merged[key] = value
    return merged


_ZH = _merge_domain_table('ZH')
_EN = _merge_domain_table('EN')


# ─── Catalogue ──────────────────────────────────────────────────
# Keys are grouped by the emitter: wf.* (workflow engine / app.py),
# llm.* (analyzers/llm_client.py), crawl.<platform>.* (crawlers), and
# misc.* / analysis.* for the rest. The two tables must stay in sync —
# ``missing_keys()`` checks that in the tests.


MESSAGES = {'zh': _ZH, 'en': _EN}


# ─── Runtime language ───────────────────────────────────────────


def normalize(value) -> str:
    """Map any accepted spelling ('zh-CN', 'en-US', 'ZH', None) onto a
    catalogue language, falling back to the default for anything unknown."""
    text = str(value or '').strip().lower().replace('_', '-')
    for lang in LANGS:
        if text == lang or text.startswith(lang + '-'):
            return lang
    return DEFAULT_LANG


def get_lang() -> str:
    """Thread-local language; defaults to zh for anything not driven by a
    request (startup messages, manual runs, tests)."""
    return getattr(_local, 'lang', None) or DEFAULT_LANG


def set_lang(value):
    """Pin the language for this thread. Workflow worker threads must call
    this themselves — thread-locals are not inherited from the starter."""
    _local.lang = normalize(value)
    return _local.lang


#: What a message carries in ``{platform}`` is a **storage key** — that is what the crawl
#: matrix, the cookie files, the browser profiles and the run records are all addressed by.
#: Printed as-is it put a bare ``zhihu`` into a Chinese console and into the pre-run dialog,
#: so the key is named in the language the message is already answering in. One rule here,
#: so every line that mentions a platform is translated — including lines written later.
#: The values are pinned equal to the frontend's ``platform.*`` catalogue by
#: ``test_frontend_contract.py::TestPlatformLabelParity``.
_PLATFORM_LABELS = {
    'zh': {
        'zhihu': '知乎',
        'weibo': '微博',
        'xiaohongshu': '小红书',
        'wechat': '微信',
        'bilibili': '哔哩哔哩',
        'douyin': '抖音',
        'hongguo': '红果短剧',
        'cnki': '中国知网',
        'twitter': 'X（推特）',
        'instagram': 'Instagram',
        'youtube': 'YouTube',
        'kuaishou': '快手',
        'tiktok': 'TikTok',
        'jd': '京东',
        'taobao': '淘宝',
        'xianyu': '闲鱼',
    },
    'en': {
        'zhihu': 'Zhihu',
        'weibo': 'Weibo',
        'xiaohongshu': 'Xiaohongshu',
        'wechat': 'WeChat',
        'bilibili': 'Bilibili',
        'douyin': 'Douyin',
        'hongguo': 'Hongguo Short Drama',
        'cnki': 'CNKI',
        'twitter': 'X (Twitter)',
        'instagram': 'Instagram',
        'youtube': 'YouTube',
        'kuaishou': 'Kuaishou',
        'tiktok': 'TikTok',
        'jd': 'JD',
        'taobao': 'Taobao',
        'xianyu': 'Xianyu',
    },
}


def platform_label(key, lang: str | None = None) -> str:
    """The word a user reads for a platform key, or the key itself when it is not one.

    Domains (``weibo.com``) and free text pass through untouched: this names keys, it does
    not judge whether a string was meant to be one.
    """
    table = _PLATFORM_LABELS.get(lang or get_lang()) or {}
    return table.get(str(key), str(key))


def _name_platforms(params: dict) -> dict:
    """Localize ``platform`` / ``platforms`` placeholders on the way into a template.

    Callers hand this slot either one key, a list of them, or a string they joined
    themselves — all three are answered, because a half-translated list is the same bug
    with a comma in it. A value that is not made of platform keys (a domain, a free-text
    reason) is passed through untouched.
    """
    named = dict(params)
    # The enumeration comma is language-specific: '、' reads right in Chinese and wrong
    # in English ("Zhihu、Weibo"). Pick the joiner by the reader's language.
    sep = '、' if get_lang() == 'zh' else ', '
    for slot in ('platform', 'platforms'):
        value = named.get(slot)
        if isinstance(value, str):
            # Split on a list separator and nothing else. Splitting on whitespace or on
            # `/` looked harmless and was not: a refusal that names what it refused
            # (`../x`) came back mangled, and a sentence would have been re-joined with
            # 、. An unknown token is passed through whole, which is the safe answer for
            # every value that was never a platform key.
            named[slot] = sep.join(
                platform_label(part.strip()) for part in re.split(r'[,、]', value.strip()) if part.strip()
            )
        elif isinstance(value, (list, tuple, set)):
            named[slot] = sep.join(platform_label(item) for item in value)
    return named


def t(key: str, **params) -> str:
    """Render ``key`` in the current thread's language.

    Missing key -> the key itself (so gaps are visible in the console).
    Missing parameter -> the raw template, never a crash mid-crawl.
    """
    lang = get_lang()
    table = MESSAGES.get(lang) or {}
    template = table.get(key)
    if template is None:
        template = MESSAGES.get(DEFAULT_LANG, {}).get(key)
    if template is None:
        logger.debug('i18n: missing message key "%s"', key)
        return key
    if not params:
        return template
    params = _name_platforms(params)
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        logger.debug('i18n: bad params for "%s": %r', key, params)
        return template


#: Machine stop-tokens a crawl walk can end on (``engine/feed.py`` / ``engine/pager.py`` return
#: these). The engine stays language-free; a log line wraps the token here so the console reads a
#: reason, not a code word like ``stuck``. An unknown token falls through unchanged rather than
#: inventing a sentence, so a new engine reason is visible, never silently swallowed.
STOP_REASONS = {
    'target': 'crawl.stopReason.target',
    'end': 'crawl.stopReason.end',
    'no_new': 'crawl.stopReason.no_new',
    'stuck': 'crawl.stopReason.stuck',
    'no_cards': 'crawl.stopReason.no_cards',
    'empty_page': 'crawl.stopReason.empty_page',
    'fetch_failed': 'crawl.stopReason.fetch_failed',
    'stopped': 'crawl.stopReason.stopped',
    # Not an engine token: a walk over a *list of URLs* (weibo's hourly windows) ends on the wall
    # itself, not on one page's shape, and it must still read as a reason rather than as a code word.
    'wall': 'crawl.stopReason.wall',
    'risk': 'crawl.stopReason.risk',
    'unreachable': 'crawl.stopReason.unreachable',
}


def stop_reason_label(reason: str) -> str:
    """Render a crawl walk's stop token as a user-readable phrase in the current language."""
    key = STOP_REASONS.get(str(reason or '').strip())
    return t(key) if key else str(reason)


def missing_keys() -> dict:
    """Catalogue gaps per language — used by the tests so a half-translated
    message cannot ship."""
    zh, en = set(_ZH), set(_EN)
    return {'en_only': sorted(en - zh), 'zh_only': sorted(zh - en)}


def audit() -> list[str]:
    """Self-check the catalogue; an empty list means it is healthy.

    Worth calling at startup: a leftover printf placeholder ('端口 %s') does
    not raise — ``str.format`` just fails and ``t()`` hands back the raw
    template, so the user sees a literal ``%s`` in the console and nothing
    points at the cause. This turns that into a warning that names the key.
    """
    problems = []
    for key in sorted(set(_ZH) | set(_EN)):
        for lang, table in MESSAGES.items():
            template = table.get(key)
            if template is None:
                problems.append(f'{key}: missing translation for {lang}')
                continue
            if _BAD_PLACEHOLDER.search(template):
                problems.append(f'{key} [{lang}]: printf-style placeholder in "{template}"')
    return problems
