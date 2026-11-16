"""Pure checks on the AI workspace's one catalog, serializer, context and store."""

import pytest

pytestmark = pytest.mark.unit


def test_provider_catalog_and_row_client_agree():
    from ai.providers import PROVIDERS
    from ai.providers.registry import ORDER

    from analyzers.llm_client import LLMClient

    assert set(PROVIDERS) == set(ORDER)
    assert set(LLMClient.PROVIDERS) == set(PROVIDERS)


def test_deepseek_has_the_full_suite_and_go_does_not_pretend():
    from ai.providers import get_provider

    deepseek = get_provider('deepseek')
    go = get_provider('opencode_go')
    assert deepseek.supports('web_search', 'deepseek-flash')
    assert deepseek.supports('safety', 'deepseek-flash')
    assert not deepseek.supports('files', 'deepseek-flash')
    assert not go.supports('web_search', 'deepseek-v4.1-flash')
    assert not go.supports('files', 'deepseek-v4.1-flash')


def test_cloud_refuses_only_the_local_transport(monkeypatch):
    from ai.providers.registry import local_transport_refusal
    from core.config import Config

    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    assert local_transport_refusal('ollama')
    assert local_transport_refusal('deepseek') == ''
    assert local_transport_refusal('opencode_go') == ''


def test_deepseek_wire_keeps_thinking_and_tool_pairs():
    from ai.errors import AIError
    from ai.providers.deepseek import to_wire_messages

    messages = [
        {'role': 'user', 'content': 'which data?', 'meta': {}},
        {
            'role': 'assistant',
            'content': '',
            'meta': {},
            'blocks': [
                {'type': 'thinking', 'thinking': 'I should ask.', 'signature': 'sig'},
                {'type': 'tool_use', 'id': 'call_1', 'name': 'ask_user_question', 'input': {'questions': []}},
            ],
        },
        {'role': 'tool', 'content': '{"answers":[]}', 'tool_call_id': 'call_1', 'meta': {}},
    ]
    wire = to_wire_messages(messages)
    assert wire[1]['content'][0]['type'] == 'thinking'
    assert wire[1]['content'][1]['type'] == 'tool_use'
    assert wire[2]['content'][0]['type'] == 'tool_result'
    with pytest.raises(AIError):
        to_wire_messages(messages[:2])


def test_context_prefix_is_added_to_the_last_user_turn_only():
    from ai.providers.deepseek import to_wire_messages

    messages = [
        {'role': 'user', 'content': 'first', 'meta': {}},
        {'role': 'assistant', 'content': '', 'name': '', 'meta': {}, 'blocks': [{'type': 'text', 'text': 'ok'}]},
        {'role': 'user', 'content': 'second', 'meta': {}},
    ]
    wire = to_wire_messages(messages, context_text='FACTS')
    first = wire[0]['content'][0]['text']
    second = wire[-1]['content'][0]['text']
    assert '<cai_xi_hui_context>' not in first
    assert '<cai_xi_hui_context>' in second and 'FACTS' in second


def test_redaction_removes_keys_from_context():
    from ai.context import redact

    text = redact('key sk-abcdefghijklmnop and oc_sk_1234567890 and Bearer abcdefghijklmnop')
    assert 'sk-abcdefghijklmnop' not in text
    assert 'oc_sk_1234567890' not in text
    assert 'Bearer abcdefghijklmnop' not in text


def test_context_off_returns_no_project_text():
    from ai.context import build_context

    text, meta = build_context('anything', {'scope': 'off'})
    assert text == ''
    assert meta['scope'] == 'off'


def test_research_is_unavailable_on_a_provider_without_web_search():
    from ai import skills
    from ai.providers import get_provider

    available, reason = skills.availability(skills.BUILTIN['research'], get_provider('opencode_go'))
    assert available is False
    assert reason.startswith('ai.skillUnavailable')


def test_router_names_the_skill_it_chose():
    from ai import skills

    assert skills.route('这个运行为什么失败？') == 'diagnose'
    assert skills.route('这份数据适合什么图？') == 'charts'
    assert skills.route('帮我搭一个工作流') == 'workflow'


def test_store_uses_max_seq_and_round_trips_blocks():
    from ai import store

    conversation = store.create_conversation('fake', 'fake-model', 'project')
    try:
        first = store.append_message(conversation['id'], 'user', 'hello', meta={'turn_id': 't1'})
        second = store.append_message(conversation['id'], 'assistant', '', blocks=[{'type': 'text', 'text': 'hi'}])
        third = store.append_message(conversation['id'], 'tool', '{}', meta={'tool_call_id': 'call_1'})
        assert [first['seq'], second['seq'], third['seq']] == [1, 2, 3]
        assert second['blocks'] == [{'type': 'text', 'text': 'hi'}]
        assert third['meta']['tool_call_id'] == 'call_1'
        loaded = store.list_messages(conversation['id'])
        assert [message['id'] for message in loaded] == [first['id'], second['id'], third['id']]
    finally:
        store.delete_conversation(conversation['id'])
