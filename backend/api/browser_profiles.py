"""Browser-profiles Blueprint — ``GET /api/browser/profiles`` and the template-build ``POST``.

Reports one row per sign-in-capable platform plus the pristine template's state, and (POST) builds
that template. Depends only on ``browser_profiles``, the shared ``profiles.ensure_profile_template``,
``crawl_capabilities``, ``CookieManager``, ``Config`` and ``api.http`` — no run state, no stores.
Paths unchanged; app-level ``before_request`` / CORS still wrap them.
"""

import os

import browser_profiles
from flask import Blueprint, jsonify
from profiles import ensure_profile_template

import crawl_capabilities as capabilities
from api.http import _bad_body, _json_body
from config import Config
from services.cookie_manager import CookieManager
from utils.helpers import as_bool

bp = Blueprint('browser_profiles', __name__)


@bp.route('/api/browser/profiles/template', methods=['POST'])
def build_profile_template():
    """One blank Chrome, once, to make the directory every new account starts from.

    On a cloud host this is how a device comes into the world at all: the button that
    used to create one by logging in is not offered there. The cookie-save path calls
    the same function by itself (see :func:`profiles.ensure_profile_template`), so this
    route exists for an operator who wants to rebuild it now — and for a machine where
    no cookie has been pasted yet.
    """
    body = _json_body()
    if body is None:
        return _bad_body()
    force = as_bool(body.get('force'))
    result = ensure_profile_template(force=force)
    # 502, not 200-with-a-lie: the directory was asked for and does not exist, and the
    # reason (no chromedriver, Chrome refused) is what the caller has to act on.
    return jsonify(result), (200 if result.get('ok') else 502)


@bp.route('/api/browser/profiles', methods=['GET'])
def get_browser_profiles():
    """One row per platform that has a login session at all.

    WeChat is deliberately absent: its article bodies need no login (there is no
    cookie row for it anywhere in this app), so a browser profile would be a
    directory of nothing — and a row in this table reads as "you should log in here".

    Three things can only be checked from the request side:

    * the payload covers **every platform the cookie panel can sign into**, in matrix
      order (a platform missing here is one whose state the user cannot see);
    * `recommended` is read off the crawl matrix, not from a second list this endpoint
      keeps by hand;
    * a directory is reported as *existing* only after something created it, and as
      *imported* only after a cookie actually went in. Those two booleans are the whole
      guidance sentence in the panel.
    """
    rows = {'ok': True, 'enabled': browser_profiles.is_enabled(), 'root': browser_profiles.root_dir()}
    # The template's own row, because "no new account can be made without it" is the
    # thing a cloud operator needs to see before they paste a cookie. The walk is over a
    # first-run skeleton (hundreds of files at most), not over a used profile — which is
    # why this may check the contents while the per-account rows below pass ``size=False``.
    rows['template'] = {
        'exists': browser_profiles.template_exists(),
        'pristine': not browser_profiles.find_session_material(),
    }
    rows['profiles'] = []
    for cap in capabilities.CAPABILITIES:
        platform = cap.platform
        if not CookieManager.is_supported(platform):
            continue
        saved = os.path.join(Config.COOKIE_DIR, f'{platform}_cookies.json')
        rows['profiles'].append(
            browser_profiles.status(
                platform,
                recommended=cap.profile_recommended,
                has_cookie=os.path.isfile(saved),
                # The path, not the contents: this is what lets the panel say "the file you
                # saved is not the session this profile holds" without reading a cookie.
                cookie_path=saved,
            )
        )
    return jsonify(rows)
