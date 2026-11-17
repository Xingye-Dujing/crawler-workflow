"""Balance, per-conversation spend and the model a conversation used.

No network: DeepSeek's ``/user/balance`` and the usage rows are answered by fakes, and the point is
that money is the PROVIDER's number (tokens are facts, a price is a published list).
"""

import pytest

pytestmark = pytest.mark.api


@pytest.fixture
def clean_ai():
    from ai import store

    store.mark_interrupted()
    yield


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = '{}'

    def json(self):
        return self._payload


def test_the_balance_route_asks_deepseek_with_the_browsers_key(client, monkeypatch, clean_ai):
    from ai.providers import deepseek

    seen = {}

    def fake_get(url, **kwargs):
        seen['url'] = url
        seen['auth'] = (kwargs.get('headers') or {}).get('Authorization')
        return FakeResponse(
            {
                'is_available': True,
                'balance_infos': [
                    {
                        'currency': 'CNY',
                        'total_balance': '110.25',
                        'granted_balance': '10.00',
                        'topped_up_balance': '100.25',
                    }
                ],
            }
        )

    monkeypatch.setattr(deepseek.requests, 'get', fake_get)
    body = client.get('/api/ai/providers/deepseek/balance', headers={'X-Provider-Key': 'sk-test'}).get_json()
    assert body['ok'] is True and body['supported'] is True
    assert body['balances'][0]['total'] == 110.25
    assert body['balances'][0]['currency'] == 'CNY'
    assert seen['url'].endswith('/user/balance')
    assert seen['auth'] == 'Bearer sk-test'


def test_a_provider_without_a_balance_endpoint_says_so(client):
    body = client.get('/api/ai/providers/ollama/balance').get_json()
    assert body['ok'] is True and body['supported'] is False


def test_no_key_means_no_balance_and_no_request(client, monkeypatch, clean_ai):
    from ai.providers import deepseek

    def boom(*_a, **_k):
        raise AssertionError('a balance request without a key')

    monkeypatch.setattr(deepseek.requests, 'get', boom)
    body = client.get('/api/ai/providers/deepseek/balance').get_json()
    assert body['ok'] is True and body['supported'] is False


def test_the_session_cost_is_priced_from_the_providers_own_table(client, clean_ai):
    from ai import costs, store

    conversation = store.create_conversation('deepseek', 'deepseek-flash', 'auto')
    store.save_usage(
        conversation['id'],
        'm1',
        'deepseek',
        'deepseek-flash',
        {'prompt_tokens': 1000, 'completion_tokens': 100, 'cached_tokens': 800},
    )
    report = costs.conversation_cost(conversation['id'])
    assert report['prompt_tokens'] == 1000
    assert report['completion_tokens'] == 100
    assert report['cache_hit_rate'] == 0.8
    # 800 hit * 0.2 + 200 miss * 2.0 + 100 out * 3.0, per 1M tokens.
    assert report['cost'] == pytest.approx((800 * 0.2 + 200 * 2.0 + 100 * 3.0) / 1_000_000)
    assert report['currency'] == 'CNY'
    assert report['cost_complete'] is True
    assert report['models'][0]['model'] == 'deepseek-flash'
    body = client.get(f'/api/ai/conversations/{conversation["id"]}/usage').get_json()
    assert body['ok'] is True and body['usage']['total_tokens'] == 1100


def test_an_unpriced_model_reports_tokens_but_no_money(client, clean_ai):
    from ai import costs, store

    conversation = store.create_conversation('openrouter', 'mystery-model', 'auto')
    store.save_usage(
        conversation['id'],
        'm1',
        'openrouter',
        'mystery-model',
        {'prompt_tokens': 500, 'completion_tokens': 50, 'cached_tokens': 0},
    )
    report = costs.conversation_cost(conversation['id'])
    assert report['total_tokens'] == 550
    assert report['cost'] is None
    assert report['cost_complete'] is False


def test_an_unknown_conversation_answers_404(client, clean_ai):
    response = client.get('/api/ai/conversations/c_nope/usage')
    assert response.status_code == 404
    assert response.get_json()['ok'] is False


def test_the_conversation_list_names_the_model_it_used(client, clean_ai):
    from ai import store

    conversation = store.create_conversation('deepseek', 'deepseek-v4-pro', 'auto')
    rows = client.get('/api/ai/conversations').get_json()['conversations']
    row = next(item for item in rows if item['id'] == conversation['id'])
    assert row['provider'] == 'deepseek'
    assert row['model'] == 'deepseek-v4-pro'
