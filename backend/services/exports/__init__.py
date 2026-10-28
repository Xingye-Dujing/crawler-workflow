"""The export directory: writing table files, and the panel's reader for what is there.

``writer`` is ``DataExporter`` — format-aware table export used by the output node, the API and
tests alike. ``browser`` is the read side: a bounded listing of ``data/exports``, a download that
can only name a file that exists, and a one-at-a-time delete. Importing this package imports
nothing; callers name ``services.exports.<module>``.
"""
