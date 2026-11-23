"""One generic trace seam for EVERY node that calls an LLM provider.

A node never opens a conversation itself. ``build_llm_run_ctx`` wraps the run's client once, so an
API-backed step -- cleaning, stance labels, topic labels, NER, aggression, qualitative coding, and
anything added later -- automatically gets a temporary AI-workspace conversation showing the exact
prompt and answer. New nodes need no new branch here; they only have to use the shared run context.

The trace lives in the agent-workspace store (``ai_host.manager``), not the legacy ``ai.db``: the
run console and the new workspace read the same conversation, and deleting the old engine does not
take the evidence with it. The key stays in the run's client and is never written anywhere.
"""

import logging
import threading
import time

from agent_workspace.types import text_block
from ai_host.manager import WorkspaceManager
from runtime import account_context
from runtime.state import add_log

from i18n import t

logger = logging.getLogger(__name__)

_MANAGER = WorkspaceManager()
_COUNTER = threading.Lock()
_SEQ = 0
#: Persist at most one delta write per this interval per call. Each write opens a SQLite connection
#: and rewrites the whole (growing) transcript, so one write per token was O(n^2) bytes and risked
#: lock contention on API runs with several workers. 200 ms still looks live to the polling viewer.
_TRACE_FLUSH_MS = 200


def _account() -> str:
    current = account_context.current()
    return str(getattr(current, 'user_id', '') or 'default')


def _workspace():
    return _MANAGER.workspace(_account())


def _append(conversation_id: str, role: str, body: str, meta: dict, status: str = 'done') -> dict:
    """One durable trace row in the framework store; the turn id is the trace itself."""
    return _workspace().store.append_message(
        conversation_id, f'trace:{conversation_id}', role, [text_block(body)], meta, status=status
    )


def _next_suffix() -> int:
    global _SEQ
    with _COUNTER:
        _SEQ += 1
        return _SEQ


def start_node_trace(run_id: str, node_id: str, op: str, client, provider: str = '', model: str = ''):
    """Return ``(possibly wrapped client, conversation_id or '')``.

    Called from the ONE place that builds node run contexts. No run id (a direct API analysis call)
    means no conversation: there is no canvas run to attach it to.
    """
    run = str(run_id or '').strip()
    if not run:
        return client, ''
    try:
        return _start_trace(run, node_id, op, client, provider, model)
    except Exception as exc:
        # Tracing is a side effect of a paid node. A full/locked store must never stop the model
        # call — log the reason and hand the ORIGINAL client back so the analyzer runs unchanged.
        logger.warning(t('trace.unavailable', err=exc))
        return client, ''


def _start_trace(run: str, node_id: str, op: str, client, provider: str, model: str):
    provider = str(provider or getattr(client, 'provider', '') or '') if client is not None else provider
    model = str(model or getattr(client, 'model', '') or '') if client is not None else model
    workspace = _workspace()
    account = _account()
    suffix = _next_suffix()
    title = f'{run} | {node_id} | {op} #{suffix}'
    conversation = workspace.store.create_conversation(account, title=title)
    _append(
        conversation['id'],
        'assistant',
        f'run={run} | node={node_id} | op={op}\n' + t('trace.intro'),
        {
            'kind': 'trace_start',
            'skill': 'node_trace',
            'run_id': run,
            'node_id': node_id,
            'op': op,
            # Display-only labels for the "model that answered" chip. A traditional node's
            # provider label ("local BERT") is NOT a provider id, so it must never drive the
            # composer's provider picker — only this read-only chip may show it.
            'provider_label': provider,
            'model_label': model,
            'estimated': False,
        },
    )
    add_log(t('trace.opened', id=conversation['id'], node=node_id))
    if client is None:
        return client, conversation['id']
    return TraceClient(client, conversation['id'], run, node_id, op), conversation['id']


