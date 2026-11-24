"""The foundation layer: every package may import it, and it imports no package.

Seven modules, each a different kind of "everybody needs this":

``config``   paths, environment knobs and the constants retention/queue/preflight read;
``refs``     small pure helpers (switch reading, name parsing, filenames, platform routing);
``values``   the numeric readers for anything a person typed (``safe_int``/``optional_float``/…).
             They lived in ``api/http.py`` until a node and an engine needed one, which made the
             domain depend on the HTTP layer; "what number did the human mean" is a core question,
             so every layer may ask it without importing Flask;
``machine``  the per-OS facts — where Chrome/chromedriver/xelatex/Node live, what the console can
             write — as tables keyed by the running system, joined with the TARGET's separator;
``procs``    process plumbing (spawn flags, reaping a driver tree) that differs by OS;
``atomic``   the staged-write rename that RETRIES on Windows, where any open handle on the target
             makes ``os.replace`` answer ``PermissionError``. Adopted by every durable store whose
             read can race its own write; each store that kept a bare ``os.replace`` on such a file
             was one reader away from a 500;
``asset``    the identity of a node output (content hash, origin, lineage), read by every layer.

The direction is one-way and mechanical: nothing under ``core/`` may import a domain package or
Flask/Selenium. ``i18n`` is the one product module allowed, because a machine-level refusal has to
be written in the user's language. pandas/numpy/requests are allowed — the app loads them on its
boot path anyway — and the point is that a startup question and a name rule stay answerable without
loading a crawler or the application. Pinned by ``tests/unit/foundation/test_foundation_layering.py``,
which enumerates this package's modules on purpose: another one is a deliberate contract change,
not a convenience — and by ``tests/unit/gates/test_import_graph.py``, which refuses a domain import.
"""
