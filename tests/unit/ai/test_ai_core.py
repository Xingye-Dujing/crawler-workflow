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
    assert deepseek.supports('files', 'deepseek-flash')
    assert not deepseek.supports('files', 'deepseek-v4-pro')
    assert not go.supports('web_search', 'deepseek-v4.1-flash')
    assert not go.supports('files', 'deepseek-v4.1-flash')


def test_cloud_refuses_only_the_local_transport(monkeypatch):
    from ai.providers.registry import local_transport_refusal, public_catalog
    from core.config import Config

    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    assert local_transport_refusal('ollama')
    assert local_transport_refusal('deepseek') == ''
    assert local_transport_refusal('opencode_go') == ''
    catalog = {item['id']: item for item in public_catalog()}
    assert catalog['ollama']['local_available'] is False
    assert catalog['ollama']['why_not_text']
    assert catalog['deepseek']['local_available'] is True


def test_deepseek_wire_keeps_thinking_and_tool_pairs():
    from ai.errors import AIError
    from ai.providers.deepseek import to_messages

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
    wire = to_messages(messages)
    # The Chat Completions shape: reasoning is a sibling field it must be replayed in when the
    # turn carries tools, and the call/result pair is ``tool_calls`` then a ``tool`` message.
    assert wire[1]['reasoning_content'] == 'I should ask.'
    assert wire[1]['tool_calls'][0]['function']['name'] == 'ask_user_question'
    assert wire[2]['role'] == 'tool' and wire[2]['tool_call_id'] == 'call_1'
    with pytest.raises(AIError):
        to_messages(messages[:2])


def test_deepseek_wire_includes_file_references():
    from ai.providers.deepseek import to_messages

    messages = [
        {
            'role': 'user',
            'content': 'what is this?',
            'meta': {'attachments': [{'file_id': 'file-api-1', 'kind': 'image', 'name': 'a.png'}]},
        }
    ]
    wire = to_messages(messages)
    assert wire[0]['content'][0] == {'type': 'file', 'file_id': 'file-api-1'}
    assert wire[0]['content'][1]['type'] == 'text'


def test_context_prefix_is_added_to_the_last_user_turn_only():
    from ai.providers.base import with_context
    from ai.providers.deepseek import to_messages

    messages = [
        {'role': 'user', 'content': 'first', 'meta': {}},
        {'role': 'assistant', 'content': '', 'name': '', 'meta': {}, 'blocks': [{'type': 'text', 'text': 'ok'}]},
        {'role': 'user', 'content': 'second', 'meta': {}},
    ]
    wire = to_messages(with_context(messages, 'FACTS'))
    assert '<cai_xi_hui_context>' not in wire[0]['content']
    assert '<cai_xi_hui_context>' in wire[-1]['content'] and 'FACTS' in wire[-1]['content']


def test_the_context_reaches_every_transport():
    """It used to be read by the DeepSeek transport alone, so a LOCAL turn sent none of it while the
    panel advertised the character count — the model then answered about a canvas it never saw."""
    from ai.providers import base, ollama, openai_compat
    from ai.providers.deepseek import to_messages as deepseek_messages

    messages = base.with_context([{'role': 'user', 'content': '画布有什么问题？', 'meta': {}}], 'FACTS-2320')
    for wire in (
        deepseek_messages(messages),
        openai_compat.to_messages('system', messages),
        ollama.OllamaProvider()._messages({'messages': messages}),
    ):
        text = [row for row in wire if row['role'] == 'user'][-1]['content']
        assert 'FACTS-2320' in text and '<cai_xi_hui_context>' in text, wire


def test_a_tool_call_whose_arguments_never_arrived_is_refused_not_run(monkeypatch):
    """A stream cut by `max_tokens` leaves half a JSON document. Running it with {} made the TOOL
    refuse for the wrong reason; the turn must say the arguments were cut."""
    from ai import agent, store, tools

    conversation = store.create_conversation('deepseek', 'deepseek-flash', 'auto')
    user = store.append_message(conversation['id'], 'user', 'build it', status='done')
    run = store.create_run(conversation['id'], user['id'])
    executed = []
    monkeypatch.setattr(tools, 'execute', lambda *args, **kwargs: executed.append(args) or {'ok': True})
    call = {'id': 'call_cut', 'name': 'apply_workflow', 'arguments': {}, 'parse_error': True}
    events = list(
        agent.AgentService()._tool_event(
            conversation,
            {'message': {'meta': {'run_id': run['id']}}},
            call,
            'turn_cut',
            '',
            'deepseek',
            'deepseek-flash',
            {'apply_workflow'},
        )
    )
    assert executed == [], 'a truncated call was executed with empty arguments'
    result = [event for event in events if event['type'] == 'tool_result'][-1]
    assert result['ok'] is False and result['error'], result
    stored = [row for row in store.list_messages(conversation['id']) if row['role'] == 'tool']
    assert stored and stored[-1]['meta']['is_error'] is True


