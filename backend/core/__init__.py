"""The foundation layer: every package may import it, and it imports no package.

Three modules, each a different kind of "everybody needs this":

``refs``     small pure helpers (switch reading, name parsing, filenames, platform routing);
``machine``  the per-OS facts — where Chrome/chromedriver/xelatex/Node live, what the console can
             write — as tables keyed by the running system, joined with the TARGET's separator;
``procs``    process plumbing (spawn flags, reaping a driver tree) that differs by OS.

The direction is one-way and mechanical: nothing under ``core/`` may import a domain package,
Flask/Selenium, or the ML stack (sklearn/scipy/matplotlib/joblib). pandas/numpy/requests are
allowed — the app loads them on its boot path anyway — and the point is that a startup question
and a name rule stay answerable without loading a crawler or the application. Pinned by
``tests/unit/test_foundation_layering.py``.
"""
