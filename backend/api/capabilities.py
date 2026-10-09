"""Capabilities Blueprint — ``GET /api/capabilities``.

Serves the crawl matrix so the Data Source panel is built from the server's own knowledge rather
than a fourth hard-coded copy in the browser. The one non-static part is 账号: which accounts exist
is which cookie files are on disk *now*, so the field's option list is extended here at send time
from ``state.cookie_manager``. Paths unchanged; app-level ``before_request`` / CORS still wrap.
"""

from flask import Blueprint, jsonify
from state import cookie_manager

import crawl_capabilities as capabilities
from services.cookie_manager import CookieManager

bp = Blueprint('capabilities', __name__)


@bp.route('/api/capabilities', methods=['GET'])
def get_capabilities():
    """The crawl matrix, so the browser can build the Data Source panel from it.

    The panel used to hard-code which platforms exist, which of them take links
    instead of a keyword and which fields belong to which mode — a fourth copy of
    a fact the executor already had to know. Labels travel as catalogue keys
    because this payload has no language: the canvas translates it into whichever
    one the user is reading.

    The one list that cannot be static is 账号: which accounts exist is which cookie
    files are on disk NOW, so the field's declared default option is extended here
    at send time. The account name doubles as its own label (it is user-typed, not
    a catalogue key — ``I18n.t`` answers an unknown key verbatim, which is exactly
    the intent); the panel needs no new code to show a new account.
    """
    payload = capabilities.as_dict()
    for cap in payload.get('platforms', []):
        # Creation order, not alphabetical: the list the node picks from is "which logins does this
        # machine have", and a user who added work-then-home expects home to still be second.
        accounts = cookie_manager.accounts_in_order(cap.get('platform') or '')
        # Creation order, not alphabetical: the list the node picks from is "which logins does this
        # machine have", and a user who added work-then-home expects home to still be second.
        # Every entry is a NAME now — the default account included — and the words for the ones
        # this program named (default, default2) come from the catalogue while a typed name is
        # shown as typed, which is the same rule the cookie rows travel by. A name with no
        # file is not offered at all: it names a login this machine cannot produce, and
        # validation refuses a node that still asks for it (#28).
        options = []
        for account in accounts:
            label_key, _args = CookieManager.account_label_key(account)
            # A generated name (default/default2) travels as its catalogue key; a typed name has
            # NO key — leave it empty so the panel shows the value as typed instead of asking i18n
            # to translate a word the program never defined (which only logged a missing-string
            # warning and echoed the raw name anyway). Same rule the cookie rows use above.
            options.append({'value': CookieManager.key(account), 'labelKey': label_key or ''})
        if not options:
            # Nothing is saved anywhere: the row stays, because a structurally empty select
            # cannot show the account the user is about to save, and it is that account.
            options = [{'value': CookieManager.DEFAULT_ACCOUNT, 'labelKey': 'cookies.accountDefault'}]
        for mode in cap.get('modes', []):
            for field in mode.get('fields', []):
                if field.get('key') == 'account':
                    field['options'] = options
                    # A node added now logs in as the first login this machine has, rather
                    # than as "not chosen" — which used to mean the default file, existing
                    # or not, and then a crawl that silently hit a wall it could not open.
                    # With nothing saved the answer is still a name: the default account is
                    # the account that save would create, so a node never carries a blank
                    # where a later comparison has to guess what it meant.
                    field['default'] = CookieManager.key(accounts[0]) if accounts else CookieManager.DEFAULT_ACCOUNT
    return jsonify(payload)
