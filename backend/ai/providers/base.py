"""Shared transport plumbing: HTTP, SSE framing, cancellation and error mapping."""

import codecs
import json
import time

import requests

from ai.errors import AIError, AIProviderError
from ai.types import ProviderSpec

#: The wrapper the model reads as "facts about the user's project", not as something they typed.
CONTEXT_OPEN = '<cai_xi_hui_context>'


def event(kind: str, **data) -> dict:
    return {'type': kind, **data}


def with_context(messages: list, context_text: str) -> list:
    """Return the canonical history with this turn's context on its NEWEST user row.

    The context is produced once, by ``ai.context.build_context``, and it has to reach whichever
    provider the user picked. It used to be read by the DeepSeek transport alone: a local Ollama
    turn advertised “项目事实 2,320 字” in the context inspector and sent none of it, so the model
    answered questions about the canvas and the datasets from thin air.

    One rule for every transport, and it is also the cache-friendly one: the block rides on the
    newest user message and stays byte-identical for the whole turn (older turns are NOT replayed
    here — a five-turn-old canvas is not the current canvas, and the sooner the bytes stop changing
    the sooner the provider's prefix cache can hit).
    """
    text = str(context_text or '')
    if not text:
        return messages
    index = -1
    for position in range(len(messages) - 1, -1, -1):
        if str(messages[position].get('role') or '') == 'user':
            index = position
            break
    if index < 0:
        return messages
    out = list(messages)
    target = dict(out[index])
    target['content'] = f'{CONTEXT_OPEN}\n{text}\n</cai_xi_hui_context>\n\n{target.get("content") or ""}'
    out[index] = target
    return out


def check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AIError('ai.cancelled', kind='cancelled')


def stream_lines(response, cancel_event):
    """Yield UTF-8 text lines from a streaming response, decoded incrementally.

    ``iter_lines(decode_unicode=True)`` decodes each chunk with ``response.encoding``, which is
    ISO-8859-1 for an event-stream with no charset parameter: Chinese text arrived as mojibake
    (``å¾…``), a multi-byte character split across two chunks became garbage, and a frame cut
    mid-string failed ``json.loads`` — the panel then reported 供应商返回了无法解析的数据 with the
    mojibake inside the quote. An incremental UTF-8 decoder never splits a character, so the
    bytes are decoded once, here, by the side that knows the stream is UTF-8.
    """
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    buffer = ''
    for chunk in response.iter_content(chunk_size=1024):
        check_cancel(cancel_event)
        if not chunk:
            continue
        buffer += decoder.decode(chunk)
        while True:
            index = buffer.find('\n')
            if index < 0:
                break
            line = buffer[:index]
            buffer = buffer[index + 1 :]
            yield line[:-1] if line.endswith('\r') else line
    tail = buffer + decoder.decode(b'', final=True)
    if tail:
        yield tail[:-1] if tail.endswith('\r') else tail


def http_error(status: int, body: str = '') -> AIProviderError:
    """Map an HTTP status onto the same kinds the row analyzer already uses."""
    text = (body or '')[:400]
    if status in (401, 403):
        return AIProviderError('ai.unauthorized', kind='auth', status=status, detail=text)
    if status == 402:
        return AIProviderError('ai.quota', kind='quota', status=status, detail=text)
    if status == 404:
        return AIProviderError('ai.modelMissing', kind='model', status=status, detail=text)
    if status == 429:
        return AIProviderError('ai.rateLimit', kind='rate_limit', status=status, detail=text)
    if status == 400 or status == 413:
        return AIProviderError('ai.badRequest', kind='bad_request', status=status, detail=text)
    if status >= 500:
        return AIProviderError('ai.server', kind='network', status=status, detail=text)
    return AIProviderError('ai.http', kind='error', status=status, detail=text)


def read_json_error(response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or '')[:400]
    error = payload.get('error') if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get('message') or error.get('code') or error)[:400]
    return str(error or payload)[:400]


