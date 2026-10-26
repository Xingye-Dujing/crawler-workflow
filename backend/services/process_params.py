"""The select-shaped parameter rules every algorithm node is judged by.

One table declares, per operation, which parameter is a select and which spellings mean
something; ``enum_param`` reads it where the value is used, so the string that is checked and
the string the analyzer receives cannot be two different things. The same table answers the
schedule/cloud gate's "will this node call a model?" question, which is why it lives in a
service rather than inside one node plugin.
"""

from api.http import _safe_float

from i18n import t
from services.data_analysis import UnknownOperationError

#: The select-shaped parameter of each analysis-algorithm node, and the spellings that
#: mean something to it. This is the same rule the crawl matrix applies to a ``select``
#: Field and ``DataAnalysisService.STEP_PARAMS`` applies to a cleaning step: a value off
#: the list is refused by name instead of being guessed into another algorithm. Before
#: the table, ``method='TF-IDF'`` ran TextRank (``keyword.py`` compared against one
#: name and treated everything else as the other), ``mode='ML'`` paid for a row-by-row
#: LLM pass the user had just declined (``emotion.py``/``tendency.py`` test only for
#: ``'ml'``), and ``mode='llm'`` on 实体识别 silently ran the rules instead.
#:
#: ``anomaly_method`` and ``topk`` are absent because their own code already refuses or
#: clamps them, and this table guards the sites that had no answer at all.
#:
#: Each entry is ``parameter -> (declared default, the spellings that mean something)``.
#: The default lives here because a blank field is "not stated", and the only safe
#: answer is the one the panel showed — read at the site that uses it, so the string
#: that is checked and the string the analyzer receives cannot be two different things.
PROCESS_ENUMS = {
    # Two ways to wash a table of Weibo comments clean: the model reads one row at a time
    # and judges relevance, or a rule set strips the artifacts a repost leaves behind
    # (转发链, @提及, 话题标签, O网页链接, 展开c) for free and at crawling speed. ``llm`` stays the
    # declared default because that is what a workflow saved before this selector existed
    # was already doing — a blank must not silently change what a stored canvas produces.
    'clean': {'mode': ('llm', ('regex', 'llm'))},
    # All three default to bert (the recommended main path — see docs/why_finetuned_bert.md); the
    # executor resolves the op's registered default model when a node names none, and degrades to a
    # dependency-free mode with a PRINTED line when bert truly cannot run (see process executor).
    'emotion': {'mode': ('bert', ('llm', 'ml', 'bert'))},
    'tendency': {'mode': ('bert', ('llm', 'ml', 'bert'))},
    # The traditional methods answer 正面/负面/中性, which is not the five-emotion or the
    # six-tendency label set — hence its own operation rather than a new mode on theirs.
    # bert is the default; snownlp is the no-model fallback the executor picks when bert cannot run.
    'sentiment': {'mode': ('bert', ('llm', 'ml', 'snownlp', 'bert'))},
    'ner': {'mode': ('regex', ('regex', 'llm'))},
    # The lexicon is the default because it needs no model, costs nothing, and answers the same
    # table every run; ``llm`` is the opt-in that can see the euphemisms a fixed list cannot.
    'aggression': {'mode': ('lexicon', ('lexicon', 'llm'))},
    'keyword': {'method': ('tfidf', ('tfidf', 'textrank', 'tfidf_corpus'))},
    'cluster': {'cluster_method': ('kmeans', ('kmeans', 'kmeans++', 'dbscan'))},
    'correlation': {'corr_method': ('pearson', ('pearson', 'spearman', 'kendall'))},
    'significance': {'sig_method': ('ttest', ('ttest', 'anova', 'mannwhitney', 'kruskal'))},
}

#: Every operation the process executor dispatches, including the four with no select-shaped
#: parameter (``PROCESS_ENUMS`` only lists the ones that have one). ``bot``/``anomaly``/
#: ``correlation``/``significance`` read typed column names instead.
PROCESS_OPS = frozenset(PROCESS_ENUMS) | {'bot', 'anomaly', 'correlation', 'significance'}

#: The operations whose whole job is to read one text column of the table.
_TEXT_COLUMN_OPS = ('clean', 'emotion', 'tendency', 'sentiment', 'keyword', 'cluster', 'ner', 'aggression')

# ─── Column contract (what each op writes, what it reads) ───
#: Ops that ADD these columns and pass the rest through (verified against each analyzer's
#: write site; see the matching unit test).
OUTPUT_ADD_COLUMNS: dict[str, tuple[str, ...]] = {
    'clean': ('action', 'cleaned_text'),
    'emotion': ('emotion', 'confidence'),
    'tendency': ('tendency', 'tendency_confidence'),
    'sentiment': ('sentiment', 'score'),
    'aggression': ('aggression', 'aggression_score', 'aggression_hits'),
    'anomaly': ('anomaly_score', 'is_anomaly'),
}

