"""The report domain: a run turned into something a person reads.

``html`` builds the self-contained HTML run report (customizable content; PDF goes only through the
LaTeX paper), and ``paper`` assembles the article+ctex paper from a run's registered LaTeX
figures/tables and compiles it. Importing this package imports nothing; callers name
``services.reports.<module>``.
"""
