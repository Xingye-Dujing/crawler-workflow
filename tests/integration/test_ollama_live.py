"""Live Ollama tests — the only tier that really talks to the local daemon.

Skips cleanly when the daemon is down or has no pulled models (the
``ollama_host`` fixture probes /api/tags first), so CI without Ollama stays
green. Kept deliberately tiny: one short prompt per scenario — the point is
that the transport, the daemon's answer shape, and the error classification
work together against the real thing, not benchmark quality.
"""

import time

import pytest

from analyzers.llm_client import LLMClient, LLMError, list_ollama_models

pytestmark = [pytest.mark.live_ollama, pytest.mark.enable_socket]


@pytest.fixture(scope='module')
def llm(ollama_host, ollama_chat_model):
    return LLMClient(provider='ollama', model=ollama_chat_model, host=ollama_host, max_tokens=48, timeout=120)


def test_daemon_lists_pulled_models(ollama_host):
    models = list_ollama_models(host=ollama_host)
    assert models, 'daemon reachable but listed no chat models'
    assert models == sorted(models)


def test_short_prompt_round_trip(llm):
    started = time.time()
    answer = llm.chat('只回复两个字：收到。不要其它内容。')
    assert isinstance(answer, str) and answer.strip()
    assert time.time() - started < 90, 'a tiny prompt must not queue for minutes'


def test_two_chats_reuse_the_transport(llm):
    # Two calls, both answered — the daemon keeps no state the second call
    # could collide with, and the client re-probes nothing that breaks.
    first = llm.chat('回复数字 1')
    second = llm.chat('回复数字 2')
    assert first.strip() and second.strip()


def test_unknown_model_is_a_deterministic_kind(llm):
    broken = LLMClient(provider='ollama', model='definitely-not-pulled-xyz:0', host=llm.host, timeout=30)
    with pytest.raises(LLMError) as err:
        broken.chat('hi')
    assert err.value.kind == 'model', f'expected a deterministic model error, got {err.value.kind}'
