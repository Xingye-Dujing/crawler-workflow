import base64
import contextlib
import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from analyzers import (
    AnomalyDetector,
    ContentCleaner,
    CorrelationAnalyzer,
    EmotionAnalyzer,
    KeywordExtractor,
    NamedEntityRecognizer,
    TendencyAnalyzer,
    TextCluster,
    build_training_data,
    get_classifier,
)
from analyzers.llm_client import LLMClient, LLMError, list_free_models, list_ollama_models
from config import Config
from crawlers import get_crawler
from engine.executor import TaskExecutor
from engine.logger import setup_logger
from engine.workflow import WorkflowEngine
from i18n import audit, normalize, set_lang, t
from services import StatsService
from services.cookie_manager import CookieManager
from services.data_analysis import DataAnalysisService, UnknownOperationError
from services.execution_history import ExecutionHistoryService
from services.exporter import DataExporter, UnsupportedFormatError
from services.visualizer import ChartConfigError, VisualizationService
from services.workflow_manager import WorkflowManager
from settings_store import all_settings, get_setting, save_settings
from utils.helpers import sanitize_filename

app = Flask(__name__, static_folder='static', static_url_path='')
app.config['SECRET_KEY'] = Config.SECRET_KEY
CORS(app)

logger = setup_logger(Config.LOG_DIR)

# Catalogue self-check. A message template carrying a printf placeholder never
# raises — it just prints as a literal "%s" in the console — so surface it here,
# where the offending key is named, instead of leaving it to be spotted later.
for _issue in audit():
    logger.warning(f'i18n: {_issue}')

# Thread-local storage: tracks which workflow index the current thread belongs to.
# Used by LogBufferHandler, _LogTee, and add_log to route log lines into the
# correct per-workflow buffer (_wf_logs[wf_idx]) in parallel mode.
_wf_local = threading.local()


# Console lines kept in memory. The frontend only ever renders the last 200,
# but the total count has to keep growing so the browser can tell how many it
# has not seen yet (see _push_log).
LOG_KEEP = 5000

# Every message that reaches the console is i18n.t(key, **params) — add_log,
# logging, and print() all funnel through here.


def _push_log(line: str, wf_idx: int = None):
    """Append one console line, keeping the buffer bounded.

    ``_log_total`` counts every line ever produced, not the number retained: the
    status endpoint ships only the tail, so without a running total the browser
    cannot work out the delta and the console silently freezes at 200 lines.
    """
    logs = execution_state['logs']
    logs.append(line)
    if len(logs) > LOG_KEEP:
        del logs[:-LOG_KEEP]
    execution_state['_log_total'] += 1
    idx = wf_idx if wf_idx is not None else getattr(_wf_local, 'idx', None)
    if idx is not None:
        buf = execution_state['_wf_logs'].setdefault(idx, [])
        buf.append(line)
        if len(buf) > LOG_KEEP:
            del buf[:-LOG_KEEP]
        execution_state['_wf_log_total'][idx] = execution_state['_wf_log_total'].get(idx, 0) + 1


class LogBufferHandler(logging.Handler):
    """Feed all logger.info/error/warning calls into execution_state['logs'] for the frontend."""

    def emit(self, record):
        if record.name.startswith('werkzeug'):
            return
        _push_log(f'[{time.strftime("%H:%M:%S")}] {self.format(record)}')

    def format(self, record):
        return record.getMessage()


_log_handler = LogBufferHandler()
_log_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_log_handler)
logging.getLogger().setLevel(logging.INFO)


class _LogTee:
    """Fallback: tee print() output into execution_state['logs'] (catches analyzer print() calls)."""

    def __init__(self, original):
        self._original = original

    def write(self, text):
        if text and text != '\n':
            ts = time.strftime('%H:%M:%S')
            for line in text.rstrip('\n').split('\n'):
                msg = line.rstrip()
                if msg:
                    _push_log(f'[{ts}] {msg}')
        self._original.write(text)

    def flush(self):
        self._original.flush()


cookie_manager = CookieManager(Config.COOKIE_DIR)
workflow_manager = WorkflowManager()
history_service = ExecutionHistoryService()


@app.before_request
def _apply_request_lang():
    """Pin the console language for this request/worker thread.

    The UI language rides along as the ``X-Lang`` header (the frontend patches
    fetch once so every call carries it); ``?lang=`` is accepted for manual
    calls. Requests are served by Flask's own thread pool, so this is the only
    place that can set it for the non-workflow endpoints.
    """
    set_lang(request.headers.get('X-Lang') or request.args.get('lang') or 'zh')


# In-memory registry of uploaded/pasted datasets, keyed by a generated id.
# This is what backs the Upload node: a file the user picked is registered
# here, and the node publishes it as ordinary rows, so downstream nodes get
# data that didn't come from a crawl without any of them knowing the
# difference.
_datasets = {}
MAX_DATASETS = 50


def _register_dataset(df: pd.DataFrame, name: str = 'dataset') -> str:
    """Store a DataFrame under a fresh id, evicting the oldest entry if the
    in-memory registry is full (this is a lightweight cache, not persistence)."""
    if len(_datasets) >= MAX_DATASETS:
        oldest = next(iter(_datasets))
        _datasets.pop(oldest, None)
    dataset_id = uuid.uuid4().hex[:12]
    _datasets[dataset_id] = {'name': name, 'df': df}
    return dataset_id


def _json_safe_records(df: pd.DataFrame, limit: int = None) -> list:
    """Convert a DataFrame slice to JSON-safe records: NaN/NaT become None
    (raw NaN is not valid JSON and breaks JSON.parse() in the browser)."""
    page = df.head(limit) if limit is not None else df
    return page.astype(object).where(pd.notna(page), None).to_dict('records')


def _resolve_dataframe(payload: dict) -> pd.DataFrame:
    """Resolve a DataFrame from a request payload that may reference an
    uploaded dataset id, a workflow node's result, or inline records."""
    dataset_id = payload.get('dataset_id')
    if dataset_id:
        entry = _datasets.get(dataset_id)
        if entry is None:
            raise KeyError(f'Unknown dataset_id: {dataset_id}')
        return entry['df']

    node_id = payload.get('node_id')
    if node_id:
        result = execution_state['results'].get(node_id)
        if isinstance(result, list):
            return pd.DataFrame(result)
        raise KeyError(f'No tabular result available for node: {node_id}')

    records = payload.get('data')
    if records is not None:
        return pd.DataFrame(records)

    raise KeyError('No data source provided (dataset_id, node_id, or data)')


def _tokenize_dataframe(df: pd.DataFrame, params: dict) -> pd.DataFrame | None:
    """Apply tokenization to a DataFrame and return the result, or None if the
    column is missing."""
    column = params.get('text_column', '')
    if column not in df.columns:
        return None
    output_mode = params.get('output_mode', 'word_freq')
    top_n = params.get('top_n', '')
    kwargs = {}
    if output_mode == 'word_freq' and top_n:
        kwargs['top_n'] = _safe_int(top_n, 120, minimum=1)
    labels, values = VisualizationService.tokenize_frequency(df, column, **kwargs)
    if not labels:
        return pd.DataFrame()
    if output_mode == 'words_only':
        return pd.DataFrame([{'word': w} for w in labels])
    if output_mode == 'csv_line':
        return pd.DataFrame([{'words': ' '.join(labels)}])
    return pd.DataFrame([{'word': w, 'frequency': v} for w, v in zip(labels, values, strict=True)])


execution_state = {
    'running': False,
    'executor': None,
    'thread': None,
    'results': {},
    'logs': [],
    '_log_total': 0,  # lines ever produced (the list itself is capped)
    'total_nodes': 0,
    'completed_nodes': 0,
    'active_crawlers': set(),
    '_wf_logs': {},  # {wf_idx: [log lines]} per-workflow logs for parallel mode
    '_wf_log_total': {},  # {wf_idx: lines ever produced} — see _push_log
    '_mode': 'serial',
    'llm': None,  # AI transport config from the settings panel (see /api/workflow/execute)
    'cancel_event': threading.Event(),  # set by Stop; checked between LLM rows
}
_completed_lock = threading.Lock()


def _workflow_needs_llm(workflow: dict) -> bool:
    """True when any process node in the payload will actually call a model.

    Cleaner always does; the two classifiers only when they are not running the
    locally trained scikit-learn model. A crawl-and-save workflow must not be
    blocked by a missing API key or an unpicked Ollama tag — the frontend makes
    the same distinction before it opens the console.
    """
    for node in workflow.get('nodes') or []:
        if not isinstance(node, dict) or node.get('type') != 'process':
            continue
        params = node.get('params') or {}
        op = str(params.get('operation') or node.get('operation') or '')
        if op == 'clean':
            return True
        if op in ('emotion', 'tendency') and str(params.get('mode') or '') != 'ml':
            return True
    return False


