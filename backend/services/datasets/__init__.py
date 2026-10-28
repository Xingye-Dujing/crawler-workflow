"""Dataset storage and row identity: the datasets.db side of the app.

``store`` is the uploaded/merged dataset ledger (content-addressed files + ``datasets.db``),
``merge`` joins stored datasets into one table with a ``来源`` column, and ``dedupe`` is the
normalise + SimHash pair that decides two rows are the same comment without hashing volatile
detail. Importing this package imports nothing; callers name ``services.datasets.<module>``.
"""
