"""The ingest runtime: the services a crawl run leans on, one layer above the crawlers themselves.

``catbus`` is the subprocess bridge to the second crawl backend, ``runtime`` the crawl-session
runtime (cookie/profile decisions, stop requests), ``lifecycle`` the crawler lifecycle a run wraps,
``net`` the reachability probe that separates "unreachable" from "slow", and ``parts`` the sharded
part-file writer. The name is ``ingest`` rather than ``crawl`` so the package is not a second name
for ``backend/crawlers``. Importing this package imports nothing; callers name
``services.ingest.<module>``.
"""