def open_stream(url: str, headers: dict, payload: dict, timeout: int, cancel_event, retries: int = 3):
    """POST a JSON body and return a streaming response.

    Retries only before the first byte of the body has been handed to the caller: once a stream
    starts, a retry would duplicate the answer. A 429/5xx answer or a dropped connection is retried
    with a short, interruptible backoff; auth/model/quota failures are deterministic and raise
    immediately.

    ``retries`` used to default to 1, which made the whole backoff branch dead code: one 429 or one
    reset TLS socket ended the turn and the user had to press 重试 by hand.
    """
    last: AIProviderError | None = None
    for attempt in range(1, retries + 1):
        check_cancel(cancel_event)
        try:
            response = requests.post(
                url,
                headers={'Accept': 'text/event-stream', **headers},
                json=payload,
                stream=True,
                timeout=(10, timeout),
            )
        except requests.RequestException as exc:
            last = AIProviderError('ai.network', kind='network', detail=str(exc)[:300])
            if attempt < retries and not _nap(cancel_event, 0.8 * attempt):
                continue
            raise last from exc
        if response.status_code == 200:
            return response
        body = read_json_error(response)
        response.close()
        error = http_error(response.status_code, body)
        if error.kind in ('rate_limit', 'network') and attempt < retries:
            last = error
            if not _nap(cancel_event, 1.2 * attempt):
                continue
        raise error
    raise last or AIProviderError('ai.network', kind='network')


def _nap(cancel_event, seconds: float) -> bool:
    """Wait unless Stop was set; return True when the caller must stop."""
    if cancel_event is not None:
        cancel_event.wait(seconds)
        return bool(cancel_event.is_set())
    time.sleep(seconds)
    return False


def data_frames(response, cancel_event):
    """Yield ``('message', payload)`` for each SSE data frame; ``[DONE]`` ends the stream.

    The Chat Completions wire both DeepSeek and the OpenAI-compatible providers speak: blank line
    dispatches a frame, ``:`` starts a comment (keep-alive), and multi-line ``data`` is joined.
    """
    data_lines: list[str] = []
    for line in stream_lines(response, cancel_event):
        if line == '':
            if not data_lines:
                continue
            payload = '\n'.join(data_lines)
            data_lines = []
            if payload.strip() == '[DONE]':
                return
            try:
                yield 'message', json.loads(payload)
            except ValueError as exc:
                raise AIProviderError('ai.badResponse', kind='bad_response', detail=payload[:200]) from exc
            continue
        if line.startswith(':'):
            continue
        field, _, value = line.partition(':')
        value = value[1:] if value.startswith(' ') else value
        if field == 'data':
            data_lines.append(value)
    if data_lines:
        payload = '\n'.join(data_lines)
        if payload.strip() != '[DONE]':
            try:
                yield 'message', json.loads(payload)
            except ValueError as exc:
                raise AIProviderError('ai.badResponse', kind='bad_response', detail=payload[:200]) from exc


class Provider:
    """A transport plus its declared capabilities."""

    spec: ProviderSpec

    def stream(self, request: dict):
        raise NotImplementedError

    def list_models(self, _api_key: str = '', _host: str = '') -> list:
        return [{'id': model.id, 'label': model.label or model.id} for model in self.spec.models]

    def balance(self, _api_key: str = '') -> dict | None:
        """The account's remaining credit, for a provider that publishes it; ``None`` elsewhere.

        A balance is the provider's own fact (it needs its own endpoint and currency), so a
        transport that has no such endpoint answers ``None`` and the panel says so instead of
        showing a zero that would read as "empty account".
        """
        return None

    def cost(self, _model: str = '', _prompt: int = 0, _completion: int = 0, _cached: int = 0) -> dict | None:
        """Estimated cost of a token count in this provider's own prices; ``None`` when unpublished."""
        return None

    def supports(self, capability: str, model: str = '') -> bool:
        return self.spec.supports(capability, model)

    def public(self) -> dict:
        """The catalog row for this provider."""
        return self.spec.to_public()
