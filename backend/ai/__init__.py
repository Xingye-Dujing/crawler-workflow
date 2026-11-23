"""The product's AI domain facts, served through the agent-workspace framework.

The package is split by what it knows rather than by route:

* ``providers`` — transports; a provider streams one request and declares what it can do;
* ``context`` — the generated project map and a search over the repository's own docs;
* ``skills`` / ``tools`` — the assistant's expert modes and its domain verbs (the framework's
  generic tools live in the framework);
* ``validators`` / ``previews`` — strict-shape checks and descriptions for a proposed artifact;
* ``vocabulary`` / ``workflow_draft`` — the legal canvas vocabulary and the draft round trip;
* ``workspace`` — the machine's folder picker and the product's table import;
* ``monitors`` — the run-event vocabulary the monitor builder offers;
* ``file_text`` / ``dataset_access`` / ``files`` — attachment extraction, per-conversation row
  grants and the standalone search/fetch APIs.

The durable store, the turn loop, approvals, plugins and the HTTP surface are the framework's
(``/api/ai/ws``). No module here imports Flask.
"""

API_VERSION = 1
