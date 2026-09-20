"""Unified LLM access for the analyzers.

Two transports behind one ``chat()`` call:

- ``ollama``     — the local daemon (the original path). Address comes from
  the runtime settings store (设置 → Ollama 服务地址) and is bound to the
  ollama *client*; the model is its own setting (AI → 模型), a tag the daemon
  actually has — ``list_ollama_models()`` lists them.
- ``openrouter`` — OpenRouter's OpenAI-compatible chat API. Aimed at the
  ``:free`` models: the API key lives in the browser's localStorage and is
  posted with each request, never written to disk on this machine.

The two share nothing but the ``chat()`` signature: the local daemon needs a
host and a pulled tag, the API needs a key and a catalog id. Keeping one
``model`` field for both is what sent OpenRouter ids like
``nex-agi/nex-n2.5-pro:free`` to a local daemon that had never heard of them.

Also lives here the machinery that keeps a slow, fragile LLM run from losing
work: ``RowCheckpoint`` (every processed row appended to a JSONL file, keyed by
the *content* of the dataset so a re-crawled table never reuses stale marks)
and ``run_llm_rows`` (batched execution with cancel checks, a consecutive-
failure circuit breaker, and incremental publishing of partial results).
"""

import contextlib
import hashlib
import inspect
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from i18n import t

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = 'https://openrouter.ai/api/v1/chat/completions'
OPENROUTER_MODELS_URL = 'https://openrouter.ai/api/v1/models'
OPENROUTER_REFERER = 'http://localhost:5000'
OPENROUTER_TITLE = 'Crawler Workflow'

OLLAMA_DEFAULT_HOST = 'http://localhost:11434'
OLLAMA_TAGS_PATH = '/api/tags'

# Filled on first use: which optional kwargs this installed ollama build takes.
_CHAT_KWARGS: frozenset | None = None


def _settings_host() -> str:
    """Ollama daemon address from the runtime settings store. Imported lazily
    so the analyzers package keeps working when copied without the backend."""
    try:
        from settings_store import get_setting

        return str(get_setting('ollama_host') or '')
    except Exception:
        # A missing settings store must not break analysis: the ollama library
        # then falls back to its own default host.
        return ''


def _ollama_base_url(host: str = '') -> str:
    """Turn whatever the settings hold into a usable daemon base URL.

    The panel normally stores ``http://localhost:11434``, but ``OLLAMA_HOST``
    (and the ollama server itself) also accept a bare ``host:port`` — so the
    scheme is added here rather than letting a scheme-less value fail much
    later with a confusing parse error.
    """
    raw = (host or os.environ.get('OLLAMA_HOST') or '').strip().rstrip('/')
    if not raw:
        return OLLAMA_DEFAULT_HOST
    if not raw.startswith(('http://', 'https://')):
        raw = 'http://' + raw
    return raw


def _chat_kwargs() -> frozenset:
    """Names of the keyword arguments this ollama build's ``Client.chat``
    accepts.

    The library type-checks keywords strictly — an unknown one raises
    ``TypeError`` before anything is sent — and ``think`` only exists in newer
    releases. Probing the signature once keeps the call portable instead of
    pinning a version.
    """
    global _CHAT_KWARGS
    if _CHAT_KWARGS is None:
        try:
            from ollama import Client

            _CHAT_KWARGS = frozenset(inspect.signature(Client.chat).parameters)
        except (ImportError, TypeError, ValueError):  # pragma: no cover
            _CHAT_KWARGS = frozenset()
    return _CHAT_KWARGS


class LLMError(Exception):
    """A chat call failed. ``kind`` tells the caller how fatal it is:
    auth / quota / model are deterministic (retrying cannot help), network /
    rate_limit / bad_response are transient, cancelled means the user stopped
    the run — rows done so far are already checkpointed."""

    def __init__(self, message: str, kind: str = 'error'):
        super().__init__(message)
        self.kind = kind