class TraceClient:
    """Drop-in wrapper: forward ``chat`` to the real client and record both sides."""

    def __init__(self, client, conversation_id: str, run_id: str, node_id: str, op: str = ''):
        self._client = client
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.node_id = node_id
        self.op = op

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _write(self, message_id: str, body: str, status: str | None = None, meta: dict | None = None) -> None:
        """One durable update; a store failure is logged and ignored, never raised into a model call."""
        fields = {'blocks': [text_block(body)]}
        if status is not None:
            fields['status'] = status
        if meta is not None:
            fields['meta'] = meta
        try:
            _workspace().store.update_message(message_id, **fields)
        except Exception as exc:
            logger.warning(t('trace.writeFailed', err=exc))

    def chat(self, prompt: str, max_retries: int = 2) -> str:
        meta = {
            'kind': 'trace_call',
            'skill': 'node_trace',
            'run_id': self.run_id,
            'node_id': self.node_id,
            'op': self.op,
            'estimated': True,
            'prompt_chars': len(str(prompt)),
        }
        try:
            _append(self.conversation_id, 'user', str(prompt), meta)
        except Exception as exc:
            logger.warning(t('trace.writeFailed', err=exc))

        stream_meta = dict(meta)
        stream_meta['node_trace_stream'] = True
        streamed = None
        try:
            streamed = _workspace().store.append_message(
                self.conversation_id, f'trace:{self.conversation_id}', 'assistant', [], stream_meta, status='streaming'
            )
        except Exception as exc:
            logger.warning(t('trace.writeFailed', err=exc))
        prompt_chars = int(meta['prompt_chars'])
        prefix = t('trace.streamingPrefix', prompt=prompt_chars, ptokens=prompt_chars // 2)
        chunks: list[str] = []
        last_flush = [0.0]

        def on_delta(text: str) -> None:
            chunks.append(str(text))
            now = time.monotonic()
            if streamed is not None and (now - last_flush[0]) * 1000 >= _TRACE_FLUSH_MS:
                last_flush[0] = now
                self._write(streamed['id'], prefix + ''.join(chunks))

        try:
            answer = self._client.chat(prompt, max_retries=max_retries, on_delta=on_delta)
        except Exception:
            if streamed is not None:
                self._write(streamed['id'], prefix + ''.join(chunks), status='interrupted')
            raise
        answer_chars = len(str(answer))
        meta['answer_chars'] = answer_chars
        note = t(
            'trace.usageNote',
            prompt=prompt_chars,
            ptokens=prompt_chars // 2,
            answer=answer_chars,
            atokens=answer_chars // 2,
        )
        if streamed is not None:
            self._write(streamed['id'], note + str(answer), status='done', meta=meta)
        return answer


_SAMPLE_ROWS = 2
_SAMPLE_CELL = 120
_SAMPLE_TOTAL = 1200


def _md_cell(value) -> str:
    """One Markdown table cell: escape pipes (the renderer's tableCells honours \\|), flatten newlines."""
    return str(value if value is not None else '').replace('\n', ' ').replace('|', '\\|')[:_SAMPLE_CELL]


def _in_out_sample(input_rows: list, output_rows: list) -> str:
    def render(label: str, rows: list) -> str:
        dict_rows = [row for row in rows[:_SAMPLE_ROWS] if isinstance(row, dict)]
        if not dict_rows:
            return ''
        columns = list(dict_rows[0].keys())[:6]
        lines = [f'**{label}**']
        lines.append('| ' + ' | '.join(_md_cell(c) for c in columns) + ' |')
        lines.append('| ' + ' | '.join('---' for _ in columns) + ' |')
        for row in dict_rows:
            lines.append('| ' + ' | '.join(_md_cell(row.get(c, '')) for c in columns) + ' |')
        return '\n'.join(lines)

    blocks = [
        b for b in (render(t('trace.sampleInput'), input_rows), render(t('trace.sampleOutput'), output_rows)) if b
    ]
    return '\n\n'.join(blocks)[:_SAMPLE_TOTAL]


def finish_node_trace(run_id: str, node_id: str, summary: dict) -> None:
    """Append the node's outcome to its trace conversation, with the rerun provenance attached."""
    run = str(run_id or '').strip()
    if not run:
        return
    try:
        _finish_trace(run, node_id, summary)
    except Exception as exc:
        logger.warning(t('trace.finishFailed', err=exc))


def _finish_trace(run: str, node_id: str, summary: dict) -> None:
    workspace = _workspace()
    for conversation in traces_for_run(run):
        title = str(conversation.get('title') or '')
        if f'| {node_id} |' not in title:
            continue
        messages = workspace.store.list_messages(conversation['id'], limit=400)
        has_chat = any((message.get('meta') or {}).get('kind') == 'trace_call' for message in messages)
        sample = '' if has_chat else _in_out_sample(summary.get('input_rows') or [], summary.get('output_rows') or [])
        if sample:
            _append(
                conversation['id'],
                'assistant',
                sample,
                {'kind': 'trace_sample', 'skill': 'node_trace', 'run_id': run, 'node_id': node_id, 'estimated': False},
            )
        closing = str(summary.get('text') or t('trace.resultDefault'))
        _append(
            conversation['id'],
            'assistant',
            closing,
            {
                'kind': 'trace_result',
                'skill': 'node_trace',
                'run_id': run,
                'node_id': node_id,
                'op': str(summary.get('op') or ''),
                'workflow_name': str(summary.get('workflow_name') or ''),
                'rows': int(summary.get('rows') or 0),
                'estimated': False,
            },
        )
        return


def traces_for_run(run_id: str) -> list[dict]:
    """Conversations opened by nodes of one run, newest first (title carries the run id)."""
    wanted = str(run_id or '').strip()
    if not wanted:
        return []
    rows = _workspace().store.list_conversations(_account(), query=wanted, limit=200)
    return [{**row, 'skill': 'node_trace'} for row in rows if str(row.get('title') or '').startswith(wanted + ' |')]