def _llm_run_ctx(node: dict, op: str) -> dict:
    """Build the per-node run context the LLM analyzers consume.

    The transport (local Ollama vs OpenRouter API), model, key and batching
    all come from the settings panel via the execute request. ``publish``
    makes finished rows visible node-by-node: the node's entry in
    execution_state['results'] updates after every batch, so a crash or a
    stop mid-run leaves the partial table usable instead of gone. Rows are
    also appended to a checkpoint file (analyzers/llm_client.RowCheckpoint),
    which a re-run resumes from.
    """
    cfg = execution_state.get('llm') or {}
    provider = cfg.get('provider') or 'ollama'
    client = LLMClient(
        provider=provider,
        model=cfg.get('model') or '',
        api_key=cfg.get('api_key') or '',
        # Cleaner outputs a full rewritten text; the classifiers answer in a
        # dozen tokens. Capping keeps a chatty model from burning quota.
        max_tokens=2048 if op == 'clean' else 512,
        max_chars=cfg.get('max_chars') or 0,
        timeout=300 if provider == 'ollama' else 120,
        # Daemon address pinned when the run started (设置 → Ollama 服务地址),
        # so a settings save mid-run cannot split one run across two hosts.
        # OpenRouter's address is its endpoint, not a setting.
        host=(cfg.get('ollama_host') or '') if provider == 'ollama' else '',
    )
    node_id = node.get('id', '')

    def publish(df):
        with _completed_lock:
            execution_state['results'][node_id] = df.to_dict('records')

    return {
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


def add_log(msg: str, wf_idx: int = None):
    _push_log(f'[{time.strftime("%H:%M:%S")}] {msg}', wf_idx)


def _record_execution_history(workflow: dict, engine: WorkflowEngine, results: dict, workflow_name: str = ''):
    """After a run completes, snapshot per-node metrics (row counts, and
    emotion/tendency distributions where present) into execution_history so
    /api/history/* can chart trends across runs over time. Best-effort: a
    failure here must never break the workflow run itself.

    The name matters: without it every run was filed as "untitled" and the
    history panel's per-workflow grouping could not distinguish anything.
    """
    try:
        run_id = uuid.uuid4().hex[:12]
        workflow_name = str(workflow_name or workflow.get('name') or '').strip() or 'untitled'
        ts = history_service.now()
        rows = []
        for nid, result in results.items():
            if not isinstance(result, list) or not result:
                continue
            node = engine.nodes.get(nid, {})
            ntype = node.get('type', '?')
            rows.append((run_id, workflow_name, nid, ntype, 'rows', 'count', float(len(result)), ts))

            df = pd.DataFrame(result)
            if 'emotion' in df.columns:
                dist = StatsService.emotion_distribution(result)
                for label, value in zip(dist['labels'], dist['values'], strict=True):
                    rows.append((run_id, workflow_name, nid, ntype, 'emotion', label, float(value), ts))
            if 'tendency' in df.columns:
                dist = StatsService.tendency_distribution(result)
                for label, value in zip(dist['labels'], dist['values'], strict=True):
                    rows.append((run_id, workflow_name, nid, ntype, 'tendency', label, float(value), ts))

        history_service.record_many(rows)
    except Exception:
        logger.exception(t('misc.history_failed'))


# ─── API Routes ────────────────────────────────────────────────


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


# ─── Workflow API ──────────────────────────────────────────────


@app.route('/api/workflow/save', methods=['POST'])
def save_workflow():
    data = request.get_json()
    name = data.get('name', 'untitled')
    workflow = data.get('workflow', {})
    try:
        path = workflow_manager.save(name, workflow)
        return jsonify({'ok': True, 'path': path})
    except OSError as e:
        logger.exception(t('misc.save_workflow_failed'))
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/workflow/load', methods=['GET'])
def load_workflow():
    name = request.args.get('name', '')
    workflow = workflow_manager.load(name)
    if workflow:
        return jsonify({'ok': True, 'workflow': workflow})
    return jsonify({'ok': False, 'error': 'Not found'}), 404


@app.route('/api/workflow/list', methods=['GET'])
def list_workflows():
    return jsonify({'ok': True, 'workflows': workflow_manager.list_workflows()})


@app.route('/api/workflow/delete', methods=['POST'])
def delete_workflow():
    name = request.get_json().get('name', '')
    workflow_manager.delete(name)
    return jsonify({'ok': True})


# ─── Execution API ─────────────────────────────────────────────


@app.route('/api/workflow/execute', methods=['POST'])
def execute_workflow():
    running_thread = execution_state['thread']
    # The previous run's thread may still be unwinding after a Stop (it clears
    # `running` first), so check liveness too — otherwise a quick Stop → Run
    # leaves two threads appending to the same console and results.
    if execution_state['running'] or (running_thread is not None and running_thread.is_alive()):
        return jsonify({'ok': False, 'error': t('api.alreadyRunning')}), 400

    data = request.get_json(silent=True) or {}
    workflow = data.get('workflow', {})
    settings = workflow.get('settings', {})
    mode = settings.get('mode', 'parallel')
    headless = settings.get('headless', True)
    max_workers = _safe_int(settings.get('max_workers'), Config.DEFAULT_MAX_WORKERS, minimum=1, maximum=16)
    # Recorded with the run so the history panel can group by workflow rather
    # than showing every run as "untitled".
    workflow_name = str(data.get('workflow_name') or workflow.get('name') or '').strip()

    # AI transport chosen in the settings panel: 'ollama' (local daemon) or
    # 'openrouter' (API). The key only ever lives in the browser's
    # localStorage; it travels with this request and is kept in memory.
    # Console language for this run. The UI sends it explicitly because the
    # run outlives the request that started it — and thread-locals are not
    # inherited by the worker threads below, so each one re-applies it.
    execution_state['lang'] = normalize(data.get('lang') or request.headers.get('X-Lang') or 'zh')

    llm_cfg = data.get('llm') or {}
    execution_state['llm'] = {
        'provider': llm_cfg.get('provider') or 'ollama',
        'model': (llm_cfg.get('model') or '').strip(),
        'api_key': (llm_cfg.get('api_key') or '').strip(),
        'ollama_host': str(get_setting('ollama_host') or ''),
        'batch_size': _safe_int(llm_cfg.get('batch_size'), 10, minimum=1, maximum=100),
        'max_chars': _safe_int(llm_cfg.get('max_chars'), 600, minimum=0, maximum=20000),
        'workers': _safe_int(llm_cfg.get('workers'), 3, minimum=1, maximum=8),
    }
    # Per-provider requirements: the key belongs to OpenRouter, the pulled tag
    # to the local daemon — and neither is demanded by a run that never calls
    # a model.
    if _workflow_needs_llm(workflow):
        if execution_state['llm']['provider'] == 'openrouter':
            if not execution_state['llm']['api_key']:
                return jsonify({'ok': False, 'error': t('api.needApiKey')}), 400
            if not execution_state['llm']['model']:
                return jsonify({'ok': False, 'error': t('api.needModel')}), 400
        elif not execution_state['llm']['model']:
            return jsonify({'ok': False, 'error': t('api.needOllamaModel')}), 400

    cancel_event = threading.Event()
    execution_state['cancel_event'] = cancel_event
    execution_state['running'] = True
    execution_state['results'] = {}
    execution_state['logs'] = []
    execution_state['_log_total'] = 0
    execution_state['_wf_logs'] = {}
    execution_state['_wf_log_total'] = {}
    execution_state['total_nodes'] = 0
    execution_state['completed_nodes'] = 0
    execution_state['_mode'] = mode
    execution_state['executor'] = TaskExecutor(max_workers=max_workers, mode=mode)

    def _run_single_workflow(wf_engine, wf_idx: int):
        """Execute one workflow (single connected component) level by level,
        with its own isolated wf_input. Returns {nid: result, ...}.

        At each level the input is SNAPSHOTTED so that forked nodes at the
        same level all receive the same parent data (e.g. node-1 → node-2 AND
        node-1 → node-4 → both see node-1's result, not node-2's).
        """
        _wf_local.idx = wf_idx
        levels = wf_engine.group_by_level()
        results = {}
        # Every node reads the result of the node wired into it. A level-wide
        # "last transform wins" input is wrong as soon as one workflow holds two
        # data branches: with s1→p1 and s2→p2 both feeding a later node, p1 and
        # p2 would each receive whichever source ran last, so p1 would silently
        # process s2's rows.
        upstream_of = {}
        for conn in wf_engine.connections:
            upstream_of.setdefault(conn['to'], []).append(conn['from'])

        def _inputs_for(nid: str):
            """→ (rows of the first incoming connection, [(parent_id, result), …]).

            The full list travels with the node so a join can use the *second*
            incoming connection as its right-hand table; every other node just
            takes the first one.
            """
            parents = upstream_of.get(nid) or []
            if not parents:
                # A source (crawler or upload) has nothing upstream.
                return [], []
            if len(parents) > 1:
                add_log(t('wf.multi_input', nid=nid, up=parents[0], n=len(parents)), wf_idx=wf_idx)
            pairs = [(pid, results.get(pid)) for pid in parents]
            primary = pairs[0][1]
            # A chart spec (dict) is not tabular input; neither is a node that
            # has not produced a list.
            return (primary if isinstance(primary, list) else []), pairs

        for level in levels:
            if not execution_state['running']:
                break
            for nid in level:
                if not execution_state['running']:
                    break
                node = wf_engine.nodes[nid]
                add_log(
                    t('wf.executing_node', i=wf_idx, nid=nid, ntype=node.get('type', '?')),
                    wf_idx=wf_idx,
                )
                try:
                    primary, upstream = _inputs_for(nid)
                    result = _execute_node(node, headless, primary, upstream=upstream)
                except Exception as e:
                    # A dead node must not take finished work with it: rows the
                    # LLM already completed were published into results as they
                    # landed, so they stay. This branch stops here rather than
                    # feeding half-processed data downstream; sibling workflows
                    # (parallel mode) keep running.
                    msg = str(e)
                    add_log(t('wf.node_failed', i=wf_idx, nid=nid, err=msg), wf_idx=wf_idx)
                    add_log(t('wf.partial_kept', i=wf_idx), wf_idx=wf_idx)
                    break
                results[nid] = result
                with _completed_lock:
                    execution_state['completed_nodes'] += 1
                add_log(
                    t(
                        'wf.node_completed',
                        i=wf_idx + 1,
                        nid=nid,
                        done=execution_state['completed_nodes'],
                        total=execution_state['total_nodes'],
                    ),
                    wf_idx=wf_idx,
                )
        return results

    def run():
        # The run thread starts here, not in a request handler — inherit the
        # language the UI asked for, or every line below would come out in the
        # server default.
        set_lang(execution_state.get('lang'))
        sys.stdout = _LogTee(sys.__stdout__)
        try:
            engine = WorkflowEngine(workflow, execution_state['executor'])
            errors = engine.validate()
            if errors:
                for e in errors:
                    add_log(t('wf.validation_error', err=e))
                execution_state['running'] = False
                return

            # Split into per-workflow connected components
            components = engine.find_workflows()
            components = engine.sort_workflows(components)
            sub_engines = [engine.extract_subworkflow(c) for c in components]

            wf_count = len(sub_engines)
            execution_state['total_nodes'] = sum(len(se.nodes) for se in sub_engines)
            add_log(t('wf.found', n=wf_count))

            if mode == 'serial' or wf_count <= 1:
                # ── Serial: one workflow at a time ──
                all_results = {}
                for wf_idx, se in enumerate(sub_engines):
                    if not execution_state['running']:
                        break
                    add_log(t('wf.starting', i=wf_idx + 1, n=wf_count))
                    results = _run_single_workflow(se, wf_idx)
                    all_results.update(results)
                # update(), not replace(): a branch that died halfway already
                # published its partial rows, and they must survive the merge.
                execution_state['results'].update(all_results)
                if execution_state['running']:
                    add_log(t('wf.completed'))
            else:
                # ── Parallel: one thread per workflow ──

                all_results = {}
                wf_lock = threading.Lock()

                def _run_workflow_wrapper(wf_engine, wf_idx):
                    # Pool threads do not inherit the starter's thread-local.
                    set_lang(execution_state.get('lang'))
                    try:
                        results = _run_single_workflow(wf_engine, wf_idx)
                        with wf_lock:
                            all_results.update(results)
                    except Exception:
                        logger.exception(t('wf.wf_exception', i=wf_idx))
                        add_log(t('wf.wf_failed', i=wf_idx), wf_idx=wf_idx)

                pool = ThreadPoolExecutor(max_workers=min(wf_count, max_workers))
                futures = [pool.submit(_run_workflow_wrapper, se, i) for i, se in enumerate(sub_engines)]
                # Wait for all to finish (respecting stop)
                for fut in futures:
                    if not execution_state['running']:
                        # Cancel remaining
                        for f in futures:
                            f.cancel()
                        break
                    with contextlib.suppress(Exception):
                        fut.result()
                pool.shutdown(wait=False, cancel_futures=True)

                if execution_state['running']:
                    with wf_lock:
                        # update() keeps partial rows published by branches that
                        # died (LLM abort) — never wipe finished work at the end.
                        execution_state['results'].update(all_results)
                    add_log(t('wf.all_completed'))

            if execution_state['running']:
                _record_execution_history(workflow, engine, execution_state['results'], workflow_name)

        except Exception:
            logger.exception(t('wf.exec_exception'))
            add_log(t('wf.exec_failed'))
        finally:
            execution_state['running'] = False
            # The tee exists to catch the analyzers' print() output *during* a
            # run; leaving it installed meant every later print — from any
            # request — also showed up in the console panel.
            if isinstance(sys.stdout, _LogTee):
                sys.stdout = sys.stdout._original

    execution_state['thread'] = threading.Thread(target=run, daemon=True)
    execution_state['thread'].start()

    return jsonify({'ok': True, 'message': 'Workflow started'})


# ─── Node execution helpers ────────────────────────────────────


def _execute_source_node(node: dict, headless: bool):
    params = node.get('params', {})
    platform = node.get('platform', params.get('platform', ''))
    keyword = params.get('keyword', '')
    target_count = _safe_int(params.get('target_count'), 50, minimum=1)
    start_time = params.get('start_time')
    end_time = params.get('end_time')

    crawler = get_crawler(platform, headless=headless, cookie_dir=Config.COOKIE_DIR)
    execution_state['active_crawlers'].add(crawler)
    try:
        if platform == 'wechat':
            # WeChat scrapes a list of article URLs, not a keyword.
            return crawler.search(urls=_split_urls(params.get('urls')))
        if platform == 'weibo' and (start_time or end_time):
            # Both bounds are required: the crawler raises a readable error
            # otherwise instead of silently searching something else.
            return crawler.search(keyword, start_time=start_time, end_time=end_time)
        return crawler.search(keyword, target_count=target_count)
    finally:
        crawler.close()
        execution_state['active_crawlers'].discard(crawler)


def _execute_upload_node(node: dict, headless: bool = True):
    """Upload node — the one place a file can enter a workflow.

    It publishes a dataset the user already picked in the node's settings
    (registered by /api/data/upload) as ordinary rows, so every downstream
    node sees a file exactly as it sees a crawl. That is why the visualize
    and tokenize nodes no longer carry their own upload UI: any node that
    needs data now connects upstream, and the upstream may be a crawler or
    a file.
    """
    params = node.get('params', {})
    dataset_id = params.get('dataset_id', '')
    if not dataset_id:
        raise ValueError(t('upload.no_file'))
    entry = _datasets.get(dataset_id)
    if entry is None:
        # Registered datasets live in memory only: a server restart (or an
        # eviction once 50 of them piled up) leaves the node pointing at
        # nothing. Say so instead of silently producing zero rows.
        raise ValueError(t('upload.stale'))
    df = entry['df']
    add_log(t('upload.loaded', name=entry.get('name') or dataset_id, n=len(df)))
    return _json_safe_records(df)


def _execute_process_node(node: dict, current_input: list, run_ctx: dict = None):
    params = node.get('params', {})
    op = node.get('operation', params.get('operation', ''))
    text_column = params.get('text_column', 'content')
    if not current_input:
        return []

    df = pd.DataFrame(current_input)

    if op == 'clean':
        topic = params.get('topic', '')
        cleaner = ContentCleaner()
        df = cleaner.clean_dataframe(df, text_column=text_column, topic=topic, ctx=run_ctx)
        return df.to_dict('records')

    mode = params.get('mode', 'llm')
    if op == 'emotion':
        analyzer = EmotionAnalyzer(mode=mode)
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'tendency':
        analyzer = TendencyAnalyzer(mode=mode)
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'keyword':
        method = params.get('method', 'tfidf')
        topk = _safe_int(params.get('topk'), 10, minimum=1)
        merge = params.get('merge', 'true') == 'true'
        extractor = KeywordExtractor()
        df = extractor.analyze_dataframe(df, text_column=text_column, method=method, topk=topk, merge=merge)
        return df.to_dict('records')

    if op == 'cluster':
        method = params.get('cluster_method', 'kmeans')
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
        recognizer = NamedEntityRecognizer()
        df = recognizer.analyze_dataframe(df, text_column=text_column)
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
        corr_method = params.get('corr_method', 'pearson')
        min_abs = _safe_float(params.get('min_abs'), 0.0)
        analyzer_corr = CorrelationAnalyzer()
        df = analyzer_corr.analyze_dataframe(df, columns=columns, method=corr_method, min_abs=min_abs)
        return df.to_dict('records')

    # An unknown operation must not look like "this node simply has no data":
    # the run continues, but the console says why the table is empty.
    add_log(t('wf.unknown_process_op', op=op or '(empty)'))
    return []


def _execute_output_node(node: dict, current_input: list):
    """Save node: exports the upstream data in the format the user picked,
    then passes the data through for downstream nodes.

    'save_csv' is kept as a back-compat alias for older saved workflows;
    both routes go through the same DataExporter used by the standalone
    /api/export/save endpoint, so behaviour is identical whether the save
    happens inside a workflow or on its own.
    """
    params = node.get('params', {})
    op = node.get('operation', params.get('operation', ''))
    if not current_input:
        return []

    df = pd.DataFrame(current_input)

    if op in ('save', 'save_csv'):
        fmt = params.get('format', 'csv' if op == 'save_csv' else None)
        filename = params.get('filename', 'export.csv')
        fmt = fmt or DataExporter.infer_format(filename)
        # Sanitize first, then (re)apply the extension: the other way round a
        # name like ".." lost its extension and landed as a hidden file.
        filename = DataExporter.normalize_filename(sanitize_filename(filename), fmt)
        filepath = os.path.join(Config.EXPORT_DIR, filename)
        try:
            result = DataExporter.save(df, filepath, fmt=fmt, text_column=params.get('text_column'))
        except UnsupportedFormatError as e:
            add_log(t('wf.save_failed', err=e))
            return {'error': str(e)}
        add_log(t('wf.data_saved', path=result['path'], fmt=result['format']))

    return current_input


def _safe_int(value, default: int = 0, minimum: int = None, maximum: int = None) -> int:
    """int() for numbers typed into the UI.

    Every settings field arrives as a string, so "abc" used to raise a bare
    ValueError from inside a request handler (HTTP 500) or from a node (opaque
    node failure). A malformed value now falls back to the default.
    """
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value):
    """Like _safe_int, but blank or unparseable means "not configured" (None)."""
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _optional_float(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _split_columns(value) -> list:
    if isinstance(value, list):
        return [str(c).strip() for c in value if str(c).strip()]
    return [c.strip() for c in str(value or '').split(',') if c.strip()]


def _split_urls(value) -> list:
    """WeChat article URLs: a real list, or one per line in a textarea."""
    raw = value if isinstance(value, (list, tuple)) else str(value or '').replace(',', '\n').split('\n')
    return [str(u).strip() for u in raw if str(u).strip()]


def _normalize_analysis_params(op: str, params: dict) -> dict:
    """The Settings panel stores everything as flat strings (e.g. a
    comma-separated 'columns' field). Translate that into the exact kwargs
    each DataAnalysisService method expects."""
    if op in ('drop_null', 'strip_whitespace', 'select_columns'):
        return {'columns': _split_columns(params.get('columns'))}
    if op == 'fill_null':
        return {'columns': _split_columns(params.get('columns')), 'value': params.get('value')}
    if op == 'drop_duplicates':
        return {'columns': _split_columns(params.get('columns')) or None}
    if op == 'filter_rows':
        return {'column': params.get('column', ''), 'op': params.get('op', 'eq'), 'value': params.get('value')}
    if op == 'rename_columns':
        mapping = {}
        if params.get('rename_from'):
            mapping[params['rename_from']] = params.get('rename_to', '')
        return {'mapping': mapping}
    if op == 'convert_type':
        return {'column': params.get('column', ''), 'dtype': params.get('dtype', 'str')}
    if op == 'sort_rows':
        return {'column': params.get('column', ''), 'ascending': params.get('ascending', 'true') == 'true'}
    if op == 'sample_rows':
        result = {'n': _optional_int(params.get('n')), 'frac': _optional_float(params.get('frac'))}
        seed = _optional_int(params.get('seed'))
        if seed is not None:
            result['seed'] = seed
        return result
    if op == 'groupby_agg':
        return {
            'group_col': params.get('group_col', ''),
            'agg_col': params.get('agg_col', ''),
            'agg_func': params.get('agg_func', 'sum'),
        }
    if op == 'join_tables':
        return {
            'how': params.get('join_how', 'left'),
            'left_on': params.get('left_on', ''),
            'right_on': params.get('right_on', ''),
        }
    if op == 'column_calc':
        return {
            'new_col': params.get('new_col', ''),
            'expr': params.get('expr', ''),
        }
    if op == 'bin_column':
        return {
            'column': params.get('column', ''),
            'new_col': params.get('bin_new_col', ''),
        }
    return {}


def _execute_analysis_node(node: dict, current_input: list, upstream: list = None):
    """Analysis node: runs a deterministic data-cleaning pipeline (null
    handling, de-duplication, filtering, renaming, ...) via
    DataAnalysisService. Supports either a single configured operation
    (as built by the Settings panel) or a full multi-step pipeline stored
    under params['steps'] for advanced use / API callers.

    A ``join_tables`` step merges with the table of the node's *second*
    incoming connection. The old design asked the user to paste an opaque
    12-character dataset id instead — an id produced by the Upload node and
    shown nowhere, so a join silently joined nothing.
    """
    params = node.get('params', {})
    if not current_input:
        return []

    df = pd.DataFrame(current_input)

    steps = params.get('steps')
    if not steps:
        op = node.get('operation', params.get('operation', ''))
        steps = [{'op': op, 'params': _normalize_analysis_params(op, params)}] if op else []

    # upstream[0] is the left table (already current_input); anything after it is
    # a candidate right table.
    right_tables = [res for _pid, res in (upstream or [])[1:] if isinstance(res, list) and res]

    for step in steps:
        if step.get('op') == 'join_tables':
            if not right_tables:
                raise UnknownOperationError(t('wf.join_no_right_table'))
            step['params']['other_df'] = pd.DataFrame(right_tables[0])

    try:
        cleaned, report = DataAnalysisService.run_pipeline(df, steps)
    except UnknownOperationError as e:
        add_log(t('wf.analysis_failed', err=e))
        return []

    for step in report:
        add_log(
            t(
                'wf.analysis_step',
                op=step['op'],
                before=step['rows_before'],
                after=step['rows_after'],
                removed=step['rows_removed'],
            )
        )
    return cleaned.to_dict('records')


def _execute_tokenize_node(node: dict, current_input: list):
    """Tokenize node: segments a free-text column with jieba and outputs
    word-frequency pairs for downstream save or word-cloud nodes.
    Data always comes from the upstream connection — a file reaches it by
    sitting behind an Upload node, not by being configured here."""
    params = node.get('params', {})
    column = params.get('text_column', '')
    output_mode = params.get('output_mode', 'word_freq')
    if not column:
        add_log(t('wf.tokenize_no_column'))
        return []
    if not current_input:
        add_log(t('wf.tokenize_no_input'))
        return []
    df = pd.DataFrame(current_input)
    result_df = _tokenize_dataframe(df, params)
    if result_df is None:
        add_log(t('wf.tokenize_no_col', col=column, cols=list(df.columns)))
        return []
    add_log(t('wf.tokenize_done', mode=output_mode, col=column, n=len(result_df)))
    return result_df.to_dict('records')


def _execute_visualize_node(node: dict, current_input: list):
    """Visualize node: builds a chart from the upstream data and returns a
    chart spec dict the frontend renders — either an ECharts option or a
    base64 image — so this node works identically to /api/visualize/render.

    It has no data source of its own on purpose: files enter a workflow
    through the Upload node, so a chart is always "whatever upstream
    produced", crawl or file alike.
    """
    params = node.get('params', {})
    chart_type = params.get('chart_type', 'bar')
    engine = params.get('engine', 'echarts')
    x_field = params.get('x_field')
    y_field = params.get('y_field')
    value_field = params.get('value_field')
    agg = params.get('agg', 'sum')
    title = params.get('title', '')
    tokenize = bool(params.get('tokenize'))
    wordcloud_style = params.get('wordcloud_style')

    if not current_input:
        add_log(t('wf.visualize_no_input'))
        return {'error': t('wf.visualize_no_input')}
    df = pd.DataFrame(current_input)

    try:
        if engine == 'matplotlib':
            image = VisualizationService.render_image(
                df, chart_type, x=x_field, y=y_field, value_field=value_field, agg=agg, title=title
            )
            spec = {'engine': 'matplotlib', 'image': image}
        else:
            kw = {'tokenize': tokenize}
            if wordcloud_style:
                kw['wordcloud_style'] = wordcloud_style
            option = VisualizationService.to_echarts_option(
                df,
                chart_type,
                x=x_field,
                y=y_field,
                value_field=value_field,
                agg=agg,
                title=title,
                **kw,
            )
            spec = {'engine': 'echarts', 'option': option}
    except ChartConfigError as e:
        add_log(t('wf.visualize_failed', err=e))
        return {'error': str(e)}

    add_log(t('wf.visualize_done', chart=chart_type, engine=engine, n=len(df)))
    return spec


def _execute_node(node: dict, headless: bool, current_input: list, run_ctx: dict = None, upstream: list = None):
    """Run one node. ``upstream`` is [(parent_id, result), …] in connection
    order — only the analysis node needs more than the first entry (a join uses
    the second one as its right-hand table)."""
    ntype = node.get('type')
    if ntype == 'source':
        return _execute_source_node(node, headless)
    if ntype == 'upload':
        return _execute_upload_node(node)
    if ntype == 'process':
        op = node.get('operation') or node.get('params', {}).get('operation', '')
        return _execute_process_node(node, current_input, run_ctx=run_ctx or _llm_run_ctx(node, op))
    if ntype == 'analysis':
        return _execute_analysis_node(node, current_input, upstream=upstream)
    if ntype == 'visualize':
        return _execute_visualize_node(node, current_input)
    if ntype == 'tokenize':
        return _execute_tokenize_node(node, current_input)
    if ntype == 'output':
        return _execute_output_node(node, current_input)
    return []


def _kill_orphaned_chromedrivers():
    """Force-kill any chromedriver.exe processes still alive. Safe because
    chromedriver is only used by Selenium in this app."""
    with contextlib.suppress(Exception):
        subprocess.run(
            ['taskkill', '/F', '/IM', 'chromedriver.exe'],
            capture_output=True,
            timeout=5,
            check=False,
        )


# ─── Stop / Status API ─────────────────────────────────────────


@app.route('/api/workflow/stop', methods=['POST'])
def stop_workflow():
    if execution_state['executor']:
        execution_state['executor'].stop()
    # Tell any row-by-row LLM loop to bail out at the next row boundary —
    # finished rows are already checkpointed and stay in results.
    execution_state['cancel_event'].set()
    execution_state['running'] = False
    crawlers = list(execution_state['active_crawlers'])
    execution_state['active_crawlers'].clear()
    for c in crawlers:
        with contextlib.suppress(OSError):
            c.close()
    # Clear the console but NOT the results: a stopped run keeps everything it
    # already produced (rows, tables, exports) so nothing paid for is lost.
    execution_state['logs'] = []
    execution_state['_log_total'] = 0
    execution_state['_wf_logs'] = {}
    execution_state['_wf_log_total'] = {}
    execution_state['total_nodes'] = 0
    execution_state['completed_nodes'] = 0
    execution_state.pop('current_input', None)
    execution_state['executor'] = None
    _kill_orphaned_chromedrivers()
    return jsonify({'ok': True})


@app.route('/api/workflow/status', methods=['GET'])
def workflow_status():
    # Build per-workflow progress lists from _wf_logs keys
    wf_list = []
    mode = execution_state.get('_mode', 'serial')
    wf_keys = sorted(execution_state['_wf_logs'].keys())
    for wk in wf_keys:
        wf_logs = execution_state['_wf_logs'][wk]
        wf_list.append(
            {
                'id': wk,
                'logs': wf_logs[-200:],
                # How many lines exist in total, so the browser can compute the
                # delta even after the tail truncation above.
                'total': execution_state['_wf_log_total'].get(wk, len(wf_logs)),
            }
        )

    chart_results = {}
    if not execution_state['running']:
        for nid, data in execution_state['results'].items():
            if isinstance(data, dict) and 'engine' in data:
                chart_results[nid] = data

    return jsonify(
        {
            'running': execution_state['running'],
            'logs': execution_state['logs'][-200:],
            'log_total': execution_state['_log_total'],
            'workflows': wf_list,
            'mode': mode,
            'results': list(execution_state['results'].keys()),
            'total_nodes': execution_state['total_nodes'],
            'completed_nodes': execution_state['completed_nodes'],
            'chart_results': chart_results,
        }
    )


@app.route('/api/workflow/processes', methods=['GET'])
def workflow_processes():
    """Return info about active threads/processes for the monitoring panel."""
    threads = []
    for thread in threading.enumerate():
        threads.append(
            {
                'name': thread.name,
                'daemon': thread.daemon,
                'alive': thread.is_alive(),
                'ident': thread.ident,
            }
        )

    executor_alive = (
        execution_state['executor'] is not None and getattr(execution_state['executor'], '_pool', None) is not None
    )
    return jsonify(
        {
            'running': execution_state['running'],
            'threads': threads,
            'executor_pool_alive': executor_alive,
            'active_crawlers': len(execution_state['active_crawlers']),
        }
    )


@app.route('/api/workflow/processes/kill', methods=['POST'])
def kill_process():
    """Force-kill a thread by its ident. MainThread and 'run' thread are protected."""
    data = request.get_json()
    ident = data.get('ident')
    if ident is None:
        return jsonify({'ok': False, 'error': 'Missing thread ident'}), 400

    target = None
    for thread in threading.enumerate():
        if thread.ident == ident:
            target = thread
            break

    if target is None:
        return jsonify({'ok': False, 'error': 'Thread not found'}), 404

    if target.name in ('MainThread', 'run'):
        return jsonify({'ok': False, 'error': f'Cannot kill protected thread: {target.name}'}), 403

    if not target.is_alive():
        return jsonify({'ok': False, 'error': 'Thread is not alive'}), 400

    try:
        ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(ident), ctypes.py_object(SystemExit))
        if ret == 0:
            return jsonify({'ok': False, 'error': 'Invalid thread ID'}), 400
        if ret > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(ident), None)
            return jsonify({'ok': False, 'error': 'Failed to kill thread'}), 500
        return jsonify({'ok': True, 'message': f'Thread "{target.name}" terminated'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ─── Data API (standalone upload / analysis / visualization) ───
#
# These endpoints let Analysis and Visualize work as fully independent
# tools — e.g. upload any CSV/JSON and chart it — without building a
# crawler workflow at all. The same DataAnalysisService/VisualizationService/
# DataExporter classes back both this API and the workflow nodes above, so
# behaviour is identical either way.


@app.route('/api/data/upload', methods=['POST'])
def upload_dataset():
    """Upload a CSV, JSON, or TXT file and register it for analysis/visualization."""
    file = request.files.get('file')
    if not file:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='missing file')}), 400
    filename = file.filename or 'upload'
    name_lower = filename.lower()
    try:
        if name_lower.endswith('.json'):
            df = pd.DataFrame(json.load(file.stream))
        elif name_lower.endswith('.txt'):
            text = file.stream.read().decode('utf-8', errors='replace')
            df = pd.DataFrame({'content': [text]})
        else:
            df = pd.read_csv(file.stream)
    except (ValueError, OSError, UnicodeDecodeError, pd.errors.ParserError) as e:
        # A corrupt or mis-encoded file is a user-input problem, not a crash.
        return jsonify({'ok': False, 'error': t('api.parseFailed', err=e)}), 400

    is_txt = name_lower.endswith('.txt')
    dataset_id = _register_dataset(df, name=filename)
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            # The Upload node labels itself with this name, so it must travel
            # back with the id — otherwise a successful upload still reads
            # "no file uploaded yet".
            'name': filename,
            'columns': list(df.columns),
            'row_count': len(df),
            'is_txt': is_txt,
            'preview': _json_safe_records(df, 10),
        }
    )


