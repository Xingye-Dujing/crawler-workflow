"""The foundation layer: every package may import it, and it imports no package.

Five modules, each a different kind of "everybody needs this":

``config``   paths, environment knobs and the constants retention/queue/preflight read;
``refs``     small pure helpers (switch reading, name parsing, filenames, platform routing);
``machine``  the per-OS facts — where Chrome/chromedriver/xelatex/Node live, what the console can
             write — as tables keyed by the running system, joined with the TARGET's separator;
``procs``    process plumbing (spawn flags, reaping a driver tree) that differs by OS;
``atomic``   the staged-write rename that RETRIES on Windows, where any open handle on the target
             makes ``os.replace`` answer ``PermissionError``. Every durable store writes through it,
             and each store that kept its own bare ``os.replace`` was one reader away from a 500.

The direction is one-way and mechanical: nothing under ``core/`` may import a domain package,
Flask/Selenium, or the ML stack (sklearn/scipy/matplotlib/joblib). pandas/numpy/requests are
allowed — the app loads them on its boot path anyway — and the point is that a startup question
and a name rule stay answerable without loading a crawler or the application. Pinned by
``tests/unit/foundation/test_foundation_layering.py``, which enumerates this package's modules on
purpose: a fifth one is a deliberate contract change, not a convenience.
"""
