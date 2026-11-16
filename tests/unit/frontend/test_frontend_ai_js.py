"""The AI workspace's stream decoder and safe renderer, driven from the real files."""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

ROOT = Path(__file__).resolve().parents[3]
JS_DIR = ROOT / 'backend' / 'static' / 'js'
HARNESS = ROOT / 'tests' / 'frontend' / 'harness_ai.mjs'


def _run():
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, proc.stderr[-1200:]
    return json.loads(proc.stdout)


class TestAIStreamAndRenderer:
    def test_stream_events_are_decoded_and_keep_alive_comments_are_ignored(self):
        out = _run()
        assert [event['type'] for event in out['events']] == ['text', 'done']

    def test_model_html_is_escaped_before_markdown(self):
        out = _run()
        assert '<script>' not in out['escapedScript']
        assert '&lt;script&gt;' in out['escapedScript']

    def test_unsafe_links_are_not_turned_into_anchors(self):
        out = _run()
        assert '<a ' not in out['escapedLink']
        assert 'href="https://example.com/a"' in out['safeLink']

    def test_question_and_artifact_cards_carry_data_actions(self):
        out = _run()
        assert 'data-ai-answer="A"' in out['question']
        assert 'data-ai-question="q1"' in out['question']
        assert 'data-ai-copy-artifact="a1"' in out['artifact']


class TestRuntimeSurfaces:
    def test_the_runtime_chip_lists_only_the_powers_this_host_has(self):
        out = _run()
        assert 'ai.runtime.desktop' in out['runtimeTitle']
        assert 'ai.runtime.daemon' in out['runtimeTitle']
        assert 'ai.runtime.files' in out['runtimeTitle']
        assert 'ai.runtime.codePlugins' in out['runtimeTitle']
        assert 'ai.runtime.source' not in out['runtimeTitle']

    def test_an_unavailable_skill_shows_the_servers_reason(self):
        out = _run()
        assert 'disabled' in out['skillOptions']
        assert 'needs the repository source' in out['skillOptions']

    def test_a_cloud_only_refusal_is_disabled_in_the_provider_picker(self):
        out = _run()
        assert 'value="ollama"' in out['providerOptions']
        assert 'disabled' in out['providerOptions']
        assert 'no local daemon on a cloud host' in out['providerOptions']
