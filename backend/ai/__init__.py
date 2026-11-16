"""The AI workspace: one provider catalog, one conversation store, one agent runtime.

The package is deliberately split by lifetime rather than by route:

* ``providers`` — transports. A provider knows how to stream one request and what it can do;
* ``store`` — the durable per-account transcript and agent records;
* ``context`` — what the model is allowed to read, in what order and under which budget;
* ``skills`` / ``tools`` — the assistant's expert modes and its read-only verbs;
* ``agent`` — the turn loop that ties a provider, a skill and the tools together;
* ``extensions`` — the plugin host that lets all of the above grow without editing this file.

No module here imports Flask. The HTTP layer lives in ``api/ai.py``.
"""

API_VERSION = 1
