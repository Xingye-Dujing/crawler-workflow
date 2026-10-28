"""The analysis domain: the data ops, their parameter vocabulary, the model context and the lexicon.

``pipeline`` is the op executor (``DataAnalysisService`` — clean/analysis/process steps over a
table), ``params`` the analysis-step parameter normalisers, ``process`` the process-node op matrix,
``llm`` the per-run LLM context a step borrows (client, cache scope, language), ``lexicon`` /
``lexicon_store`` the editable sentiment/topic word lists (``data/lexicon.db``) and ``stats`` the
sentiment/tendency summary service.

Importing this package imports nothing: callers name ``services.analysis.<module>``.
"""
