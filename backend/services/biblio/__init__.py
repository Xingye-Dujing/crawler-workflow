"""The bibliometrics domain: import, normalise, build the network, view it, monitor it.

One module per concept, without the old ``biblio_`` prefix: ``importer`` turns an export into
rows (the per-format readers live in ``formats/``), ``schema`` is the normalised column contract,
``metrics`` builds the co-occurrence/citation network and its indicators, ``cluster``/``refs``/
``fuse``/``geo`` are the algorithmic pieces, ``charts`` renders, ``store`` keeps projects and
snapshots, ``monitor`` compares runs, ``sources`` describes where to export from.

This ``__init__`` imports nothing: callers name ``services.biblio.<module>`` so the import graph
stays explicit and a page that only needs ``schema`` does not pay for pandas or the chart stack.
"""