def _ollama_error(err: Exception, model: str) -> LLMError:
    """Map a daemon failure onto one of LLMError's kinds.

    The client raises ``ResponseError`` carrying the daemon's own status and
    message. A 404 means the tag was never pulled, which no amount of retrying
    fixes — saying so stops the row loop instead of letting it grind through
    the circuit breaker.
    """
    status = getattr(err, 'status_code', None)
    text = str(err)
    lowered = text.lower()
    # "not found" on its own is too loose — a wrong address can answer 404 with
    # an HTML page. Require the daemon's own wording, or the model's own name.
    named = bool(model) and model.lower() in lowered and 'not found' in lowered
    if status == 404 or 'try pulling' in lowered or named:
        return LLMError(t('llm.ollama_model_missing', model=model, err=text), 'model')
    if status in (401, 403):
        return LLMError(t('llm.ollama_http', code=status, err=text), 'auth')
    return LLMError(text, 'network')


class LLMClient:
    """One chat transport plus the token-throttling settings for a run."""

    def __init__(
        self,
        provider: str = 'ollama',
        model: str = '',
        api_key: str = '',
        temperature: float = 0.1,
        max_tokens: int = 512,
        max_chars: int = 600,
        timeout: int = 180,
        host: str = '',
    ):
        self.provider = provider if provider in ('ollama', 'openrouter') else 'ollama'
        self.model = (model or '').strip()
        self.api_key = (api_key or '').strip()
        self.temperature = temperature
        self.max_tokens = max_tokens
        # Rows longer than this are cut before reaching the prompt. Long texts
        # are what burns tokens on a per-row API; 0 disables the cut.
        self.max_chars = max(0, int(max_chars or 0))
        self.timeout = timeout
        # Ollama daemon address (设置 → Ollama 服务地址); empty = default host.
        # Only used by the ollama transport — OpenRouter carries its address in
        # the URL, so the two providers no longer share any connection setting.
        self.host = (host or '').strip()

    @property
    def label(self) -> str:
        return f'{self.provider}:{self.model or "(default)"}'

    def truncate(self, text: str) -> str:
        if self.max_chars and len(text) > self.max_chars:
            return text[: self.max_chars] + '…'
        return text

    def chat(self, prompt: str, max_retries: int = 2) -> str:
        """One user message in, the model's plain text out. Raises LLMError."""
        if self.provider == 'openrouter':
            if not self.api_key:
                raise LLMError(t('llm.no_key'), 'auth')
            if not self.model:
                raise LLMError(t('llm.no_model'), 'model')
            return self._openrouter(prompt, max_retries)
        return self._ollama(prompt, max_retries)

    # ── transports ──────────────────────────────────────────────

    def _ollama(self, prompt: str, max_retries: int) -> str:
        try:
            from ollama import Client  # imported lazily: the daemon is optional
        except ImportError as e:  # pragma: no cover
            raise LLMError(t('llm.ollama_pkg_missing', err=e), 'model') from e

        if not self.model:
            raise LLMError(t('llm.no_ollama_model'), 'model')

        # `host` is a *client* option, never a chat() one. Handing it to chat()
        # (or to the module-level ollama.chat, which forwards to Client.chat)
        # raises "unexpected keyword argument 'host'" before a single byte is
        # sent — which is exactly how the local Ollama path used to die.
        base = _ollama_base_url(self.host)
        try:
            client = Client(host=base)
        except Exception as e:
            raise LLMError(t('llm.ollama_client_failed', host=base, err=e), 'network') from e

        kwargs = {
            'model': self.model,
            'messages': [{'role': 'user', 'content': prompt}],
            'stream': False,
            'options': {'temperature': self.temperature, 'num_predict': self.max_tokens},
        }
        if 'think' in _chat_kwargs():
            # A thinking model would otherwise spend the whole token budget
            # between  tags and hand back an empty answer.
            kwargs['think'] = False

        last = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.chat(**kwargs)
                content = self._ollama_content(resp)
                if not content or not content.strip():
                    raise LLMError(t('llm.ollama_empty'), 'bad_response')
                return content
            except LLMError as e:
                last = e
                logger.warning(t('llm.ollama_fail_attempt', i=attempt, n=max_retries, err=e))
            except Exception as e:  # connection refused, model missing, timeout…
                last = _ollama_error(e, self.model)
                logger.warning(t('llm.ollama_exception', i=attempt, n=max_retries, err=last))
                if last.kind == 'model':
                    # Missing model / bad tag: deterministic, retrying is noise.
                    raise LLMError(t('llm.ollama_failed', model=self.model, err=last), last.kind) from e
            time.sleep(0.5 * attempt)
        kind = last.kind if isinstance(last, LLMError) else 'network'
        if kind == 'network':
            # "Connection refused" alone is unactionable — name the address,
            # which is the thing the settings panel controls.
            raise LLMError(t('llm.ollama_unreachable', host=base, err=last), kind)
        raise LLMError(t('llm.ollama_failed', model=self.model, err=last), kind)

    @staticmethod
    def _ollama_content(resp) -> str:
        if isinstance(resp, dict) and 'message' in resp:
            return resp['message'].get('content') or ''
        msg = getattr(resp, 'message', None)
        content = getattr(msg, 'content', None) if msg is not None else None
        return content if content is not None else str(resp)

    def _openrouter(self, prompt: str, max_retries: int) -> str:
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': OPENROUTER_REFERER,
            'X-Title': OPENROUTER_TITLE,
        }
        payload = {
            'model': self.model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
        }
        delay = 2.0
        last = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(OPENROUTER_CHAT_URL, headers=headers, json=payload, timeout=self.timeout)
            except requests.RequestException as e:
                last = LLMError(t('llm.net_error', err=e), 'network')
                logger.warning(t('llm.or_net_exception', i=attempt, n=max_retries, err=e))
                time.sleep(delay)
                delay *= 2
                continue

            if resp.status_code == 200:
                try:
                    content = resp.json()['choices'][0]['message']['content'] or ''
                except (KeyError, IndexError, TypeError, ValueError) as e:
                    raise LLMError(t('llm.or_bad_format', err=e), 'bad_response') from e
                if content.strip():
                    return content
                last = LLMError(t('llm.or_empty'), 'bad_response')
            elif resp.status_code == 401:
                raise LLMError(t('llm.or_401'), 'auth')
            elif resp.status_code == 402:
                raise LLMError(t('llm.or_402'), 'quota')
            elif resp.status_code == 404:
                raise LLMError(t('llm.or_404', model=self.model), 'model')
            elif resp.status_code == 429:
                try:
                    wait = max(1.0, min(20.0, float(resp.headers.get('Retry-After', 2.0))))
                except (TypeError, ValueError):
                    wait = 2.0
                last = LLMError(t('llm.or_429'), 'rate_limit')
                logger.warning(t('llm.or_429_wait', i=attempt, n=max_retries, wait=f'{wait:.1f}'))
                time.sleep(wait)
                continue
            elif 500 <= resp.status_code < 600:
                last = LLMError(t('llm.or_5xx', code=resp.status_code), 'network')
                logger.warning(t('llm.or_5xx_attempt', code=resp.status_code, i=attempt, n=max_retries))
                time.sleep(delay)
                delay *= 2
                continue
            else:
                raise LLMError(t('llm.or_http_fail', code=resp.status_code, body=resp.text[:200]), 'error')

            time.sleep(delay)
            delay *= 2

        raise last if last is not None else LLMError(t('llm.or_failed'), 'network')


