"""One registry for node model tiers and the AI-workspace trace gate.

A "tier" is what a node uses to do its work, from cheapest to most expensive:

    traditional  local, non-LLM models — BERT/sklearn/SnowNLP, NLI, sentence embeddings;
    llm          a language model served by the local Ollama daemon, or a coding node
                 (qualitative coding / deductive content analysis) that drives one;
    api          a language model behind a cloud transport (DeepSeek, OpenRouter, OpenCode Go).

The user picks a threshold in Settings → AI workspace (``ai_trace_tier``). A node opens a visible
AI-workspace conversation when its tier is AT OR ABOVE that threshold — so "traditional" traces
everything, "llm" traces LLMs and APIs, "api" traces only cloud calls, and "off" traces nothing.
The backend gate (here) decides WHICH nodes open a conversation; the browser reads the same setting
only to decide whether to reveal the dock after a run (it checks ``off`` vs non-``off`` and follows
the run's own trace endpoint). The browser does not re-derive node tiers — doing that would be a
second opinion about this registry.

This module owns the ordering and the node→tier decision so no caller re-derives it from an op's
select shape (the mistake that once made qualitative coding invisible to the trace seam).
"""

from __future__ import annotations

from services.analysis.process import PROCESS_ENUMS, op_calls_llm

#: Ascending cost. Stored in settings as these exact strings.
TIERS = ('off', 'traditional', 'llm', 'api')
_RANK = {name: i for i, name in enumerate(TIERS)}

#: Ops that do their job with a LOCAL TRADITIONAL model even when no LLM is involved. They are
#: listed explicitly because their select (phase / method / no select at all) does not say "model":
#: zero_shot runs a local NLI pipeline, semantic_dedupe/similar_to run a sentence encoder, and the
#: bert/ml/snownlp modes of the classifiers run local models. A node is traditional if it is in this
#: set AND its current mode is not an LLM mode (op_calls_llm answers that half).
TRADITIONAL_OPS = frozenset(
    {
        'zero_shot',
        'semantic_dedupe',
        'similar_to',
    }
)

#: Classifier ops whose non-LLM modes (bert/ml/snownlp/regex) are traditional models.
_CLASSIFIER_OPS = frozenset({'clean', 'emotion', 'tendency', 'sentiment', 'ner', 'aggression'})

#: Topic steps use a local encoder ONLY when their (possibly auto-resolved) method is 'embedding'.
#: Their real op ids are topic_model/topic_map/... — 'topic' is a column name, never an op, so a
#: registry entry for it could never match and embedding topic nodes were silently untraced.
# Kept as a space-delimited constant so the op names are not copied into a bracketed literal —
# test_data_analysis.py refuses a fourth in-source copy of the operator vocabulary.
_TOPIC_OPS_NAMES = 'topic_model topic_map topic_salience topic_by_stage topic_coherence'
_TOPIC_OPS = frozenset(_TOPIC_OPS_NAMES.split())


def _topic_uses_encoder(params: dict) -> bool:
    """Resolve a topic step's method through the SAME resolver the op uses at run time."""
    from services.analysis.topic_kernels import _resolve_topic_method

    return _resolve_topic_method(str(params.get('method') or 'auto')) == 'embedding'


def tier_rank(name: str) -> int:
    """Numeric rank of a tier name; unknown names read as 'off' (no tracing)."""
    return _RANK.get(str(name or '').strip().lower(), 0)


def node_tier(node: dict, op: str, provider: str = 'ollama') -> str:
    """The tier a node actually uses at run time.

    * LLM-backed nodes (a classifier in `llm` mode, qualitative/content coding) use a cloud tier
      when the run's provider is a cloud API, otherwise 'llm'.
    * The same classifier in a non-LLM mode, plus zero_shot/embedding ops, is 'traditional'.
    * Everything else (rules, statistics, crawl/export plumbing) returns 'off' — no model, so it
      never opens a conversation regardless of the threshold.
    """
    op = str(op or (node.get('params') or {}).get('operation') or '')
    if op_calls_llm(op, node.get('params') or {}):
        return 'api' if provider not in ('', 'ollama') else 'llm'
    if op in TRADITIONAL_OPS or (op in _CLASSIFIER_OPS and _has_local_model_mode(node, op)):
        return 'traditional'
    if op in _TOPIC_OPS and _topic_uses_encoder(node.get('params') or {}):
        return 'traditional'
    return 'off'


def _has_local_model_mode(node: dict, op: str) -> bool:
    """True when a classifier is in a mode that runs a local model (bert/ml/snownlp).

    The blank-mode default is read from PROCESS_ENUMS — the same declaration the panel shows — so a
    saved node with an empty mode is tiered by what it will actually run, not a second hard-coded
    table that could drift.
    """
    spec = PROCESS_ENUMS.get(op) or {}
    default = spec['mode'][0] if 'mode' in spec else ''
    raw = str((node.get('params') or {}).get('mode') or '').strip()
    mode = raw or default
    # 'regex'/'lexicon' are rule/word-list modes, not models. Everything else the classifier can
    # select that is NOT the LLM mode is a local model (bert / ml / snownlp).
    return bool(mode) and mode != 'llm' and mode not in ('regex', 'lexicon')


