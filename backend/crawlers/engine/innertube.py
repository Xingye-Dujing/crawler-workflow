"""innertube — Google's internal JSON API, asked from *inside* the page.

YouTube's whole UI is driven by ``POST /youtubei/v1/<endpoint>`` with a context
the page itself ships (``ytcfg``). Two things make this worth its own module
rather than a method on the crawler:

* **the page is the credential.** Issuing the call from inside the document means
  cookies, origin, and TLS fingerprint are the browser's, so no signature is
  needed (measured 2026-09: search 0.68 s for 10 videos, player 0.31 s, one
  comment round 0.32 s for 20 comments — against 3-4 s and *fewer* rows from the
  same page rendered as DOM). The crawler navigates once and then reads data.
* **the key rotates.** ``INNERTUBE_API_KEY`` and the context are read off the
  document on every run instead of written into this repo, because a hardcoded
  key is a crawler that breaks silently the week Google changes it.

Nothing here knows what a video is: it moves JSON in and JSON out, and reports
what the answer looked like so the caller can tell an empty list from a refusal.
"""

import time

from .jsonpath import collect

#: Read the API key and request context the page ships with. Returns
#: ``{'key': …, 'context': …}`` with empty values when the page is not one of
#: these apps (a consent wall, an error page, a shell that has not booted).
READ_CONFIG_JS = (
    "return {key: (window.ytcfg && window.ytcfg.get('INNERTUBE_API_KEY')) || '',"
    " context: (window.ytcfg && window.ytcfg.get('INNERTUBE_CONTEXT')) || null};"
)

#: POST ``body`` to ``url`` from inside the page and hand back the parsed answer.
#: The status and the raw head travel with it because an HTML risk-control page
#: served where JSON was promised has to be distinguishable from an empty list.
POST_JS = """
var done = arguments[arguments.length - 1];
var url = arguments[0], body = arguments[1], t0 = Date.now();
fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(body)
}).then(function (r) {
    return r.text().then(function (text) {
        var parsed = null;
        try { parsed = JSON.parse(text); } catch (e) { parsed = null; }
        done({status: r.status, ms: Date.now() - t0, json: parsed, head: parsed ? '' : text.slice(0, 400)});
    });
}).catch(function (e) { done({status: 0, ms: Date.now() - t0, json: null, error: String(e)}); });
"""

API_HOST = 'https://www.youtube.com'
#: What a refusal looks like when it is not a status code: Google answers risk
#: control with an interstitial, and the shape of that page is the signal.
REFUSAL_MARKS = ('captcha', 'unusual traffic', 'Verify you are human', 'https://www.google.com/sorry')


def ready(driver, attempts: int = 10, tick: float = 0.4) -> tuple[str, dict] | None:
    """Wait for the page to carry its own API config, and return ``(key, context)``.

    Bounded and polled rather than slept: a page that has booted answers on the
    first read, and one that never will (a consent wall) should cost 4 seconds and
    be reported, not 30.
    """
    for _ in range(attempts):
        try:
            found = driver.execute_script(READ_CONFIG_JS)
        except Exception:
            found = None
        if found and found.get('key') and found.get('context'):
            return str(found['key']), found['context']
        time.sleep(tick)
    return None


def call(driver, endpoint: str, key: str, context: dict, extra: dict | None = None) -> dict:
    """One innertube round trip. ``{}`` means "no usable answer".

    ``ms`` rides along on the returned payload's ``_innertube_ms`` so a caller that
    cares about timing (the run log's "this crawl was slow" claim) can read it
    without a second transport.
    """
    body = {'context': context}
    body.update(extra or {})
    url = f'{API_HOST}/youtubei/v1/{endpoint}?key={key}'
    try:
        answer = driver.execute_async_script(POST_JS, url, body)
    except Exception:
        return {}
    if not isinstance(answer, dict):
        return {}
    payload = answer.get('json')
    if int(answer.get('status') or 0) != 200 or not isinstance(payload, dict):
        return {
            '_status': int(answer.get('status') or 0),
            '_refused': _refusal(answer),
            '_ms': int(answer.get('ms') or 0),
        }
    payload['_ms'] = int(answer.get('ms') or 0)
    payload.setdefault('_status', 200)
    return payload