def list_free_models(timeout: int = 15) -> list:
    """Model ids whose prompt AND completion price is zero. The catalog is
    public (no key needed), so the dropdown is always current instead of a
    hardcoded list that rots as models come and go."""
    resp = requests.get(OPENROUTER_MODELS_URL, timeout=timeout)
    resp.raise_for_status()
    models = resp.json().get('data', [])
    free = [
        m['id']
        for m in models
        if str(m.get('pricing', {}).get('prompt', '1')) == '0'
        and str(m.get('pricing', {}).get('completion', '1')) == '0'
    ]
    return sorted(free)


def list_ollama_models(host: str = '', timeout: int = 8) -> list:
    """Tags the *local* daemon has pulled, for the AI panel's model picker.

    Read straight off ``/api/tags`` over HTTP instead of going through the
    ollama package: the panel only needs names, and a plain GET keeps working
    across client releases (the package's own list() has changed shape more
    than once). Embedding-only models are dropped — they are listed like any
    other but cannot answer a chat request.
    """
    resp = requests.get(_ollama_base_url(host) + OLLAMA_TAGS_PATH, timeout=timeout)
    resp.raise_for_status()
    names = set()
    for model in resp.json().get('models', []):
        name = str(model.get('name') or model.get('model') or '').strip()
        if name and 'embed' not in name.lower():
            names.add(name)
    return sorted(names)


# ─── Row checkpoint ─────────────────────────────────────────────


def content_key(texts) -> str:
    """A fingerprint of the dataset the rows came from."""
    joined = '\x1e'.join(str(t) for t in texts)
    return hashlib.sha1(joined.encode('utf-8')).hexdigest()[:16]


