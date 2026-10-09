"""Request-body / argument helpers shared by every HTTP handler.

These moved out of ``app.py`` so a Blueprint can use them without importing the whole Flask
module (which would be a cycle). ``app.py`` imports them back under the same names, so its other
call sites are unchanged. Each is pure: it reads ``flask.request`` and renders ``flask.jsonify``,
with no closure over ``app``-only globals.
"""

import math

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


def _safe_int(value, default: int = 0, minimum: int = None, maximum: int = None) -> int:
    """int() for numbers typed into the UI.

    Every settings field arrives as a string, so "abc" used to raise a bare
    ValueError from inside a request handler (HTTP 500) or from a node (opaque
    node failure). A malformed value now falls back to the default.

    ``inf`` / ``nan`` are the same class of mistake and used to escape it:
    ``float('inf')`` parses fine and only ``int()`` then refuses it with an
    OverflowError, which no ``except (TypeError, ValueError)`` catches — so
    ``/api/history/runs?limit=inf`` answered 500. Anything not finite is
    rejected up front, exactly like unparseable text.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    result = int(number)
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _safe_float(value, default: float = 0.0) -> float:
    """``_safe_int`` for a float field.

    ``inf``/``nan`` poison every pandas call downstream instead of failing here, so they
    are not usable numbers any more than "abc" is — both fall back to ``default``.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _optional_int(value):
    """Like :func:`_safe_int`, but blank or unparseable means "not configured" (None)."""
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number)


def _optional_float(value):
    """``_optional_int`` that keeps the fraction. ``frac=inf`` reached df.sample as a
    ValueError and ``frac=nan`` as a silent no-op; both mean "no fraction configured"."""
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
