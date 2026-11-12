"""Which exit (proxy) a browser for one account should leave through.

Two rules, both about not looking like a different person between two requests:

* **Sticky** — an account keeps the exit it first crawled with. A login that changes country
  between the search page and the article page is itself a risk signal, so the binding is a
  written fact (``bindings``) rather than a fresh choice per run.
* **Exit rotation is not account rotation** — when the bound exit is benched, a healthy exit
  is bound instead and the SAME account keeps working. That is the case the pool exists for
  on the IP side, and it must not silently fall back to the host's own address: going direct
  after a proxy failure would expose the very IP the proxy was hiding.

The module deliberately knows nothing about crawlers or browsers: it answers with a plain
description of a proxy, and ``crawlers.core.proxy`` turns that into Chrome arguments.
"""

from services.pool import health as pool_health
from services.pool import store


def exits_for(platform: str) -> list:
    """Enabled exits that serve *platform* — the candidate set for a binding."""
    return [row for row in store.list_exits(platform, include_disabled=False)]


def healthy_exit(platform: str, exclude=()) -> dict:
    """The best enabled exit whose cooldown has expired, oldest use first.

    Ranking by ``last_attempt_at`` rather than "first in the list" spreads accounts over the
    pool instead of piling every new one onto exit #1.
    """
    rows = []
    for row in exits_for(platform):
        if row['id'] in exclude:
            continue
        health = store.get_health('exit', platform, row['id'])
        if pool_health.effective_state(health) != 'ok':
            continue
        rows.append((float(health.get('last_attempt_at') or 0), str(row.get('created_at') or ''), row))
    if not rows:
        return {}
    rows.sort(key=lambda item: (item[0], item[1]))
    return rows[0][2]


def proxy_for(platform: str, account: str, *, auto_bind: bool = True, even_if_cooling: bool = False) -> dict:
    """The proxy spec this account's browser should use, or ``{}`` for a direct connection.

    A bound exit whose cooldown is still running is replaced for an AUTOMATIC browser: the
    pool's whole IP side is "a benched exit is the only reason to change address", and
    returning it anyway made a `risk` cooldown inert for every non-pool/fixed-login crawl
    (only the selector's claim path used to re-bind). ``even_if_cooling`` is the manual door:
    a person pressing 验证 or opening the login window is asking "what does this login see from
    where it lives", and moving that probe would answer a question nobody asked.
    """
    account = str(account or '').strip()
    bound = store.binding_exit_id(platform, account) if account else ''
    if bound:
        spec = store.exit_secret(bound)
        if spec and spec.get('enabled') and _serves(spec, platform):
            cooling = pool_health.effective_state(store.get_health('exit', platform, bound)) != 'ok'
            if not cooling or even_if_cooling:
                spec['username'] = spec.get('username') or ''
                spec['password'] = spec.get('password') or ''
                return spec
    if not exits_for(platform):
        return {}
    choice = healthy_exit(platform)
    if not choice:
        # Every exit is cooling or disabled. Answering "direct" here would leak the host's
        # address; the caller reports that the exit pool has nothing usable instead.
        return {'unavailable': True, 'platform': platform}
    if auto_bind and account:
        store.bind(platform, account, choice['id'])
    spec = store.exit_secret(choice['id'])
    return spec or {'unavailable': True, 'platform': platform}


def _serves(spec: dict, platform: str) -> bool:
    allowed = spec.get('allowed_platforms') or []
    return not allowed or platform in allowed


def describe(spec: dict) -> str:
    """The words for one exit in a console line — ``香港03 (1.2.3.4:8080)``, never credentials."""
    if not spec:
        return ''
    if spec.get('unavailable'):
        return ''
    name = str(spec.get('name') or '').strip()
    address = f'{spec.get("host", "")}:{spec.get("port", "")}'
    return f'{name} ({address})' if name and name != address else address
