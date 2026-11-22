"""The local Ollama daemon transport.

Ollama serves newline-delimited JSON rather than SSE, and its chat API speaks the same tool
vocabulary as the hosted providers: ``tools`` on the request, ``message.tool_calls`` in the stream,
and a ``role: tool`` message for each result. The workspace's whole point is that the assistant can
ACT, so this transport implements tools instead of hiding them — a model the daemon reports as
tool-capable gets the real schemas.

What belongs to the daemon, not to us:

* **Which models exist** — ``GET /api/tags``. The picker used to offer one hardcoded name, so a user
  with four downloaded models could only ever run one of them.
* **What a model can do** — ``POST /api/show`` answers ``capabilities`` (``completion``, ``tools``,
  ``thinking``, ``vision``). ``supports()`` asks it, so a model without tools is not handed schemas
  it would refuse with a 400.
* **How much context it really has** — the same answer carries ``*.context_length``; Ollama's own
  ``num_ctx`` default is 4096, which silently truncates the system prompt once a turn carries tool
  results. We send the model's real window, capped so a 262k model does not eat the machine.
"""

import json
import re
import threading
import time

import requests

from ai.errors import AIProviderError
from ai.providers.base import Provider, event, stream_lines
from ai.types import ModelSpec, ProviderSpec

#: What this transport implements. ``tools`` and ``thinking`` are per-model (asked of the daemon);
#: ``files``/``web_search`` are NOT declared — Ollama has no file-id or server-side search API, and
#: a promise the transport cannot keep must be refused by name instead of silently ignored.
OLLAMA_CAPABILITIES = frozenset({'tools', 'thinking'})

#: Ollama's ``num_ctx`` default is 4096 and it does NOT grow with the model. A harness turn carries
#: a vocabulary-heavy system prompt plus tool results, so the window is raised to the model's own
#: answer — capped, because a 262k-token window is memory the user did not ask to spend.
MAX_NUM_CTX = 32768

#: Model metadata is a local, cheap call but not free; a turn asks twice (supports + payload).
INFO_TTL = 300.0
CATALOG_TTL = 20.0
#: A local daemon answers in single-digit milliseconds; a machine with no daemon must not pay a
#: socket timeout on every page bootstrap, so the answer is cached for ``CATALOG_TTL`` either way.
PROBE_TIMEOUT = 1.0

#: Some GGUF templates ignore ``think: false`` and put their reasoning in ``content``. The daemon
#: may also return a ``thinking`` field even when it was told not to. Both are stripped here: the
#: product's policy is that a local turn never carries a visible reasoning trace.
_THINK_TAGS = re.compile(r'(?is)<think(?:ing)?>.*?</think(?:ing)?>')

SPEC = ProviderSpec(
    id='ollama',
    label_key='ai.provider.ollama',
    notes_key='ai.providerNote.ollama',
    protocol='ollama',
    base_url='',
    models=(ModelSpec('qwen3.5:9b', 'qwen3.5:9b', MAX_NUM_CTX, OLLAMA_CAPABILITIES),),
    local_only=True,
    requires_key=False,
    capabilities=OLLAMA_CAPABILITIES,
)

_LOCK = threading.Lock()
_CATALOG: dict[str, tuple[float, list[dict]]] = {}
_INFO: dict[str, tuple[float, dict]] = {}