@app.route('/api/data/paste', methods=['POST'])
def paste_dataset():
    """Register hand-typed/pasted JSON records (array of objects) as a dataset."""
    data = request.get_json(silent=True) or {}
    records = data.get('data')
    if not isinstance(records, list):
        return jsonify({'ok': False, 'error': t('api.badRequest', what='data must be a list of records')}), 400
    df = pd.DataFrame(records)
    dataset_id = _register_dataset(df, name=data.get('name', 'pasted'))
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            'name': data.get('name', 'pasted'),
            'columns': list(df.columns),
            'row_count': len(df),
            'preview': _json_safe_records(df, 10),
        }
    )


@app.route('/api/data/inspect', methods=['POST'])
def inspect_dataset():
    """Return null counts / dtypes / duplicate counts for a dataset."""
    data = request.get_json(silent=True) or {}
    try:
        df = _resolve_dataframe(data)
    except KeyError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'report': DataAnalysisService.inspect(df)})


@app.route('/api/data/preview', methods=['POST'])
def preview_dataset():
    """Paginated tabular preview of any dataset (uploaded, pasted, a
    workflow node's result, or inline data) — backs the generic Data
    Preview panel so users can inspect real rows instead of only JSON/charts."""
    data = request.get_json(silent=True) or {}
    try:
        df = _resolve_dataframe(data)
    except KeyError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    limit = _safe_int(data.get('limit'), 50, minimum=1, maximum=500)
    offset = _safe_int(data.get('offset'), 0, minimum=0)
    total = len(df)
    page = df.iloc[offset : offset + limit]
    return jsonify(
        {
            'ok': True,
            'columns': list(df.columns),
            'rows': _json_safe_records(page),
            'total_rows': total,
            'offset': offset,
            'limit': limit,
        }
    )


