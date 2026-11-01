"""``/api/lexicon`` — CRUD for the user-editable word lists behind the analysis pipeline.

Two kinds: ``stopword`` (extra words dropped from every frequency table) and ``userdict``
(jieba domain terms that must survive tokenisation). Mirrors ``api/data.py``: the same body
helpers, the same ``{ok, ...}`` envelope, refusals localised through ``t('lex.*')``. Every
write bumps the store version (so the analyzers reload their cached stopword set) and, for
``userdict``, re-materialises + reloads the jieba dictionary so the next run sees it.
"""

import logging

from core.refs import as_bool
from flask import Blueprint, jsonify, request
from runtime.stores import get_lexicon_store

from api.auth import is_admin
from api.http import _bad_body, _bad_param, _json_body, _safe_int
from i18n import t
from services.accounts.service import accounts_mode
from services.analysis.lexicon import reload_userdict
from services.analysis.lexicon_store import KINDS

logger = logging.getLogger(__name__)

bp = Blueprint('lexicon', __name__)


@bp.route('/api/lexicon', methods=['GET'])
def list_lexicon():
    kind = (request.args.get('kind') or '').strip()
    if kind and kind not in KINDS:
        return jsonify({'ok': False, 'error': t('lex.unknownKind', kind=kind)}), 400
    limit = _safe_int(request.args.get('limit'), 5000, minimum=1, maximum=20000)
    store = get_lexicon_store()
    return jsonify({'ok': True, 'entries': store.list(kind or None, limit=limit), 'counts': store.counts()})


def _write_refusal():
    """Why this caller may not edit the lexicons.

    The store is a SINGLETON on this machine (``runtime.stores.get_lexicon_store``) — there is
    no per-account slot — and every write reloads jieba for the whole process. So an ordinary
    account adding a stopword (or clearing the user dictionary) silently changes what every
    OTHER account's next tokenisation, word cloud and topic analysis produce. That is the same
    machine-level write ``/api/settings`` guards, and it gets the same door.
    """
    if accounts_mode() and not is_admin():
        return jsonify({'ok': False, 'error': t('accounts.adminRequired')}), 403
    return None


@bp.route('/api/lexicon', methods=['POST'])
def add_lexicon():
    refusal = _write_refusal()
    if refusal is not None:
        return refusal
    body = _json_body()
    if body is None:
        return _bad_body()
    kind = body.get('kind')
    if kind not in KINDS:
        return jsonify({'ok': False, 'error': t('lex.unknownKind', kind=str(kind))}), 400
    terms = body.get('terms')
    if not terms or (isinstance(terms, str) and not terms.strip()):
        return jsonify({'ok': False, 'error': t('lex.needTerms')}), 400
    if not isinstance(terms, (list, tuple, str)):
        return _bad_param('terms')
    result = get_lexicon_store().add(kind, terms)
    if kind == 'userdict':
        reload_userdict()
    return jsonify({'ok': True, **result, 'counts': get_lexicon_store().counts()})


@bp.route('/api/lexicon', methods=['DELETE'])
def delete_lexicon():
    refusal = _write_refusal()
    if refusal is not None:
        return refusal
    body = _json_body()
    if body is None:
        return _bad_body()
    kind = body.get('kind')
    if kind not in KINDS:
        return jsonify({'ok': False, 'error': t('lex.unknownKind', kind=str(kind))}), 400
    store = get_lexicon_store()
    if as_bool(body.get('clear')):
        removed = store.clear(kind)
    else:
        term = body.get('term')
        if not isinstance(term, str) or not term.strip():
            return _bad_param('term')
        removed = store.remove(kind, term)
    if kind == 'userdict':
        reload_userdict()
    return jsonify({'ok': True, 'removed': removed, 'counts': store.counts()})
