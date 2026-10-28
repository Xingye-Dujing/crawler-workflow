"""The per-node context every model-backed analyzer consumes, built in ONE place.

Transport (local Ollama vs OpenRouter), model, key, batching and the run's Stop event all come
from the settings panel via the execute request. Two readers of those settings — one here and
one in a node executor — would be two opinions about which model a run is using, so the process
node, the analysis node and the API all call this builder.

Every answered row also lands in a cache keyed by text, not by row index, so re-running after a
re-crawl still gets those answers free. The cache SCOPE is assembled by the row runner itself:
it is the one place that genuinely knows the prompt builder, the truncation cap and the daemon
address, all of which change what an answer means.
"""

import os

from core.config import Config
from core.refs import as_bool
from state import _completed_lock, add_log, execution_state

from analyzers.llm_client import LLMClient
from i18n import t
from services.runs.files import record_file


def build_llm_run_ctx(node: dict, op: str, ctx: dict = None) -> dict:
    """Build the per-node run context the LLM analyzers consume.

    ``publish`` makes finished rows visible node-by-node: the node's entry in
    ``execution_state['results']`` updates after every batch, so a crash or a stop mid-run
    leaves the partial table usable instead of gone.

    A node may pick its own Ollama tag, but the transport (provider/host/key) stays run-level.
    The daemon address is pinned when the run started, so a settings save mid-run cannot split
    one run across two hosts.
    """
    cfg = execution_state.get('llm') or {}
    provider = cfg.get('provider') or 'ollama'
    # Per-node model override: only Ollama is overridable — an OpenRouter run must not be
    # handed a daemon tag it has no id for — and a blank node model falls back to the run's
    # global model.
    node_model = str((node.get('params') or {}).get('model') or '').strip() if provider == 'ollama' else ''
    client = LLMClient(
        provider=provider,
        model=node_model or (cfg.get('model') or ''),
        api_key=cfg.get('api_key') or '',
        # Cleaner outputs a full rewritten text; the classifiers answer in a
        # dozen tokens. Capping keeps a chatty model from burning quota.
        max_tokens=2048 if op == 'clean' else 512,
        max_chars=cfg.get('max_chars') or 0,
        timeout=300 if provider == 'ollama' else 120,
        # OpenRouter's address is its endpoint, not a setting.
        host=(cfg.get('ollama_host') or '') if provider == 'ollama' else '',
        # Retries sleep between attempts; Stop used to wait them out in full
        # (backoff + Retry-After + a 300 s daemon timeout could mean minutes).
        # The client now naps on this event instead, so Stop lands between
        # attempts rather than after them.
        cancel_event=execution_state.get('cancel_event'),
    )
    node_id = node.get('id', '')
    # ── live snapshot (AI 调用实时导出) ──
    # A long LLM pass enriches rows in batches; the honest artifact there is
    # 'the table as it stands', so every settled batch rewrites the whole
    # snapshot (atomic tmp+replace — an opened file is never half-written).
    live_writer = None
    if as_bool((node.get('params') or {}).get('live_export')):
        from services.part_writer import SnapshotWriter, safe_stem

        stem = safe_stem(f'{execution_state.get("workflow_name") or "llm"}-{node_id}')
        lfmt = 'json' if str((node.get('params') or {}).get('format') or 'csv') == 'json' else 'csv'
        live_writer = SnapshotWriter(Config.EXPORT_DIR, stem, lfmt)
        add_log(t('run.live_export', file=os.path.basename(live_writer.path)))
        # The live file has one fixed name from the moment it is made, so it is registered once
        # here rather than on every batch's rewrite — it is a run artifact and 智能清除 must find it.
        record_file(ctx, node_id, live_writer.path, 'live')

    def publish(df):
        records = df.to_dict('records')
        with _completed_lock:
            execution_state['results'][node_id] = records
        if live_writer is not None:
            try:
                live_writer.write(records)
            except Exception as e:
                # run_llm_rows swallows publish errors; say it out loud here
                # so a read-only export dir does not silently kill the feature.
                add_log(t('run.live_export_failed', err=e))

    run_ctx = {
        'client': client,
        'node_id': node_id,
        'batch_size': cfg.get('batch_size') or 10,
        # API providers tolerate a little concurrency (free tiers are shared
        # and rate-limited); the local daemon serves one request at a time.
        'workers': (cfg.get('workers') or 3) if provider == 'openrouter' else 1,
        'publish': publish,
        'cancel_event': execution_state.get('cancel_event'),
        'checkpoint_dir': Config.LLM_CHECKPOINT_DIR,
    }
    if ctx is not None:
        # Only the store is lent — see the docstring on why the row runner
        # builds the cache scope itself.
        run_ctx['store_for_cache'] = ctx['store']
        # A run-level, per-node cancellation ledger the executor also reads. The
        # direct analyzers leave 未处理 in their rows for the executor's scan, but
        # NER transforms that marker away; the shared dict (identity survives the
        # analyzer's shallow ``dict(ctx)`` copy) lets the row runner report "this
        # node was stopped mid-way" so no LLM node settles DONE on skipped rows.
        run_ctx['node_id'] = node_id
        run_ctx['cancel_book'] = ctx.setdefault('node_cancelled', {})
    return run_ctx