@app.route('/api/analysis/run', methods=['POST'])
def run_analysis():
    """Run a cleaning pipeline against a dataset (uploaded, pasted, or a
    workflow node's result) without needing to execute a full workflow."""
    data = request.get_json(silent=True) or {}
    try:
        df = _resolve_dataframe(data)
    except KeyError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    steps = data.get('steps', [])
    try:
        cleaned, report = DataAnalysisService.run_pipeline(df, steps)
    except UnknownOperationError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    dataset_id = _register_dataset(cleaned, name='cleaned')
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            'report': report,
            'row_count': len(cleaned),
            'preview': _json_safe_records(cleaned, 10),
        }
    )


@app.route('/api/analysis/train', methods=['POST'])
def train_ml_model():
    """Train a traditional ML classifier (emotion or tendency) from existing
    LLM-labeled data. Uses the text and label columns specified to fit a
    TF-IDF + LogisticRegression pipeline, then saves the model to disk so
    subsequent runs can use ``mode='ml'`` for fast batch inference."""
    data = request.get_json(silent=True) or {}
    try:
        df = _resolve_dataframe(data)
    except KeyError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    model_type = data.get('model_type', 'emotion')
    text_column = data.get('text_column', '正文')
    label_column = data.get('label_column', 'emotion')

    if text_column not in df.columns:
        return jsonify({'ok': False, 'error': t('api.columnMissing', column=text_column)}), 400
    if label_column not in df.columns:
        return jsonify({'ok': False, 'error': t('api.columnMissing', column=label_column)}), 400

    texts, labels = build_training_data(df, text_column, label_column)
    if len(texts) < 10:
        return jsonify({'ok': False, 'error': t('api.needLabeledRows', n=len(texts))}), 400

    classifier = get_classifier(model_type)
    try:
        classifier.fit(texts, labels)
    except ValueError as e:
        # One distinct label (or no usable rows) is a data problem the user can
        # fix — it used to escape as an HTTP 500 from inside sklearn.
        return jsonify({'ok': False, 'error': str(e)}), 400

    unique_labels = sorted(set(labels))
    return jsonify(
        {
            'ok': True,
            'model_type': model_type,
            'trained_on': len(texts),
            'labels': unique_labels,
            'label_count': len(unique_labels),
        }
    )


