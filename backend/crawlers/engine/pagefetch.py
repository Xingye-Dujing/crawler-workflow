"""The one home for asking a site's own API from INSIDE its loaded page.

Every JSON-first crawl in this project works the same way: load one page of the site,
then ``fetch(url, {credentials: 'include'})`` from within that document. The browser's
own session rides along, which is why no request signature has to be forged (measured:
``code=0`` from the search page and from the video page alike), and why the request is
same-origin rather than a standalone call a WAF answers with a wall.

The mechanics — script assembly, the script timeout, the cost ledger — live HERE and
nowhere else. Three entry points, because the three historical callers genuinely read
different things out of one answer, and a caller that has to judge a refusal picks the
one that keeps the fact it judges:

* :func:`fetch` — the full answer: HTTP ``status``, ``body`` text and transport
  ``error``. A 403 edge page and a 200 JSON answer are different facts, and this is
  the only variant that can tell them apart. New refusals-to-be-named crawls (the
  weibo author walk) start here.
* :func:`fetch_json` — the parsed object, or ``{}`` for anything unparseable. The
  shape the platform crawls dispatch on (bilibili's ``code`` field).
* :func:`fetch_text` — the raw body text, ``'ERR …'`` when the fetch itself died. The
  shape the comment engine reads, because it inspects HTML bodies for wall wording
  that a JSON parse would throw away.
"""

import json
import logging

logger = logging.getLogger(__name__)


def _bridge(url: str) -> str:
    # Built by concatenation, never an f-string body: the payload is JavaScript full
    # of ``{}`` and doubling every one of them for a format string once produced a
    # ``SyntaxError: Unexpected token ';'`` inside the browser.
    return json.dumps(str(url))


def fetch(driver, url: str, requests: list | None = None, timeout: float = 25) -> dict:
    """GET *url* in-page and return ``{'status': int, 'body': str, 'error': str}``.

    ``status`` is -1 with a non-empty ``error`` when the fetch never answered at all.
    *requests*, when given, is the crawl's cost ledger — the URL is appended BEFORE
    the call, because a refused request was still a request made.
    """
    js = (
        'var done = arguments[arguments.length - 1];'
        + 'fetch('
        + _bridge(url)
        + ', {credentials: "include"})'
        + '.then(function (r) { return r.text().then(function (t) {'
        + 'done(JSON.stringify({status: r.status, body: t, error: ""})); }); })'
        + '.catch(function (e) { done(JSON.stringify({status: -1, body: "", error: String(e)})); });'
    )
    if requests is not None:
        requests.append(str(url))
    try:
        driver.set_script_timeout(timeout)
        raw = driver.execute_async_script(js)
        answer = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception as e:
        return {'status': -1, 'body': '', 'error': str(e)}
    if not isinstance(answer, dict):
        return {'status': -1, 'body': '', 'error': f'unexpected answer: {answer!r}'}
    answer.setdefault('status', -1)
    answer.setdefault('body', '')
    answer.setdefault('error', '')
    return answer


def fetch_json(driver, url: str, requests: list | None = None, timeout: float = 25) -> dict:
    """The parsed JSON object, or ``{}`` when the answer is not JSON.

    The shape the platform crawls dispatch on (bilibili's ``code`` field, the weibo
    mymblog envelope's ``data``): a non-JSON body — a WAF's HTML page, a transport
    death — arrives as ``{}`` with no field to read, which is what every caller here
    already branches on for "this answer refused", never "this site is empty".

    It resolves the fetch to the object directly (``done(j)``) rather than routing
    through :func:`fetch`, because that is the contract the crawls' page-context
    doubles are written against; the mechanics it shares with the other two (script
    assembly, timeout, ledger) live here, in one file.
    """
    js = (
        'var done = arguments[arguments.length - 1];'
        + 'fetch('
        + _bridge(url)
        + ', {credentials: "include"})'
        + '.then(function (r) { return r.json(); })'
        + '.then(function (j) { done(j); })'
        + '.catch(function (e) { done({err: String(e)}); });'
    )
    if requests is not None:
        requests.append(str(url))
    try:
        driver.set_script_timeout(timeout)
        payload = driver.execute_async_script(js)
    except Exception as e:
        logger.debug('in-page fetch failed: %s', e)
        return {}
    return payload if isinstance(payload, dict) else {}


def fetch_text(driver, url: str, requests: list | None = None, timeout: float = 25) -> str:
    """The raw body text, prefixed ``'ERR '`` when the fetch itself died.

    The comment engine reads this text to tell a risk-control page from a dead link
    (an HTML refusal carries wall wording a JSON parse would only throw away), so it
    gets the bytes, not a verdict.
    """
    js = (
        'var done = arguments[arguments.length - 1];'
        + 'fetch('
        + _bridge(url)
        + ', {credentials: "include"})'
        + '.then(function (r) { return r.text(); })'
        + '.then(function (t) { done(t); })'
        + ".catch(function (e) { done('ERR ' + e); });"
    )
    if requests is not None:
        requests.append(str(url))
    try:
        driver.set_script_timeout(timeout)
        raw = driver.execute_async_script(js)
    except Exception as e:
        return f'ERR {e}'
    return raw if isinstance(raw, str) else json.dumps(raw)
