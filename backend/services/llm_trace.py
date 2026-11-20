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
from ai.types import text_block
from runtime.state import add_log

from i18n import t

_COUNTER = threading.Lock()
_SEQ = 0


def _next_suffix() -> int:
    global _SEQ
    with _COUNTER:
        _SEQ += 1
        return _SEQ


def start_node_trace(run_id: str, node_id: str, op: str, client, provider: str = '', model: str = ''):
    """Return ``(possibly wrapped client, conversation_id or '')``.

    Called from the ONE place that builds node run contexts. No run id (a direct API analysis call)
    means no conversation: there is no canvas run to attach it to.

    ``provider``/``model`` override what is read off ``client``. Traditional local models (BERT,
    NLI, embeddings) have no LLM client with those attributes, so the caller stamps the resolved
    model identity here — this is what the AI workspace's bottom chip then displays. A node with no
    chat loop passes ``wrap=False`` semantics simply by not using the returned TraceClient; the
    conversation still records the intro/result.
    """
    run = str(run_id or '').strip()
    if not run:
        return client, ''
    provider = str(provider or getattr(client, 'provider', '') or '') if client is not None else provider
    model = str(model or getattr(client, 'model', '') or '') if client is not None else model
    conversation = store.create_conversation(provider=provider, model=model, skill='node_trace')
    suffix = _next_suffix()
    title = f'{run} | {node_id} | {op} #{suffix}'
    store.touch_conversation(conversation['id'], title=title, title_source='node')
    store.append_message(
        conversation['id'],
        'assistant',
        content=(f'run={run}\nnode={node_id}\nop={op}\nprovider={provider}\nmodel={model}\n\n' + t('trace.intro')),
        blocks=[text_block(f'run={run} | node={node_id} | op={op}\n' + t('trace.intro'))],
        meta={'kind': 'trace_start', 'run_id': run, 'node_id': node_id, 'op': op, 'estimated': False},
    )
    add_log(t('trace.opened', id=conversation['id'], node=node_id))
    # A traditional node has no chat client to wrap. It still gets the conversation (intro/result),
    # but we must not hand back a TraceClient whose inner client is None — any accidental chat call
    # would crash. Return the original (None) client so the analyzer's own path is untouched.
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

    def chat(self, prompt: str, max_retries: int = 2) -> str:
        meta = {
            'kind': 'trace_call',
            'run_id': self.run_id,
            'node_id': self.node_id,
            'op': self.op,
            'estimated': True,
            'prompt_chars': len(str(prompt)),
        }
        provider = str(getattr(self._client, 'provider', '') or '')
        model = str(getattr(self._client, 'model', '') or '')
        store.append_message(
            self.conversation_id, 'user', content=str(prompt), meta=meta, provider=provider, model=model
        )

        # Mirror the answer as it is GENERATED, not after it finished. The assistant row is born
        # 'streaming'; each token appends to its content and the final settle writes the token
        # estimate + answer_chars. A poll of this conversation (the demo deep link) then sees the
        # text grow token by token. The row runner still gets the FULL string back to parse.
        # A marker the boot/reader-disconnect sweep respects: those sweeps interrupt every
        # 'streaming' row, but a node-trace row is written by a background worker with no SSE
        # reader, so it must be spared until this worker settles it itself.
        stream_meta = dict(meta)
        stream_meta['node_trace_stream'] = True
        streamed = store.append_message(
            self.conversation_id,
            'assistant',
            content='',
            status='streaming',
            meta=stream_meta,
            provider=provider,
            model=model,
        )
        prompt_chars = int(meta['prompt_chars'])
        # The prompt-side estimate is known up front; prefix it during streaming so the text the
        # camera sees grow is the same text that finally settles (no note jumping in at the end).
        prefix = f'（本次调用估算：提示 {prompt_chars} 字 ≈ {prompt_chars // 2} token，回答生成中… 非账单数字）\n'
        chunks: list[str] = []

        def on_delta(text: str) -> None:
            chunks.append(str(text))
            body = prefix + ''.join(chunks)
            store.update_message(streamed['id'], content=body, blocks=[text_block(body)])

        try:
            answer = self._client.chat(prompt, max_retries=max_retries, on_delta=on_delta)
        except Exception:
            # A failed generation must not leave a half-written row looking live forever. Keep the
            # tokens that did arrive, mark it interrupted, then let the caller's error propagate.
            partial = prefix + ''.join(chunks)
            store.update_message(streamed['id'], content=partial, blocks=[text_block(partial)], status='interrupted')
            raise
        answer_chars = len(str(answer))
        meta['answer_chars'] = answer_chars
        note = (
            f'（本次调用估算：提示 {prompt_chars} 字 ≈ {prompt_chars // 2} token，'
            f'回答 {answer_chars} 字 ≈ {answer_chars // 2} token；非账单数字）\n'
        )
        final = note + str(answer)
        store.update_message(streamed['id'], content=final, blocks=[text_block(final)], status='done', meta=meta)
        return answer


_SAMPLE_ROWS = 2
_SAMPLE_CELL = 120
_SAMPLE_TOTAL = 1200


def _md_cell(value) -> str:
    """One Markdown table cell: escape pipes (the renderer's tableCells honours \\|), flatten newlines."""
    return str(value if value is not None else '').replace('\n', ' ').replace('|', '\\|')[:_SAMPLE_CELL]


def _in_out_sample(input_rows: list, output_rows: list) -> str:
    """A short, bounded "input → output" excerpt as MARKDOWN TABLES for a traditional model's trace.

    The rows are tabular data, so render them as tables — the AI workspace's safe Markdown renderer
    turns `|` rows into `<table class="ai-table">` (escaping cell text first). Only the first couple
    of rows and six columns are shown: this is a sample for a human to sanity-check what ran, not the
    whole table (those rows live in the run store). Every cell is capped so one long comment cannot
    flood the conversation.
    """

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

    blocks = [b for b in (render('输入样本', input_rows), render('输出样本', output_rows)) if b]
    text = '\n\n'.join(blocks)
    return text[:_SAMPLE_TOTAL]


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
        # Traditional-model nodes have no chat loop, so show a bounded in/out sample — the exact
        # text the model saw and what it produced. This is what makes their trace auditable rather
        # than an empty shell. LLM nodes already carry their full prompts/answers as trace_calls,
        # so they skip this (no input_rows passed).
        sample = _in_out_sample(summary.get('input_rows') or [], summary.get('output_rows') or [])
        if sample:
            store.append_message(
                conversation['id'],
                'assistant',
                content=sample,
                blocks=[text_block(sample)],
                meta={'kind': 'trace_sample', 'run_id': run, 'node_id': node_id, 'estimated': False},
            )
        store.append_message(
            conversation['id'],
            'assistant',
            content=str(summary.get('text') or '节点已完成；如不满意，请继续在对话里修改，再确认重跑。'),
            blocks=[text_block(str(summary.get('text') or '节点已完成；如不满意，请继续在对话里修改，再确认重跑。'))],
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