def test_a_rate_limit_is_retried_before_the_stream_starts(monkeypatch):
    """`retries` defaulted to 1, which made the whole backoff branch dead code: one 429 ended the
    turn and the user had to press retry by hand."""
    from ai.errors import AIProviderError
    from ai.providers import base

    monkeypatch.setattr(base, '_nap', lambda *args: False)
    calls = []

    class _Answer:
        status_code = 200
        text = ''

    def fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return _HttpAnswer(429, '{"error":"slow down"}')
        return _Answer()

    monkeypatch.setattr(base.requests, 'post', fake_post)
    response = base.open_stream('https://example.invalid/chat', {}, {}, 5, None)
    assert response.status_code == 200 and len(calls) == 2

    # A deterministic refusal is not retried: an auth failure answers the same thing every time.
    calls.clear()

    def bad_key(*args, **kwargs):
        calls.append(1)
        return _HttpAnswer(401, '{"error":"bad key"}')

    monkeypatch.setattr(base.requests, 'post', bad_key)
    with pytest.raises(AIProviderError) as refusal:
        base.open_stream('https://example.invalid/chat', {}, {}, 5, None)
    assert refusal.value.kind == 'auth' and len(calls) == 1


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


def test_the_project_facts_name_each_platforms_modes_without_empty_commas():
    """The 采集平台 block printed `- zhihu: , ,` for every platform: it read `mode['mode']`, a key
    the capability payload no longer carries, and joined the blanks."""
    from ai.context import project_facts

    lines = project_facts().splitlines()
    platforms = [line for line in lines if line.startswith('- ') and '：' in line]
    assert platforms, 'the context named no platform at all'
    assert not [line for line in platforms if '：, ' in line or line.rstrip().endswith('：')], platforms
    zhihu = next((line for line in platforms if line.startswith('- zhihu')), '')
    assert 'posts' in zhihu and '模式' in zhihu, zhihu
    assert 'selenium' in zhihu, f'the available engine is not named: {zhihu}'


def test_the_wire_sends_fetch_only_with_the_search_switch():
    from ai.providers import get_provider

    provider = get_provider('deepseek')
    model = next(spec.id for spec in provider.spec.models if 'read_url' in spec.capabilities)

    def tools_for(web_search: bool) -> list:
        payload = provider._payload(
            {
                'provider': 'deepseek',
                'model': model,
                'api_key': 'k',
                'messages': [{'role': 'user', 'content': 'x', 'meta': {}}],
                'thinking': False,
                'web_search': web_search,
                'tools': [],
            }
        )
        return [tool.get('type') or tool.get('name') for tool in payload.get('tools') or []]

    assert 'deepseek_read_url' not in tools_for(False)
    assert 'deepseek_read_url' in tools_for(True)
    assert 'deepseek_web_search' in tools_for(True)


class _HttpAnswer:
    def __init__(self, status: int, body: str):
        self.status_code = status
        self.text = body
        self.closed = False

    def close(self):
        self.closed = True

    def json(self):
        import json

        return json.loads(self.text)


def test_listing_models_with_a_key_reports_the_providers_answer(monkeypatch):
    from ai.errors import AIProviderError
    from ai.providers import deepseek as transport
    from ai.providers import get_provider

    provider = get_provider('deepseek')
    monkeypatch.setattr(transport.requests, 'get', lambda *args, **kwargs: _HttpAnswer(401, '{"error":"bad key"}'))
    with pytest.raises(AIProviderError) as refusal:
        provider.list_models('not-a-key')
    assert refusal.value.status == 401
    # Without a key there is nothing to ask: the static catalogue is the honest answer.
    assert provider.list_models('')


def test_environment_separates_desktop_local_web_and_cloud(monkeypatch):
    from ai import environment
    from core import machine
    from core.config import Config

    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(machine, 'is_frozen', lambda: False)
    local = environment.capabilities()
    assert local['kind'] == 'local_web' and local['local_source'] and local['ollama']
    monkeypatch.setattr(machine, 'is_frozen', lambda: True)
    desktop = environment.capabilities()
    assert desktop['kind'] == 'desktop' and desktop['user_files'] and not desktop['local_source']
    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    cloud = environment.capabilities()
    assert cloud['kind'] == 'cloud' and not cloud['user_files'] and not cloud['code_plugins']
    # A cloud host runs from a checkout too; the deploy shape must not hand it the server source.
    assert not cloud['local_source'] and environment.code_root() == ''


