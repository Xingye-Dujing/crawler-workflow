"""Shared transport plumbing: HTTP, SSE framing, cancellation and error mapping."""

import json
import time

import requests

from ai.errors import AIError, AIProviderError
from ai.types import ProviderSpec


def event(kind: str, **data) -> dict:
    return {'type': kind, **data}


def check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AIError('ai.cancelled', kind='cancelled')


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


def open_stream(url: str, headers: dict, payload: dict, timeout: int, cancel_event, retries: int = 1):
    """POST a JSON body and return a streaming response.

    Retries only before the first byte of the body has been handed to the caller: once a stream
    starts, a retry would duplicate the answer. A 429/5xx answer is retried with a short,
    interruptible backoff; auth/model/quota failures are deterministic and raise immediately.
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


def sse_events(response, cancel_event):
    """Yield ``(event_name, payload)`` from a text/event-stream response.

    The parser follows the WHATWG rules the page's own decoder follows: multi-line ``data`` is
    joined with a newline, comments (``: keep-alive``) are ignored, and an event is dispatched on
    a blank line. A malformed JSON frame is a provider failure, never a silently skipped answer.
    """
    data_lines: list[str] = []
    event_name = ''
    for raw in response.iter_lines(decode_unicode=True, chunk_size=1024):
        check_cancel(cancel_event)
        if raw is None:
            continue
        line = raw if isinstance(raw, str) else raw.decode('utf-8', 'replace')
        if line == '':
            if data_lines:
                payload = '\n'.join(data_lines)
                data_lines = []
                name = event_name or 'message'
                event_name = ''
                try:
                    decoded = json.loads(payload)
                except ValueError as exc:
                    raise AIProviderError('ai.badResponse', kind='bad_response', detail=payload[:200]) from exc
                yield name, decoded
            continue
        if line.startswith(':'):
            continue
        field, _, value = line.partition(':')
        value = value[1:] if value.startswith(' ') else value
        if field == 'data':
            data_lines.append(value)
        elif field == 'event':
            event_name = value
    if data_lines:
        payload = '\n'.join(data_lines)
        try:
            decoded = json.loads(payload)
        except ValueError as exc:
            raise AIProviderError('ai.badResponse', kind='bad_response', detail=payload[:200]) from exc
        yield event_name or 'message', decoded


class Provider:
    """A transport plus its declared capabilities."""

    spec: ProviderSpec

    def stream(self, request: dict):
        raise NotImplementedError

    def list_models(self, _api_key: str = '', _host: str = '') -> list:
        return [{'id': model.id, 'label': model.label or model.id} for model in self.spec.models]

    def supports(self, capability: str, model: str = '') -> bool:
        return self.spec.supports(capability, model)

    def public(self) -> dict:
        return self.spec.to_public()
