"""Request-body / argument helpers shared by every HTTP handler.

These moved out of ``app.py`` so a Blueprint can use them without importing the whole Flask
module (which would be a cycle). ``app.py`` imports them back under the same names, so its other
call sites are unchanged. Each is pure: it reads ``flask.request`` and renders ``flask.jsonify``,
with no closure over ``app``-only globals.

Numeric readers live in ``core.values``: a service or a node that only needs "what number did
the human mean" must not import the HTTP layer.
"""

from flask import jsonify, request

from i18n import t


def _json_body() -> dict | None:
    """The request's JSON body as an object, or ``None`` when it is unusable.

    Every POST handler here used to open with ``request.get_json()`` (optionally
    ``or {}``). A body that is *valid JSON but not an object* — ``null``,
    ``[1, 2]``, ``"abc"`` — then reached ``data.get(...)`` and raised
    AttributeError, i.e. an HTML 500 for what is a client mistake; and the
    ``silent=True`` variants hid the same mistake behind an empty dict, so the
    handler answered as if the user had sent nothing.

    A request with no body at all keeps meaning "no fields" (``{}``), which is
    what ``or {}`` did and what the frontend relies on for its optional
    payloads. Only a body that *is* there but is not an object is refused.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    # ``get_json`` answers None both for "nothing to parse" and for the literal
    # ``null``, so the raw bytes tell those two apart.
    if not request.is_json or not request.get_data().strip():
        return {}
    return None


def _bad_body():
    """The 400 every route returns for a body :func:`_json_body` refused."""
    return jsonify({'ok': False, 'error': t('api.bodyNotObject')}), 400


def _bad_param(name: str):
    """The 400 for one body field whose type a handler cannot work with."""
    return jsonify({'ok': False, 'error': t('api.paramInvalid', name=name)}), 400