@app.route('/api/visualize/render', methods=['POST'])
def render_visualization():
    """Render a chart from any registered dataset / workflow result / inline
    data. Works for arbitrary tabular data, not just crawler output."""
    data = request.get_json(silent=True) or {}
    try:
        df = _resolve_dataframe(data)
    except KeyError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    chart_type = data.get('chart_type', 'bar')
    engine = data.get('engine', 'echarts')
    x_field = data.get('x_field')
    y_field = data.get('y_field')
    value_field = data.get('value_field')
    agg = data.get('agg', 'sum')
    title = data.get('title', '')
    tokenize = bool(data.get('tokenize'))
    wordcloud_style = data.get('wordcloud_style')

    try:
        if engine == 'matplotlib':
            image = VisualizationService.render_image(
                df, chart_type, x=x_field, y=y_field, value_field=value_field, agg=agg, title=title
            )
            return jsonify({'ok': True, 'engine': 'matplotlib', 'image': image})
        kw = {'tokenize': tokenize}
        if wordcloud_style:
            kw['wordcloud_style'] = wordcloud_style
        option = VisualizationService.to_echarts_option(
            df,
            chart_type,
            x=x_field,
            y=y_field,
            value_field=value_field,
            agg=agg,
            title=title,
            **kw,
        )
        return jsonify({'ok': True, 'engine': 'echarts', 'option': option})
    except ChartConfigError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except (ValueError, KeyError, TypeError) as e:
        # e.g. matplotlib refusing a pie chart of negative values: report it as
        # a bad request instead of letting Flask return an HTML 500 (which the
        # caller cannot even json.parse()).
        logger.warning(t('misc.visualize_failed', err=e))
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/export/save', methods=['POST'])
def export_dataset():
    """Save any dataset (uploaded, pasted, cleaned, or a workflow result)
    to disk in the requested format — independent of a workflow's Save node."""
    data = request.get_json(silent=True) or {}
    try:
        df = _resolve_dataframe(data)
    except KeyError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

    filename = data.get('filename', 'export.csv')
    fmt = data.get('format') or DataExporter.infer_format(filename)
    filename = DataExporter.normalize_filename(sanitize_filename(filename), fmt)
    filepath = os.path.join(Config.EXPORT_DIR, filename)
    try:
        result = DataExporter.save(df, filepath, fmt=fmt, text_column=data.get('text_column'))
    except UnsupportedFormatError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except OSError as e:
        logger.exception(t('misc.export_failed'))
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, **result})


