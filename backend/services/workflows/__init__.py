"""The workflow domain: the saved canvases, their history, reusable templates and project bundles.

``manager`` owns ``data/workflows/*.json`` (save/list/load/rename), ``history`` the canvas
snapshots and layout baselines in ``workflow_history.db``, ``reusable`` the reusable-node
template store, ``expand`` the server-side expansion of a reusable node into the nodes a run
executes, and ``bundle`` the project zip (workflows + the datasets/templates they reference).

Importing this package imports nothing: callers name ``services.workflows.<module>``.
"""
