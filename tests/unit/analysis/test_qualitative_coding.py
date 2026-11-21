"""Grounded-theory coding contracts and the generic node-LLM trace seam.

No provider is called: parsers are fed deterministic strings and the trace store is a recording
fake. What is pinned is the three-phase contract, codebook versioning, and that every API-backed
node gets the same visible-conversation wrapper from the shared run context.
"""

import pandas as pd
import pytest
from core.config import Config

from analyzers import qualitative
from services.coding import codebooks
from services.llm_trace import start_node_trace, traces_for_run

pytestmark = pytest.mark.unit


def test_open_parser_reads_code_and_evidence_lines():
    answer = '焦虑 | 这让我很焦虑\n讨论 | 大家一起讨论一下'
    codes, quotes = qualitative.parse_open(answer)
    assert codes == '焦虑|讨论'
    assert quotes == '这让我很焦虑\n大家一起讨论一下'


def test_aggregate_counts_codes_and_keeps_one_evidence_quote():
    frame = pd.DataFrame({'open_codes': ['焦虑|讨论', '焦虑'], 'evidence': ['很焦虑\n一起讨论', '有点焦虑']})
    rows = qualitative.aggregate_open_codes(frame)
    assert rows[0] == {'code': '焦虑', 'count': 2, 'evidence': '很焦虑'}
    assert rows[1]['code'] == '讨论'


def test_axial_parser_groups_known_codes_only():
    book = {'codes': [{'code': '焦虑', 'count': 3}, {'code': '讨论', 'count': 2}], 'phase': 'open'}
    answer = '风险感知 | 情绪反应 | 焦虑 | 表现为担忧\n公共参与 | 互动 | 讨论 | 形成共识'
    result = qualitative.parse_axial(answer, book)
    assert result['phase'] == 'axial'
    assert result['categories'][0]['subcategories'][0]['codes'] == ['焦虑']


def test_selective_parser_refuses_a_malformed_answer():
    book = {'categories': [{'name': '风险感知'}]}
    with pytest.raises(qualitative.CodingError, match='CORE|MEMO|核心'):
        qualitative.parse_selective('没有结构', book)


def test_codebook_saves_versions_and_lists(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))
    first = codebooks.save_codebook({'name': '第一版', 'phase': 'open', 'codes': [{'code': '焦虑'}]})
    second = codebooks.save_codebook({'id': first['id'], 'name': '第一版', 'phase': 'axial', 'codes': []})
    assert (first['version'], second['version']) == (1, 2)
    assert [row['id'] for row in codebooks.list_codebooks()] == [first['id']]
    assert codebooks.load_codebook(first['id'])['version'] == 2
    assert codebooks.delete_codebook(first['id']) is True


class FakeClient:
    provider = 'ollama'
    model = 'qwen3.5:2b'

    def __init__(self, chunks=None):
        self.chunks = chunks

    def chat(self, prompt, max_retries=2, on_delta=None):
        answer = '回答:' + prompt[:5]
        if on_delta is not None:
            # Emit the answer in pieces, the way a provider stream yields text_delta events.
            for chunk in self.chunks or [answer[:3], answer[3:]]:
                on_delta(chunk)
        return answer


class FakeStore:
    def __init__(self):
        self.conversations = []
        self.messages = []
        self.updates = []

    def create_conversation(self, provider='', model='', skill='auto'):
        row = {'id': f'c{len(self.conversations)}', 'provider': provider, 'model': model, 'skill': skill, 'title': ''}
        self.conversations.append(row)
        return row

    def touch_conversation(self, conversation_id, **fields):
        row = next(item for item in self.conversations if item['id'] == conversation_id)
        row.update(fields)

    def append_message(self, conversation_id, role, content='', **fields):
        mid = f'm{len(self.messages) + 1}'
        row = {
            'id': mid,
            'conversation_id': conversation_id,
            'role': role,
            'content': content,
            '_born_status': fields.get('status', 'done'),
            **fields,
        }
        self.messages.append(row)
        return row

    def update_message(self, message_id, **fields):
        row = next(item for item in self.messages if item['id'] == message_id)
        row.update(fields)
        self.updates.append((message_id, fields.get('content'), fields.get('status')))
        return row

    def list_conversations(self, limit=80, q='', **kwargs):
        return [row for row in self.conversations if q in str(row.get('title') or '')]


def test_trace_client_records_both_sides_without_touching_the_key(monkeypatch):
    import services.llm_trace as trace

    fake = FakeStore()
    monkeypatch.setattr(trace, 'store', fake)
    monkeypatch.setattr(trace, 'add_log', lambda msg: None)
    client, conversation_id = start_node_trace('r1', 'n2', 'open_code', FakeClient())
    assert conversation_id == 'c0'
    assert 'r1' in fake.conversations[0]['title']
    assert client.chat('提示词') == '回答:提示词'
    assert [item['role'] for item in fake.messages[1:]] == ['user', 'assistant']
    assert fake.messages[1]['content'] == '提示词'
    assert fake.messages[2]['content'].endswith('回答:提示词')
    assert '估算' in fake.messages[2]['content']
    assert fake.messages[2]['status'] == 'done'
    assert all(item['meta'].get('estimated') is True for item in fake.messages[1:])
    assert traces_for_run('r1') and not traces_for_run('other')


def test_trace_streams_answer_deltas_then_settles(monkeypatch):
    """The trace mirror buffers token deltas, then settles the row with the estimate."""
    import services.llm_trace as trace

    fake = FakeStore()
    monkeypatch.setattr(trace, 'store', fake)
    monkeypatch.setattr(trace, 'add_log', lambda msg: None)
    client, _ = start_node_trace('r2', 'n3', 'open_code', FakeClient(chunks=['体验', '卡顿', ' | 很卡']))
    assert client.chat('提示词') == '回答:提示词'

    assistant = fake.messages[2]
    assert assistant['_born_status'] == 'streaming', 'the trace row is born streaming'
    # Deltas are flushed at most every TRACE_FLUSH_MS, so three instant chunks produce at most
    # three intermediate writes — never one DB write per token. The final settle is always 'done'
    # and carries the full answer, so nothing is lost even when a chunk arrived between flushes.
    deltas = [content for _, content, status in fake.updates if status is None]
    assert len(deltas) <= 3
    assert assistant['content'].endswith('回答:提示词')
    assert '估算' in assistant['content']
    assert assistant['status'] == 'done'
    assert any(status == 'done' for _, _, status in fake.updates), 'a final settle writes the estimate'


def test_no_run_id_means_no_trace(monkeypatch):
    import services.llm_trace as trace

    fake = FakeStore()
    monkeypatch.setattr(trace, 'store', fake)
    client, conversation_id = start_node_trace('', 'n2', 'clean', FakeClient())
    assert isinstance(client, FakeClient) and conversation_id == ''
    assert not fake.conversations