#: Ops that REPLACE the whole table with a fixed set (the analyzer returns a fresh frame;
#: downstream can only read these).
OUTPUT_REPLACE_COLUMNS: dict[str, tuple[str, ...]] = {
    'correlation': ('col1', 'col2', 'method', 'correlation', 'abs_correlation'),
    'significance': (
        'method',
        'group_column',
        'value_column',
        'statistic',
        'p_value',
        'n_groups',
        'group_sizes',
        'significant_005',
    ),
}

#: Params that name a column the op reads from its input.
READ_PARAMS: dict[str, tuple[str, ...]] = {
    'clean': ('text_column',),
    'emotion': ('text_column',),
    'tendency': ('text_column',),
    'sentiment': ('text_column',),
    'aggression': ('text_column',),
    'ner': ('text_column',),
    'keyword': ('text_column',),
    'cluster': ('text_column',),
    'bot': ('text_column', 'author_column', 'time_column'),
    'anomaly': (),
    'correlation': (),
    'significance': ('group_column', 'value_column'),
}


def enum_param(op: str, params: dict, key: str) -> str:
    """The value a select-shaped process parameter will really be called with.

    ``'TF-IDF'``, ``'ML'`` and ``' tfidf '`` are each a name the operation does not
    know, and every site used to answer one of those with a different algorithm:
    ``keyword.py`` compared against ``'tfidf'`` and took TextRank for everything else
    (then stamped the table's ``method`` column with the name that had not run), while
    ``emotion``/``tendency`` tested only for ``'ml'`` and so took the **row-by-row LLM
    pass** for a misspelled request to use the local model. Clustering already refused;
    this is the same contract, applied where the parameter is read.
    """
    default, allowed = PROCESS_ENUMS[op][key]
    raw = params.get(key)
    value = default if raw is None or (isinstance(raw, str) and not raw.strip()) else str(raw).strip().strip()
    if value not in allowed:
        raise UnknownOperationError(t('analysis.bad_option', op=op, param=key, value=value, allowed=', '.join(allowed)))
    return value


def sentiment_thresholds(params: dict) -> tuple:
    """The two polarity cut-offs a sentiment node asked for, refused when they overlap.

    ``pos=0.3, neg=0.7`` is not an aggressive setting: read in order, every row is at once
    positive (score >= 0.3) and negative (score <= 0.7), so the whole column would come
    back 正面 and nothing would say the question was unanswerable. The band is checked
    rather than normalised because a swap is a guess about which number the user meant.
    """
    pos = _safe_float(params.get('pos_threshold'), 0.6)
    neg = _safe_float(params.get('neg_threshold'), 0.4)
    if neg > pos:
        raise UnknownOperationError(t('sentiment.bad_thresholds', pos=pos, neg=neg))
    return pos, neg


def check_process_params(op: str, params: dict, df) -> None:
    """Refuse an algorithm node whose parameters name nothing it can run.

    Every analyzer answers a missing 文本列 by logging 未找到列 and handing back the
    frame **unchanged**, which settles the node DONE: the run went green, the table
    downstream was the input table, and the only sentence saying why was in the log
    file. A node that did nothing is a failure, so the reason is raised here — at the
    one boundary every op passes through, where the node's own label can be attached
    by the executor.
    """
    for key in PROCESS_ENUMS.get(op) or {}:
        enum_param(op, params, key)
    if op == 'sentiment':
        # Asked here as well as where it is used, so a workflow that cannot answer the
        # question fails at the validation boundary the executor already reports by node.
        sentiment_thresholds(params)
    if op in _TEXT_COLUMN_OPS:
        name = str(params.get('text_column') or '正文').strip()
        if name not in [str(col) for col in df.columns]:
            raise UnknownOperationError(t('analysis.step_col_missing', op=op, col=name))
    if op == 'bot':
        # bot reads three columns, not one: text alone would score the whole table as a single
        # author. Each is refused by name so a missing 评论者 / 评论时间 fails the node rather than
        # producing a plausible-looking all-zero column.
        columns = [str(col) for col in df.columns]
        for key, default in (('text_column', '正文'), ('author_column', '评论者'), ('time_column', '评论时间')):
            name = str(params.get(key) or default).strip()
            if name not in columns:
                raise UnknownOperationError(t('analysis.step_col_missing', op=op, col=name))