def _refusal(answer: dict) -> str:
    head = str(answer.get('head') or answer.get('error') or '').lower()
    return head if any(mark in head for mark in REFUSAL_MARKS) else ''


def refused(payload: dict) -> bool:
    """Did the answer come back as risk control rather than as data?"""
    return bool(payload.get('_refused'))


def pager_tokens(node, out: list | None = None) -> list[str]:
    """Every ``continuationCommand.token`` in the answer, in **document order**.

    Order and length are both useless as a rule for picking one, and the two
    measurements that proved it are worth recording because they point opposite
    ways: a channel tab's grid pager is its **longest** token (1664 chars, and
    every round after that answers with exactly one 4192-char token), while a
    watch page's comment pager measured 78 chars on one video and 1414 on
    another, with menu tokens of both longer and shorter kinds beside it.

    So callers treat this as a *candidate list*: :func:`grid_token` picks the one
    the list's own markup marks, and the comment walk tries them until one
    answers with comments.
    """
    if out is None:
        out = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'continuationCommand' and isinstance(value, dict) and value.get('token'):
                out.append(str(value['token']))
            else:
                pager_tokens(value, out)
    elif isinstance(node, list):
        for item in node:
            pager_tokens(item, out)
    return out


#: The keys whose value is "the items of one list". A pager token is only
#: meaningful *inside* the list it pages, which is what :func:`pager_of` uses.
LIST_KEYS = ('continuationItems', 'contents', 'items', 'subMenuItems')


def _contains(node, marker: str, depth: int = 0) -> bool:
    if depth > 30:
        return False
    if isinstance(node, dict):
        if marker in node:
            return True
        return any(_contains(value, marker, depth + 1) for value in node.values())
    if isinstance(node, list):
        return any(_contains(item, marker, depth + 1) for item in node)
    return False


def _marked_token(items: list) -> str:
    """The token of a pager that sits **as an element of** this list.

    Direct children only, and that distinction is measured: a comment round nests a
    ``continuationItemRenderer`` inside every thread that has replies — that one
    pages *that thread's* replies — and puts the list's own pager as the last
    element of the list. Picking "any marked pager below the list" walks into one
    comment's replies and stops the whole crawl there.
    """
    found = []
    for entry in items:
        if isinstance(entry, dict) and isinstance(entry.get('continuationItemRenderer'), dict):
            found.extend(pager_tokens(entry['continuationItemRenderer']))
    return max(found, key=len) if found else ''


def pager_of(node, marker: str) -> str:
    """The pager that belongs to the list *containing* ``marker``.

    Measured on a comment round: it carries three continuation tokens — two 78-character
    ones under ``commentsHeaderRenderer.sortMenu`` (the Top/Newest switch, each of which
    answers **the first page again**) and one 522-character token sitting at the end of
    the same ``continuationItems`` list as the comments. Taking "a token from the answer"
    therefore re-reads page one forever: the row ledger refuses the duplicates, the walk
    reports success, and the user gets 20 comments out of a video with thousands. So the
    pager is chosen by *which list it lives in* — the one the items came from.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in LIST_KEYS and isinstance(value, list) and _contains(value, marker):
                token = _marked_token(value)
                if token:
                    return token
            nested = pager_of(value, marker)
            if nested:
                return nested
    elif isinstance(node, list):
        for item in node:
            nested = pager_of(item, marker)
            if nested:
                return nested
    return ''


def grid_token(payload: dict) -> str:
    """The token that pages a video list — comments excluded, marks fall back.

    Preference order, all of it measured: the pager inside the list that actually
    carries video rows; failing that, the longest ``continuationItemRenderer``
    token in the answer. A channel tab needs the fallback because its first page
    arrives as a document whose items are ``lockupViewModel``, and a search round's
    is ``videoRenderer``.
    """
    for marker in ('lockupViewModel', 'videoRenderer', 'gridVideoRenderer'):
        token = pager_of(payload, marker)
        if token:
            return token
    marked = []
    for renderer in collect(payload, 'continuationItemRenderer'):
        marked.extend(pager_tokens(renderer))
    return max(marked, key=len) if marked else ''