# ─── Stats API ─────────────────────────────────────────────────


@app.route('/api/stats/emotion', methods=['GET'])
def emotion_stats():
    all_data = []
    for _nid, data in execution_state['results'].items():
        if isinstance(data, list):
            for item in data:
                if 'emotion' in item:
                    all_data.append(item)
    stats_data = StatsService.emotion_distribution(all_data)
    return jsonify({'ok': True, 'stats': stats_data})


@app.route('/api/stats/tendency', methods=['GET'])
def tendency_stats():
    all_data = []
    for _nid, data in execution_state['results'].items():
        if isinstance(data, list):
            for item in data:
                if 'tendency' in item:
                    all_data.append(item)
    stats_data = StatsService.tendency_distribution(all_data)
    return jsonify({'ok': True, 'stats': stats_data})


@app.route('/api/stats/summary', methods=['GET'])
def platform_summary():
    summary = {}
    for nid, data in execution_state['results'].items():
        if isinstance(data, list) and data:
            summary[nid] = {'count': len(data), 'sample_keys': list(data[0].keys()) if data else []}
    return jsonify({'ok': True, 'summary': summary})


# ─── Cookie API ────────────────────────────────────────────────


@app.route('/api/cookies/status', methods=['GET'])
def cookie_status():
    platforms = ['zhihu', 'weibo', 'xiaohongshu', 'wechat']
    status = {p: cookie_manager.exists(p) for p in platforms}
    return jsonify({'ok': True, 'cookies': status})


@app.route('/api/cookies/save', methods=['POST'])
def save_cookies():
    data = request.get_json(silent=True) or {}
    platform = data.get('platform', '')
    cookies = data.get('cookies', [])
    if not platform:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_supported(platform):
        # The platform becomes part of a filename — refuse anything else.
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if not cookies:
        return jsonify({'ok': False, 'error': t('api.cookiesRequired')}), 400
    try:
        cookie_manager.save(platform, cookies)
        return jsonify({'ok': True, 'message': t('cookie.saved', platform=platform)})
    except (OSError, ValueError) as e:
        logger.exception(t('misc.cookie_save_failed'))
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/cookies/generate', methods=['POST'])
def generate_cookies():
    data = request.get_json(silent=True) or {}
    platform = data.get('platform', '')
    if not platform:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    # Bounded on purpose: this handler sleeps for the whole login wait, in a
    # request thread. An unbounded value would hold that thread hostage.
    wait_seconds = _safe_int(data.get('wait_seconds'), 120, minimum=10, maximum=600)

    crawler = None
    try:
        crawler = get_crawler(platform, headless=False, cookie_dir=Config.COOKIE_DIR)
        url = crawler.login_url
        if not url:
            return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
        crawler.driver.get(url)
        add_log(t('wf.browser_opened', platform=platform, n=wait_seconds))
        time.sleep(wait_seconds)
        cookies = crawler.driver.get_cookies()
        cookie_manager.save(platform, cookies)
        add_log(t('wf.cookies_generated', platform=platform, n=len(cookies)))
        return jsonify(
            {
                'ok': True,
                'message': t('wf.cookies_generated', platform=platform, n=len(cookies)),
                'count': len(cookies),
            }
        )
    except Exception as e:
        # Selenium failures (no browser, no driver, network) are not OSErrors;
        # without this they escaped as an HTML 500 the panel could not read.
        logger.exception(t('misc.cookie_gen_failed'))
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if crawler is not None:
            crawler.close()


# ─── Config API ────────────────────────────────────────────────


@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(
        {
            'ollama_model': Config.OLLAMA_MODEL,
            'default_headless': Config.DEFAULT_HEADLESS,
            'max_workers': Config.DEFAULT_MAX_WORKERS,
        }
    )


# ─── Runtime settings API ──────────────────────────────────────
#
# Machine-local values that used to be hardcoded (chromedriver path, browser
# window, timeouts, Ollama address). Persisted to data/settings.json by the
# settings store; crawlers and LLM calls read them per run, so a save applies
# on the next execution without restarting the server.


@app.route('/api/settings', methods=['GET'])
def get_runtime_settings():
    return jsonify({'ok': True, 'settings': all_settings()})


@app.route('/api/settings', methods=['POST'])
def set_runtime_settings():
    data = request.get_json() or {}
    patch = data.get('settings') if isinstance(data.get('settings'), dict) else data
    values, warnings = save_settings(patch or {})
    return jsonify({'ok': True, 'settings': values, 'warnings': warnings})


