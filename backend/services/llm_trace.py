"""One generic trace seam for EVERY node that calls an LLM provider.

A node never opens a conversation itself. ``build_llm_run_ctx`` wraps the run's client once, so an
API-backed step -- cleaning, stance labels, topic labels, NER, aggression, qualitative coding, and
anything added later -- automatically gets a temporary AI-workspace conversation showing the exact
prompt and answer. New nodes need no new branch here; they only have to use the shared run context.

The key stays in the run's client and is never written to ai.db. Token figures are estimates because
the row client does not expose provider usage; the message meta says `estimated: true` so nobody
mistakes them for billed units.
"""

import threading

from ai import store
from runtime.state import add_log

from i18n import t

_COUNTER = threading.Lock()
_SEQ = 0


def _next_suffix() -> int:
    global _SEQ
    with _COUNTER:
        _SEQ += 1
        return _SEQ


def start_node_trace(run_id: str, node_id: str, op: str, client):
    """Return ``(possibly wrapped client, conversation_id or '')``.

    Called from the ONE place that builds LLM run contexts. No run id (a direct API analysis call)
    means no conversation: there is no canvas run to attach it to.
    """
    run = str(run_id or '').strip()
    if not run or client is None:
        return client, ''
    conversation = store.create_conversation(
        provider=str(getattr(client, 'provider', '') or ''),
        model=str(getattr(client, 'model', '') or ''),
        skill='node_trace',
    )
    suffix = _next_suffix()
    title = f'{run} | {node_id} | {op} #{suffix}'
    store.touch_conversation(conversation['id'], title=title, title_source='node')
    store.append_message(
        conversation['id'],
        'assistant',
        content=(
            f'run={run}\nnode={node_id}\nop={op}\n'
            f'provider={getattr(client, "provider", "")}\nmodel={getattr(client, "model", "")}\n\n' + t('trace.intro')
        ),
        meta={'kind': 'trace_start', 'run_id': run, 'node_id': node_id, 'op': op, 'estimated': False},
    )
    add_log(t('trace.opened', id=conversation['id'], node=node_id))
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

    def chat(self, prompt: str, max_retries: int = 2) -> str:
        answer = self._client.chat(prompt, max_retries=max_retries)
        meta = {
            'kind': 'trace_call',
            'run_id': self.run_id,
            'node_id': self.node_id,
            'op': self.op,
            'estimated': True,
            'prompt_chars': len(str(prompt)),
            'answer_chars': len(str(answer)),
        }
        provider = str(getattr(self._client, 'provider', '') or '')
        model = str(getattr(self._client, 'model', '') or '')
        store.append_message(
            self.conversation_id, 'user', content=str(prompt), meta=meta, provider=provider, model=model
        )
        store.append_message(
            self.conversation_id, 'assistant', content=str(answer), meta=meta, provider=provider, model=model
        )
        return answer


def finish_node_trace(run_id: str, node_id: str, summary: dict) -> None:
    """Append the node's outcome to its trace conversation, with the rerun provenance attached.

    Called from the engine after a node settles, so every LLM-backed node gets the same closing
    message without knowing anything about conversations. The payload is a small SUMMARY, never the
    whole result table; the user edits the result in the conversation and applies it explicitly.
    """
    run = str(run_id or '').strip()
    if not run:
        return
    for conversation in traces_for_run(run):
        title = str(conversation.get('title') or '')
        if f'| {node_id} |' not in title:
            continue
        store.append_message(
            conversation['id'],
            'assistant',
            content=str(summary.get('text') or '节点已完成；如不满意，请继续在对话里修改，再确认重跑。'),
            meta={
                'kind': 'trace_result',
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
    return [
        row
        for row in store.list_conversations(limit=200, q=wanted)
        if row.get('skill') == 'node_trace' and str(row.get('title') or '').startswith(wanted + ' |')
    ]