def test_every_host_keeps_the_complete_workspace(monkeypatch):
    """The three shapes differ only in host powers, never in the workspace's own features.

    A packaged desktop and a cloud page each must keep chat, files, search, sessions, skills and
    declarative plugins; otherwise "the desktop has AI" would be a half-workspace claim.
    """
    from ai import environment
    from core import machine
    from core.config import Config

    shared = ('chat', 'sessions', 'skills', 'declarative_plugins', 'files_api', 'web_search')
    shapes = []
    for cloud, frozen in ((False, False), (False, True), (True, False)):
        monkeypatch.setattr(Config, 'CLOUD_MODE', cloud)
        monkeypatch.setattr(machine, 'is_frozen', lambda frozen=frozen: frozen)
        caps = environment.capabilities()
        assert all(caps[name] is True for name in shared), (caps['kind'], caps)
        shapes.append(caps['kind'])
    assert shapes == ['local_web', 'desktop', 'cloud']


def test_the_prompt_never_grants_source_to_a_bundled_or_cloud_host(monkeypatch):
    from ai import environment
    from core import machine
    from core.config import Config

    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(machine, 'is_frozen', lambda: True)
    desktop = environment.prompt_line()
    assert 'read-only source snapshot' in desktop and 'cannot change the running program' in desktop
    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    line = environment.prompt_line()
    assert 'no local model daemon' in line and 'no user-local filesystem' in line
    assert 'repository source' in line
    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(machine, 'is_frozen', lambda: False)
    assert 'repository source' in environment.prompt_line()
    assert 'local_source' in environment.feature_words()


def test_developer_skill_is_only_available_where_source_is(monkeypatch):
    from ai import skills
    from ai.providers import get_provider
    from core import machine
    from core.config import Config

    monkeypatch.setattr(Config, 'CLOUD_MODE', False)
    monkeypatch.setattr(machine, 'is_frozen', lambda: False)
    monkeypatch.setattr(skills, 'get_setting', lambda key: True if key == 'ai_allow_code_context' else '')
    assert skills.availability(skills.BUILTIN['developer'], get_provider('deepseek'))[0] is True
    monkeypatch.setattr(machine, 'is_frozen', lambda: True)
    available, reason = skills.availability(skills.BUILTIN['developer'], get_provider('deepseek'))
    assert available is False and reason.startswith('ai.skillCodeLocal')
    # The same switch on a cloud source deploy is still a refusal by name: the verdict comes from
    # the host kind, not from "is this a checkout".
    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    monkeypatch.setattr(machine, 'is_frozen', lambda: False)
    available, reason = skills.availability(skills.BUILTIN['developer'], get_provider('deepseek'))
    assert available is False and reason.startswith('ai.skillCodeLocal')


def test_a_tool_the_turn_never_offered_is_refused_at_execution_time():
    """A replayed ``tool_use`` can name a tool this turn's schema list does not contain."""
    from ai import tools
    from ai.errors import AIError

    with pytest.raises(AIError) as refusal:
        tools.execute('project_facts', {}, {}, allowed={'run_status'})
    assert refusal.value.key == 'ai.toolRefused'
    assert refusal.value.params.get('reason') == 'not offered in this turn'


def test_source_reads_need_the_users_code_switch(monkeypatch):
    from ai import tools
    from ai.errors import AIError

    monkeypatch.setattr(tools, 'get_setting', lambda key: False if key == 'ai_allow_code_context' else '')
    with pytest.raises(AIError) as refusal:
        tools.execute('code_read', {'path': 'app.py'}, {}, allowed={'code_read'})
    assert refusal.value.key == 'ai.codeCloudRefused'


def test_python_tools_are_refused_on_a_cloud_host(monkeypatch):
    from ai import tools
    from ai.errors import AIError
    from core.config import Config

    monkeypatch.setattr(tools, 'get_setting', lambda key: True)
    monkeypatch.setattr(Config, 'CLOUD_MODE', True)
    with pytest.raises(AIError) as refusal:
        tools.execute('python_scripts', {}, {}, allowed={'python_scripts'})
    assert refusal.value.key == 'ai.pythonCloud'


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
