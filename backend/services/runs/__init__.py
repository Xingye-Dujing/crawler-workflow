"""The run domain: what a run is, what it produced, and when it goes away.

``store`` is the checkpointing core (``runs.db``: runs, node attempts, rows, fingerprints, the
LLM cache, the run→file ledger), ``files`` the per-run artefact ledger, ``windows`` the time-window
helpers a run/panel filters by, ``compare`` the run-vs-run diff, ``history`` the execution-history
ledger (``history.db``) and ``housekeeping`` the retention/cleanup pass.

Importing this package imports nothing: callers name ``services.runs.<module>``.
"""
