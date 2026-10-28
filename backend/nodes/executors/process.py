"""Process node: every text/algorithm operation the canvas offers, plus multi-model BERT.

The select-shaped parameters of each operation are validated HERE, at the one boundary all
ops pass through, so a misspelling is refused by name instead of being guessed into a
neighbouring algorithm (``method='TF-IDF'`` used to run TextRank and stamp the table with the
name that had not run). The same table is what the panel's dropdowns declare, and the
``check_process_params`` door is asked before any model or analyzer is paid for.

A node may name several BERT models for emotion/tendency/sentiment; that switches to ONE tidy
table (one row per original row × model), the shape the 模型对比 charts read. It never
degrades to a general mode — a comparison with fewer models is a different question.
"""

import json
import os

import pandas as pd
from api.config import default_model_path_for
from api.http import _safe_float, _safe_int
from core.config import Config
from core.refs import as_bool
from core.refs import split_columns as _split_columns
from state import add_log

from analyzers import (
    BERT_BATCH,
    AggressionAnalyzer,
    AnomalyDetector,
    ContentCleaner,
    CorrelationAnalyzer,
    EmotionAnalyzer,
    KeywordExtractor,
    NamedEntityRecognizer,
    SentimentAnalyzer,
    SignificanceAnalyzer,
    TendencyAnalyzer,
    TextCluster,
)
from analyzers.bot import BotLikelihoodAnalyzer
from analyzers.sentiment import bert_backend, resolve_bert_model
from i18n import t
from nodes.context import NodeCall
from services.analysis.llm import build_llm_run_ctx
from services.analysis.pipeline import UnknownOperationError
from services.analysis.process import check_process_params, enum_param, sentiment_thresholds

NODE_TYPE = 'process'


# ─── Multi-model BERT comparison ──────────────────────────────
#: The label/score columns each analyzer writes in bert mode. A multi-model run stacks
#: several models into ONE tidy table and the 模型对比 charts read these names, so this
#: mapping is the input contract between the analysis step and the comparison visualizations
#: — renaming a column here must be reflected on the chart side or it refuses by name.
BERT_RESULT_COLUMNS = {
    'emotion': ('emotion', 'confidence'),
    'tendency': ('tendency', 'tendency_confidence'),
    'sentiment': ('sentiment', 'score'),
}


def _model_registry():
    """The registered models as a list, or [] when absent/broken — the same graceful
    reading `/api/models` uses, so a name lookup can never crash a run."""
    path = os.path.join(Config.DATA_DIR, 'model_registry.json')
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _registry_name(model_path):
    """Friendly NAME for a model path (registry reverse-lookup), else its folder name.
    The 模型 column a comparison chart groups by is a word the user chose, not a path."""
    for m in _model_registry():
        if isinstance(m, dict) and str(m.get('path', '')).strip() == model_path:
            return str(m.get('name') or '').strip() or os.path.basename(model_path)
    return os.path.basename(model_path)


def bert_model_list(params):
    """The model paths an analysis node asked to run.

    ``bert_models`` is a comma-separated list (the ``stack_fields`` shape): split, trimmed,
    de-duplicated and **sorted**, so one model set is one fingerprint no matter the click
    order. When it is empty the node falls back to the single ``bert_model`` field — every
    canvas written before multi-model runs exactly one model as it always did, and only an
    explicit multi-selection changes the output shape.
    """
    raw = str(params.get('bert_models') or '').replace('，', ',')
    seen = []
    for part in (p.strip() for p in raw.split(',')):
        if part and part not in seen:
            seen.append(part)
    if len(seen) > 1:
        return sorted(seen)
    if seen:
        return seen
    single = str(params.get('bert_model') or '').strip()
    return [single] if single else []


def _build_bert_analyzer(op, params, model_path):
    """Construct the one analyzer for (op, model), shared by the single and multi paths so
    the batch_size/threshold validation is identical either way."""
    batch = _safe_int(params.get('batch_size'), BERT_BATCH, minimum=1, maximum=256)
    max_len = _safe_int(params.get('max_length'), 512, minimum=16, maximum=2048)
    if op == 'emotion':
        return EmotionAnalyzer(mode='bert', bert_model=model_path, batch_size=batch, max_length=max_len)
    if op == 'tendency':
        return TendencyAnalyzer(mode='bert', bert_model=model_path, batch_size=batch, max_length=max_len)
    if op == 'sentiment':
        pos, neg = sentiment_thresholds(params)
        return SentimentAnalyzer(
            mode='bert',
            pos_threshold=pos,
            neg_threshold=neg,
            bert_model=model_path,
            batch_size=batch,
            max_length=max_len,
        )
    raise UnknownOperationError(
        t('analysis.bad_option', op=op, param='operation', value=op, allowed=', '.join(BERT_RESULT_COLUMNS))
    )


