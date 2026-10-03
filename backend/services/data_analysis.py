import hashlib
import logging
import math
import re

import pandas as pd

from i18n import t
from utils.helpers import split_names

logger = logging.getLogger(__name__)

# Values that mean false when a text column is converted to bool. Without this
# map ``astype(bool)`` turns the *string* 'False' — and '0' — into True.
_FALSEY_TEXT = {'', '0', '0.0', 'false', 'no', 'n', 'off', 'none', 'null', 'nan', '假', '否', '不'}


def _stable_seed(df: pd.DataFrame) -> int:
    """A sampling seed that repeats for one input and differs between inputs.

    ``df.sample`` without ``random_state`` draws from the process-wide RNG, so any
    pipeline containing a sample step answered differently on every run of *the
    same* data — which breaks the promise the whole engine is built on (a
    repeated or resumed run reproduces the previous result, so re-running never
    silently changes the rows a paid-for downstream step was computed from).

    The seed is therefore derived from the frame itself: its shape, its column
    names and the row hashes of its first and last row. Deterministic (pandas
    hashes with a fixed key), cheap enough to pay per step, and still spread
    across the seed space so two datasets do not sample the same rows.
    """
    digest = hashlib.sha1()
    digest.update(f'{df.shape[0]}x{df.shape[1]}|'.encode())
    digest.update(repr([str(c) for c in df.columns]).encode('utf-8', 'replace'))
    edges = pd.concat([df.head(1), df.tail(1)]) if len(df) else df.iloc[0:0]
    try:
        # uint64 row hashes, not the values themselves: this stays cheap on a
        # wide text frame and never trips over the encoding of a cell.
        digest.update(pd.util.hash_pandas_object(edges, index=True).to_numpy().tobytes())
    except (TypeError, ValueError):
        # Unhashable cells (a column of dicts or lists) — fall back to a textual
        # dump, which is still the same bytes for the same rows.
        digest.update(repr(edges.values.tolist()).encode('utf-8', 'replace'))
    # 4 bytes: numpy's legacy RandomState only accepts a seed in 0 … 2**32 - 1.
    return int.from_bytes(digest.digest()[:4], 'big')


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        try:
            if pd.isna(value):
                return False
        except (TypeError, ValueError):
            return False
        return value != 0
    return str(value).strip().lower() not in _FALSEY_TEXT


class UnknownOperationError(ValueError):
    pass


#: The select-shaped parameters of each cleaning step. A step reads these the way the
#: crawl matrix reads a ``select`` Field: only the listed spellings mean something,
#: and anything else is refused by name instead of being guessed into a different
#: operation. Before this table, ``convert_type(dtype='number')`` silently produced
#: text, ``fill_null(method='mean')`` silently filled a literal value, and
#: ``drop_null(how='none')`` died inside pandas with a stack trace.
FILTER_OPS = (
    'eq',
    'ne',
    'gt',
    'gte',
    'lt',
    'lte',
    'contains',
    'not_contains',
    'in',
    'not_in',
    'is_null',
    'not_null',
)
CONVERT_TYPES = ('str', 'int', 'float', 'bool', 'datetime')
DROP_HOW = ('any', 'all')
#: ``fill_null`` accepts pandas' own aliases, so both spellings of each pair are named
#: rather than mapped: the value that reaches the step has to be one the step honours.
FILL_METHODS = ('ffill', 'pad', 'bfill', 'backfill')
#: How ``drop_duplicates`` decides two rows are the same row. ``exact`` is pandas'
#: equality over the selected columns; ``normalized`` compares the identity form
#: that :mod:`services.text_dedupe` computes, so a comment farm's extra emoji code, a
#: fresh tracking link or a re-pasted forward chain no longer makes a row unique.
DEDUPE_MODES = ('exact', 'normalized')
#: Which calendar part :meth:`DataAnalysisService.extract_time` can derive. ``date`` is the
#: one an event study is built on — a day is the unit every phase boundary is drawn in.
TIME_PARTS = ('date', 'hour', 'weekday', 'month', 'year')


# Module-level, not lambdas: sklearn's vectorisers keep the callable they were built with,
# and these two are handed to one inside ``topic_model``. They are also what makes the
# tokenisation explicit — jieba has already cut the text into space-separated tokens, so the
# vectoriser only has to split, and doing that here keeps the same convention the ML
# classifiers use (``analyzers.ml_base``).
def _split_tokens(text: str) -> list:
    return str(text).split()


def _keep_text(text: str) -> str:
    return text


JOIN_HOW = ('left', 'right', 'inner', 'outer', 'cross')

#: Where a topic's 特征词 come from. ``tfidf`` is what the study says it used (TF-IDF over the
#: words LDA put in a document), and it inherits jieba's candidate rule of two characters or
#: more — so a single-character word like 捞, which is in the paper's own table, can only come
#: out of ``lda`` (the topic-word distribution reads the vectoriser's vocabulary directly).
#: That difference is why the switch is visible on the panel instead of being one behaviour.
WORD_SOURCES = ('tfidf', 'lda')

#: What :meth:`DataAnalysisService.topic_label` does when the model refuses one topic.
#: ``abort`` is the default: a table whose 主题概括 column is quietly half empty is the paper's
#: table with holes in it, and the export cannot tell an empty cell from a topic the model
#: was never asked about. ``blank`` is the opt-in for a long run the user does not want to
#: restart, and it logs one line per topic it gave up on.
ON_FAIL = ('abort', 'blank')

#: Steps that need the run's LLM client, and so are handed it by :func:`run_pipeline`.
#: Kept out of the step's own ``params`` because the pipeline report — which the console
#: prints and the run record keeps — echoes every parameter it is given.
LLM_OPS = frozenset({'topic_label'})

#: What :meth:`DataAnalysisService.forecast` extrapolates with. Both are computed in this
#: module: statsmodels is not a dependency of this project, and a two-parameter smoothing
#: written out is short enough to read next to the numbers it produced.
FORECAST_METHODS = ('moving_average', 'holt')

#: The stage part of a topic id: 表 1 numbers its topics TopicⅠ-1 … TopicⅤ-4, and the numeral
#: is the stage's POSITION in the lifecycle — which is why the order has to be declared rather
#: than read off the code points of Chinese names ('二次爆发期' sorts before '发酵期').
STAGE_NUMERALS = ('Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ', 'Ⅺ', 'Ⅻ')

#: Sentinel for a select with no fallback: leaving it blank is a missing choice, and
#: guessing one is the bug this table exists to stop. ``filter_rows`` uses it — defaulting
#: a blank comparison to ``eq`` would answer a mistyped filter with "the data was already
#: clean", which is the sentence this repo refuses to print.
NO_DEFAULT = object()

#: What each step needs from the table it is handed, checked before it runs.
#:
#: ``one`` names exactly one column, so a blank or an absent name is a mistake the user
#: can fix — it is NOT read as "every column". ``some`` names a subset where an empty
#: list legitimately means "every column" (the panel's 留空=全部 behaviour, which several
#: saved pipelines rely on). ``enums`` maps each select to ``(its fallback, the names it
#: accepts)``, the fallback being :data:`NO_DEFAULT` when a blank has to be refused.
#: ``nonblank`` is a parameter that names a *new* column or an expression: writing it
#: blank used to "succeed" by adding a header the CSV export shows as an empty cell.
#:
#: Applied in :meth:`DataAnalysisService.run_pipeline`, which both the analysis node and
#: ``/api/analysis/run`` go through, so one table guards every entry point — and after
#: :func:`normalize_step_params`, which is what makes each check a question about the
#: value the operation really receives.
STEP_PARAMS: dict = {
    'drop_null': {'some': ('columns',), 'enums': {'how': ('any', DROP_HOW)}},
    'fill_null': {'some': ('columns',), 'enums': {'method': (None, FILL_METHODS)}},
    'drop_duplicates': {'some': ('columns',), 'enums': {'mode': ('exact', DEDUPE_MODES)}},
    # SimHash near-duplicates read ONE column: the fingerprint is over a text, so a
    # multi-column ask would have to invent a concatenation order nobody chose.
    'dedupe_similar': {'one': ('column',)},
    'select_columns': {'some': ('columns',)},
    'strip_whitespace': {'some': ('columns',)},
    'filter_rows': {'one': ('column',), 'enums': {'op': (NO_DEFAULT, FILTER_OPS)}},
    'rename_columns': {'mapping': True},
    'convert_type': {'one': ('column',), 'enums': {'dtype': ('str', CONVERT_TYPES)}},
    'sort_rows': {'one': ('column',)},
    'groupby_agg': {'one': ('group_col', 'agg_col')},
    'join_tables': {'enums': {'how': ('left', JOIN_HOW)}},
    'column_calc': {'nonblank': ('new_col', 'expr')},
    'bin_column': {'one': ('column',)},
    'sample_rows': {},
    # ── the event-study steps ──
    # All four name ONE column: an unnamed timestamp is not "every timestamp", and a topic
    # model over a column nobody named has no corpus to read. A blank is refused by name
    # rather than defaulted to 正文, because comment crawls file their text under 评论内容 —
    # a default there would model the wrong column and report it as a result.
    'extract_time': {'one': ('column',)},
    'bin_time': {'one': ('column',)},
    # The boundary proposal reads one timestamp column and writes a table of its own, so a
    # column it cannot find is a refusal, not an empty suggestion.
    'suggest_stages': {'one': ('column',)},
    'topic_model': {'one': ('column',)},
    # The staged model needs BOTH columns named: a phase column it has to guess would decide
    # the paper's table by dict order. ``topics`` is nonblank because a blank stage-topic count
    # has no defensible default — 5 would be this project's choice, not the user's.
    'topic_by_stage': {
        'one': ('column', 'stage_col'),
        'nonblank': ('topics',),
        'enums': {'word_source': ('tfidf', WORD_SOURCES)},
    },
    # The two figure steps read a text column and fit their own model, so the column is the one
    # thing they cannot do without. Their topic count keeps the declared default the panel
    # shows, exactly as ``topic_model`` does.
    'topic_map': {'one': ('column',)},
    'topic_salience': {'one': ('column',)},
    # The labelling step reads the word cell and writes the summary cell; both are named, and
    # an unnamed 概括 column would "succeed" by adding a header the export shows as empty.
    'topic_label': {
        'one': ('words_col',),
        'nonblank': ('summary_col',),
        'enums': {'on_fail': ('abort', ON_FAIL)},
    },
    'sentiment_evolution': {'one': ('column',)},
    # The three reads that follow the staged model all name the columns 分阶段 LDA writes: a
    # lifecycle built on a guessed word column is a story about the wrong cell, and these steps
    # would still print a complete-looking table. ``size_col`` for the timeline is gated for the
    # same reason — a peak taken from a column that holds text is a peak measured from zeros.
    'topic_timeline': {'one': ('stage_col', 'words_col', 'size_col')},
    'topic_flow': {'one': ('stage_col', 'topic_col', 'weights_col')},
    # The sweep and the co-occurrence graph both read one text column, exactly as the topic
    # steps do: neither has a defensible fallback corpus to pick.
    'topic_coherence': {'one': ('column',)},
    'cooccur': {'one': ('column',)},
    # Both look-forward steps read a CURVE, so the period column and the value column are each
    # named: a forecast of whichever numeric column was nearest in the table would put a line on
    # a chart nobody asked for and label it 预测情感走向.
    'forecast': {
        'one': ('column', 'value_col'),
        'enums': {'method': ('moving_average', FORECAST_METHODS)},
    },
    'alert': {'one': ('column', 'index_col')},
}


def _blank(value) -> bool:
    """Nothing stated: absent, or the empty text a cleared settings box leaves behind."""
    return value is None or (isinstance(value, str) and not value.strip())


#: The timestamp shape THIS PROJECT'S OWN weibo crawler writes: '2022年01月27日 00:59'.
#:
#: ``crawlers/weibo.py`` normalises an absolute RFC-822 stamp to ISO, but the search page
#: hands back the site's own Chinese display label for most rows and that label is kept as
#: it came (``times.normalise_rfc822`` returns anything it cannot parse untouched, on
#: purpose — inventing an absolute time for a relative label would be worse). So the
#: project emits a column its own time operators cannot read: ``pd.to_datetime`` answers
#: every one of those rows with NaT, and the whole day/phase/sentiment-curve chain then
#: produces one empty column and reports success. Measured on a real export: 4000 of 4000
#: sampled rows are this shape and nothing else.
_CJK_DATE_RE = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')


def _to_datetime(values):
    """Parse a timestamp column, including the shape our own crawler writes.

    The CJK date form is folded to ISO first and then parsed once for the whole column.
    The substitution is a no-op on a string that is already ISO, so a column carrying both
    shapes (an export where some rows took the absolute path and others did not) parses
    whole rather than half — which is the case the old single call got wrong.
    """
    text = values.astype('string')
    folded = text.str.replace(_CJK_DATE_RE, r'\1-\2-\3', regex=True)
    return pd.to_datetime(folded, errors='coerce', format='mixed')