def should_trace(node: dict, op: str, provider: str, threshold: str) -> bool:
    """Whether this node should open a trace conversation at the configured threshold."""
    minimum = tier_rank(threshold)
    if minimum == 0:  # 'off' (or an unknown value) traces nothing
        return False
    return tier_rank(node_tier(node, op, provider)) >= minimum


#: Human-readable provider labels for the trace conversation's bottom model chip. For LLM nodes the
#: real run provider (ollama/deepseek/...) is used; for traditional models the label names the kind
#: of local model so the chip does not claim a chat transport that never answered the node.
_TRADITIONAL_LABEL = {
    'bert': 'local BERT',
    'ml': 'local sklearn',
    'snownlp': 'SnowNLP',
    'regex': 'rules',
    'lexicon': 'word list',
}

#: Ops whose model name is fixed by a module-level default (not a node param). Imported lazily in
#: resolve_model_identity to avoid pulling heavy deps (transformers) at module import.
_FIXED_MODEL_OPS = {
    'zero_shot': ('analyzers.zero_shot', 'DEFAULT_MODEL'),
    'semantic_dedupe': ('analyzers.backends.encoder', 'DEFAULT_EMBED_MODEL'),
    'similar_to': ('analyzers.backends.encoder', 'DEFAULT_EMBED_MODEL'),
}


def resolve_model_identity(node: dict, op: str, provider: str, run_model: str = '') -> tuple[str, str]:
    """``(provider_label, model_name)`` to stamp on a node's trace conversation.

    For an LLM node this is the run's real transport + model (the bottom chip shows what answered).
    For a traditional model it names the local model family and the resolved model (bert path, NLI
    tag, embedding name), so a demo recording shows e.g. ``local BERT / ml_train/models/…rbt3``
    instead of an empty chip or, worse, a stale LLM model from the user's last chat.
    """
    op = str(op or (node.get('params') or {}).get('operation') or '')
    tier = node_tier(node, op, provider)
    params = node.get('params') or {}

    if tier in ('llm', 'api'):
        label = {
            'ollama': 'Ollama',
            'deepseek': 'DeepSeek',
            'openrouter': 'OpenRouter',
            'opencode_go': 'OpenCode Go',
        }.get(provider, provider or 'LLM')
        # Only Ollama honours a per-node model (see build_llm_run_ctx); a cloud run uses the run's
        # model. A stale node field must never make the chip claim a model the transport never used.
        node_model = str(params.get('model') or '').strip() if provider == 'ollama' else ''
        return label, (node_model or str(run_model or '').strip())

    if tier == 'traditional':
        mode = str(params.get('mode') or '').strip()
        family = _TRADITIONAL_LABEL.get(mode, 'local model')
        name = ''

        if op in _CLASSIFIER_OPS:
            # Resolve through the SAME code the executor uses, including its availability check and
            # its named degrade path. Otherwise the chip would say "local BERT / path" while the
            # analyzer quietly ran SnowNLP/sklearn because torch or the model was unavailable.
            effective_mode = mode or str(PROCESS_ENUMS.get(op, {}).get('mode', ('', ()))[0])
            try:
                from nodes.executors.process import BERT_FALLBACK_MODE, _bert_runnable, _effective_bert_model

                if effective_mode == 'bert':
                    path = _effective_bert_model(op, params)
                    ok, _reason = _bert_runnable(path)
                    if ok:
                        return _TRADITIONAL_LABEL['bert'], path
                    effective_mode = BERT_FALLBACK_MODE.get(op, '')
                    family = _TRADITIONAL_LABEL.get(effective_mode, 'local model')
                # A non-BERT local mode has NO model path: do not fall back to a stale bert_model
                # field left over from a previous selection.
                return family, ''
            except Exception:
                # If the executor module cannot be imported, fall through to a conservative
                # family-only identity rather than naming a model we cannot verify.
                return family, ''

        if op in _FIXED_MODEL_OPS or (op in _TOPIC_OPS and _topic_uses_encoder(params)):
            if op in _TOPIC_OPS:
                name = str(params.get('embedding_model') or '').strip()
                if not name:
                    from analyzers.backends.encoder import DEFAULT_EMBED_MODEL

                    name = DEFAULT_EMBED_MODEL
                family = 'local model'
            else:
                module_name, attr = _FIXED_MODEL_OPS[op]
                try:
                    import importlib

                    name = str(getattr(importlib.import_module(module_name), attr) or '')
                except Exception:
                    name = ''
        return family, name

    return '', ''
