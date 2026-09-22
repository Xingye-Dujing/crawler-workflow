"""Live Ollama tests — the only tier that really talks to the local daemon.

Skips cleanly when the daemon is down or has no pulled models (the
``ollama_host`` fixture probes /api/tags first), so CI without Ollama stays
green. Kept deliberately small: a short prompt per scenario, because the point
is that the transport, the daemon's answer shape and the error classification
work together against the real thing — not benchmarking quality. The entity
extraction scenarios are the exception: a mock can prove the parser reads a
format, but only a live model says whether it answers that way.
"""

import time

import pandas as pd
import pytest

from analyzers.llm_client import LLMClient, LLMError, list_ollama_models
from analyzers.ner import COLUMNS, NamedEntityRecognizer

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


ARTICLE = '张伟前往上海参加人工智能峰会，与北京大学的李教授会面。'
NOTHING = '这家创业公司上周宣布完成了新一轮融资。'


@pytest.fixture
def ner_llm(ollama_host, ollama_chat_model):
    """A wider budget than ``llm``: an entity list is longer than two words."""
    return LLMClient(provider='ollama', model=ollama_chat_model, host=ollama_host, max_tokens=256, timeout=300)


@pytest.fixture
def ner_ctx(ner_llm):
    """The row-runner's context, with no store and no checkpoint file: this
    proves the transport and the answer format, and must not leave a file."""
    return {
        'client': ner_llm,
        'node_id': 'live-ner',
        'batch_size': 1,
        'workers': 1,
        'publish': lambda frame: None,
        'cancel_event': None,
        'checkpoint_dir': '',
    }


class TestLiveEntityExtraction:
    """The NER prompt is product code a mock cannot validate.

    Every mock asserts that ``answer_pair`` reads a format; only the real model
    says whether it *answers* in that format, which is the difference between a
    working feature and one that quietly returns an empty table on every row.
    """

    def test_the_model_answers_in_the_shape_the_parser_reads(self, ner_ctx):
        frame = pd.DataFrame({'正文': [ARTICLE]})
        table = NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, ctx=ner_ctx)
        assert list(table.columns) == COLUMNS, 'the node changed shape under the model'
        assert not table.empty, 'the model answered, and nothing survived the parser'
        for _pos, hit in table.iterrows():
            assert ARTICLE[int(hit['start']) : int(hit['end'])] == hit['text']
            assert hit['label'] in {'PERSON', 'ORG', 'LOC', 'DATE'}
        # Quality, not just plumbing: a person and a place in this sentence.
        found = {(hit['text'], hit['label']) for _pos, hit in table.iterrows()}
        assert ('张伟', 'PERSON') in found, f'entities the model reported: {found}'
        assert ('上海', 'LOC') in found, f'entities the model reported: {found}'

    def test_a_text_without_entities_stays_empty(self, ner_ctx):
        frame = pd.DataFrame({'正文': [NOTHING]})
        table = NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, ctx=ner_ctx)
        assert table.empty, 'an invented entity is worse data than a missing one'

    def test_the_category_filter_holds_with_a_real_model(self, ner_ctx):
        frame = pd.DataFrame({'正文': [ARTICLE]})
        table = NamedEntityRecognizer(mode='llm').analyze_dataframe(frame, entity_types='person,loc', ctx=ner_ctx)
        assert set(table['label']) <= {'PERSON', 'LOC'}
        # 北京大学 is literal in the text, so an ORG row here can only mean the
        # filter never reached the prompt or never reached the answer.
        assert not table.empty, 'no person or place at all — the run asked for both'