# ─── AI (LLM) API ──────────────────────────────────────────────
#
# The settings panel picks a transport: the local Ollama daemon or OpenRouter
# (aimed at :free models). The API key never touches disk here — the browser
# keeps it in localStorage and posts it with each request.


@app.route('/api/llm/models', methods=['GET'])
def llm_models():
    """Current OpenRouter catalog filtered to zero-cost models, so the
    dropdown never goes stale the way a hardcoded list would."""
    try:
        models = list_free_models(timeout=15)
        return jsonify({'ok': True, 'models': models})
    except (requests.RequestException, ValueError, KeyError) as e:
        # Offline / catalog changed shape: the panel just shows no models.
        logger.warning(t('api.llmModelsFailed', err=e))
        return jsonify({'ok': False, 'error': t('api.llmModelsFailed', err=e), 'models': []}), 502


@app.route('/api/llm/ollama/models', methods=['GET'])
def llm_ollama_models():
    """Tags the local daemon has pulled, so the AI panel can offer a picker
    instead of demanding a hand-typed model name.

    Kept apart from /api/llm/models (the OpenRouter catalog) on purpose: the
    two providers no longer share a model setting, so they must not share a
    dropdown either.
    """
    host = str(get_setting('ollama_host') or '')
    shown = host or 'http://localhost:11434'
    try:
        models = list_ollama_models(host, timeout=8)
        return jsonify({'ok': True, 'models': models, 'host': shown})
    except (requests.RequestException, ValueError) as e:
        # Daemon not running / wrong address / something else answering on the
        # port: the panel shows the reason *and* the address it tried, which is
        # the whole point of the button.
        logger.warning(t('api.ollamaModelsFailed', host=shown, err=e))
        return jsonify({'ok': False, 'error': t('api.ollamaModelsFailed', host=shown, err=e), 'models': []}), 502


@app.route('/api/llm/test', methods=['POST'])
def llm_test():
    """Tiny round-trip so the user can validate provider/model/key before
    committing to a long row-by-row run."""
    data = request.get_json() or {}
    provider = data.get('provider') or 'ollama'
    client = LLMClient(
        provider=provider,
        model=data.get('model') or '',
        api_key=data.get('api_key') or '',
        max_tokens=16,
        max_chars=0,
        timeout=60 if provider == 'ollama' else 45,
        host=str(get_setting('ollama_host') or '') if provider == 'ollama' else '',
    )
    started = time.time()
    try:
        reply = client.chat('Reply with exactly: OK', max_retries=1)
        latency = int((time.time() - started) * 1000)
        return jsonify(
            {
                'ok': True,
                'latency_ms': latency,
                'reply': reply.strip()[:80],
                'provider': client.label,
                'model': client.model,
                # Which daemon answered — with the local transport the address
                # is half of "why did this fail", so the panel can show it.
                'host': client.host if provider == 'ollama' else '',
            }
        )
    except LLMError as e:
        return jsonify({'ok': False, 'error': str(e), 'kind': e.kind})
    except Exception as e:
        # The test endpoint reports the failure; it never raises.
        return jsonify({'ok': False, 'error': str(e), 'kind': 'error'})


# ─── Clear Dataset Cache API ─────────────────────────────────────


@app.route('/api/data/clear', methods=['POST'])
def clear_datasets():
    _datasets.clear()
    return jsonify({'ok': True, 'message': 'All datasets cleared'})


# ─── Chart Studio API (embedded ZENVIZ workbench) ─────────────────
#
# The studio runs in a same-origin iframe and authors charts from a workflow
# dataset. These two endpoints close the loop: hand it real rows, and take the
# finished chart back as a file next to the other workflow exports.

STUDIO_MAX_ROWS = 5000
# A chart PNG is a few hundred KB; 20 MB is a generous ceiling that still keeps
# a malformed payload from ballooning the process.
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _first_tabular_result():
    """Return (node_id, DataFrame) for the first node that produced a tabular
    result, or (None, None). Used as a fallback so the Chart Studio still gets
    data when the user picked a node that has not produced output yet."""
    for node_id, result in execution_state['results'].items():
        if isinstance(result, list) and result:
            return node_id, pd.DataFrame(result)
    return None, None


def _merge_unique_names(names: list, used: dict) -> list:
    """Make a frame's column names unique across everything already merged.

    A repeat gets the source's ordinal appended (`freq` → `freq_2`), and that
    again (`freq_2_3`) if even that is taken — the studio binds columns by name,
    so two columns called `freq` would make the second one unreachable.
    """
    out = []
    for raw in names:
        name = str(raw)
        if name not in used:
            used[name] = 1
            out.append(name)
            continue
        # `used[name]` doubles as the ordinal to try next for that name.
        used[name] += 1
        candidate = f'{name}_{used[name]}'
        while candidate in used:
            used[name] += 1
            candidate = f'{name}_{used[name]}'
        used[candidate] = 1
        out.append(candidate)
    return out


def _merge_frames(frames: list, mode: str) -> tuple[pd.DataFrame, str]:
    """Combine several nodes' tables into one. → (DataFrame, mode actually used)

    Both modes place whole tables next to each other, the way you would paste
    them into one sheet — never interleaved. Nothing is matched up by value, so
    the result is always a full rectangle with no half-empty rows:

    rows — put the other table *below*: its rows are appended after the first
           table's, re-using the first table's column names for the columns they
           line up with. Nothing is dropped and nothing is left blank.
    side — put the other table *to the right*: its columns are appended after
           the first table's, row 1 next to row 1. A shorter table just stops
           early.
    """
    if len(frames) < 2:
        return frames[0], 'rows'
    if mode in ('side', 'columns', 'right'):
        parts = []
        used: dict = {}
        for frame in frames:
            part = frame.reset_index(drop=True).copy()
            part.columns = _merge_unique_names(list(part.columns), used)
            parts.append(part)
        return pd.concat(parts, axis=1), 'side'

    # Appending rows. Identical column sets stack by name (the ordinary case:
    # two word-frequency tables joined end to end).
    base = [str(c) for c in frames[0].columns]
    if all([str(c) for c in f.columns] == base for f in frames[1:]):
        return pd.concat(frames, ignore_index=True, sort=False), 'rows'

    # Different schemas: line the tables up by *position* instead, so the second
    # table lands under the first rather than on the empty cells beside it.
    width = max(len(f.columns) for f in frames)
    header = list(base)
    for frame in frames[1:]:
        for idx, col in enumerate(frame.columns):
            if idx >= len(header):
                header.append(str(col))
    header = header[:width]

    rows = []
    for frame in frames:
        for record in frame.itertuples(index=False, name=None):
            row = list(record)
            rows.append(row + [None] * (width - len(row)) if len(row) < width else row)
    return pd.DataFrame(rows, columns=header), 'rows'


def _studio_dataset_merged(data: dict, sources: list):
    """Load several nodes at once and hand the studio a single merged table.

    A source that cannot be served is *skipped*, not fatal: the picker already
    greys those out, so this only happens when the probe went stale (a server
    restart wipes the in-memory results). Every source's fate is reported back so
    the bar can say "2 of 3 loaded" rather than quietly pretending.
    """
    limit = _safe_int(data.get('limit'), STUDIO_MAX_ROWS, minimum=1, maximum=STUDIO_MAX_ROWS)
    mode = str(data.get('merge') or 'concat').lower()
    frames = []
    report = []
    for src in sources[:STUDIO_MAX_SOURCES]:
        src = src if isinstance(src, dict) else {}
        node_id = str(src.get('node_id') or '')
        try:
            df = _resolve_dataframe(src)
            if df is None or df.empty:
                report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_EMPTY})
                continue
            frames.append(df)
            report.append(
                {
                    'node_id': node_id,
                    'ok': True,
                    'rows': len(df),
                    'columns': len(df.columns),
                    'reason': '',
                }
            )
        except KeyError:
            report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_NO_RESULT})
        except Exception:
            logger.exception(t('misc.studio_source_failed'))
            report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_ERROR})

    if not frames:
        return jsonify(
            {
                'ok': False,
                'code': 'no_result',
                'error': t('api.noSourceTable'),
                'sources': report,
            }
        )

    merged, used_mode = _merge_frames(frames, mode)
    total = len(merged)
    page = merged.iloc[:limit]
    return jsonify(
        {
            'ok': True,
            'columns': [str(c) for c in merged.columns],
            'rows': _json_safe_records(page),
            'total_rows': total,
            'truncated': total > limit,
            'merged': len(frames) > 1,
            'merge_mode': used_mode,
            'sources': report,
            'fallback': None,
        }
    )


