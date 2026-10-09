"""HTTP-layer modules split out of ``app.py`` (see docs/ARCHITECTURE.md, Refactor step A).

Each module here defines a Flask ``Blueprint`` for one route cluster, with paths unchanged so the
test client and frontend keep hitting the same URLs. Shared request plumbing lives in
``api.http``; process state in ``backend/state.py``. ``app.py`` imports and registers these.
"""
