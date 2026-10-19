"""mitmproxy addon for the 红果 comment harvest — runs INSIDE the mitmdump process.

This file is loaded by ``mitmdump -s`` and must not import anything from the
project (different interpreter: wherever mitmdump lives). Its whole job is the
narrowest possible filter — the two comment endpoints the desktop player calls —
appended as one JSON line per response to the file named by ``CIXI_HG_OUT``:

    {"ts", "kind", "group_id", "url", "payload"}

``kind`` is ``comment`` for ``comment/list`` and ``reply`` for ``reply/list``;
``group_id`` is lifted from the URL path so the tailer can match a page to the
episode it belongs to without parsing the payload. Everything else the player
fetches (video segments, covers, telemetry, the player's own update server) is
dropped unread — a capture file that holds the user's whole viewing traffic is
not what this crawl needs.

The file is opened in append mode per record so the tailer sees complete lines
(line-buffered writes across processes on Windows are not guaranteed otherwise).
"""

import json
import os
import time

_OUT = os.environ.get('CIXI_HG_OUT') or ''

_MARKS = (
    ('/novel/commentapi/comment/list/', 'comment'),
    ('/novel/commentapi/reply/list/', 'reply'),
)


def response(flow):
    if not _OUT:
        return
    path = flow.request.path or ''
    kind = ''
    for mark, name in _MARKS:
        if mark in path:
            kind = name
            break
    if not kind:
        return
    if flow.response is None or flow.response.status_code != 200:
        return
    try:
        payload = flow.response.get_json()
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    # The group id sits in the path: /novel/commentapi/comment/list/<id>/v1/
    parts = [p for p in path.split('?')[0].split('/') if p]
    group_id = ''
    for i, p in enumerate(parts):
        if p == 'list' and i + 1 < len(parts):
            group_id = parts[i + 1]
            break
    rec = {
        'ts': time.time(),
        'kind': kind,
        'group_id': group_id,
        'url': flow.request.pretty_url,
        # The request body carries WHICH comment was expanded (reply/list pages) —
        # without it a reply page cannot be tied back to its parent's floor.
        'req_body': flow.request.get_text(strict=False) or '',
        'payload': payload,
    }
    with open(_OUT, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(rec, ensure_ascii=False) + '\n')
