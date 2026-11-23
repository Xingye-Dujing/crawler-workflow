"""Node traces live in the agent-workspace store: same conversation the run console reads.

The legacy sweep is gone with the legacy store; the framework's boot recovery settles a row a killed
worker left behind, and a live worker keeps writing because nothing sweeps during a run.
"""

from __future__ import annotations

import uuid

import pytest
from ai_host.manager import WorkspaceManager

from services import llm_trace

pytestmark = pytest.mark.unit


class FakeClient:
    provider = 'deepseek'
    model = 'deepseek-chat'

    def __init__(self):
        self.prompts = []

    def chat(self, prompt, max_retries=2, on_delta=None):
        self.prompts.append(prompt)
        if on_delta:
            on_delta('half ')
            on_delta('answer')
        return 'half answer'


def _run_id() -> str:
    return 'run_' + uuid.uuid4().hex[:10]


def _messages(conversation_id: str) -> list[dict]:
    return WorkspaceManager().workspace('default').store.list_messages(conversation_id)


class TestAnLlmTrace:
    def test_the_prompt_and_answer_are_rows_in_one_conversation(self):
        run = _run_id()
        client, conversation_id = llm_trace.start_node_trace(run, 'n1', 'clean', FakeClient())
        assert conversation_id
        client.chat('please clean this')
        rows = _messages(conversation_id)
        kinds = [(row['role'], (row['meta'] or {}).get('kind')) for row in rows]
        assert kinds[0] == ('assistant', 'trace_start')
        assert ('user', 'trace_call') in kinds
        assistant = [row for row in rows if row['role'] == 'assistant' and row['meta'].get('kind') == 'trace_call']
        assert assistant and assistant[-1]['status'] == 'done'
        assert 'half answer' in assistant[-1]['blocks'][0]['text']
        assert rows[0]['meta']['skill'] == 'node_trace'

    def test_traces_for_run_lists_the_conversation(self):
        run = _run_id()
        _client, conversation_id = llm_trace.start_node_trace(run, 'n2', 'topic', FakeClient())
        found = llm_trace.traces_for_run(run)
        assert [row['id'] for row in found] == [conversation_id]
        assert found[0]['skill'] == 'node_trace'

    def test_the_result_carries_the_rerun_provenance(self):
        run = _run_id()
        llm_trace.start_node_trace(run, 'n3', 'clean', FakeClient())
        llm_trace.finish_node_trace(run, 'n3', {'text': 'finished', 'rows': 2, 'workflow_name': 'wf', 'op': 'clean'})
        conversation = llm_trace.traces_for_run(run)[0]
        result = [row for row in _messages(conversation['id']) if row['meta'].get('kind') == 'trace_result'][0]
        assert result['meta']['run_id'] == run
        assert result['meta']['node_id'] == 'n3'
        assert result['meta']['workflow_name'] == 'wf'
        assert result['blocks'][0]['text'] == 'finished'


class TestATraditionalModel:
    def test_no_client_still_gets_a_conversation_and_an_in_out_sample(self):
        run = _run_id()
        client, conversation_id = llm_trace.start_node_trace(run, 'n4', 'bert', None, provider='local BERT')
        assert client is None and conversation_id
        llm_trace.finish_node_trace(
            run,
            'n4',
            {
                'text': 'classified',
                'input_rows': [{'正文': '甲', '平台': 'weibo'}],
                'output_rows': [{'正文': '甲', 'emotion': '喜'}],
            },
        )
        rows = _messages(conversation_id)
        sample = [row for row in rows if row['meta'].get('kind') == 'trace_sample']
        assert sample and '| 正文 |' in sample[0]['blocks'][0]['text']
        assert [row for row in rows if row['meta'].get('kind') == 'trace_result']