def text_hash(text) -> str:
    return hashlib.sha1(str(text).encode('utf-8')).hexdigest()[:16]


class RowCheckpoint:
    """Append-only JSONL store of per-row results.

    Every completed row is one line ``{"i": row_index, "h": text_hash, "r": [...]}``.
    A run that dies halfway leaves the file behind; the next run on the same
    dataset reads it back and skips the rows it already paid for. Removed by
    the caller once the node finishes cleanly."""

    def __init__(self, directory: str, key: str):
        digest = hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]
        self.path = os.path.join(directory, digest + '.jsonl')
        self.rows = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and 'i' in rec and 'h' in rec and 'r' in rec:
                        self.rows[rec['i']] = rec
        except OSError:
            pass
        if self.rows:
            logger.info(t('llm.checkpoint_loaded', n=len(self.rows), file=os.path.basename(self.path)))

    def get(self, idx, thash: str):
        rec = self.rows.get(idx)
        # Same row index AND same text — a re-crawled table must not inherit
        # marks made for different content.
        if rec is not None and rec.get('h') == thash:
            return rec
        return None

    def add(self, idx, thash: str, result: tuple):
        rec = {'i': idx, 'h': thash, 'r': list(result)}
        with self._lock:
            self.rows[idx] = rec
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            except OSError:
                pass  # checkpointing is best-effort; the run continues

    def discard(self):
        """Call when the node finished cleanly — the real outputs own the data now."""
        # Best-effort: an already-removed or locked checkpoint file is fine.
        with contextlib.suppress(OSError):
            os.remove(self.path)


# ─── Shared row runner ──────────────────────────────────────────


def _call_row(client, parse, prompt, idx, thash):
    """Chat + parse for one row. Runs in a worker thread for API providers;
    returns (idx, text_hash, result-or-None) so the collector can checkpoint
    the row by content no matter which order the answers land in."""
    return idx, thash, parse(client.chat(prompt))