def _run_bert_compare(op, params, df, text_column, run_ctx):
    """Run every selected BERT model over the column and return ONE tidy table.

    One row per (original row × model), tagged by 模型 and aligned across models by 原行,
    plus the operation's own label/score columns — the shape the comparison charts read.
    A single model never enters here (it keeps its in-place two-column shape), so fewer
    than two is refused by name rather than silently returning a long table nobody asked
    for. Each model's own analyzer still refuses by name for a missing stack or an unknown
    label, and a row it cannot answer stays blank.
    """
    models = bert_model_list(params)
    if len(models) < 2:
        raise UnknownOperationError(t('analysis.need_multi_models', op=op, n=len(models)))
    # The label/score columns are NOT read here on purpose: each analyzer writes its own
    # pair (``BERT_RESULT_COLUMNS`` is the chart side's contract), so stacking the answers
    # only needs ``模型`` and ``原行``.
    base = df.copy()
    base['原行'] = range(len(base))
    collected = []
    names = []
    for path in models:
        sub = base.copy()
        analyzer = _build_bert_analyzer(op, params, path)
        sub = analyzer.analyze_dataframe(sub, text_column=text_column, ctx=run_ctx)
        name = _registry_name(path)
        sub['模型'] = name
        names.append(name)
        collected.append(sub)
    tidy = pd.concat(collected, ignore_index=True)
    add_log(t('analysis.multi_models_run', op=op, n=len(models), models='、'.join(names)))
    return tidy.to_dict('records')


#: When an explicitly-chosen ``bert`` run cannot execute on this machine, the node executor
#: degrades that op to its dependency-free mode and PRINTS which mode actually produced the
#: column — the analyzer itself still refuses by name if it is ever reached as bert (the never-
#: SILENT-cross-model invariant, kept as the last line of defense). Multi-model BERT comparison
#: does not degrade (it has no general-mode equivalent).
BERT_FALLBACK_MODE = {'sentiment': 'snownlp', 'emotion': 'ml', 'tendency': 'ml'}


def _bert_runnable(bert_model: str) -> tuple:
    """``(ok, reason)`` using the SAME availability the analyzer's bert path applies.

    ok iff ``bert_backend()`` finds torch+transformers and ``resolve_bert_model`` returns a path
    for the requested model. ``reason`` is the missing package list, or the localized no-model text.
    """
    missing = bert_backend()
    if missing:
        return False, missing
    try:
        resolved = resolve_bert_model(str(bert_model or '').strip())
    except Exception:
        resolved = ''
    if not resolved:
        return False, t('sentiment.bert_no_model')
    return True, ''


def _resolve_bert_mode(op: str, mode: str, bert_model: str) -> str:
    """Degrade an explicit/default ``bert`` the machine cannot run to the op's general mode, and SAY so.

    ``mode`` has already been validated by ``enum_param``; anything other than ``bert`` returns
    unchanged. When ``bert`` cannot run for the given ``bert_model`` (no torch/transformers, or no
    resolvable model), the executor falls back to ``BERT_FALLBACK_MODE[op]`` and ``add_log``s the mode
    that ACTUALLY ran, so the column is never silently mislabeled as bert. The analyzer's own
    refuse-by-name is untouched — it simply is not reached from here when it would fail.
    """
    if str(mode) != 'bert':
        return mode
    ok, reason = _bert_runnable(bert_model)
    if ok:
        return mode
    fallback = BERT_FALLBACK_MODE[op]
    add_log(t('analysis.bert_fallback', op=op, reason=reason, used=fallback))
    return fallback


def _effective_bert_model(op: str, params: dict) -> str:
    """The model a bert run loads: the node's own path if named, else that op's registered default.

    This is what makes the DEFAULT actually run bert — a node that names no model resolves
    ``default_model_path_for(op)`` (registry order = the operator's preference). ``''`` means nothing
    is registered for the op, which ``_resolve_bert_mode`` then treats as bert-unavailable and degrades.

    Read through :func:`bert_model_list`, the one function that knows where a node keeps its models:
    the panel's checkboxes write ``bert_models``, while ``bert_model`` is the legacy single-path box.
    Reading only the latter meant a user who ticked exactly ONE model — the ``> 1`` branch below sends
    that to this path, not to the comparison — watched a DIFFERENT model produce the column, with the
    registry default chosen silently and nothing printed about it. That is the one thing the model
    rule forbids: never answer with a model other than the one it claims.
    """
    listed = bert_model_list(params)
    named = listed[0] if len(listed) == 1 else ''
    return named or str(params.get('bert_model') or '').strip() or default_model_path_for(op)


