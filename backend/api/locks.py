"""面板锁 Blueprint — the ``/api/locks`` cluster, split out of ``app.py``.

Reads and writes the per-panel lock ledger over ``services.lock_store``. It touches no run
state and no store singleton, so it stands entirely on its own; paths and behaviour are
unchanged from when these two handlers lived in ``app.py``.
"""

from flask import Blueprint, jsonify

from api.http import _bad_body, _json_body
from i18n import t
from services import lock_store

bp = Blueprint('locks', __name__)


@bp.route('/api/locks', methods=['GET'])
def locks_list():
    """Every locked key per panel, so a list panel can paint its lock icons on load.

    One call for all four panels rather than four: the panels open one at a time but the
    answer is tiny, and a single source means a row cannot be locked in one view and not
    another.
    """
    return jsonify({'ok': True, 'locks': lock_store.all_locks()})


@bp.route('/api/locks', methods=['POST'])
def locks_set():
    """Lock or unlock one entry, and return that panel's full lock list.

    Locking is a UI intent with no destructive consequence, so it needs no confirm; the
    panels optimistically flip the icon and reconcile with the returned list.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    panel = data.get('panel')
    key = data.get('key')
    if panel not in lock_store.PANELS or not isinstance(key, str) or not key.strip():
        return jsonify({'ok': False, 'error': t('lock.badKey')}), 400
    locked = bool(data.get('locked'))
    current = lock_store.set_locked(panel, key.strip(), locked)
    return jsonify({'ok': True, 'panel': panel, 'key': key.strip(), 'locked': locked, 'locks': current})