def _stage_key(value) -> str:
    """One stage cell as the name it is matched by; ``''`` for "this row got no phase"."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ''
    return str(value).strip()


def _stage_order(df: pd.DataFrame, stage_col: str, order_col: str, op: str = 'topic_by_stage') -> list:
    """The lifecycle order of the stage names in this table, or a refusal naming the fix.

    :meth:`DataAnalysisService.bin_time` builds an ORDERED categorical, so a phase column that
    never left its own node carries the order the user typed. The moment the table crosses a
    node boundary it is rebuilt from records (``pd.DataFrame(current_input)``) and the ordering
    is gone: what remains is a column of Chinese strings whose code-point order puts 二次爆发期
    before 发酵期. Sorting by that would reprint 表 1 out of sequence and renumber every Topic
    numeral, so this asks for the order instead of guessing one.
    """
    values = df[stage_col]
    if getattr(values.dtype, 'name', '') == 'category' and values.cat.ordered:
        return [str(name) for name in values.cat.categories if str(name).strip()]
    if order_col:
        if order_col not in df.columns:
            raise UnknownOperationError(t('analysis.stage_order_col', op=op, col=order_col))
        # Two kinds of column answer this, in this order of preference. A NUMBER is the phase's
        # own position — which is exactly what :meth:`DataAnalysisService.topic_by_stage` writes
        # into ``stage_order`` so the lifecycle survives the records round trip that erases the
        # categorical. A TIME places each phase at its earliest post, which is the only way to
        # recover the order from a table that has never been modelled yet.
        ranks = pd.to_numeric(df[order_col], errors='coerce')
        if ranks.notna().any():
            return _stage_order_by_rank(values, ranks, order_col, op, 'rank')
        stamps = _to_datetime(df[order_col])
        if stamps.notna().any():
            return _stage_order_by_rank(values, stamps, order_col, op, 'time')
        raise UnknownOperationError(
            t(
                'analysis.stage_order_unparsed',
                op=op,
                col=order_col,
                stages='、'.join(key for key in dict.fromkeys(_stage_key(value) for value in values.tolist()) if key),
            )
        )
    raise UnknownOperationError(t('analysis.stage_order', op=op, col=stage_col))


def _stage_order_by_rank(values, ranks, order_col: str, op: str, kind: str) -> list:
    """Order the phase names by the earliest rank (or timestamp) any of their rows carries.

    ``kind`` only reaches the refusal: "no row of this phase has a number" and "no row of this
    phase has a date" are different mistakes to fix, and a message that says ``{col}`` without
    saying which reading of it failed sends the user to re-type a column that was right.
    """
    first_seen: dict = {}
    names: list = []
    for value, rank in zip(values.tolist(), ranks.tolist(), strict=True):
        key = _stage_key(value)
        if not key:
            continue
        if key not in names:
            names.append(key)
        if pd.notna(rank) and (key not in first_seen or rank < first_seen[key]):
            first_seen[key] = rank
    adrift = [key for key in names if key not in first_seen]
    if adrift:
        # A phase that cannot be placed on the ordering column has no position in the numbering,
        # and appending it at the end would invent one.
        raise UnknownOperationError(
            t(
                'analysis.stage_order_unranked' if kind == 'rank' else 'analysis.stage_order_unparsed',
                op=op,
                col=order_col,
                stages='、'.join(adrift),
            )
        )
    return sorted(names, key=lambda key: first_seen[key])


def _stage_topic_counts(value, stages: list) -> list:
    """Per-stage topic numbers aligned to the lifecycle order the caller resolved.

    One number applies to every stage; a list is matched position by position, because the
    study's own table runs 5/6/4/4/4. A length that does not fit is refused rather than
    truncated or padded — the position is the meaning, and a padded list would silently put
    four topics on the stage the user asked five questions about.
    """
    items = value if isinstance(value, (list, tuple)) else split_names(str(value or ''))
    picked = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        try:
            number = int(text)
        except (TypeError, ValueError):
            raise UnknownOperationError(t('analysis.topic_stage_number', value=text)) from None
        if number < 2:
            raise UnknownOperationError(t('analysis.topic_count', value=number))
        picked.append(number)
    if not picked:
        raise UnknownOperationError(t('analysis.need_param', op='topic_by_stage', param='topics'))
    if len(picked) == 1:
        return picked * len(stages)
    if len(picked) != len(stages):
        raise UnknownOperationError(
            t('analysis.topic_stage_counts', stages=len(stages), counts=','.join(str(n) for n in picked))
        )
    return picked


#: The separators a 特征词 cell can be written with (see :func:`_word_cells`).
_WORD_CELL_RE = re.compile(r'[、,，;；/|]+')

#: The ceiling on candidate words for :meth:`DataAnalysisService.cooccur`. A co-occurrence
#: network is complete: every candidate is compared with every other, so ``topn`` costs
#: ``topn·(topn−1)/2`` pair counters per document — 30 words is 435 pairs, 120 is 7,140, and
#: 500 would be 124,750 per post on a corpus of tens of thousands.
COOCCUR_WORD_CAP = 120


def _whole(value, op: str, param: str) -> int:
    """A count the step reads as an integer, or a named refusal.

    The panel cannot send junk here (``_optional_int`` in ``app.py`` drops an unreadable box to
    the step's default), but a hand-written workflow file and ``/api/analysis/run`` both reach
    this module directly — and ``int('abc')`` arriving at the executor is the opaque node
    failure this repo keeps converting into a sentence that names the parameter.
    """
    if isinstance(value, bool):
        raise UnknownOperationError(t('analysis.need_number', op=op, param=param, value=value))
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise UnknownOperationError(t('analysis.need_number', op=op, param=param, value=value)) from None
    if not math.isfinite(number):
        raise UnknownOperationError(t('analysis.need_number', op=op, param=param, value=value))
    return int(number)


def _word_cells(value) -> list:
    """One 特征词 cell as the ordered list of words it names, without repeats.

    :meth:`DataAnalysisService.topic_by_stage` writes its words joined by 、 and the keyword
    node writes them space-separated, so both spellings (plus the comma and semicolon forms a
    hand-edited CSV picks up) are read here. Order is kept because the paper's table is read
    as a *ranked* list — the first word is the one the topic is most about — and a set would
    throw that away before it reached the comparison.
    """
    words: list = []
    for token in _WORD_CELL_RE.split(str(value if value is not None else '')):
        word = token.strip()
        if word and word not in words:
            words.append(word)
    return words


def _word_weights(value) -> dict:
    """A ``word:weight`` cell as ``{word: weight}``; words without a number are dropped.

    The weights :meth:`topic_by_stage` files are the ones a distribution comparison needs, and
    a cell that parses to nothing is not a flat distribution: treating it as one would compare
    a topic nobody scored against a topic that was, and report the result as a flow. The caller
    refuses on an empty result instead.
    """
    weights: dict = {}
    for chunk in str(value if value is not None else '').split():
        word, _, raw = chunk.rpartition(':')
        if not word:
            continue
        try:
            number = float(raw)
        except ValueError:
            continue
        weights[word.strip()] = number
    return weights


def _standard_deviation(values) -> float:
    """Sample standard deviation (n−1), or 0.0 when there is nothing to spread.

    Written here rather than taken from numpy because the two callers need the SAME convention
    as each other: a band computed with n and one computed with n−1 are different widths, and a
    forecast table whose intervals came from two rules would not be one model's answer.
    """
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((float(value) - mean) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def _forecast_row(stamp, actual, centre, band, horizon: int) -> dict:
    """One row of the forecast table: a past point with its fit, or a future point alone.

    A future row's ``actual`` is ``None`` and never a repeat of the last number: an export that
    fills the cell the reader is looking for would claim the period was observed.
    """
    label = stamp.strftime('%Y-%m-%d') if hasattr(stamp, 'strftime') else str(stamp)
    return {
        'period': label,
        'actual': None if actual is None else round(float(actual), 4),
        'predicted': None if centre is None else round(float(centre), 4),
        'lower': None if centre is None or band is None else round(float(centre) - float(band), 4),
        'upper': None if centre is None or band is None else round(float(centre) + float(band), 4),
        'horizon': horizon,
    }


def _prepare_topic_model(df, column, n_topics, max_features):
    """The guards and the fit that every topic-VISUALISATION step shares.

    Refusals live here rather than in each step because the two views ask the same question of
    the same table, and a ``topic_map`` that answers "not enough texts" in different words from
    ``topic_salience`` is two bugs pretending to be one contract.
    """
    topics = int(n_topics)
    if topics < 2:
        raise UnknownOperationError(t('analysis.topic_count', value=topics))
    usable = df[df[column].notna() & (df[column].astype(str).str.strip() != '')]
    texts = [str(value) for value in usable[column].tolist()]
    if len(texts) < topics:
        raise UnknownOperationError(t('analysis.topic_rows', rows=len(texts), topics=topics))
    try:
        model, matrix, doc_topic, vocabulary = _fit_topic_model(texts, topics, max_features)
    except ValueError as e:
        raise UnknownOperationError(t('analysis.topic_features', err=e)) from e
    return texts, model, matrix, doc_topic, vocabulary


def _fit_topic_model(texts, n_topics, max_features):
    """Fit the LDA that both topic-view steps read, with the same conventions as the table.

    Same tokenizer, same ``random_state`` and the same vectoriser as
    :meth:`DataAnalysisService.topic_model`: a term's frequency in the map, in the salience
    table and in the exported topic list has to be the same number, or the three artifacts
    describe three different models while reading like one analysis.
    """
    import jieba
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer

    tokenized = [
        ' '.join(token for token in jieba.cut(text) if any(char.isalnum() for char in token)) for text in texts
    ]
    vectorizer = CountVectorizer(
        tokenizer=_split_tokens,
        preprocessor=_keep_text,
        token_pattern=None,
        max_features=max(10, int(max_features)),
    )
    matrix = vectorizer.fit_transform(tokenized)
    model = LatentDirichletAllocation(n_components=int(n_topics), random_state=42, learning_method='batch')
    doc_topic = model.fit_transform(matrix)
    return model, matrix, doc_topic, vectorizer.get_feature_names_out()


def _kl2(p, q):
    """KL(p‖q) in bits, over the support where both carry mass (a zero is not a ratio)."""
    import numpy as np

    mask = (p > 0) & (q > 0)
    return float(np.sum(p[mask] * np.log2(p[mask] / q[mask])))


def _jsd(p, q):
    """Jensen-Shannon divergence between two vectors over the SAME vocabulary, in bits.

    Both sides are normalised here, so a caller can hand it raw counts. The vectors have to be
    aligned first: two topics from different stages each carry their own vocabulary, and
    numpy's elementwise arithmetic would either fail on the length difference or — worse,
    because it returns a number — line the two word lists up by position and call the result a
    distance. :meth:`DataAnalysisService.topic_flow` builds the union vocabulary for exactly
    this reason.
    """
    import numpy as np

    left = np.asarray(p, dtype=float)
    right = np.asarray(q, dtype=float)
    if left.sum() <= 0 or right.sum() <= 0:
        return 0.0
    left = left / left.sum()
    right = right / right.sum()
    mixture = (left + right) / 2.0
    return 0.5 * _kl2(left, mixture) + 0.5 * _kl2(right, mixture)


def _jsd_matrix(distributions):
    """Pairwise Jensen-Shannon divergence between topic-word distributions.

    Euclidean distance on the probability vectors is not what this picture needs: two topics
    that differ mostly in rare words are further apart in meaning than their raw distance
    says. The divergence is the symmetric, bounded form of the KL comparison the topic-model
    literature uses for exactly this plot (Sievert & Shirley's intertopic distance map).
    """
    import numpy as np

    rows = np.asarray(distributions, dtype=float)
    rows = rows / rows.sum(axis=1, keepdims=True)
    size = len(rows)
    out = [[0.0] * size for _ in range(size)]
    for left in range(size):
        for right in range(left + 1, size):
            out[left][right] = out[right][left] = _jsd(rows[left], rows[right])
    return out


def _mds_2d(distances):
    """Classical (Torgerson) MDS of a distance matrix, as two stable-signed columns.

    Eigendecomposition of the double-centred squared distances rather than scikit-learn's
    iterative ``MDS``: it is deterministic, and a map whose bubbles move between two runs of
    the SAME table is a figure nobody can cite. Eigenvector signs are arbitrary up to a flip,
    so each axis is turned to make its largest-magnitude coordinate positive — the layout
    then repeats byte for byte, which is what the test asserts.
    """
    import numpy as np

    matrix = np.asarray(distances, dtype=float)
    size = matrix.shape[0]
    if size < 2:
        return [[0.0, 0.0] for _ in range(size)]
    centering = np.eye(size) - np.ones((size, size)) / size
    doubled = -0.5 * (matrix**2) @ centering
    # Symmetrised before the eigensolver: floating-point drift in the product above is real,
    # and ``eigh`` on a non-symmetric input answers with numbers that mean nothing.
    gram = (doubled + doubled.T) / 2.0
    values, vectors = np.linalg.eigh(gram)
    order = np.argsort(values)[::-1][:2]
    coordinates = []
    for position in range(size):
        point = [vectors[position, axis] for axis in order]
        coordinates.append(
            [
                # The eigenvalue of the axis actually chosen (``order`` is a descending
                # permutation of an ASCENDING solver output), not of the solver's first slots:
                # indexing ``values`` by ``axis`` reads the two SMALLEST eigenvalues, which are
                # the noise floor, and silently flattens the map onto one line.
                point[axis] * float(np.sqrt(max(values[order[axis]], 0.0))) if values[order[axis]] > 0 else 0.0
                for axis in range(len(order))
            ]
        )
    for axis in range(len(order)):
        tallest = max(range(len(coordinates)), key=lambda row: abs(coordinates[row][axis]))
        if coordinates[tallest][axis] < 0:
            for row in coordinates:
                row[axis] = -row[axis]
    return [list(point) + [0.0] * (2 - len(point)) for point in coordinates]


def _label_from(answer) -> str:
    """The model's phrase as ONE cell: first non-empty line, decoration off, capped.

    A small local model wraps the phrase in quotes, in 【】, or prefixes it with 「概括：」 even
    when the prompt says not to. The cell goes straight into an exported table, so that is
    taken off here rather than in every reader's spreadsheet; the cap is what keeps one
    rambling answer from turning a 概括 column into a paragraph. An answer that leaves nothing
    returns ``''``, which the caller refuses instead of filing as a blank.
    """
    for line in str(answer or '').splitlines():
        phrase = line.strip().strip('"“”\'`「」 ').strip()
        for prefix in ('主题概括', '概括', 'Summary', 'summary', 'Label', 'label'):
            if phrase.startswith(prefix):
                phrase = phrase[len(prefix) :].lstrip('：: ').strip()
        phrase = phrase.strip('【】《》').strip('：:　').strip()
        # An answer with no letter, digit or ideograph in it is not a label: punctuation only
        # is what a small model returns when it has nothing to say, and filing it as a summary
        # would put 「。」 in the column the paper's findings are read from.
        if phrase and any(char.isalnum() for char in phrase):
            return phrase[:60]
    return ''


def normalize_step_params(op: str, params: dict) -> dict:
    """Coerce one step's parameters into the shape and spelling the operation reads.

    Two entry paths used to disagree about this and nothing told the caller. The node
    executor sends the *flat* panel fields through ``_normalize_analysis_params``, which
    splits ``columns: '名称, 城市'`` into two stripped names; ``/api/analysis/run`` and a
    workflow file's own ``steps`` handed the same params to ``run_pipeline`` as they were,
    so a string was iterated as its **characters** — seven "columns" that match nothing, a
    step that quietly did nothing, and a green node. Normalizing here, at the one place
    both doors pass through, makes them mean the same thing.

    Padding comes off the names and selects, matching what the crawl matrix does with a
    text field (``Field.value_from`` strips), and a blank select becomes its declared
    fallback: passing ``how=''`` on to pandas is a ``ValueError: invalid how option:``
    for a box the user simply left alone. A *value* is deliberately untouched —
    ``filter_rows(value=' ')`` searches for a space, which is a real answer rather than a
    missing one.
    """
    spec = STEP_PARAMS.get(op)
    if spec is None or not isinstance(params, dict):
        return params or {}
    out = dict(params)
    for key in spec.get('some', ()):
        if key in out:
            out[key] = split_names(out[key])
    for key in (*spec.get('one', ()), *spec.get('nonblank', ())):
        if isinstance(out.get(key), str):
            out[key] = out[key].strip()
    for key, (default, _allowed) in (spec.get('enums') or {}).items():
        if key not in out or default is NO_DEFAULT or isinstance(out[key], bool):
            continue
        out[key] = default if _blank(out[key]) else str(out[key]).strip()
    return out


def validate_step(df: pd.DataFrame, op: str, params: dict) -> None:
    """Refuse a step this table cannot carry out, naming the reason.

    The silent alternatives were each worse than an error: a mistyped entry in a column
    *list* was dropped, and when every entry missed, ``drop_null`` read the emptied subset
    as "all columns" and deleted rows the user never aimed at, while
    ``filter_rows``/``sort_rows``/``convert_type`` on a column that does not exist settled
    the node **done** and passed the untouched table downstream — so an export shipped
    unfiltered data with a green check on it.

    Call it with :func:`normalize_step_params` output: it compares the value the operation
    will receive, so a name that passes here is a name that resolves there.
    """
    spec = STEP_PARAMS.get(op)
    if spec is None:
        # An op with no entry here is a gap in this table, not a licence to skip the
        # check; `test_the_gate_knows_every_registered_step` fails the suite first.
        return
    params = params or {}
    columns = [str(col) for col in df.columns]
    for key in spec.get('one', ()):
        name = params.get(key)
        if _blank(name):
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
        if str(name) not in columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op=op, col=str(name)))
    for key in spec.get('some', ()):
        wanted = params.get(key) or []
        missing = [str(name) for name in wanted if str(name) not in columns]
        if wanted and missing:
            raise UnknownOperationError(t('analysis.step_cols_missing', op=op, cols=', '.join(missing)))
    for key, (_default, allowed) in (spec.get('enums') or {}).items():
        if key not in params or params[key] is None:
            continue  # absent: the operation's own signature default answers
        value = str(params[key])
        if not value.strip():
            # A blank here survived normalize_step_params, so this select has no
            # fallback to fall back on and the choice is simply missing.
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
        if value not in allowed:
            raise UnknownOperationError(
                t('analysis.bad_option', op=op, param=key, value=value, allowed=', '.join(allowed))
            )
    for key in spec.get('nonblank', ()):
        if _blank(params.get(key)):
            raise UnknownOperationError(t('analysis.need_param', op=op, param=key))
    if spec.get('mapping'):
        _validate_renames(df, op, params.get('mapping'))


def _validate_renames(df: pd.DataFrame, op: str, mapping) -> None:
    """A rename that would erase a column's name is refused, not applied.

    ``{'标题': ''}`` used to rename the column to the empty string: every later step
    that named 标题 then found nothing, and the exported CSV carried a header cell
    with no word in it. A blank *source* name is the same mistake on the other side,
    and an empty mapping "succeeded" while changing nothing.
    """
    if not isinstance(mapping, dict) or not mapping:
        raise UnknownOperationError(t('analysis.need_param', op=op, param='rename_from'))
    columns = [str(col) for col in df.columns]
    missing, blank_target = [], []
    for source, target in mapping.items():
        name = str(source)
        if not name.strip() or name not in columns:
            missing.append(name.strip() or name)
        elif _blank(target):
            blank_target.append(name)
    if missing:
        raise UnknownOperationError(t('analysis.step_cols_missing', op=op, cols=', '.join(missing)))
    if blank_target:
        raise UnknownOperationError(t('analysis.rename_blank', op=op, cols=', '.join(blank_target)))


class DataAnalysisService:
    """Stateless helpers for cleaning/transforming a DataFrame, plus a
    pipeline runner that chains several steps and reports what changed."""

    # ── Individual, composable operations ───────────────────────

    @staticmethod
    def inspect(df: pd.DataFrame) -> dict:
        return {
            'rows': int(len(df)),
            'columns': list(df.columns),
            'dtypes': {c: str(t) for c, t in df.dtypes.items()},
            'null_counts': {c: int(n) for c, n in df.isna().sum().items()},
            'duplicate_rows': int(df.duplicated().sum()),
        }

    @staticmethod
    def drop_null(df: pd.DataFrame, columns: list = None, how: str = 'any') -> pd.DataFrame:
        subset = [c for c in (columns or []) if c in df.columns] or None
        work = df.copy()
        if subset:
            work[subset] = work[subset].replace('', pd.NA)
        else:
            work = work.replace('', pd.NA)
        return work.dropna(subset=subset, how=how).reset_index(drop=True)

    @staticmethod
    def fill_null(df: pd.DataFrame, columns: list = None, value=None, method: str = None) -> pd.DataFrame:
        work = df.copy()
        cols = [c for c in (columns or []) if c in work.columns] or list(work.columns)
        # Forward/backward filling is its own method now — pandas 3 removed the
        # ``fillna(method=…)`` keyword the original code relied on.
        filler = {'ffill': 'ffill', 'pad': 'ffill', 'bfill': 'bfill', 'backfill': 'bfill'}.get(str(method or ''))
        for c in cols:
            work[c] = work[c].replace('', pd.NA)
            if filler == 'ffill':
                work[c] = work[c].ffill()
            elif filler == 'bfill':
                work[c] = work[c].bfill()
            else:
                work[c] = work[c].fillna(value)
        return work

    @staticmethod
    def drop_duplicates(
        df: pd.DataFrame, columns: list = None, keep: str = 'first', mode: str = 'exact'
    ) -> pd.DataFrame:
        """Drop repeated rows, by exact equality or by their normalised identity.

        ``exact`` is plain pandas equality. ``normalized`` compares the identity form
        from :mod:`services.text_dedupe`: a comment farm reposts the same sentence with a
        different tracking link, one more emoji code, or a re-pasted forward chain, and
        every one of those is a new string but the same comment. The original text is what
        survives — the key is a temporary column and never reaches the output.
        """
        subset = [c for c in (columns or []) if c in df.columns] or None
        work = df.copy()
        if mode == 'exact':
            return work.drop_duplicates(subset=subset, keep=keep).reset_index(drop=True)
        if mode not in DEDUPE_MODES:
            raise UnknownOperationError(
                t(
                    'analysis.bad_option',
                    op='drop_duplicates',
                    param='mode',
                    value=mode,
                    allowed=', '.join(DEDUPE_MODES),
                )
            )
        from services.text_dedupe import normalized_key

        cols = subset or [str(col) for col in work.columns]
        # Joined with a byte that cannot appear in a cell, so ('ab', 'c') and ('a', 'bc')
        # are not handed the same key — the bug a plain ''.join would produce.
        joined = work[cols[0]].fillna('').astype(str)
        for name in cols[1:]:
            joined = joined + '\x1e' + work[name].fillna('').astype(str)
        work['__dedupe_key__'] = joined.map(normalized_key)
        out = work.drop_duplicates(subset=['__dedupe_key__'], keep=keep)
        return out.drop(columns=['__dedupe_key__']).reset_index(drop=True)

    @staticmethod
    def dedupe_similar(df: pd.DataFrame, column: str, max_distance: int = 8) -> pd.DataFrame:
        """Drop near-duplicate rows — SimHash distance within ``max_distance`` bits.

        What ``drop_duplicates`` cannot see: a comment reposted with one word changed, or
        the same sentence padded to a different length. SimHash puts each comment's
        *meaning-bearing tokens* into 64 bits, so a small edit flips few bits and the row
        collapses into the group it belongs to.

        The first row of each group is kept, matching ``keep='first'`` above, and the
        search is sub-quadratic by banding (see :mod:`services.text_dedupe`) — an
        all-pairs scan over a hundred-thousand-row comment table is not a thing this can
        afford, so a distance the banded index cannot prove is refused by name rather than
        answered with a slow scan or a quietly incomplete group.

        The default is 8 rather than the tightest distance that could be justified, and it
        is measured rather than chosen: on hand-written Weibo comments a one-word rewrite
        sits 5–18 bits away while two unrelated comments sit 26–28, so 8 catches the
        clearly-identical rewrites and leaves the genuinely-different ones alone. Raising
        it towards 15 buys recall and spends precision — worth doing per table, with the
        row counts the run reports, rather than once for every table.
        """
        work = df.copy()
        if column not in work.columns:
            return work
        # Imported here, not at module scope: this module is what the app loads on a plain
        # crawl, and the dedupe helpers pull in jieba for tokenising.
        from services.text_dedupe import MAX_BANDED_DISTANCE, group_near_duplicates, normalize_text, simhash64

        distance = 8 if max_distance is None else int(max_distance)
        if not 0 <= distance <= MAX_BANDED_DISTANCE:
            raise UnknownOperationError(t('analysis.dedupe_distance', value=distance, max=MAX_BANDED_DISTANCE))
        candidates = []
        for idx, raw in work[column].items():
            if pd.isna(raw):
                continue
            text = str(raw)
            # A comment that is only artifacts has no fingerprint of its own: every such
            # row hashes to the same value, so including them would collapse unrelated
            # rows into one group. They are not duplicates of each other — they are empty.
            if not normalize_text(text):
                continue
            candidates.append((str(idx), simhash64(text)))
        dropped = []
        for group in group_near_duplicates(candidates, max_distance=distance):
            dropped.extend(int(member) for member in group[1:])
        if dropped:
            work = work.drop(index=dropped)
        logger.info(t('analysis.dedupe_similar', n=len(dropped), column=column, distance=distance))
        return work.reset_index(drop=True)

    @staticmethod
    def filter_rows(df: pd.DataFrame, column: str, op: str, value) -> pd.DataFrame:
        if column not in df.columns:
            return df
        s = df[column]
        if op == 'eq':
            mask = s == value
        elif op == 'ne':
            mask = s != value
        elif op in ('gt', 'gte', 'lt', 'lte'):
            try:
                bound = float(value)
            except (TypeError, ValueError) as e:
                # Without this the pipeline died inside float() with a bare
                # "could not convert string to float".
                raise UnknownOperationError(f'"{op}" needs a numeric value, got: {value!r}') from e
            numeric = pd.to_numeric(s, errors='coerce')
            mask = {
                'gt': numeric > bound,
                'gte': numeric >= bound,
                'lt': numeric < bound,
                'lte': numeric <= bound,
            }[op]
        elif op == 'contains':
            mask = s.astype(str).str.contains(str(value), na=False)
        elif op == 'not_contains':
            mask = ~s.astype(str).str.contains(str(value), na=False)
        elif op == 'in':
            values = value if isinstance(value, (list, tuple, set)) else [v.strip() for v in str(value).split(',')]
            mask = s.isin(values)
        elif op == 'not_in':
            values = value if isinstance(value, (list, tuple, set)) else [v.strip() for v in str(value).split(',')]
            mask = ~s.isin(values)
        elif op == 'is_null':
            mask = s.replace('', pd.NA).isna()
        elif op == 'not_null':
            mask = s.replace('', pd.NA).notna()
        else:
            raise UnknownOperationError(f'Unknown filter operator: {op}')
        return df[mask].reset_index(drop=True)

    @staticmethod
    def select_columns(df: pd.DataFrame, columns: list) -> pd.DataFrame:
        cols = [c for c in columns if c in df.columns]
        return df[cols] if cols else df

    @staticmethod
    def rename_columns(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
        return df.rename(columns=mapping)

    @staticmethod
    def strip_whitespace(df: pd.DataFrame, columns: list = None) -> pd.DataFrame:
        work = df.copy()
        # is_string_dtype() instead of select_dtypes('object'): pandas 3 stores
        # text as 'str' (not 'object') and the old call is deprecated.
        text_cols = [c for c in work.columns if pd.api.types.is_string_dtype(work[c])]
        cols = [c for c in (columns or []) if c in work.columns] or text_cols
        for c in cols:
            # Strip only real strings: astype(str) would rewrite every missing
            # value as the text 'None'/'nan'.
            work[c] = work[c].map(lambda v: v.strip() if isinstance(v, str) else v)
        return work

    @staticmethod
    def convert_type(df: pd.DataFrame, column: str, dtype: str) -> pd.DataFrame:
        if column not in df.columns:
            return df
        work = df.copy()
        try:
            if dtype == 'int':
                work[column] = pd.to_numeric(work[column], errors='coerce').astype('Int64')
            elif dtype == 'float':
                work[column] = pd.to_numeric(work[column], errors='coerce')
            elif dtype == 'bool':
                work[column] = work[column].map(_to_bool)
            elif dtype == 'datetime':
                # ``format='mixed'`` is not a fix for a wrong guess, it is the guess being *said out
                # loud*: without a format pandas tries one for the whole column, fails on a table
                # whose rows came from different sources, and then parses every element individually
                # with dateutil anyway — while warning that it did. Declaring the per-element path
                # keeps the behaviour identical and removes the noise the user cannot act on
                # (pandas >= 2.0; the project venv carries 3.x).
                # ``format='mixed'`` is not a fix for a wrong guess, it is the guess being *said out
                # loud*: without a format pandas tries one for the whole column, fails on a table
                # whose rows came from different sources, and then parses every element individually
                # with dateutil anyway — while warning that it did. Measured, the undeclared path was
                # worse than noisy: on ``['2024-01-01', '2024-01-02 03:04:05']`` it inferred
                # ``%Y-%m-%d`` from row one and coerced row two to ``NaT``, so the timestamps simply
                # disappeared from the user's table. Declaring the per-element path keeps every row
                # and removes the noise the user cannot act on (pandas >= 2.0; the venv has 3.x).
                #
                # Through ``_to_datetime`` rather than pandas directly: this is the second door onto
                # the same column, and a 发布时间 that parses in ``extract_time`` while ``convert_type``
                # answers NaT for it is the same defect wearing a different control.
                work[column] = _to_datetime(work[column])
            else:
                work[column] = work[column].astype(str)
        except (ValueError, TypeError) as e:
            logger.warning(t('analysis.type_convert_failed', col=column, dtype=dtype, err=e))
        return work

    # ── New operations (Phase 2) ────────────────────────────────

    @staticmethod
    def sort_rows(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
        if column not in df.columns:
            return df
        return df.sort_values(by=column, ascending=ascending).reset_index(drop=True)

    @staticmethod
    def sample_rows(df: pd.DataFrame, n: int = None, frac: float = None, seed: int = None) -> pd.DataFrame:
        # Neither bound configured: pandas' own default is n=1, which silently
        # threw away every other row. Ask for nothing, change nothing.
        if n is None and frac is None:
            return df
        # An explicit seed is authoritative; a blank one (the settings panel
        # stores every field as a string, so '' is "left empty") is treated as
        # absent. Without either, the frame's own hash decides — see
        # ``_stable_seed``: the sample stays reproducible for the same input.
        raw_seed = str(seed).strip() if seed is not None else ''
        state = int(float(raw_seed)) if raw_seed else _stable_seed(df)
        # Both configured: an explicit row count is the more specific request.
        if n is not None:
            n = max(0, int(n))
            if n >= len(df):
                return df
            return df.sample(n=n, random_state=state).reset_index(drop=True)
        frac = min(max(float(frac), 0.0), 1.0)
        if frac >= 1.0:
            return df
        return df.sample(frac=frac, random_state=state).reset_index(drop=True)

    @staticmethod
    def groupby_agg(
        df: pd.DataFrame, group_col: str, agg_col: str, agg_func: str = 'sum', order_col: str = ''
    ) -> pd.DataFrame:
        """One row per group with the aggregate beside it.

        ``order_col`` says which column decides the result's ROW ORDER. Left blank, groups come
        back sorted by their own name — right for 'YYYY-MM-DD' days, wrong for Chinese phase
        labels, where 二次爆发期 sorts before 发酵期 by code point and a 各阶段 table then reads
        the lifecycle backwards while looking complete. The number 划分阶段's 阶段序号 writes is
        what fixes it, and it is dropped afterwards: a helper column left in the export would be
        a second opinion about the same group.
        """
        if group_col not in df.columns or agg_col not in df.columns:
            return df
        if order_col and order_col not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='groupby_agg', col=order_col))
        try:
            agg_map = {agg_col: (agg_col, agg_func)}
            if order_col:
                agg_map['_group_rank'] = (order_col, 'min')
            grouped = df.groupby(group_col, dropna=True).agg(**agg_map).reset_index()
            if order_col:
                ranks = pd.to_numeric(grouped['_group_rank'], errors='coerce')
                adrift = [str(name) for name, rank in zip(grouped[group_col], ranks, strict=True) if pd.isna(rank)]
                if adrift:
                    # A group whose every row lacks a rank has no position; appending it at the
                    # end would invent one.
                    raise UnknownOperationError(
                        t('analysis.stage_order_unranked', op='groupby_agg', col=order_col, stages='、'.join(adrift))
                    )
                grouped = grouped.assign(_group_rank=ranks).sort_values('_group_rank', kind='stable')
                grouped = grouped.drop(columns=['_group_rank'])
            else:
                grouped = grouped.sort_values(group_col, kind='stable')
        except (TypeError, ValueError) as e:
            # e.g. sum() over a text column: report the operation instead of a
            # raw pandas error deeper in the pipeline.
            raise UnknownOperationError(f'groupby_agg({agg_func}) failed on "{agg_col}": {e}') from e
        return grouped.reset_index(drop=True)

    @staticmethod
    def join_tables(
        df: pd.DataFrame, other_df: pd.DataFrame, how: str = 'left', left_on: str = '', right_on: str = ''
    ) -> pd.DataFrame:
        """Merge with the right-hand table.

        Every way this can fail used to return the left table unchanged, so a
        mistyped column name looked exactly like a successful join. Each case
        now raises a message naming what is missing.
        """
        if other_df is None or len(other_df) == 0:
            raise UnknownOperationError(t('analysis.join_no_right'))
        if not left_on or not right_on:
            raise UnknownOperationError(t('analysis.join_need_keys'))
        missing = []
        if left_on not in df.columns:
            missing.append(f'{left_on} (left)')
        if right_on not in other_df.columns:
            missing.append(f'{right_on} (right)')
        if missing:
            raise UnknownOperationError(t('analysis.join_missing_cols', cols=', '.join(missing)))
        return df.merge(other_df, how=how, left_on=left_on, right_on=right_on)

    @staticmethod
    def column_calc(df: pd.DataFrame, new_col: str, expr: str) -> pd.DataFrame:
        """Add a computed column, or refuse with the expression that could not run.

        This used to log a warning and hand the table back UNCHANGED, which is the one
        outcome this project forbids everywhere else: the node settled DONE, the column the
        user named was never created, and the only trace was a line in ``logs/``. A
        mistyped column name then surfaced two nodes later as a chart with nothing in it —
        on a run that had already paid for its crawl.

        The column name inside an expression is the reason this could not simply be added
        to :data:`STEP_PARAMS`: no table of column names can validate a formula, so the
        check has to be the evaluation itself. Which means the refusal has to BE the
        evaluation's failure, carrying the expression the user typed.
        """
        if not new_col or not expr:
            return df
        work = df.copy()
        try:
            work[new_col] = work.eval(expr)
        except Exception as e:
            raise UnknownOperationError(t('analysis.calc_failed', col=new_col, expr=expr, err=e)) from e
        return work

    @staticmethod
    def bin_column(
        df: pd.DataFrame, column: str, bins: list = None, labels: list = None, new_col: str = ''
    ) -> pd.DataFrame:
        if column not in df.columns:
            return df
        work = df.copy()
        bin_col = new_col or f'{column}_bin'
        if bins is None:
            bins = 4
        try:
            work[bin_col] = pd.cut(pd.to_numeric(work[column], errors='coerce'), bins=bins, labels=labels)
        except Exception as e:
            # Same rule as ``column_calc`` above: a refusal, never a silent no-op. The
            # inputs that reach here are real — edges given in the wrong order, a label
            # list that does not match the number of buckets — and each of them used to
            # settle the node DONE with no new column and one line in the log file.
            raise UnknownOperationError(t('analysis.bin_failed', col=column, err=e)) from e
        return work

    # ── Time dimension ──────────────────────────────────────────
    #
    # An event study is a study of WHEN, and nothing above answers that: `评论时间` holds
    # "2024-05-02 13:45", so grouping by it groups by the minute, and a line chart of a
    # per-minute series is noise. These two steps are the floor the whole analysis stands
    # on — daily post counts, the phase split, and the sentiment curve are all defined
    # over a calendar day rather than over a timestamp.

    @staticmethod
    def extract_time(df: pd.DataFrame, column: str, new_col: str = '日期', part: str = 'date') -> pd.DataFrame:
        """Derive one calendar part of a timestamp column.

        ``date`` answers with ``YYYY-MM-DD`` text rather than a date object: the value is
        grouped, exported and charted, and a lexical sort of ISO dates IS a chronological
        sort, so the text form costs nothing and survives every serialisation in this
        pipeline. The other parts answer with a number.

        A timestamp the site handed back as a relative label ("09月26日 21:00" is what Weibo
        shows when it has no year) cannot be turned into a calendar day, and guessing this
        year for it would move rows between phases. Those rows are left EMPTY and counted
        in the console — an empty is not a date, and pandas' own ``groupby`` then drops them
        instead of inventing a 1970 bucket for them.
        """
        if column not in df.columns:
            return df
        if part not in TIME_PARTS:
            raise UnknownOperationError(
                t('analysis.bad_option', op='extract_time', param='part', value=part, allowed=', '.join(TIME_PARTS))
            )
        work = df.copy()
        stamps = _to_datetime(work[column])
        unparsed = int(stamps.isna().sum())
        if part == 'date':
            work[new_col] = stamps.dt.strftime('%Y-%m-%d')
            # strftime answers 'NaT' for a missing stamp, and a column whose missing value
            # is the text "NaT" groups those rows together as if they were one day.
            work.loc[stamps.isna(), new_col] = pd.NA
        else:
            work[new_col] = getattr(stamps.dt, part)
        if unparsed:
            logger.warning(t('analysis.time_unparsed', col=column, n=unparsed))
        return work

    @staticmethod
    def bin_time(
        df: pd.DataFrame,
        column: str,
        edges: list = None,
        labels: list = None,
        new_col: str = '阶段',
        order_new_col: str = '',
    ) -> pd.DataFrame:
        """Cut a timestamp column into named windows — the event's lifecycle phases.

        ``edges`` are the boundaries, left-closed and right-open: five phases need SIX
        edges, and the last one is the day after the final phase ends. That is stated
        rather than smoothed over because the alternative reading ("edges are the phase
        ends") silently shifts every row on a boundary day into the neighbouring phase —
        and those are exactly the days an event study is about.

        Which is why the comparison runs on the calendar DAY: a row stamped 23:59 on the
        day before a boundary belongs to the earlier phase, not to the next one by two
        minutes.

        ``order_new_col`` adds the phase's POSITION as a number (first phase = 1). The label
        column alone cannot survive the node boundary — ``pd.DataFrame(records)`` turns the
        ordered categorical into plain strings, and the code-point order of Chinese phase
        names puts 二次爆发期 first, so every 各阶段 chart and table would read the lifecycle
        backwards. A number is the only spelling of the order that survives the round trip;
        分阶段 LDA writes its own ``stage_order`` for the same reason. Left blank, no column is
        added and this step behaves exactly as it always did.
        """
        if column not in df.columns:
            return df
        work = df.copy()
        bounds = [value for value in (edges or []) if not _blank(value)]
        names = [str(name).strip() for name in (labels or []) if str(name).strip()]
        if len(bounds) < 2:
            raise UnknownOperationError(t('analysis.need_param', op='bin_time', param='edges'))
        if len(names) != len(bounds) - 1:
            raise UnknownOperationError(t('analysis.time_bin_labels', edges=len(bounds), labels=len(names)))
        parsed = pd.to_datetime(pd.Series(bounds), errors='coerce', format='mixed')
        if parsed.isna().any():
            bad = [bounds[index] for index, ok in enumerate(parsed.notna()) if not ok]
            raise UnknownOperationError(t('analysis.time_bin_edges', edges=', '.join(str(x) for x in bad)))
        if not parsed.is_monotonic_increasing:
            # pd.cut would raise on unsorted bins with pandas' own wording; naming the
            # parameter is what lets the user find the box that holds it.
            raise UnknownOperationError(t('analysis.time_bin_order', op='bin_time'))
        stamps = _to_datetime(work[column])
        unparsed = int(stamps.isna().sum())
        work[new_col] = pd.cut(stamps.dt.normalize(), bins=parsed, labels=names, right=False)
        if order_new_col and str(order_new_col).strip():
            order_name = str(order_new_col).strip()
            # The numeric position survives what the label cannot: pandas gives an unbinned row
            # no category at all, so a missing phase stays missing here instead of being ranked.
            positions = {name: number + 1 for number, name in enumerate(names)}
            work[order_name] = pd.Series(
                [
                    positions.get(str(value).strip()) if str(value).strip() in positions else None
                    for value in work[new_col].tolist()
                ],
                index=work.index,
                dtype='object',
            )
        if unparsed:
            logger.warning(t('analysis.time_unparsed', col=column, n=unparsed))
        counts = work[new_col].value_counts()
        detail = '、'.join(f'{name} {int(counts.get(name, 0))} 行' for name in names)
        logger.info(t('analysis.time_binned', col=new_col, detail=detail))
        return work

    # ── Topic modelling ─────────────────────────────────────────

    @staticmethod
    def suggest_stages(
        df: pd.DataFrame,
        column: str,
        min_days: int = 3,
        max_windows: int = 6,
        peak_ratio: float = 2.0,
    ) -> pd.DataFrame:
        """Candidate 舆情阶段 boundaries, read off the daily post-count curve.

        The study this exists for cut its five phases two ways at once: by eye on its 图 2
        (posts per day) and on the dates the police issued a notice. Only the first is
        something a table can answer, and it answers it as a PROPOSAL — the rows out of this
        step are windows to consider and the console holds the ``edges``/``labels`` text that
        pastes into :meth:`bin_time`. Nothing is applied, because a boundary this step
        invented is a boundary the researcher did not take, and 「官方通报」 is not in the
        post counts.

        Two rules make the paste safe. The last edge is the day AFTER the final window,
        because ``bin_time`` is left-closed/right-open and an edge list ending on the last
        observed day would silently lose it. And a new window opens the day AFTER the valley
        between two peaks, not on the valley itself: the quietest day belongs to the phase
        that is winding down, and putting it at the head of the next one would make every
        phase look like it began in silence.

        Peak heights are reported as the RAW count of that day, not the smoothed one the
        boundary search used — 349/7624/1038/8029/2286 are the numbers the paper prints, and
        a proposal has to be comparable with them.
        """
        if column not in df.columns:
            return df
        stamps = _to_datetime(df[column])
        unparsed = int(stamps.isna().sum())
        if unparsed:
            # The same rows :meth:`bin_time` will leave blank: said once, here, rather than
            # discovered later as a phase table with fewer rows than the crawl reported.
            logger.warning(t('analysis.time_unparsed', col=column, n=unparsed))
        days = stamps.dt.normalize().value_counts().sort_index()
        if days.empty:
            raise UnknownOperationError(t('analysis.stages_sparse', days=0, least=int(min_days) * 2))
        span = pd.date_range(days.index.min(), days.index.max(), freq='D')
        counts = days.reindex(span, fill_value=0)
        if len(counts) < int(min_days) * 2:
            raise UnknownOperationError(t('analysis.stages_sparse', days=len(counts), least=int(min_days) * 2))
        ratio = float(peak_ratio)
        if ratio < 1:
            # "twice the usual day" is what a peak means here. Below 1 every ordinary day
            # clears the bar, and the curve would be cut at its own noise.
            raise UnknownOperationError(t('analysis.stages_ratio', value=peak_ratio))
        # The floor is put on the RAW day. The smoothing exists only to stop a one-day spike
        # from reading as a turning point, and comparing a flattened peak with a floor taken
        # from unflattened days would reject exactly the tall narrow 爆发期 a lifecycle is
        # named for.
        daily = counts.to_numpy()
        live = float(counts[counts > 0].median())
        floor = live * ratio
        smoothed = counts.rolling(3, center=True, min_periods=1).mean().to_numpy()
        peak_positions = [
            position
            for position in range(1, len(smoothed) - 1)
            if smoothed[position] > smoothed[position - 1]
            and smoothed[position] >= smoothed[position + 1]
            and daily[position] >= floor
        ]
        if len(peak_positions) < 2:
            raise UnknownOperationError(t('analysis.stages_no_peak', ratio=peak_ratio, floor=round(floor, 1)))
        if len(peak_positions) > int(max_windows):
            # The tallest peaks are the phases; folding the rest into their neighbours is a
            # decision the user can reverse by raising the ceiling, so it is said out loud.
            folded = len(peak_positions) - int(max_windows)
            peak_positions = sorted(
                sorted(peak_positions, key=lambda position: daily[position], reverse=True)[: int(max_windows)]
            )
            logger.warning(t('analysis.stages_folded', kept=int(max_windows), dropped=folded))

        # A window's start carries the valley day that closed the previous one, so 依据 can
        # name it: a parallel list would go out of step the moment a boundary is dropped.
        starts = [(span[0], None)]
        last_open = span[-1] + pd.Timedelta(days=1)
        for left, right in zip(peak_positions[:-1], peak_positions[1:], strict=True):
            between = range(left + 1, right)
            if not between:
                continue  # two adjacent peaks share no valley, so they stay in one window
            valley = min(between, key=lambda position: smoothed[position])
            boundary = span[valley] + pd.Timedelta(days=1)
            if starts[-1][0] < boundary < last_open:
                starts.append((boundary, span[valley]))
        starts.append((last_open, None))

        rows = []
        for index in range(len(starts) - 1):
            window = counts[(counts.index >= starts[index][0]) & (counts.index < starts[index + 1][0])]
            peak_day = window.idxmax()
            valley = starts[index][1]
            rows.append(
                {
                    '序号': index + 1,
                    '起点': starts[index][0].strftime('%Y-%m-%d'),
                    '终点': (starts[index + 1][0] - pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                    '天数': len(window),
                    '行数': int(window.sum()),
                    '峰值日': peak_day.strftime('%Y-%m-%d'),
                    '峰值计数': int(window.max()),
                    '依据': (
                        t('analysis.stages_basis_first', day=starts[index][0].strftime('%Y-%m-%d'))
                        if valley is None
                        else t('analysis.stages_basis_valley', valley=valley.strftime('%Y-%m-%d'))
                    ),
                }
            )
        logger.info(
            t(
                'analysis.stages_done',
                n=len(rows),
                rows=int(counts.sum()),
                span=f'{span[0].date()} … {span[-1].date()}',
            )
        )
        # Two lines because the panel holds two boxes; a merged line cannot be pasted into
        # either without editing, and the editing is where a boundary gets lost.
        logger.info(t('analysis.stages_edges', edges=', '.join(start.strftime('%Y-%m-%d') for start, _ in starts)))
        logger.info(
            t('analysis.stages_labels', labels=', '.join(f'阶段{number}' for number in range(1, len(rows) + 1)))
        )
        return pd.DataFrame(rows)

    @staticmethod
    def topic_model(
        df: pd.DataFrame, column: str, n_topics: int = 5, topn: int = 10, max_features: int = 2000
    ) -> pd.DataFrame:
        """LDA over one text column: which subjects is this corpus made of.

        ``sklearn``'s ``LatentDirichletAllocation``, not Gensim's: scikit-learn is already
        a dependency of this project and gensim is not, and a topic model that needs a
        second numerical stack installed to read a table is not worth the extra words it
        would type. Both fit the same generative model; the numbers they report are not
        identical, so a replication should say which one produced its table.

        The output is ONE ROW PER (topic, keyword) rather than one row per topic with its
        words joined: it is the shape the keyword node already answers with, it keeps every
        weight addressable, and a chart can group it by ``topic`` directly. Reading it as
        the paper's table is a job for the console line, which prints each topic's words in
        order.

        The perplexity is logged because "设定主题个数" is a real decision and the paper
        does not say how it was made: run the node at several ``n_topics`` and read the
        number, which falls as the model fits better and stops meaning anything once it
        starts memorising rows.
        """
        import jieba
        from sklearn.decomposition import LatentDirichletAllocation
        from sklearn.feature_extraction.text import CountVectorizer

        if column not in df.columns:
            return df
        topics = int(n_topics)
        if topics < 2:
            raise UnknownOperationError(t('analysis.topic_count', value=topics))
        texts = [str(value) for value in df[column].dropna().tolist() if str(value).strip()]
        if len(texts) < topics:
            raise UnknownOperationError(t('analysis.topic_rows', rows=len(texts), topics=topics))
        # Tokens with no letter or digit in them are dropped before the model sees them, the
        # same rule the word-cloud tokenizer applies: jieba hands back the punctuation it
        # split on, and a topic model whose vocabulary is "。" and "！" has topics that are
        # punctuation. A corpus that is nothing BUT punctuation then has no vocabulary at
        # all, which is refused below rather than answered with an empty table.
        tokenized = [
            ' '.join(token for token in jieba.cut(text) if any(char.isalnum() for char in token)) for text in texts
        ]
        vectorizer = CountVectorizer(
            tokenizer=_split_tokens,
            preprocessor=_keep_text,
            token_pattern=None,
            max_features=max(10, int(max_features)),
        )
        try:
            matrix = vectorizer.fit_transform(tokenized)
        except ValueError as e:
            raise UnknownOperationError(t('analysis.topic_features', err=e)) from e
        model = LatentDirichletAllocation(n_components=topics, random_state=42, learning_method='batch')
        model.fit(matrix)
        vocabulary = vectorizer.get_feature_names_out()
        rows = []
        lines = []
        for index, component in enumerate(model.components_):
            best = component.argsort()[::-1][: max(1, int(topn))]
            words = [str(vocabulary[position]) for position in best]
            lines.append(f'Topic-{index + 1}: {" ".join(words)}')
            for rank, position in enumerate(best):
                rows.append(
                    {
                        'topic': f'Topic-{index + 1}',
                        'rank': rank + 1,
                        'keyword': str(vocabulary[position]),
                        'weight': round(float(component[position]), 6),
                    }
                )
        logger.info(
            t(
                'analysis.topic_done',
                n=topics,
                rows=len(texts),
                perplexity=round(float(model.perplexity(matrix)), 2),
            )
        )
        for line in lines:
            # One line per topic, so the console reads like the paper's table without an
            # export round trip — the whole point of running the node.
            logger.info(line)
        return pd.DataFrame(rows, columns=['topic', 'rank', 'keyword', 'weight'])

    @staticmethod
    def topic_by_stage(
        df: pd.DataFrame,
        column: str,
        stage_col: str = '阶段',
        order_col: str = '',
        topics=None,
        topn: int = 10,
        max_features: int = 2000,
        word_source: str = 'tfidf',
        sample_n: int = 5,
    ) -> pd.DataFrame:
        """LDA fitted **inside each 舆情阶段** — the table the study publishes.

        One model over the whole corpus cannot produce it. A pooled LDA spends its topics on
        whichever phase supplied most of the text (爆发期 and 二次爆发期 are 7624 and 8029 of the
        paper's 19326 rows), so 发酵期's 349 rows either get no topic of their own or share one
        with a phase three weeks later — and 「谣言、暴力、刘某、发布、捞、细节、谩骂」 would stop
        being a description of the first week. So the corpus is split by the 阶段 column
        :meth:`bin_time` wrote, modelled stage by stage, and numbered Ⅰ-1 … Ⅴ-4 by lifecycle
        position, which is exactly how 表 1 reads.

        The output is WIDE — one row per (stage, topic) — because that is the artifact: the
        feature words go into one cell joined by 、, the same cell the paper prints. The long
        (topic, keyword, weight) shape stays available from :meth:`topic_model`.

        ``word_source='tfidf'`` follows the paper's stated method: LDA assigns each post to a
        topic, and the words are then the corpus TF-IDF of THAT bucket, so the list is what is
        distinctive about the posts rather than what the model's weight matrix happens to top.
        ``'lda'`` reads the weight matrix directly and is kept because the two lists differ
        (see :data:`WORD_SOURCES`).

        An assignment can leave a topic with no posts at all — a property of the fit, not of the
        user's choice — and then there is no bucket to score. The row is filled from that topic's
        own word distribution, ``doc_n`` reports 0, and one warning names it: the stage's other
        topics are real output, and dropping the table over an empty bucket (or printing an empty
        特征词 cell) would each lose information the model actually has.

        Sample posts are the ``sample_n`` rows with the highest posterior probability for the
        topic — not a random draw. A random one would hand :meth:`topic_label` different
        evidence on every run, and a summary that changes between two identical runs is not a
        finding.
        """
        import jieba
        from sklearn.decomposition import LatentDirichletAllocation
        from sklearn.feature_extraction.text import CountVectorizer

        from analyzers.keyword import KeywordExtractor

        if column not in df.columns or stage_col not in df.columns:
            return df
        stages = _stage_order(df, stage_col, order_col)
        per_stage = _stage_topic_counts(topics, stages)
        # Read once, positionally: ``Series.map`` on a categorical maps its CATEGORIES, not its
        # values, so the comparison would silently match nothing and every phase would come
        # back "has no rows".
        stage_keys = pd.Series([_stage_key(value) for value in df[stage_col].tolist()], index=df.index)
        blank = int((stage_keys == '').sum())
        if blank:
            logger.warning(t('analysis.stage_blank', col=stage_col, n=blank))

        rows = []
        for stage_index, stage in enumerate(stages):
            stage_rows = df[stage_keys == stage]
            # The rows the model actually reads: a blank text is not a document, and counting
            # it would let the guard below pass on a stage that is really empty.
            usable = stage_rows[stage_rows[column].notna() & (stage_rows[column].astype(str).str.strip() != '')]
            wanted = per_stage[stage_index]
            if not len(usable):
                raise UnknownOperationError(t('analysis.topic_stage_empty', stage=stage, col=stage_col))
            if len(usable) < wanted:
                # Refusing rather than dropping to "3 topics for 2 texts": the stage would then
                # report fewer numbered topics than the user asked for, and the numbering is the
                # thing the paper's table is read by.
                raise UnknownOperationError(
                    t('analysis.topic_stage_rows', stage=stage, rows=len(usable), topics=wanted)
                )
            texts = [str(value) for value in usable[column].tolist()]
            tokenized = [
                ' '.join(token for token in jieba.cut(text) if any(char.isalnum() for char in token)) for text in texts
            ]
            vectorizer = CountVectorizer(
                tokenizer=_split_tokens,
                preprocessor=_keep_text,
                token_pattern=None,
                max_features=max(10, int(max_features)),
            )
            try:
                matrix = vectorizer.fit_transform(tokenized)
            except ValueError as e:
                raise UnknownOperationError(t('analysis.topic_stage_features', stage=stage, err=e)) from e
            model = LatentDirichletAllocation(n_components=wanted, random_state=42, learning_method='batch')
            doc_topic = model.fit_transform(matrix)
            perplexity = round(float(model.perplexity(matrix)), 2)
            vocabulary = vectorizer.get_feature_names_out()
            # One pass assigns every document to its strongest topic. Doing the argmax inside the
            # topic loop would walk the whole stage again per topic, which on a 19,326-post
            # corpus is the difference between seconds and minutes for no extra information.
            buckets: dict = {}
            for position, owner in enumerate(int(row) for row in doc_topic.argmax(axis=1)):
                buckets.setdefault(owner, []).append(position)
            # The stage's POSITION, not its name: 表 1 says TopicⅠ-1 belongs to 发酵期 because
            # 发酵期 came first, and the numeral has to survive a rename of the phase labels.
            numeral = STAGE_NUMERALS[stage_index] if stage_index < len(STAGE_NUMERALS) else str(stage_index + 1)
            logger.info(t('analysis.topic_stage_done', stage=stage, n=wanted, rows=len(usable), perplexity=perplexity))
            for topic_index in range(wanted):
                label = f'Topic{numeral}-{topic_index + 1}'
                members = buckets.get(topic_index, [])
                doc_n = len(members)
                if word_source == 'tfidf':
                    bucket = usable.iloc[members]
                    scored = KeywordExtractor().tfidf_corpus(bucket, text_column=column, topk=int(topn), merge=True)
                    words = [
                        (str(word), float(weight))
                        for word, weight in zip(scored['keyword'], scored['weight'], strict=True)
                    ]
                    if not words:
                        # An argmax can leave a topic with NO documents, and then there is no
                        # bucket to score TF-IDF over. That is a property of the fit, not a
                        # mistake by the user, and killing a stage's other three topics for it
                        # would be worse than saying so: the model does hold a word distribution
                        # for the unused topic, so the row is filled from that and ``doc_n`` = 0
                        # is what tells the reader no post was assigned to it.
                        component = model.components_[topic_index]
                        best = component.argsort()[::-1][: max(1, int(topn))]
                        words = [(str(vocabulary[position]), float(component[position])) for position in best]
                        logger.warning(t('analysis.topic_stage_unused', stage=stage, topic=label))
                else:
                    component = model.components_[topic_index]
                    best = component.argsort()[::-1][: max(1, int(topn))]
                    words = [(str(vocabulary[position]), float(component[position])) for position in best]
                if not words:
                    raise UnknownOperationError(t('analysis.topic_stage_words', stage=stage, topic=label))
                ranked = sorted(range(len(texts)), key=lambda position: -float(doc_topic[position][topic_index]))
                samples = ' ／ '.join(texts[position][:80] for position in ranked[: max(0, int(sample_n))])
                rows.append(
                    {
                        'stage': stage,
                        'stage_order': stage_index + 1,
                        'topic': label,
                        'feature_words': '、'.join(word for word, _ in words),
                        'weights': ' '.join(f'{word}:{weight:.6f}' for word, weight in words),
                        'doc_n': doc_n,
                        'perplexity': perplexity,
                        'sample_texts': samples,
                    }
                )
                logger.info(f'{label}（{stage}）: {" ".join(word for word, _ in words)}')
        if not rows:
            # Unreachable while ``stages`` is non-empty (the guard above raises on an empty
            # stage), but a table with no topic rows must not settle the node DONE.
            raise UnknownOperationError(t('analysis.topic_stage_rows', stage='、'.join(stages), rows=0, topics=1))
        return pd.DataFrame(rows)

    @staticmethod
    def topic_label(
        df: pd.DataFrame,
        llm=None,
        cancel=None,
        words_col: str = 'feature_words',
        samples_col: str = 'sample_texts',
        summary_col: str = '主题概括',
        on_fail: str = 'abort',
        max_topics: int = 30,
    ) -> pd.DataFrame:
        """Ask the model for the 主题概括 column the study's authors wrote by hand.

        One prompt per topic row and nothing else: the evidence handed over is the phase, the
        topic's own number, its feature words and the sample posts :meth:`topic_by_stage`
        already picked — which is what a reader of 表 1 sees. The paper's summaries came from
        reading the corpus; these come from reading the same WORDS, so the column is data this
        project produced, not the authors' finding restated.

        The answer's language follows the run's own, because the prompt is an ``i18n`` string:
        a node that answers English into a Chinese interface would have to be re-run to be
        readable.

        ``llm`` is handed in by :func:`run_pipeline` for the ops in :data:`LLM_OPS`, and a
        missing one is a refusal rather than a skip — the column would come back empty and the
        node would settle DONE over work that did not happen. ``cancel`` is the run's Stop
        flag; a cut-short pass leaves :data:`ABORT_MARK` in the rows the model never saw, which
        is how the executor already learns an LLM node was interrupted instead of finished.
        """
        from analyzers.llm_client import ABORT_MARK, LLMError

        if llm is None:
            raise UnknownOperationError(t('analysis.label_no_llm', op='topic_label'))
        if words_col not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='topic_label', col=words_col))
        limit = int(max_topics)
        if limit < 1 or len(df) > limit:
            # One call per row, so a 5,000-row table is 5,000 paid questions nobody meant to
            # ask. 表 1 is 25 rows; the ceiling is there to catch the mis-wired pipeline.
            raise UnknownOperationError(t('analysis.label_too_many', rows=len(df), limit=limit))
        work = df.copy()
        work[summary_col] = ''
        has_stage = 'stage' in work.columns
        has_topic = 'topic' in work.columns
        positions = list(work.index)
        labelled = 0
        for offset, position in enumerate(positions):
            if cancel is not None and cancel.is_set():
                for rest in positions[offset:]:
                    work.at[rest, summary_col] = ABORT_MARK
                logger.warning(t('analysis.label_cancelled', n=len(positions) - offset))
                return work
            name = str(work.at[position, 'topic']) if has_topic else f'#{offset + 1}'
            words = str(work.at[position, words_col] or '').strip()
            if not words:
                raise UnknownOperationError(t('analysis.label_no_words', topic=name, col=words_col))
            samples = ''
            if samples_col and samples_col in work.columns:
                samples = str(work.at[position, samples_col] or '').strip()
            prompt = t(
                'analysis.label_prompt',
                stage=str(work.at[position, 'stage']) if has_stage else '',
                topic=name,
                words=words,
                samples=samples or '—',
            )
            try:
                answer = llm.chat(prompt)
            except LLMError as e:
                if on_fail != 'blank':
                    raise UnknownOperationError(t('analysis.label_failed', topic=name, err=e)) from e
                # One line per topic the model gave up on, and the cell stays empty: the user
                # asked for the run to continue, not for the gap to be invisible.
                logger.warning(t('analysis.label_failed', topic=name, err=e))
                continue
            label = _label_from(answer)
            if not label:
                # An answer of punctuation, or of nothing: a blank cell would be
                # indistinguishable from a topic nobody asked the model about.
                if on_fail != 'blank':
                    raise UnknownOperationError(t('analysis.label_empty', topic=name))
                logger.warning(t('analysis.label_empty', topic=name))
                continue
            work.at[position, summary_col] = label
            labelled += 1
        logger.info(t('analysis.label_done', n=labelled, model=getattr(llm, 'label', '')))
        return work

    @staticmethod
    def topic_map(
        df: pd.DataFrame, column: str, n_topics: int = 5, max_features: int = 2000, topn: int = 6
    ) -> pd.DataFrame:
        """The intertopic distance map's DATA: where each topic sits, and how big it is.

        pyLDAvis draws topics as bubbles placed by multidimensional scaling of the distance
        between their word distributions, sized by how much of the corpus each one claims. It
        is a picture of the MODEL rather than of the words, and it answers the question the
        exported topic list cannot: are these five subjects actually distinct, or is one of
        them a slightly louder copy of another? Overlapping bubbles say the split was not in
        the text.

        Prevalence is the model's own document mass (``doc_topic.sum(axis=0)``), not the argmax
        count :meth:`topic_by_stage` files as ``doc_n``: a post that leans 40/60 between two
        topics belongs to both here, because the map shows what the model is unsure about while
        the table records what it decided. ``doc_n`` is still reported beside it so the two
        readings can be compared rather than confused.
        """
        if column not in df.columns:
            return df
        topics = int(n_topics)
        texts, model, matrix, doc_topic, vocabulary = _prepare_topic_model(df, column, topics, max_features)
        mass = doc_topic.sum(axis=0)
        total = float(mass.sum())
        claimed = [int(owner) for owner in doc_topic.argmax(axis=1)]
        points = _mds_2d(_jsd_matrix(model.components_))
        rows = []
        for index in range(topics):
            component = model.components_[index]
            best = component.argsort()[::-1][: max(1, int(topn))]
            rows.append(
                {
                    'topic': f'Topic-{index + 1}',
                    'pc1': round(float(points[index][0]), 6),
                    'pc2': round(float(points[index][1]), 6),
                    'prevalence_pct': round(float(mass[index]) / total * 100, 2) if total else 0.0,
                    'doc_n': claimed.count(index),
                    'feature_words': '、'.join(str(vocabulary[position]) for position in best),
                }
            )
        logger.info(
            t(
                'analysis.topic_map_done',
                n=topics,
                rows=len(texts),
                perplexity=round(float(model.perplexity(matrix)), 2),
            )
        )
        return pd.DataFrame(rows)

    @staticmethod
    def topic_salience(
        df: pd.DataFrame,
        column: str,
        n_topics: int = 5,
        max_features: int = 2000,
        topn: int = 30,
        relevance: float = 1.0,
    ) -> pd.DataFrame:
        """The figure's right-hand panel: the terms a topic is ABOUT, with both counts.

        Two bars per term, exactly as the study prints them — the corpus-wide frequency (blue)
        and the frequency this topic alone would produce (red). Which terms belong on the list
        at all is decided by the relevance weighting of Sievert & Shirley (2014):
        ``λ·log p(w|t) + (1−λ)·log(p(w|t)/p(w))``. λ=1 ranks by the topic's own probability, so
        a common word can win; λ=0 ranks by over-representation, so rare-but-diagnostic words
        surface and a topic of nothing but 「的」 becomes impossible to read. The paper's figure
        has a slider for this; here it is a parameter, and the number used is printed with the
        rows because two λs give two different answers from one model.
        """
        import numpy as np

        if column not in df.columns:
            return df
        topics = int(n_topics)
        lam = float(relevance)
        if not 0.0 <= lam <= 1.0:
            raise UnknownOperationError(t('analysis.topic_lambda', value=relevance))
        texts, model, matrix, _doc_topic, vocabulary = _prepare_topic_model(df, column, topics, max_features)
        counts = np.asarray(matrix.sum(axis=0), dtype=float).ravel()
        total_tokens = float(counts.sum())
        if not total_tokens:
            raise UnknownOperationError(t('analysis.topic_features', err='the corpus has no tokens left to count'))
        p_w = counts / total_tokens
        word_topic = np.asarray(model.components_, dtype=float)
        word_topic = word_topic / word_topic.sum(axis=1, keepdims=True)
        prior = word_topic.sum(axis=1) / len(word_topic)
        rows = []
        for index in range(topics):
            own = word_topic[index]
            within = own * float(prior[index]) * total_tokens
            scored = []
            for position in range(len(vocabulary)):
                probability = float(own[position])
                if probability <= 0.0:
                    continue  # a term this topic never uses has no relevance to rank
                share = float(p_w[position])
                lift = probability / share if share > 0 else 0.0
                if lift <= 0.0:
                    continue
                value = lam * math.log2(probability) + (1.0 - lam) * math.log2(lift)
                # Ties break on the term itself so two runs of one table list the same words
                # in the same order; numpy's argsort would leave the order to floating point.
                scored.append((value, str(vocabulary[position]), position))
            scored.sort(key=lambda pair: (-pair[0], pair[1]))
            for rank, (value, term, position) in enumerate(scored[: max(1, int(topn))]):
                rows.append(
                    {
                        'topic': f'Topic-{index + 1}',
                        'rank': rank + 1,
                        'term': term,
                        'overall_freq': int(counts[position]),
                        'within_freq': round(float(within[position]), 2),
                        'relevance': round(value, 4),
                    }
                )
        logger.info(t('analysis.topic_salience_done', n=topics, rows=len(texts), terms=len(rows), value=lam))
        return pd.DataFrame(rows)

    # ── What the phases did to each other ───────────────────────

    @staticmethod
    def topic_timeline(
        df: pd.DataFrame,
        stage_col: str = 'stage',
        words_col: str = 'feature_words',
        size_col: str = 'doc_n',
        topic_col: str = 'topic',
        order_col: str = '',
        min_overlap: float = 0.5,
    ) -> pd.DataFrame:
        """When each subject appeared, and which ones were 次生舆情.

        表 1 is one snapshot per phase. It cannot say that 「外卖空包」 only became a subject
        after the first week — that is a statement about rows in DIFFERENT phases, and the
        paper makes it: the 次生舆情 (the secondary flare-up of a case, off a subject the
        first week never had) is one of its findings.

        A phase-by-phase LDA gives every topic a label scoped to its own stage (TopicⅠ-1 is
        not the same object as TopicⅡ-1), so a subject is tracked by the WORDS it is about:
        two rows belong to one lifecycle when their word lists overlap by at least
        ``min_overlap`` (Jaccard over the two sets). That threshold is the user's call about
        how much similarity counts as the same subject, which is why it is a parameter and is
        printed with the result rather than buried in this function.

        Families are grown in lifecycle order against the union of the words the family has
        already shown, so a subject that drifts one word per phase stays ONE subject instead
        of being filed as five — and the price of that choice is that a subject which changes
        abruptly opens a second family. Both readings are defensible; neither is silent,
        because the threshold and the union rule are stated here and on the panel.

        ``is_secondary`` is the paper's own two-part shape: the subject did not first appear
        in the opening phase, AND its largest phase came after its first one. A subject that
        was born late and peaked immediately (one phase only) is a late topic, not a
        flare-up, and is reported ``False`` — the columns beside it (``first_stage``,
        ``peak_stage``, ``stages_present``) are what the reader needs to judge that
        themselves, which is why they are in the table rather than folded into one flag.
        """
        stages = _stage_order(df, stage_col, order_col, op='topic_timeline')
        if len(stages) < 2:
            raise UnknownOperationError(t('analysis.timeline_stages', stages=len(stages)))
        for name in (size_col, topic_col):
            if name and name not in df.columns:
                raise UnknownOperationError(t('analysis.step_col_missing', op='topic_timeline', col=name))
        try:
            threshold = float(min_overlap)
        except (TypeError, ValueError):
            raise UnknownOperationError(t('analysis.timeline_overlap', value=min_overlap)) from None
        if not 0.0 < threshold <= 1.0:
            raise UnknownOperationError(t('analysis.timeline_overlap', value=min_overlap))

        positions = {stage: index for index, stage in enumerate(stages)}
        # Read positionally and once per column: ``Series.map`` on a categorical maps its
        # CATEGORIES, ``df.at`` addresses by row LABEL (and a filtered table's labels are not
        # its positions), and this table usually arrives across a node boundary as plain
        # strings anyway (see the invariant in AGENTS.md).
        keys = [_stage_key(value) for value in df[stage_col].tolist()]
        unusable = sum(1 for key in keys if key not in positions)
        if unusable:
            logger.warning(t('analysis.timeline_blank', col=stage_col, n=unusable))
        ordered = sorted(
            (positions[key], number) for number, key in enumerate(keys) if key in positions
        )  # stage order first, and the table's own order inside one stage
        if not ordered:
            raise UnknownOperationError(t('analysis.timeline_stages', stages=0))
        present = {position for position, _ in ordered}
        if len(present) < 2:
            # The declared lifecycle can carry an empty category (a phase 按时间划分阶段 named and
            # no post fell into). A lifecycle is about the phases with rows in them: one of
            # those is not a before and an after, whatever the column's category list says.
            raise UnknownOperationError(t('analysis.timeline_stages', stages=len(present)))
        word_lists = [_word_cells(value) for value in df[words_col].tolist()]
        label_list = [str(value).strip() for value in df[topic_col].tolist()] if topic_col else [''] * len(keys)

        sizes = pd.to_numeric(df[size_col], errors='coerce') if size_col else pd.Series(dtype=float)
        usable_sizes = int(sizes.notna().sum()) if len(sizes) else 0
        if size_col and not usable_sizes:
            # Every cell of the size column is text the numbers cannot come out of. Peak is
            # then not "flat", it is UNMEASURED, and a table of peaks built on zeros would be
            # the paper's finding manufactured out of nothing.
            raise UnknownOperationError(t('analysis.timeline_size', col=size_col))
        if size_col and usable_sizes < len(sizes):
            logger.warning(t('analysis.timeline_partial', col=size_col, n=len(sizes) - usable_sizes))
        size_list = sizes.tolist() if size_col else [0.0] * len(keys)

        families: list = []
        for stage_position, number in ordered:
            words = word_lists[number]
            if not words:
                raise UnknownOperationError(
                    t(
                        'analysis.timeline_words',
                        stage=stages[stage_position],
                        topic=label_list[number] or f'#{number + 1}',
                        col=words_col,
                    )
                )
            raw_size = size_list[number]
            size = float(raw_size) if pd.notna(raw_size) else 0.0
            best, best_score = None, 0.0
            unique = set(words)
            for family in families:
                union = family['words'] | unique
                score = len(family['words'] & unique) / len(union) if union else 0.0
                if score > best_score:
                    # Ties go to the family that opened first, because "same subject" is judged
                    # against the debut that got there earliest, not against whichever the row
                    # order happened to test first.
                    best, best_score = family, score
            record = {'pos': stage_position, 'size': size, 'words': words, 'label': label_list[number]}
            if best is not None and best_score >= threshold:
                best['rows'].append(record)
                best['words'].update(words)
            else:
                families.append({'words': set(words), 'rows': [record]})

        rows = []
        for family in families:
            entries = sorted(family['rows'], key=lambda record: record['pos'])
            debut = entries[0]['pos']
            peak = max(entries, key=lambda record: (record['size'], -record['pos']))['pos']
            shown: list = []
            for record in entries:
                for word in record['words']:
                    if word not in shown:
                        shown.append(word)
            rows.append(
                {
                    'topic': entries[0]['label'] or f'Subject-{len(rows) + 1}',
                    'topic_words': '、'.join(shown),
                    'first_stage': stages[debut],
                    'peak_stage': stages[peak],
                    'last_stage': stages[entries[-1]['pos']],
                    'stages_present': len({record['pos'] for record in entries}),
                    'stage_path': ' → '.join(stages[record['pos']] for record in entries),
                    'size_total': round(float(sum(record['size'] for record in entries)), 4),
                    'peak_size': round(float(max(record['size'] for record in entries)), 4),
                    'is_secondary': bool(debut > 0 and peak > debut),
                }
            )
        rows.sort(key=lambda row: (stages.index(row['first_stage']), row['topic']))
        multi = sum(1 for row in rows if row['stages_present'] > 1)
        secondary = sum(1 for row in rows if row['is_secondary'])
        logger.info(
            t(
                'analysis.timeline_done',
                topics=len(rows),
                multi=multi,
                secondary=secondary,
                value=threshold,
                stages=len(stages),
            )
        )
        for row in rows:
            if row['is_secondary']:
                logger.info(t('analysis.timeline_secondary', topic=row['topic'], path=row['stage_path']))
        return pd.DataFrame(rows)

    @staticmethod
    def topic_flow(
        df: pd.DataFrame,
        stage_col: str = 'stage',
        topic_col: str = 'topic',
        words_col: str = 'feature_words',
        weights_col: str = 'weights',
        order_col: str = '',
        min_similarity: float = 0.5,
    ) -> pd.DataFrame:
        """Which topic of one phase carried over into the next — the sankey's edges.

        表 1 says what each phase was about; it does not say how one phase's subject BECAME the
        next one's. That is the paper's other structural claim (「外卖黑盒→外卖空包」 is one subject
        mutating, not two subjects), and the only way to read it from a per-phase model is to
        compare the topics of adjacent phases with each other.

        The comparison is the Jensen-Shannon divergence of the two word DISTRIBUTIONS, taken
        from the ``word:weight`` cell :meth:`topic_by_stage` writes, turned into a similarity by
        ``1 / (1 + d)``. The distributions rather than the word lists, because two topics can
        share 「外卖」 and mean different things by how hard they lean on it; where the lists are
        all that is left, :meth:`topic_timeline` is the step to use.

        Adjacent phases only, and deliberately so: comparing 发酵期 with 衰退期 would draw an
        edge across the whole lifecycle and make the flow figure unreadable in exactly the way
        the paper's own stage-by-stage narrative is not.

        A threshold nobody clears is an answer, not an empty table: the refusal names the best
        similarity that was measured, so lowering it is a decision the user can make with the
        number in front of them.
        """
        stages = _stage_order(df, stage_col, order_col, op='topic_flow')
        if len(stages) < 2:
            raise UnknownOperationError(t('analysis.flow_stages', stages=len(stages)))
        for name in (topic_col, words_col, weights_col):
            if name and name not in df.columns:
                raise UnknownOperationError(t('analysis.step_col_missing', op='topic_flow', col=name))
        try:
            threshold = float(min_similarity)
        except (TypeError, ValueError):
            raise UnknownOperationError(t('analysis.flow_similarity', value=min_similarity)) from None
        if not 0.0 < threshold <= 1.0:
            raise UnknownOperationError(t('analysis.flow_similarity', value=min_similarity))

        positions = {stage: index for index, stage in enumerate(stages)}
        keys = [_stage_key(value) for value in df[stage_col].tolist()]
        # Positional reads, for the reason given in ``topic_timeline``: a filtered table's row
        # labels are not its positions, and ``df.at`` would answer with the wrong row.
        weights_list = [_word_weights(value) for value in df[weights_col].tolist()]
        topic_list = [str(value).strip() for value in df[topic_col].tolist()]
        words_list = (
            ['、'.join(_word_cells(value)) for value in df[words_col].tolist()] if words_col else [''] * len(keys)
        )
        buckets: list = [[] for _ in stages]
        skipped = 0
        for number, key in enumerate(keys):
            if key not in positions:
                skipped += 1
                continue
            weights = weights_list[number]
            if not weights:
                # No weights means no distribution. Filing the row as uniform-over-its-words
                # would compute a similarity from a list overlap while the message reported a
                # divergence, which is two different measurements wearing one name.
                raise UnknownOperationError(
                    t('analysis.flow_weights', topic=topic_list[number] or f'#{number + 1}', stage=key, col=weights_col)
                )
            buckets[positions[key]].append(
                {'topic': topic_list[number], 'words': words_list[number], 'weights': weights}
            )
        if skipped:
            logger.warning(t('analysis.timeline_blank', col=stage_col, n=skipped))
        for stage, entries in zip(stages, buckets, strict=True):
            if not entries:
                raise UnknownOperationError(t('analysis.flow_stage_empty', stage=stage, col=stage_col))

        edges = []
        best_seen = 0.0
        for left_index in range(len(stages) - 1):
            for source in buckets[left_index]:
                for target in buckets[left_index + 1]:
                    vocabulary = sorted(set(source['weights']) | set(target['weights']))
                    divergence = _jsd(
                        [source['weights'].get(word, 0.0) for word in vocabulary],
                        [target['weights'].get(word, 0.0) for word in vocabulary],
                    )
                    similarity = 1.0 / (1.0 + divergence)
                    best_seen = max(best_seen, similarity)
                    if similarity < threshold:
                        continue
                    edges.append(
                        {
                            'source': source['topic'],
                            'target': target['topic'],
                            'similarity': round(similarity, 6),
                            'divergence': round(divergence, 6),
                            'from_stage': stages[left_index],
                            'to_stage': stages[left_index + 1],
                            'source_words': source['words'],
                            'target_words': target['words'],
                        }
                    )
        if not edges:
            raise UnknownOperationError(t('analysis.flow_no_edges', value=threshold, best=round(best_seen, 4)))
        # Thickest link first: the sankey draws what it is handed, and a flow table read top-down
        # should start with the carry-over that was strongest.
        edges.sort(key=lambda edge: (-edge['similarity'], edge['source'], edge['target']))
        logger.info(
            t(
                'analysis.flow_done',
                edges=len(edges),
                stages=len(stages),
                value=threshold,
                best=round(best_seen, 4),
            )
        )
        return pd.DataFrame(edges)

    @staticmethod
    def topic_coherence(
        df: pd.DataFrame,
        column: str,
        min_topics: int = 2,
        max_topics: int = 8,
        topn: int = 10,
        max_features: int = 2000,
        max_documents: int = 2000,
    ) -> pd.DataFrame:
        """Score a SWEEP of topic counts, for the decision the paper never explains.

        「设定主题个数」 is a real choice and 表 1 gives no reason for 5/6/4/4/4. This step fits
        the same model :meth:`topic_model` fits, once per count, and prints two numbers per
        count: the log perplexity (how well the model predicts held-out word counts — it keeps
        falling as the model memorises rows) and a word-coherence score (whether a topic's top
        words actually appear together in the same posts, which perplexity does not check).

        The coherence score is **document-level NPMI over each topic's top ``topn`` words**,
        averaged over pairs and then over topics. That is a fraction of the coherence literature
        named C_v, not C_v: there is no sliding-window segmentation (each post is one window,
        which for short social posts is the same thing, but is not what the published algorithm
        does) and no reference-measure cosine step between topic pairs. It is reported here as
        ``coherence`` because it measures the same property; a replication of a published C_v
        number should not expect to agree with it.

        The pair count is what a zero-co-occurrence pair would silently become (an undefined
        log ratio), so such pairs are skipped and ``pairs_used`` says how many were not. A sweep
        with almost no usable pairs is a corpus whose topics do not share documents, and the
        perplexity alone is then the only number worth reading.
        """
        from itertools import combinations

        import jieba

        if column not in df.columns:
            raise UnknownOperationError(t('analysis.step_col_missing', op='topic_coherence', col=column))
        texts = [str(value) for value in df[column].dropna().tolist() if str(value).strip()]
        limit = _whole(max_documents, 'topic_coherence', 'max_documents')
        if limit > 0 and len(texts) > limit:
            # Deterministic on purpose: a sweep whose sample changes between runs changes its
            # numbers, and the user cannot tell the difference between a worse model and a
            # different dozen posts.
            texts = pd.Series(texts).sample(n=limit, random_state=_stable_seed(df)).sort_index().tolist()
            logger.info(t('analysis.coherence_sampled', used=limit, total=len(df[column].dropna())))
        low = _whole(min_topics, 'topic_coherence', 'min_topics')
        high = _whole(max_topics, 'topic_coherence', 'max_topics')
        if low < 2:
            raise UnknownOperationError(t('analysis.topic_count', value=low))
        if high < low:
            raise UnknownOperationError(t('analysis.coherence_range', low=low, high=high))
        if len(texts) < low:
            raise UnknownOperationError(t('analysis.topic_rows', rows=len(texts), topics=low))
        if high > len(texts):
            # Fitting five topics on three posts is not a model, and every count above the row
            # count would answer with the same degenerate fit. Saying so is the whole message.
            logger.info(t('analysis.coherence_capped', high=high, rows=len(texts)))
            high = len(texts)
        # One tokenisation per document, reused by every count: the vectoriser inside
        # ``_fit_topic_model`` re-cuts these texts (its contract is raw text, and sharing a
        # token list would make the two steps disagree the moment either changed its rule),
        # so this copy is for the co-occurrence counts only.
        documents = [
            frozenset(token for token in jieba.cut(text) if any(char.isalnum() for char in token)) for text in texts
        ]
        keep = max(1, _whole(topn, 'topic_coherence', 'topn'))
        rows = []
        for topics in range(low, high + 1):
            try:
                model, matrix, _doc_topic, vocabulary = _fit_topic_model(texts, topics, max_features)
            except ValueError as e:
                raise UnknownOperationError(t('analysis.topic_features', err=e)) from e
            perplexity = round(float(model.perplexity(matrix)), 2)
            tops = [
                [str(vocabulary[position]) for position in component.argsort()[::-1][:keep]]
                for component in model.components_
            ]
            candidates = set().union(*(set(words) for words in tops))
            singles = {word: sum(1 for document in documents if word in document) for word in candidates}
            joint: dict = {}
            for document in documents:
                present = sorted(document & candidates)
                for pair in combinations(present, 2):
                    joint[pair] = joint.get(pair, 0) + 1
            total_documents = len(documents)
            scores = []
            used_pairs = 0
            skipped = 0
            for words in tops:
                values = []
                for pair in combinations(sorted(words), 2):
                    count = joint.get(pair, 0)
                    if not count or not singles[pair[0]] or not singles[pair[1]]:
                        skipped += 1
                        continue  # an undefined ratio is not a zero score
                    used_pairs += 1
                    p_ij = count / total_documents
                    if p_ij >= 1.0:
                        # Both words are in every document, which is the one case where the
                        # denominator −log₂ p(i,j) is 0. Perfect co-occurrence is the maximum
                        # score by definition, so it is filed as 1.0 rather than as a division.
                        values.append(1.0)
                        continue
                    numerator = (
                        math.log2(p_ij)
                        - math.log2(singles[pair[0]] / total_documents)
                        - math.log2(singles[pair[1]] / total_documents)
                    )
                    values.append(numerator / -math.log2(p_ij))
                if values:
                    scores.append(sum(values) / len(values))
            coherence = round(sum(scores) / len(scores), 4) if scores else None
            rows.append(
                {
                    'n_topics': topics,
                    'coherence': coherence,
                    'perplexity': perplexity,
                    'documents': total_documents,
                    'terms': len(vocabulary),
                    'pairs_used': used_pairs,
                    'pairs_skipped': skipped,
                }
            )
            logger.info(f'n_topics={topics}  coherence={coherence}  perplexity={perplexity}')
        scored = [row for row in rows if row['coherence'] is not None]
        if not scored:
            raise UnknownOperationError(
                t('analysis.coherence_pairs', topn=keep, pairs=sum(row['pairs_skipped'] for row in rows))
            )
        best_coherence = max(scored, key=lambda row: row['coherence'])['n_topics']
        best_perplexity = min(rows, key=lambda row: row['perplexity'])['n_topics']
        logger.info(
            t(
                'analysis.coherence_best',
                coherence=best_coherence,
                perplexity=best_perplexity,
                low=low,
                high=high,
            )
        )
        return pd.DataFrame(rows)

    @staticmethod
    def cooccur(df: pd.DataFrame, column: str, topn: int = 30, min_count: int = 2, window: int = 0) -> pd.DataFrame:
        """Which words travel together — the co-occurrence edges of 论文's knowledge graph.

        One row per word pair, with the number of posts that contain both (or both within
        ``window`` tokens of each other, when a window is asked for). The paper's other figure
        is a 知识图谱 built from exactly this: two words are related in the graph because readers
        put them in the same sentence, not because a topic model grouped them.

        The candidate words are the corpus TF-IDF list :class:`KeywordExtractor` already ranks
        by how distinctive a term is in THIS table, and the token rule (two characters or more,
        jieba's cut) is the same call — a second tokenizer here would produce a graph whose
        words are not the words the keyword node reports for the same corpus.

        ``topn`` is capped at :data:`COOCCUR_WORD_CAP` and a larger request is refused rather
        than clamped: the graph is complete over its candidates, so quietly keeping 120 of the
        500 words asked for decides WHICH EDGES EXIST, and that is a data choice.
        """
        from itertools import combinations

        from analyzers.keyword import KeywordExtractor

        wanted = _whole(topn, 'cooccur', 'topn')
        if wanted < 2:
            raise UnknownOperationError(t('analysis.cooccur_topn', value=topn, cap=COOCCUR_WORD_CAP))
        if wanted > COOCCUR_WORD_CAP:
            raise UnknownOperationError(t('analysis.cooccur_topn', value=wanted, cap=COOCCUR_WORD_CAP))
        floor = _whole(min_count, 'cooccur', 'min_count')
        if floor < 1:
            raise UnknownOperationError(t('analysis.cooccur_count', value=min_count))
        span = max(0, _whole(window, 'cooccur', 'window'))

        scored = KeywordExtractor().tfidf_corpus(df, text_column=column, topk=wanted, merge=True)
        candidates = {str(word) for word in scored['keyword'].tolist()} if 'keyword' in scored.columns else set()
        if len(candidates) < 2:
            raise UnknownOperationError(t('analysis.cooccur_words', found=len(candidates), topn=wanted))

        counts: dict = {}
        documents = 0
        for text in df[column].dropna().tolist():
            tokens = KeywordExtractor._tokenize(str(text), None)
            sequence = [token for token in tokens if token in candidates]
            if len(sequence) < 2:
                continue
            documents += 1
            size = len(sequence) if span <= 0 else min(span, len(sequence))
            starts = range(1) if size >= len(sequence) else range(len(sequence) - size + 1)
            for start in starts:
                present = sorted(set(sequence[start : start + size]))
                for pair in combinations(present, 2):
                    counts[pair] = counts.get(pair, 0) + 1
        edges = [
            {'source': left, 'target': right, 'value': count}
            for (left, right), count in counts.items()
            if count >= floor
        ]
        if not edges:
            raise UnknownOperationError(
                t(
                    'analysis.cooccur_empty',
                    floor=floor,
                    top=max(counts.values()) if counts else 0,
                    pairs=len(counts),
                )
            )
        # Strongest link first, and one fixed order for ties: the graph's edge width is read
        # from these rows, and a list that reorders itself between runs is a different figure.
        edges.sort(key=lambda edge: (-edge['value'], edge['source'], edge['target']))
        logger.info(
            t(
                'analysis.cooccur_done',
                words=len(candidates),
                docs=documents,
                pairs=len(counts),
                edges=len(edges),
                floor=floor,
            )
        )
        return pd.DataFrame(edges)

    # ── The sentiment curve ─────────────────────────────────────

    @staticmethod
    def sentiment_evolution(
        df: pd.DataFrame,
        column: str,
        label_col: str = 'sentiment',
        positive: str = 'positive',
        neutral: str = 'neutral',
        negative: str = 'negative',
        new_col: str = 'sentiment_index',
        score_col: str = '',
        order_col: str = '',
    ) -> pd.DataFrame:
        """Per-period sentiment shares and one signed intensity — the evolution curve.

        The number this exists for is ``sentiment_index`` = (positive − negative) / total,
        which is the paper's daily value: +1 means the period was wholly positive, −1
        wholly negative, and 0 means either everything was neutral or the two sides
        cancelled. It is deliberately NOT a mean of per-row scores: a mean over rows answers
        "how strong was the average opinion", while this answers "which way did the crowd
        lean", and a phase with a large silent neutral majority must read as moderate even
        when the few opinions are extreme. That distinction is the paper's central finding
        (爆发期 76% negative but a phase index near −0.56), so it is computed rather than
        approximated.

        Rows whose label is none of the three named values are counted in ``total`` and in
        none of the three buckets — a blank the polarity node could not judge is not a
        neutral opinion, and folding it into 中性 would report a finding the data does not
        contain. Their count is ``other_n``, so the difference is visible rather than lost.

        ``volume_pct`` is the other half of the figure the study is famous for: 舆情热度, the
        share of the corpus each period holds. It is taken over the rows that reached a
        period (a blank period belongs to none, so its share is not missing — it is
        undefined), which is what makes the column add up to 100.

        ``score_col`` adds the second curve the paper reads against 热度: 情感强度 =
        mean(|score − 0.5|) × 2 over the rows that carry a score, which is how far the
        crowd pushed, in either direction, from neutral. Signed means would answer "which
        way" a second time and collapse toward 0 in a period where both sides are loud —
        exactly the 二次爆发期 the paper says was COLDER in volume and HOTTER in intensity.
        A period with no scored rows gets ``None``, never 0.5: a half-way value would read
        as "measured and found neutral".

        ``order_col`` is how a 阶段 grouping keeps its lifecycle order. The rows come back
        sorted by PERIOD NAME, which is right for 'YYYY-MM-DD' days and wrong for Chinese
        phase labels: 二次爆发期 sorts before 发酵期 by code point, so 表 2 and 图 3 would
        present the case out of sequence while looking complete. The user names a column to
        order by — the NUMBER 按时间划分阶段's 序号列 writes, or a time — and a group whose
        rows hold none of it is refused by name rather than appended at the end.
        """
        if column not in df.columns or label_col not in df.columns:
            return df
        if score_col and score_col not in df.columns:
            # The user asked for the intensity curve and named a column this table does not
            # hold. Answering with the shares only would ship a chart with one line and no
            # word about the missing one.
            raise UnknownOperationError(t('analysis.step_col_missing', op='sentiment_evolution', col=score_col))
        work = df.copy()
        labels = work[label_col].astype('string').fillna('').str.strip()
        work['_pos'] = (labels == positive).astype(int)
        work['_neu'] = (labels == neutral).astype(int)
        work['_neg'] = (labels == negative).astype(int)
        agg_map = {
            'positive_n': ('_pos', 'sum'),
            'neutral_n': ('_neu', 'sum'),
            'negative_n': ('_neg', 'sum'),
            'total': ('_pos', 'size'),
        }
        if score_col:
            scores = pd.to_numeric(work[score_col], errors='coerce')
            work['_deviation'] = (scores - 0.5).abs() * 2
            work['_scored'] = scores.notna().astype(int)
            agg_map['score_n'] = ('_scored', 'sum')
            # ``mean`` skips NaN, so an unscored row neither lifts nor drags the intensity —
            # it is simply absent from it, and ``score_n`` says how many rows were.
            agg_map['intensity'] = ('_deviation', 'mean')
        if order_col:
            if order_col not in df.columns:
                raise UnknownOperationError(t('analysis.step_col_missing', op='sentiment_evolution', col=order_col))
            # Numeric first (a 序号 column), then time (a 日期 column): the two ways this
            # project's own steps say "which phase came first".
            ranks = pd.to_numeric(work[order_col], errors='coerce')
            if not ranks.notna().any():
                ranks = _to_datetime(work[order_col]).astype('int64') / 1e9
                ranks = ranks.where(ranks.notna() & (ranks > 0) & (ranks < 2**62))
            work['_rank'] = ranks
            agg_map['_rank'] = ('_rank', 'min')
        grouped = work.groupby(column, dropna=True).agg(**agg_map)
        grouped = grouped.reset_index()
        grouped['other_n'] = grouped['total'] - grouped['positive_n'] - grouped['neutral_n'] - grouped['negative_n']
        # A zero total cannot happen (groupby only makes groups from rows) but the ratio is
        # written defensively: a division here would surface as an inf in a chart, not as
        # an error anyone could trace back to this line.
        totals = grouped['total'].replace(0, pd.NA)
        for name, source in (
            ('positive_pct', 'positive_n'),
            ('neutral_pct', 'neutral_n'),
            ('negative_pct', 'negative_n'),
        ):
            grouped[name] = (grouped[source] / totals * 100).round(2)
        grouped[new_col] = ((grouped['positive_n'] - grouped['negative_n']) / totals).round(4)
        heat = int(grouped['total'].sum())
        grouped['volume_pct'] = (grouped['total'] / max(1, heat) * 100).round(2)
        if score_col:
            # NaN would serialise as a bare ``NaN`` token, which the browser's JSON.parse
            # rejects for the WHOLE response, and writing None back into the float column
            # pandas already built just folds it back into NaN. An object column is the one
            # spelling that keeps an unjudged period an empty cell.
            grouped['intensity'] = pd.Series(
                [
                    None if not count else round(float(value), 4)
                    for count, value in zip(grouped['score_n'], grouped['intensity'], strict=True)
                ],
                index=grouped.index,
                dtype='object',
            )
        # Ascending by the period so a line chart draws left-to-right in time without the
        # user having to add a sort step — and 'YYYY-MM-DD' sorts chronologically as text,
        # which is why extract_time answers with text. With ``order_col`` the lifecycle order
        # comes from that column instead, because a phase NAME does not sort in time.
        if order_col:
            # ``grouped`` has already been reset_index()-ed above, so its index is 0..n-1 and
            # naming a row from it would report "4" where the user needs the phase's name.
            adrift = [str(name) for name, rank in zip(grouped[column], grouped['_rank'], strict=True) if pd.isna(rank)]
            if adrift:
                # A period with no rank has no position; putting it at the end would invent one.
                raise UnknownOperationError(
                    t(
                        'analysis.stage_order_unranked',
                        op='sentiment_evolution',
                        col=order_col,
                        stages='、'.join(adrift),
                    )
                )
            grouped = grouped.sort_values('_rank', kind='stable')
            grouped = grouped.drop(columns=['_rank'])
        else:
            grouped = grouped.sort_values(column, kind='stable')
        grouped = grouped.reset_index(drop=True)
        grouped = grouped.rename(columns={column: 'period'})
        logger.info(
            t(
                'analysis.evolution_done',
                n=len(grouped),
                periods=str(grouped['period'].iloc[0]) + ' … ' + str(grouped['period'].iloc[-1])
                if len(grouped)
                else '',
            )
        )
        if score_col:
            unscored = [
                str(name) for name, count in zip(grouped['period'], grouped['score_n'], strict=True) if not count
            ]
            if unscored:
                logger.warning(t('analysis.evolution_unscored', col=score_col, periods='、'.join(unscored)))
        return grouped

    # ── Looking forward: the paper's 预测情感走向 and 提前干预 ─────

    @staticmethod
    def forecast(
        df: pd.DataFrame,
        column: str = 'period',
        value_col: str = 'sentiment_index',
        method: str = 'moving_average',
        horizon: int = 3,
        window: int = 3,
        alpha: float = 0.5,
        beta: float = 0.3,
        min_periods: int = 4,
    ) -> pd.DataFrame:
        """Extrapolate the sentiment CURVE a few periods ahead.

        The study's closing argument is that a curve like this one could have been used to
        intervene before the second flare-up, so the question worth asking of
        :meth:`sentiment_evolution` is what the next few periods look like if nothing changes.
        This is an extrapolation of a SHAPE, not a prediction of events: no model here knows
        about a police notification, and the honest reading of the band is "where this curve's
        own momentum and wobble put the next points", not "what will happen".

        Two methods, both computed here rather than imported:

        ``moving_average`` repeats the mean of the last ``window`` observations and keeps the
        band FLAT, because a moving average has no trend to add and no more uncertainty the
        further out it goes — a widening band here would be theatre.

        ``holt`` is Holt's two-parameter linear method (level + trend), written out rather than
        taken from a statsmodels dependency, and its band grows with ``sqrt(horizon)`` because a
        trend extrapolated further really is less certain. The band uses the standard deviation
        of the fitted one-step errors, which is the only uncertainty this model measured.

        History is kept in the same table: every past period comes back with its ``actual`` and
        the one-step-ahead ``predicted`` the model would have made from the period before it, at
        ``horizon`` 0, so a chart shows the fit and the forecast as one line rather than two
        tables the user has to join. A future row has ``actual`` empty — it has not happened.

        Equal spacing is checked, not assumed: with missing days the "next period" the step
        names on the axis is not the next day, so the modal gap is used for the labels and the
        deviating count is logged. The input has to be dates for any of that to mean anything,
        which is why a phase NAME column (发酵期…) is refused instead of being numbered 1, 2, 3.
        """
        steps = int(horizon)
        for name in (column, value_col):
            # Refused by name rather than reaching pandas, which answers a missing column with a
            # bare KeyError: the gate catches this on both doors, but a hand-called step should
            # still say which of its own inputs is gone.
            if name not in df.columns:
                raise UnknownOperationError(t('analysis.step_col_missing', op='forecast', col=name))
        if steps < 1:
            raise UnknownOperationError(t('analysis.forecast_horizon', value=horizon))
        look = int(window)
        if look < 2:
            raise UnknownOperationError(t('analysis.forecast_window', value=window))
        for name, value in (('alpha', alpha), ('beta', beta)):
            number = float(value)
            if not 0.0 < number < 1.0:
                raise UnknownOperationError(t('analysis.forecast_smooth', name=name, value=value))
        floor = int(min_periods)

        stamps = _to_datetime(df[column])
        if stamps.isna().all():
            raise UnknownOperationError(t('analysis.forecast_dates', col=column))
        work = pd.DataFrame({'stamp': stamps, 'actual': pd.to_numeric(df[value_col], errors='coerce')})
        work = work[work['stamp'].notna() & work['actual'].notna()].sort_values('stamp', kind='stable')
        if len(work) < floor:
            raise UnknownOperationError(t('analysis.forecast_rows', rows=len(work), least=floor))
        if len(work) < look + 1:
            raise UnknownOperationError(t('analysis.forecast_window_rows', rows=len(work), window=look))
        doubled = work['stamp'].duplicated()
        if doubled.any():
            # Two rows for one day would be read as two steps of a trend and quietly flatten or
            # steepen it, so the duplicate is the finding here, not something to average away.
            raise UnknownOperationError(
                t(
                    'analysis.forecast_duplicate',
                    col=column,
                    days='、'.join(str(value.date()) for value in work.loc[doubled, 'stamp'].head(5)),
                )
            )
        gaps = work['stamp'].diff().dropna()
        sizes = gaps.dt.days.value_counts()
        modal = int(sizes.index[0])
        uneven = int(sizes.drop(index=modal).sum()) if len(sizes) > 1 else 0
        if uneven:
            logger.warning(t('analysis.forecast_uneven', steps=uneven, gap=modal, rows=len(work)))
        stamps_in = work['stamp'].tolist()
        values = [float(value) for value in work['actual'].tolist()]
        centres: list = []
        spreads: list = []
        future: list = []
        if method == 'moving_average':
            for position in range(len(values)):
                if position < look:
                    # Nothing is claimed for the first ``window`` points: the estimator has not
                    # seen enough of the curve yet, and a value here would be a guess wearing
                    # the same column heading as the forecasts.
                    centres.append(None)
                    spreads.append(None)
                    continue
                past = values[position - look : position]
                centres.append(sum(past) / look)
                spreads.append(1.96 * _standard_deviation(past))
            tail = values[-look:]
            centre = sum(tail) / look
            band = 1.96 * _standard_deviation(tail)
            # A moving average has no trend, so the forecast is flat and the band stays the same
            # width: widening it here would be theatre about a model that adds nothing each step.
            future = [(offset, centre, band) for offset in range(1, steps + 1)]
        else:
            level, slope = values[0], 0.0
            errors: list = []
            a = float(alpha)
            b = float(beta)
            for position, value in enumerate(values):
                if position == 0:
                    centres.append(None)
                    spreads.append(None)
                    continue
                predicted = level + slope
                errors.append(value - predicted)
                centres.append(predicted)
                # No band on a fitted point: an interval around a value already observed would
                # be a second, wider answer to a question this table answers once.
                spreads.append(None)
                previous = level
                level = a * value + (1.0 - a) * (level + slope)
                slope = b * (level - previous) + (1.0 - b) * slope
            spread = 1.96 * _standard_deviation(errors)
            # The band grows with the square root of the horizon because a trend carried further
            # really is less certain, and the only uncertainty this model measured is the
            # standard deviation of its own one-step errors.
            future = [(offset, level + offset * slope, spread * (offset**0.5)) for offset in range(1, steps + 1)]

        rows = [
            _forecast_row(stamps_in[position], values[position], centres[position], spreads[position], 0)
            for position in range(len(values))
        ]
        final = stamps_in[-1]
        for offset, centre, band in future:
            rows.append(_forecast_row(final + pd.Timedelta(days=modal * offset), None, centre, band, offset))
        logger.info(
            t(
                'analysis.forecast_done',
                method=method,
                rows=len(work),
                horizon=steps,
                gap=modal,
                last=str(work['stamp'].iloc[-1].date()),
            )
        )
        return pd.DataFrame(rows)

    @staticmethod
    def alert(
        df: pd.DataFrame,
        column: str = 'period',
        index_col: str = 'sentiment_index',
        intensity_col: str = '',
        volume_col: str = '',
        streak: int = 2,
        swing: float = 0.2,
        heating: float = 0.15,
        volume_floor: float = 0.6,
    ) -> pd.DataFrame:
        """Say which periods look like the start of another flare-up — and why each one qualifies.

        提前干预 in the study is an operational claim: someone has to be told while there is
        still time. The rule here is deliberately plain and every row states the number it
        checked, so a reader can disagree with the threshold rather than with a black box:

        * **转向** — ``streak`` consecutive steps each moved the sentiment index by at least
          ``swing``, in the same direction. One big jump is a reaction to an event; a run of
          them in one direction is a crowd moving.
        * **升温** — the sentiment INTENSITY rose by at least ``heating`` per step over the last
          ``streak`` steps. The index can sit near zero while both sides get louder, which is the
          二次爆发期 shape the paper describes, so the signed curve alone would miss it.
        * Both are suppressed unless the volume is still holding: ``volume`` has to be at least
          ``volume_floor`` times the mean of the previous ``streak`` periods, because a swing in
          a period with almost nobody posting is a handful of people, not a flare-up. A
          suppressed candidate is still reported as a row saying it was suppressed and by how
          much — "nothing fired" and "the swing fired but the crowd had left" are different
          answers, and only one of them is a reason to act.

        ``intensity_col`` and ``volume_col`` are read exactly like ``score_col`` on
        :meth:`sentiment_evolution`: left blank on the panel, that half of the rule is simply not
        asked for (升温 never fires, and nothing is suppressed on volume); a name that is typed
        and missing is refused, because a signal that silently stopped firing would make the
        table look like a reading of both.

        An empty result is never returned: when nothing fired the table answers with one row of
        ``未触发`` carrying the strongest value that was measured. An empty table would read as
        "not checked" — and in a monitoring step, that is the difference between calm and blind.
        """
        run = int(streak)
        if run < 1:
            raise UnknownOperationError(t('analysis.alert_streak', value=streak))
        for name, value in (('swing', swing), ('heating', heating), ('volume_floor', volume_floor)):
            number = float(value)
            if number <= 0:
                raise UnknownOperationError(t('analysis.alert_threshold', name=name, value=value))
        if volume_floor > 1.0:
            raise UnknownOperationError(t('analysis.alert_floor', value=volume_floor))
        if len(df) < run + 1:
            raise UnknownOperationError(t('analysis.alert_rows', rows=len(df), least=run + 1))
        # A name typed here that the table does not hold is refused rather than dropped: the
        # 升温 half of the rule would simply stop firing, and the table would look like a calm
        # reading of both signals.
        for name in (column, index_col, intensity_col, volume_col):
            if name and name not in df.columns:
                raise UnknownOperationError(t('analysis.step_col_missing', op='alert', col=name))

        stamps = _to_datetime(df[column])
        if stamps.isna().all():
            raise UnknownOperationError(t('analysis.forecast_dates', col=column))
        usable = [(stamp, number) for number, stamp in enumerate(stamps.tolist()) if pd.notna(stamp)]
        skipped = len(df) - len(usable)
        if skipped:
            logger.warning(t('analysis.alert_skipped', col=column, n=skipped))
        if len(usable) < run + 1:
            raise UnknownOperationError(t('analysis.alert_rows', rows=len(usable), least=run + 1))
        positions = [number for _stamp, number in sorted(usable, key=lambda pair: pair[0])]
        periods = [str(df[column].iloc[position]) for position in positions]
        indexes = [
            float(value) if pd.notna(value) else None
            for value in pd.to_numeric(df[index_col], errors='coerce').iloc[positions].tolist()
        ]
        intensities = (
            [
                float(value) if pd.notna(value) else None
                for value in pd.to_numeric(df[intensity_col], errors='coerce').iloc[positions].tolist()
            ]
            if intensity_col and intensity_col in df.columns
            else [None] * len(positions)
        )
        volumes = (
            [
                float(value) if pd.notna(value) else 0.0
                for value in pd.to_numeric(df[volume_col], errors='coerce').iloc[positions].tolist()
            ]
            if volume_col and volume_col in df.columns
            else [None] * len(positions)
        )

        rows = []
        best_swing = (None, 0.0)
        for position in range(run, len(positions)):
            if indexes[position] is None or indexes[position - run] is None:
                continue
            moves = []
            for step in range(position - run + 1, position + 1):
                here, before = indexes[step], indexes[step - 1]
                if here is None or before is None:
                    moves.append(None)
                    continue
                moves.append(here - before)
            if any(move is None for move in moves):
                continue
            biggest = max(abs(move) for move in moves)
            if biggest >= abs(best_swing[1]):
                best_swing = (periods[position], biggest)
            same_direction = all(move > 0 for move in moves) or all(move < 0 for move in moves)
            turned = same_direction and all(abs(move) >= float(swing) for move in moves)
            heated = False
            rise = None
            if intensities[position] is not None and intensities[position - run] is not None:
                rise = (intensities[position] - intensities[position - run]) / run
                heated = rise >= float(heating)
            if not (turned or heated):
                continue
            signal = '转向' if turned and not heated else ('升温' if heated and not turned else '转向+升温')
            value = sum(abs(move) for move in moves) / run if turned else rise
            held = True
            if volumes[position] is not None:
                previous = [volumes[step] for step in range(position - run, position) if volumes[step] is not None]
                if previous:
                    baseline = sum(previous) / len(previous)
                    held = volumes[position] >= float(volume_floor) * baseline
            rows.append(
                {
                    'period': periods[position],
                    'signal': signal if held else f'{signal}（已抑制）',
                    'value': round(float(value), 4) if value is not None else None,
                    'threshold': round(float(swing), 4) if turned else round(float(heating), 4),
                    'reason': t(
                        'analysis.alert_reason',
                        streak=run,
                        moves='、'.join(f'{move:+.4f}' for move in moves),
                        intensity='—' if rise is None else f'{rise:+.4f}',
                        volume='未提供' if volumes[position] is None else f'{volumes[position]:.0f}',
                        held='仍在线' if held else f'低于前 {run} 期均量的 {float(volume_floor):.2f} 倍',
                    ),
                }
            )
        if not rows:
            rows.append(
                {
                    'period': periods[-1] if periods else '',
                    'signal': '未触发',
                    'value': round(float(best_swing[1]), 4) if best_swing[1] else None,
                    'threshold': round(float(swing), 4),
                    'reason': t(
                        'analysis.alert_none',
                        streak=run,
                        period=best_swing[0] or '—',
                        swing=float(swing),
                        heating=float(heating),
                    ),
                }
            )
            logger.info(t('analysis.alert_none_log', checked=len(positions), streak=run, swing=float(swing)))
        else:
            for row in rows:
                logger.info(t('analysis.alert_fired', period=row['period'], signal=row['signal'], value=row['value']))
        return pd.DataFrame(rows)

    # ── Operation registry + pipeline runner ────────────────────

    @classmethod
    def _operations(cls) -> dict:
        return {
            'drop_null': cls.drop_null,
            'fill_null': cls.fill_null,
            'drop_duplicates': cls.drop_duplicates,
            'dedupe_similar': cls.dedupe_similar,
            'filter_rows': cls.filter_rows,
            'select_columns': cls.select_columns,
            'rename_columns': cls.rename_columns,
            'strip_whitespace': cls.strip_whitespace,
            'convert_type': cls.convert_type,
            'sort_rows': cls.sort_rows,
            'sample_rows': cls.sample_rows,
            'groupby_agg': cls.groupby_agg,
            'join_tables': cls.join_tables,
            'column_calc': cls.column_calc,
            'bin_column': cls.bin_column,
            'extract_time': cls.extract_time,
            'bin_time': cls.bin_time,
            'suggest_stages': cls.suggest_stages,
            'topic_model': cls.topic_model,
            'topic_by_stage': cls.topic_by_stage,
            'topic_label': cls.topic_label,
            'topic_map': cls.topic_map,
            'topic_salience': cls.topic_salience,
            'topic_timeline': cls.topic_timeline,
            'topic_flow': cls.topic_flow,
            'topic_coherence': cls.topic_coherence,
            'cooccur': cls.cooccur,
            'sentiment_evolution': cls.sentiment_evolution,
            'forecast': cls.forecast,
            'alert': cls.alert,
        }

    @classmethod
    def run_pipeline(cls, df: pd.DataFrame, steps: list, llm=None, cancel=None) -> tuple:
        """Run the steps in order and report what each one did to the table.

        ``llm`` and ``cancel`` reach only the steps in :data:`LLM_OPS`, and only as call
        arguments: the report echoes every step's ``params`` into the console and the run
        record, so a client object in there would be a live object written into a durable
        ledger — and the checkpoint/reuse machinery keys on those params.
        """
        operations = cls._operations()
        report = []
        current = df
        for step in steps or []:
            op = step.get('op')
            params = normalize_step_params(op, step.get('params', {}))
            func = operations.get(op)
            if func is None:
                raise UnknownOperationError(f'Unknown analysis operation: {op}')
            validate_step(current, op, params)
            before = len(current)
            # Only the steps in LLM_OPS are handed the run's client and Stop flag; every other
            # step is deterministic and gets the table alone.
            current = func(current, **({'llm': llm, 'cancel': cancel} if op in LLM_OPS else {}), **params)
            report.append(
                {
                    'op': op,
                    'params': params,
                    'rows_before': before,
                    'rows_after': len(current),
                    'rows_removed': before - len(current),
                }
            )
        return current, report