class OllamaProvider(Provider):
    spec = SPEC

    def _base(self, host: str = '') -> str:
        raw = (host or '').strip().rstrip('/')
        if not raw:
            raw = 'http://localhost:11434'
        if not raw.startswith(('http://', 'https://')):
            raw = 'http://' + raw
        return raw

    def _host(self) -> str:
        """The configured daemon, read at use time so a settings change needs no restart."""
        from runtime.settings import get_setting

        return str(get_setting('ollama_host') or '')

    # ─── The daemon's own answers ───

    def _catalog(self, host: str = '') -> list[dict]:
        """The models this daemon really has, as ``/api/tags`` answers (empty when unreachable)."""
        base = self._base(host or self._host())
        now = time.monotonic()
        with _LOCK:
            hit = _CATALOG.get(base)
            if hit and hit[0] > now:
                return hit[1]
        try:
            response = requests.get(base + '/api/tags', timeout=PROBE_TIMEOUT)
            response.raise_for_status()
            rows = response.json().get('models') or []
        except (requests.RequestException, ValueError, AttributeError):
            with _LOCK:
                _CATALOG[base] = (now + CATALOG_TTL, [])
            return []
        models = []
        for row in rows:
            name = str((row or {}).get('name') or (row or {}).get('model') or '')
            # An embedding model cannot chat; listing it would offer a dead choice.
            if not name or 'embed' in name.lower():
                continue
            models.append({'id': name, 'label': name})
        with _LOCK:
            _CATALOG[base] = (now + CATALOG_TTL, models)
        return models

    def _cached_catalog(self) -> list[dict]:
        """The last answer ``/api/tags`` gave, without touching the network."""
        base = self._base(self._host())
        with _LOCK:
            hit = _CATALOG.get(base)
        return hit[1] if hit else []

    def _info(self, model: str, host: str = '') -> dict:
        """``/api/show`` for one model: capabilities and the real context window."""
        base = self._base(host or self._host())
        key = base + '|' + str(model or '')
        now = time.monotonic()
        with _LOCK:
            hit = _INFO.get(key)
            if hit and hit[0] > now:
                return hit[1]
        info: dict = {}
        try:
            response = requests.post(base + '/api/show', json={'model': model}, timeout=PROBE_TIMEOUT)
            if response.status_code == 200:
                payload = response.json()
                caps = payload.get('capabilities')
                info['capabilities'] = [str(item) for item in caps] if isinstance(caps, list) else []
                context = 0
                for name, value in (payload.get('model_info') or {}).items():
                    if str(name).endswith('context_length') and isinstance(value, int) and value > context:
                        context = value
                info['context'] = context
        except (requests.RequestException, ValueError, AttributeError):
            info = {}
        with _LOCK:
            _INFO[key] = (now + INFO_TTL, info)
        return info

    def supports(self, capability: str, model: str = '') -> bool:
        caps = self._info(model).get('capabilities') if model else None
        if caps:
            return capability in caps
        return capability in self.spec.capabilities

    def context_window(self, model: str = '') -> int:
        """The window this request really gets — exactly what ``num_ctx`` is set to.

        It is the model's own ``context_length`` (from ``/api/show``) capped at ``MAX_NUM_CTX``, not
        the static catalogue: the daemon is the only side that knows what a pulled tag was built
        with, and the agent needs the SAME number here to trim a history that would not fit.
        """
        info = self._info(model)
        context = int(info.get('context') or 0)
        return min(MAX_NUM_CTX, context) if context else MAX_NUM_CTX

    def public(self) -> dict:
        """The picker's static row; the daemon's real list is ``GET …/models``.

        ``/api/ai/bootstrap`` must not wait on a socket — a page load is not the place to probe a
        daemon that may not be running. The panel asks ``/models`` once for a local provider and
        replaces this list, so four downloaded models are all choosable.
        """
        item = self.spec.to_public()
        models = self._cached_catalog()
        if models:
            item['models'] = [
                {**row, 'max_context': MAX_NUM_CTX, 'capabilities': sorted(self.spec.capabilities)} for row in models
            ]
        return item

    def list_models(self, api_key: str = '', host: str = '') -> list:
        models = self._catalog(host)
        if models:
            return models
        return super().list_models(api_key, host)

    # ─── The request ───

    def _tool_schemas(self, tools: list) -> list:
        return [
            {
                'type': 'function',
                'function': {
                    'name': str(tool.get('name') or ''),
                    'description': str(tool.get('description') or ''),
                    'parameters': tool.get('input_schema') or {'type': 'object', 'properties': {}},
                },
            }
            for tool in tools or ()
            if tool.get('name')
        ]

    def _messages(self, request: dict) -> list:
        out: list[dict] = []
        if request.get('system'):
            out.append({'role': 'system', 'content': str(request['system'])})
        for message in request.get('messages') or ():
            role = str(message.get('role') or 'user')
            if role == 'assistant':
                blocks = message.get('blocks') or []
                text = ''.join(str(block.get('text') or '') for block in blocks if block.get('type') == 'text')
                calls = [
                    {
                        'type': 'function',
                        'function': {
                            'name': str(block.get('name') or ''),
                            'arguments': block.get('input') if isinstance(block.get('input'), dict) else {},
                        },
                    }
                    for block in blocks
                    if block.get('type') == 'tool_use' and block.get('name')
                ]
                item = {'role': 'assistant', 'content': text}
                if calls:
                    # The daemon replays the assistant's calls so the following `tool` messages have
                    # something to answer; without them Ollama refuses the history.
                    item['tool_calls'] = calls
                out.append(item)
                continue
            if role == 'tool':
                # A tool result is its own role here — the old transport turned it into `user`,
                # which told the model the answer was something the person said.
                out.append({'role': 'tool', 'content': str(message.get('content') or '')})
                continue
            out.append({'role': 'user', 'content': str(message.get('content') or '')})
        return out

    def _payload(self, request: dict) -> dict:
        model = str(request.get('model') or (self.spec.models[0].id if self.spec.models else ''))
        info = self._info(model, str(request.get('host') or ''))
        context = int(info.get('context') or 0)
        # ``or 0.2`` treated a deliberate 0.0 (fully deterministic) as "unset" and quietly ran at
        # 0.2 — a number the user did not choose. Only a missing value takes the default.
        temperature = request.get('temperature')
        options = {
            'temperature': 0.2 if temperature is None else float(temperature),
            'num_ctx': min(MAX_NUM_CTX, context) if context else MAX_NUM_CTX,
        }
        if request.get('max_tokens'):
            # The daemon defaults to "generate until the window is full"; the agent's output budget
            # was silently ignored, so one answer could run for minutes on a local model.
            options['num_predict'] = int(request['max_tokens'])
        payload = {
            'model': model,
            'messages': self._messages(request),
            'stream': True,
            'options': options,
        }
        tools = self._tool_schemas(request.get('tools') or ())
        if tools and self.supports('tools', model):
            payload['tools'] = tools
        # Local models never think in this product. This is a server policy, not a UI preference:
        # qwen3.5 thinks by default, a reasoning trace doubles a local turn's wall time and is not
        # what the workspace shows. The field is always sent so a daemon/model default cannot win.
        payload['think'] = False
        return payload

    def stream(self, request: dict):
        url = self._base(request.get('host')) + '/api/chat'
        try:
            response = requests.post(
                url, json=self._payload(request), stream=True, timeout=(10, int(request.get('timeout') or 180))
            )
        except requests.RequestException as exc:
            raise AIProviderError('ai.network', kind='network', detail=str(exc)[:300]) from exc
        if response.status_code != 200:
            response.close()
            raise AIProviderError('ai.http', kind='error', status=response.status_code, detail=response.text[:300])
        stop_reason = 'end_turn'
        try:
            for line in stream_lines(response, request.get('cancel_event')):
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                except ValueError as exc:
                    raise AIProviderError('ai.badResponse', kind='bad_response', detail=line[:200]) from exc
                if frame.get('error'):
                    raise AIProviderError('ai.server', kind='network', detail=str(frame['error'])[:300])
                message = frame.get('message') or {}
                # A daemon or template that ignores ``think: false`` must not leak reasoning into
                # the transcript. Drop the field and strip paired think tags from the content.
                if message.get('content'):
                    text = _THINK_TAGS.sub('', str(message['content']))
                    if text.strip():
                        yield event('text_delta', text=text)
                for call in message.get('tool_calls') or ():
                    function = (call or {}).get('function') or {}
                    arguments = function.get('arguments')
                    yield event(
                        'tool_call',
                        # The daemon matches results by order, not by id; one is minted here so the
                        # transcript can pair the call with its result.
                        id=str((call or {}).get('id') or ''),
                        name=str(function.get('name') or ''),
                        arguments=arguments if isinstance(arguments, dict) else {},
                        raw_arguments='',
                    )
                if frame.get('done'):
                    usage = {
                        'prompt_tokens': frame.get('prompt_eval_count') or 0,
                        'completion_tokens': frame.get('eval_count') or 0,
                    }
                    yield event('usage', usage=usage)
                    stop_reason = 'max_tokens' if str(frame.get('done_reason') or '') == 'length' else 'end_turn'
                    break
            yield event('done', stop_reason=stop_reason)
        finally:
            response.close()