def execute_process_node(node: dict, current_input: list, run_ctx: dict = None):
    params = node.get('params', {})
    op = node.get('operation', params.get('operation', ''))
    # Default matches the frontend canvas default and every crawler's output
    # column; the old 'content' silently mismatched real crawl data. Read through the
    # same blank-means-default rule `check_process_params` validates, so the column it
    # checks is the column the analyzer gets.
    text_column = str(params.get('text_column') or '正文').strip()
    if not current_input:
        return []

    df = pd.DataFrame(current_input)
    check_process_params(op, params, df)

    if op == 'clean':
        topic = params.get('topic', '')
        cleaner = ContentCleaner()
        df = cleaner.clean_dataframe(
            df,
            text_column=text_column,
            topic=topic,
            ctx=run_ctx,
            mode=enum_param(op, params, 'mode'),
        )
        return df.to_dict('records')

    if op == 'emotion':
        mode = enum_param(op, params, 'mode')
        if mode == 'bert' and len(bert_model_list(params)) > 1:
            return _run_bert_compare(op, params, df, text_column, run_ctx)
        bert_model = _effective_bert_model(op, params)
        mode = _resolve_bert_mode(op, mode, bert_model)
        analyzer = EmotionAnalyzer(
            mode=mode,
            bert_model=bert_model,
            # Read by the transformer path; validated here for every mode so a stored 0
            # cannot reach the chunking loop and score an empty column while reporting success.
            batch_size=_safe_int(params.get('batch_size'), BERT_BATCH, minimum=1, maximum=256),
            # Only the bert path truncates, but validated for every mode so a stored garbage
            # value falls back to 512 rather than reaching the tokenizer.
            max_length=_safe_int(params.get('max_length'), 512, minimum=16, maximum=2048),
        )
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'tendency':
        mode = enum_param(op, params, 'mode')
        if mode == 'bert' and len(bert_model_list(params)) > 1:
            return _run_bert_compare(op, params, df, text_column, run_ctx)
        bert_model = _effective_bert_model(op, params)
        mode = _resolve_bert_mode(op, mode, bert_model)
        analyzer = TendencyAnalyzer(
            mode=mode,
            bert_model=bert_model,
            # Read by the transformer path; validated here for every mode so a stored 0
            # cannot reach the chunking loop and score an empty column while reporting success.
            batch_size=_safe_int(params.get('batch_size'), BERT_BATCH, minimum=1, maximum=256),
            # Only the bert path truncates; a garbage value falls back to 512, not the tokenizer.
            max_length=_safe_int(params.get('max_length'), 512, minimum=16, maximum=2048),
        )
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'sentiment':
        mode = enum_param(op, params, 'mode')
        if mode == 'bert' and len(bert_model_list(params)) > 1:
            return _run_bert_compare(op, params, df, text_column, run_ctx)
        bert_model = _effective_bert_model(op, params)
        mode = _resolve_bert_mode(op, mode, bert_model)
        pos, neg = sentiment_thresholds(params)
        analyzer = SentimentAnalyzer(
            mode=mode,
            pos_threshold=pos,
            neg_threshold=neg,
            bert_model=bert_model,
            # Only the transformer path reads this, but it is validated here for every
            # mode so a stored 0 cannot reach the chunking loop and score nothing.
            batch_size=_safe_int(params.get('batch_size'), BERT_BATCH, minimum=1, maximum=256),
            # Only the bert path truncates; a garbage value falls back to 512, not the tokenizer.
            max_length=_safe_int(params.get('max_length'), 512, minimum=16, maximum=2048),
        )
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'keyword':
        method = enum_param(op, params, 'method')
        topk = _safe_int(params.get('topk'), 10, minimum=1)
        # ``as_bool``, never ``== 'true'``: real ``True`` is unequal to the text 'true',
        # so a workflow that stored the boolean (an exported file, /api/analysis/run)
        # asking for one merged keyword table silently got the per-row expansion.
        merge = as_bool(params.get('merge'), True)
        # A blank is "no filter" — the behaviour this node always had — so an untouched
        # canvas keeps producing exactly the keywords it used to.
        allow_pos = str(params.get('allow_pos') or '').strip()
        extractor = KeywordExtractor()
        df = extractor.analyze_dataframe(
            df,
            text_column=text_column,
            method=method,
            topk=topk,
            merge=merge,
            allow_pos=allow_pos,
        )
        return df.to_dict('records')

    if op == 'cluster':
        method = enum_param(op, params, 'cluster_method')
        n_clusters = _safe_int(params.get('n_clusters'), 3, minimum=1)
        eps = _safe_float(params.get('eps'), 0.5)
        min_samples = _safe_int(params.get('min_samples'), 2, minimum=1)
        clusterer = TextCluster()
        df = clusterer.analyze_dataframe(
            df,
            text_column=text_column,
            method=method,
            n_clusters=n_clusters,
            eps=eps,
            min_samples=min_samples,
        )
        return df.to_dict('records')

    if op == 'ner':
        # Its own mode default: the rules need no model, and a workflow saved
        # before the mode selector existed must not start paying for one.
        recognizer = NamedEntityRecognizer(mode=enum_param(op, params, 'mode'))
        df = recognizer.analyze_dataframe(
            df,
            text_column=text_column,
            entity_types=params.get('entity_types'),
            ctx=run_ctx,
        )
        return df.to_dict('records')

    if op == 'aggression':
        # The paper's own object: how violent the speech is, as opposed to how negative. The
        # lexicon mode is the default (no model, no cost, reproducible), and ``llm`` reuses the
        # shared row-by-row runner, so batching, checkpointing, Stop and 未处理 all arrive with it.
        analyzer = AggressionAnalyzer(
            mode=enum_param(op, params, 'mode'),
            model_name=str(params.get('model') or '').strip(),
        )
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'bot':
        # A per-AUTHOR coordinated-posting signal read off the whole table (near-duplicate text
        # across accounts + a posting burst). Like aggression it is a recall device, not a verdict,
        # and it refuses by name when 评论者 / 评论时间 are absent — check_process_params has already
        # run those guards by the time this branch executes.
        analyzer_bot = BotLikelihoodAnalyzer()
        author_column = str(params.get('author_column') or '评论者').strip()
        time_column = str(params.get('time_column') or '评论时间').strip()
        df = analyzer_bot.analyze_dataframe(
            df,
            text_column=text_column,
            author_column=author_column,
            time_column=time_column,
            cancel_event=(run_ctx or {}).get('cancel_event'),
        )
        return df.to_dict('records')

    if op == 'anomaly':
        # _split_columns, not raw .split(','): a list like "a, b" used to keep
        # the leading space and match no column at all, silently.
        columns = _split_columns(params.get('columns')) or None
        contamination = min(max(_safe_float(params.get('contamination'), 0.1), 0.001), 0.5)
        detector = AnomalyDetector()
        df = detector.analyze_dataframe(df, columns=columns, contamination=contamination)
        return df.to_dict('records')

    if op == 'correlation':
        columns = _split_columns(params.get('columns')) or None
        corr_method = enum_param(op, params, 'corr_method')
        min_abs = _safe_float(params.get('min_abs'), 0.0)
        analyzer_corr = CorrelationAnalyzer()
        df = analyzer_corr.analyze_dataframe(df, columns=columns, method=corr_method, min_abs=min_abs)
        return df.to_dict('records')

    if op == 'significance':
        # One group column and one value column, read whole (a single name, not a split list):
        # the test compares ONE numeric field across the levels of ONE categorical field.
        group_col = str(params.get('group_column') or '').strip()
        value_col = str(params.get('value_column') or '').strip()
        sig_method = enum_param(op, params, 'sig_method')
        analyzer_sig = SignificanceAnalyzer()
        df = analyzer_sig.analyze_dataframe(df, group_column=group_col, value_column=value_col, sig_method=sig_method)
        return df.to_dict('records')

    # An unknown operation is a broken node, not an empty table. Returning [] here
    # settled it DONE: the run went green, every downstream node complained 「上游没有
    # 数据」 about itself, and the single sentence explaining why carried no node name
    # at all — so the user was sent to diagnose the healthy boxes. Raising hands the
    # reason to the executor, which fails THIS node and prints it with its label.
    raise ValueError(t('wf.unknown_process_op', op=op or '(empty)'))


def run(node: dict, call: NodeCall):
    op = node.get('operation') or node.get('params', {}).get('operation', '')
    return execute_process_node(node, call.current_input, run_ctx=call.run_ctx or build_llm_run_ctx(node, op, call.ctx))