def run_llm_rows(
    jobs: list,
    client: LLMClient,
    build_prompt,
    parse,
    checkpoint=None,
    apply_result=None,
    publish=None,
    cancel_event=None,
    batch_size: int = 10,
    workers: int = 1,
    max_consecutive_failures: int = 5,
    log=None,
    label: str = '',
):
    """Drive one row per message through ``client`` — with the losses contained.

    jobs          — [(row_index, text)] in order.
    build_prompt  — text -> prompt string.
    parse         — content -> result tuple, or a tuple whose first item is
                    None when the output was unparseable.
    apply_result  — (idx, result) written the moment a row lands.
    publish       — no-arg callback after every batch: whatever is done so far
                    becomes visible, so a crash never takes finished rows with it.
    cancel_event  — set by the Stop button; checked before every row.
    workers       — >1 only for API providers: that many rows in flight per
                    batch. Local Ollama stays serial (one GPU queue anyway).

    Raises LLMError('cancelled') when stopped, or the underlying LLMError once
    ``max_consecutive_failures`` rows died back to back — both only after every
    completed row is already checkpointed and published.
    """
    say = log if log is not None else (lambda msg: None)
    total = len(jobs)
    results = {}
    failures = 0
    done = 0
    pool = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None

    def _check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise LLMError(t('llm.cancelled'), 'cancelled')

    # One line per finished row on small tables; on a 2 000-row crawl that
    # would be 2 000 console lines, so thin it to roughly a hundred of them.
    progress_step = 1 if total <= 100 else -(-total // 100)

    def _finish(idx, result, announce=True):
        nonlocal done, failures
        if result is None or (isinstance(result, tuple) and result and result[0] is None):
            failures += 1
            say(t('llm.parse_failed', label=label, i=done + 1, total=total, f=failures))
            return
        failures = 0
        results[idx] = result
        if apply_result is not None:
            apply_result(idx, result)
        done += 1
        # Rows replayed from a checkpoint land far too fast to narrate; the
        # "loaded N finished rows" line at startup already covers them.
        if announce and (done % progress_step == 0 or done == total):
            say(t('llm.row_done', label=label, done=done, total=total))

    def _complete(idx, thash, result, announce=True):
        """A row actually finished: land it in the checkpoint file first, then
        everywhere else. The file is what survives a crash. Rows the model
        could not classify are NOT checkpointed — the next run should retry
        them, not inherit the failure."""
        if (
            result is not None
            and not (isinstance(result, tuple) and result and result[0] is None)
            and checkpoint is not None
        ):
            checkpoint.add(idx, thash, result)
        _finish(idx, result, announce=announce)

    def _wait_pending(pending):
        """Drain a batch: (future, row_index, text_hash) triples, finish order."""
        nonlocal failures
        futures = [f for f, _i, _h in pending]
        meta = {id(f): (i, h) for f, i, h in pending}
        for fut in as_completed(futures):
            idx, thash = meta[id(fut)]
            try:
                got_idx, got_hash, result = fut.result()
                _complete(got_idx, got_hash or thash, result)
            except LLMError:
                for other, _i, _h in pending:
                    other.cancel()
                raise
            except Exception as e:
                # One row failing is never fatal by itself — count it and keep going.
                failures += 1
                logger.warning(t('llm.row_exception', label=label, err=e))

    def _after_batch():
        nonlocal in_batch
        in_batch = 0
        if publish is not None:
            with contextlib.suppress(Exception):
                publish()
        say(t('llm.progress', label=label, done=done, total=total))

    pending = []  # [(future, row_index, text_hash)] in flight within the current batch
    try:
        in_batch = 0
        for idx, text in jobs:
            _check_cancel()
            if failures >= max_consecutive_failures:
                raise LLMError(
                    t('llm.circuit_break', f=failures, done=done, total=total),
                    'circuit_break',
                )

            thash = text_hash(text)
            # Resume: the checkpoint owns any row this exact dataset already paid for.
            cached = checkpoint.get(idx, thash) if checkpoint is not None else None
            if cached is not None:
                _finish(idx, tuple(cached['r']), announce=False)
                continue

            truncated = client.truncate(str(text))
            if pool is not None:
                prompt = build_prompt(truncated)
                pending.append(
                    (
                        pool.submit(_call_row, client, parse, prompt, idx, thash),
                        idx,
                        thash,
                    )
                )
                in_batch += 1
                if in_batch >= batch_size:
                    _wait_pending(pending)
                    pending = []
                    _after_batch()
            else:
                try:
                    _idx, _hash, parsed = _call_row(client, parse, build_prompt(truncated), idx, thash)
                except LLMError:
                    raise
                except Exception as e:
                    # One row failing is never fatal by itself — count it and
                    # keep going (the circuit breaker handles a real outage).
                    failures += 1
                    logger.warning(t('llm.row_exception', label=label, err=e))
                    parsed = None
                _complete(idx, thash, parsed)
                in_batch += 1
                if in_batch >= batch_size:
                    _after_batch()

        # Drain whatever the last partial batch left in flight.
        if pending:
            _wait_pending(pending)
            pending = []
        if publish is not None:
            with contextlib.suppress(Exception):
                publish()
        say(t('llm.node_done', label=label, done=done, total=total))
    except LLMError as e:
        # Cancel / circuit-break: publish what is done, then bubble up so the
        # workflow stops this branch instead of feeding partial data downstream.
        # pending holds triples — unpacking two of them here used to raise a
        # ValueError that replaced the real LLM error, so the node died with a
        # baffling "too many values to unpack".
        for fut, _i, _h in pending:
            fut.cancel()
        if publish is not None:
            with contextlib.suppress(Exception):
                publish()
        say(f'[{label}] {e}')
        raise
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
    return results


ABORT_MARK = '未处理'


def run_llm_dataframe(
    df,
    text_column: str,
    op: str,
    result_columns: list,
    blank: list,
    skip_value: tuple,
    fail_value: tuple,
    build_prompt,
    parse,
    ctx=None,
    label: str = '',
    min_len: int = 10,
    default_model: str = '',
    extra_key: str = '',
):
    """Run a row-by-row LLM job over a DataFrame with the loss-containment rules
    the three analyzers share.

    ctx (built by app.py) may carry: client, node_id, batch_size, workers,
    publish(df), cancel_event, checkpoint_dir. Without a ctx everything falls
    back to the plain local Ollama default — the original behaviour.

    Rows the model could not classify keep the analyzer's fail_value (same as
    before). Rows never reached — user stop, or the circuit breaker tripping —
    are marked ``未处理`` instead of silently faking a result, and the
    checkpoint file lets the next identical run pick up exactly where this one
    died. Re-raises LLMError for circuit_break / transport errors so the
    workflow branch stops; a user cancel is absorbed (the global stop flag
    halts the rest of the workflow anyway).
    """
    cfg = ctx or {}
    client = cfg.get('client') or LLMClient(provider='ollama', model=default_model, host=_settings_host())

    for col, val in zip(result_columns, blank, strict=True):
        df[col] = val

    if text_column not in df.columns:
        logger.error(t('llm.missing_column', col=text_column, label=label))
        return df

    mask = df[text_column].notna() & (df[text_column].astype(str).str.strip() != '')
    process_indices = df[mask].index.tolist()
    if not process_indices:
        logger.info(t('llm.no_rows', label=label, col=text_column))
        return df
    total = len(process_indices)
    logger.info(t('llm.start', label=label, total=total, transport=client.label))

    def publish():
        cb = cfg.get('publish')
        if callable(cb):
            cb(df)

    # Skip rules stay per-analyzer (they know what a useless row means).
    jobs = []
    for idx in process_indices:
        text = str(df.at[idx, text_column]).strip()
        if len(text) < min_len:
            for col, val in zip(result_columns, skip_value, strict=True):
                df.at[idx, col] = val
            continue
        jobs.append((idx, text))

    checkpoint_dir = cfg.get('checkpoint_dir')
    checkpoint = None
    if checkpoint_dir:
        # Keyed by node + operation + transport + the dataset's own content:
        # a different table, model or column starts a fresh file, the same one
        # resumes.
        key = '|'.join(
            str(part)
            for part in (
                cfg.get('node_id') or 'adhoc',
                op,
                client.provider,
                client.model,
                text_column,
                extra_key,
                content_key(df[text_column]),
            )
        )
        checkpoint = RowCheckpoint(checkpoint_dir, key)

    def apply_result(idx, result):
        for col, val in zip(result_columns, result, strict=True):
            df.at[idx, col] = val

    abort_reason = None
    try:
        run_llm_rows(
            jobs,
            client,
            build_prompt,
            parse,
            checkpoint=checkpoint,
            apply_result=apply_result,
            publish=publish,
            cancel_event=cfg.get('cancel_event'),
            batch_size=max(1, int(cfg.get('batch_size') or 10)),
            workers=max(1, int(cfg.get('workers') or 1)),
            log=lambda msg: logger.info(msg),
            label=label,
        )
    except LLMError as e:
        abort_reason = str(e)
        if e.kind != 'cancelled':
            # Transport death / circuit breaker: stop the branch, but only
            # after the finished rows are published and visible.
            _mark_unprocessed(df, process_indices, result_columns, blank)
            publish()
            # Count only rows that really carry a result: the ones just marked
            # 未处理 are non-empty too, and counting them used to claim
            # "14/14 rows saved" when only one had actually landed.
            col = df[result_columns[0]]
            finished = int((col.notna() & (col != blank[0]) & (col != ABORT_MARK)).sum())
            logger.error(t('llm.aborted', label=label, err=e, done=finished))
            raise
        logger.warning(t('llm.stopped', label=label, err=e))

    # Rows that never landed: explicit parse-failures keep the analyzer's
    # failure value (same as the original code); anything the run never
    # reached stays 未处理 so the gap is visible instead of faked.
    unfinished = 0
    for idx in process_indices:
        if df.at[idx, result_columns[0]] != blank[0]:
            continue
        if abort_reason is not None:
            df.at[idx, result_columns[0]] = ABORT_MARK
            for col in result_columns[1:]:
                df.at[idx, col] = None
            unfinished += 1
        else:
            for col, val in zip(result_columns, fail_value, strict=True):
                df.at[idx, col] = val

    if abort_reason is None and checkpoint is not None:
        checkpoint.discard()  # clean finish — the real outputs own the data now
    if unfinished:
        logger.warning(t('llm.unfinished', label=label, n=unfinished, mark=ABORT_MARK))
    return df


def _mark_unprocessed(df, indices, result_columns, blank):
    """Give every row that produced nothing yet a visible 未处理 marker."""
    for idx in indices:
        if df.at[idx, result_columns[0]] == blank[0]:
            df.at[idx, result_columns[0]] = ABORT_MARK
            for col in result_columns[1:]:
                df.at[idx, col] = None