@app.route('/api/studio/dataset', methods=['POST'])
def studio_dataset():
    """Full tabular dump of a node's result / uploaded dataset.

    /api/data/preview is deliberately paginated for on-screen browsing; the
    studio needs the whole table in one shot so it can bind columns and series
    itself, so this returns everything up to STUDIO_MAX_ROWS.

    Two request shapes:

      {"node_id": …}                       one node — what the picker sends when
                                           exactly one row is selected
      {"sources": [{…}, {…}], "merge": …}  several nodes, merged into one table

    Node results only exist after a workflow run, and they live in memory, so a
    freshly (re)started server has none. For a single node we fall back to
    whichever node does have data and say so via `fallback`; a merged load never
    does that silently — it reports each source instead.
    """
    data = request.get_json(silent=True) or {}
    sources = data.get('sources')
    if isinstance(sources, list) and sources:
        if len(sources) > 1:
            return _studio_dataset_merged(data, sources)
        src = sources[0] if isinstance(sources[0], dict) else {}
        limit = data.get('limit', STUDIO_MAX_ROWS)
        data = dict(src)
        data.setdefault('limit', limit)

    fallback_note = None
    try:
        df = _resolve_dataframe(data)
    except KeyError as e:
        fb_id, fb_df = _first_tabular_result()
        if fb_df is None or fb_df.empty:
            return jsonify({'ok': False, 'code': 'no_result', 'error': str(e)})
        df = fb_df
        fallback_note = {'requested': data.get('node_id'), 'used': fb_id}

    limit = _safe_int(data.get('limit'), STUDIO_MAX_ROWS, minimum=1, maximum=STUDIO_MAX_ROWS)
    total = len(df)
    page = df.iloc[:limit]
    return jsonify(
        {
            'ok': True,
            'columns': [str(c) for c in df.columns],
            'rows': _json_safe_records(page),
            'total_rows': total,
            'truncated': total > limit,
            'fallback': fallback_note,
        }
    )


# Why a candidate cannot be served. Stable short codes so the browser can
# localise them; the picker shows a short form inline and the long form as a
# tooltip / toast.
SRC_NO_UPSTREAM = 'no_upstream'
SRC_NO_RESULT = 'no_result'
SRC_STALE_DATASET = 'stale_dataset'
SRC_EMPTY = 'empty'
SRC_ERROR = 'error'
STUDIO_MAX_CANDIDATES = 500
# Column names travel with each probe so the picker can tell the user what is
# inside a node before they combine it; only the first few are ever shown.
PROBE_MAX_COLUMNS = 24
# How many nodes one merged load may combine.
STUDIO_MAX_SOURCES = 50


def _column_names(df) -> list:
    """Column names for the picker's tooltip. Capped: the picker shows a handful
    and the probe runs for every node on the canvas."""
    try:
        return [str(c) for c in list(df.columns)[:PROBE_MAX_COLUMNS]]
    except Exception:
        return []


def _probe_source(payload: dict | None) -> tuple[bool, int, str, list]:
    """Can this payload produce a table right now? → (available, rows, reason,
    columns).

    Deliberately cheap. The picker probes every node on the canvas in one go, so
    for the two common cases — an uploaded dataset and a node's stored run
    result — the row count and column names are read straight off the stored
    DataFrame / list instead of materialising a copy. Only payloads carrying
    inline records have to go through _resolve_dataframe, because those are
    computed rather than stored.
    """
    if not isinstance(payload, dict):
        return False, 0, SRC_NO_UPSTREAM, []

    dataset_id = payload.get('dataset_id')
    if dataset_id:
        entry = _datasets.get(dataset_id)
        if entry is None:
            return False, 0, SRC_STALE_DATASET, []
        df = entry['df']
        rows = len(df)
        return (True, rows, '', _column_names(df)) if rows else (False, 0, SRC_EMPTY, [])

    node_id = payload.get('node_id')
    if not node_id:
        return False, 0, SRC_NO_UPSTREAM, []
    result = execution_state['results'].get(node_id)
    if isinstance(result, list):
        rows = len(result)
        if not rows:
            return False, 0, SRC_EMPTY, []
        first = result[0]
        cols = list(first.keys()) if isinstance(first, dict) else []
        return True, rows, '', [str(c) for c in cols[:PROBE_MAX_COLUMNS]]

    try:
        df = _resolve_dataframe(payload)
    except KeyError:
        return False, 0, SRC_NO_RESULT, []
    except Exception:
        logger.exception(t('misc.source_probe_failed'))
        return False, 0, SRC_ERROR, []
    rows = 0 if df is None else len(df)
    return (True, rows, '', _column_names(df)) if rows else (False, 0, SRC_EMPTY, [])


@app.route('/api/studio/sources', methods=['POST'])
def studio_sources():
    """Pre-flight for the studio's source picker.

    Every node on the canvas is listed, but only those that can actually hand
    the studio a table are selectable. The browser works out the static dead
    ends itself (a Visualize node with nothing connected has no payload at all);
    this endpoint answers the runtime half — has the node produced a result yet,
    is the uploaded dataset still around — so the user is told *why* a row is
    unselectable before clicking Load instead of after.

    Body: {"candidates": [{"node_id": str, "payload": {...} | null}]}
    """
    data = request.get_json(silent=True) or {}
    candidates = data.get('candidates')
    if not isinstance(candidates, list):
        return jsonify({'ok': False, 'error': t('api.badRequest', what='candidates list')}), 400

    sources = []
    for item in candidates[:STUDIO_MAX_CANDIDATES]:
        item = item if isinstance(item, dict) else {}
        available, rows, reason, cols = _probe_source(item.get('payload'))
        sources.append(
            {
                'node_id': str(item.get('node_id') or ''),
                'available': available,
                'rows': rows,
                'reason': reason,
                'cols': cols,
            }
        )
    return jsonify({'ok': True, 'sources': sources})


@app.route('/api/studio/save-image', methods=['POST'])
def studio_save_image():
    """Persist a chart rendered in the studio (PNG data URL) into EXPORT_DIR."""
    data = request.get_json(silent=True) or {}
    image = data.get('image') or ''
    match = re.match(r'^data:image/(png|jpeg|jpg|webp);base64,(.+)$', image, re.DOTALL)
    if not match:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='image data URL')}), 400

    ext = match.group(1)
    if ext == 'jpeg':
        ext = 'jpg'
    try:
        payload = base64.b64decode(match.group(2), validate=False)
    except (ValueError, TypeError) as e:
        return jsonify({'ok': False, 'error': t('api.parseFailed', err=e)}), 400
    if not payload:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='empty image')}), 400
    if len(payload) > MAX_IMAGE_BYTES:
        # A full-canvas chart is a few hundred KB; anything far past the cap is
        # either a mistake or an attempt to exhaust memory.
        return jsonify({'ok': False, 'error': t('api.badRequest', what='image too large')}), 400

    name = data.get('name') or 'studio-chart'
    name = re.sub(r'\.(png|jpe?g|webp)$', '', str(name), flags=re.IGNORECASE)
    filename = sanitize_filename(f'{name}-{uuid.uuid4().hex[:8]}.{ext}')
    filepath = os.path.join(Config.EXPORT_DIR, filename)
    try:
        os.makedirs(Config.EXPORT_DIR, exist_ok=True)
        with open(filepath, 'wb') as fh:
            fh.write(payload)
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Could not write file: {e}'}), 500

    logger.info(t('misc.studio_saved', path=filepath, bytes=len(payload)))
    return jsonify({'ok': True, 'filename': filename, 'path': filepath, 'bytes': len(payload)})


# ─── Execution History API (time-series comparison across runs) ───


@app.route('/api/history/runs', methods=['GET'])
def history_runs():
    limit = _safe_int(request.args.get('limit'), 50, minimum=1, maximum=1000)
    df = history_service.list_runs(limit=limit)
    return jsonify({'ok': True, 'runs': df.to_dict('records'), 'workflow_names': history_service.list_workflow_names()})


@app.route('/api/history/series', methods=['GET'])
def history_series():
    workflow_name = request.args.get('workflow_name') or None
    metric = request.args.get('metric') or None
    node_id = request.args.get('node_id') or None
    limit = _safe_int(request.args.get('limit'), 2000, minimum=1, maximum=20000)
    df = history_service.series(workflow_name=workflow_name, metric=metric, node_id=node_id, limit=limit)
    return jsonify({'ok': True, 'rows': df.to_dict('records')})


@app.route('/api/history/clear', methods=['POST'])
def history_clear():
    history_service.clear()
    return jsonify({'ok': True, 'message': 'History cleared'})


# ─── Main ──────────────────────────────────────────────────────


def _open_browser(url: str):
    """Open the UI in the default browser once the server is up."""
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception as e:
        # A headless box has no browser to open — warn, never crash the startup.
        logger.warning(t('misc.browser_open_failed', err=e))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    url = f'http://127.0.0.1:{port}'
    # debug=True runs the werkzeug reloader: this module executes twice — once
    # in the watcher (WERKZEUG_RUN_MAIN unset) and once in the serving child
    # (set to 'true'). Opening from the watcher means exactly one tab, and the
    # child's restarts on code changes don't spawn new ones. The 1.5s delay
    # lets the child bind the port before the browser arrives.
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        threading.Timer(1.5, _open_browser, args=(url,)).start()
    logger.info(t('misc.server_starting', port=port))
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)
