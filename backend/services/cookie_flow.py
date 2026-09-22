"""What each platform's cookie is *for*, and how to obtain it.

The cookie panel used to offer one generic action — "open a browser and log in"
— which is unhelpful exactly where the platforms differ most: some need a
keyword search login, some a note page, and the pasteable entry link has to be
restricted to hosts the crawler will actually plant cookies on.

The guidance is data here, the enforcement of the link is the validation below,
and neither is duplicated in the frontend.
"""

import logging
from urllib.parse import urlparse

from i18n import t

logger = logging.getLogger(__name__)


def flow_for(platform: str, allowed_hosts: tuple = (), login_url: str = '') -> dict:
    """The panel's description of one platform's cookie: purpose, steps, and
    whether a custom entry link is accepted.

    ``allowed_hosts`` and ``login_url`` come from the crawler itself (its
    ``domain`` plus the hosts its cookies must be planted on), so the panel can
    never advertise a host the crawler would then refuse.
    """
    return {
        'platform': platform,
        'purpose': t(f'cookie.{platform}.purpose'),
        'steps': [line for line in t(f'cookie.{platform}.steps').split('\n') if line.strip()],
        'login_url': login_url,
        'accepts_custom_url': bool(allowed_hosts),
        'allowed_hosts': list(allowed_hosts),
    }


def normalize_entry_url(candidate: str, allowed_hosts: tuple) -> str:
    """Return *candidate* as an https URL to open, or '' when it is not one.

    The login browser is driven with the user's real session, so the address it
    opens is not arbitrary: an off-platform link would plant that site's
    cookies into the platform's cookie file, and the crawl would later be
    carrying someone else's session. Empty (not an exception) means "fall back
    to the platform's own login page", which is what an untouched field should
    do.
    """
    raw = str(candidate or '').strip()
    if not raw:
        return ''
    url = raw if raw.startswith(('http://', 'https://')) else f'https://{raw}'
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
    except ValueError:
        return ''
    if parsed.scheme not in ('http', 'https') or not host:
        return ''
    if not _host_allowed(host, tuple(allowed_hosts or ())):
        return ''
    return url


def _host_allowed(host: str, allowed_hosts: tuple) -> bool:
    """Exact host or a subdomain of an allowed host — ``evil-weixin.qq.com``
    must not pass as ``qq.com`` did under a bare ``endswith``.

    A host recorded with its ``www.`` prefix (Zhihu is crawled at
    ``www.zhihu.com``) also accepts the bare form: people paste the address of
    the page they are reading, and ``zhihu.com/question/…`` is the same site.
    """
    for allowed in allowed_hosts:
        base = str(allowed or '').strip().lower().lstrip('.')
        if not base:
            continue
        candidates = [base]
        if base.startswith('www.'):
            candidates.append(base[len('www.') :])
        for candidate in candidates:
            if host == candidate or host.endswith(f'.{candidate}'):
                return True
    return False
