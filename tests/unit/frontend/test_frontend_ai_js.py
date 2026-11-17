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
WORKSPACE_HARNESS = ROOT / 'tests' / 'frontend' / 'harness_ai_workspace.mjs'


def _run():
    proc = run_node(str(HARNESS), str(JS_DIR))
    assert proc.returncode == 0, proc.stderr[-1200:]
    return json.loads(proc.stdout)


def _run_workspace():
    proc = run_node(str(WORKSPACE_HARNESS), str(JS_DIR))
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
        assert 'Desktop app' in out['runtimeTitle']
        assert 'local model daemon' in out['runtimeTitle']
        assert 'user files' in out['runtimeTitle']
        assert 'code plugins' in out['runtimeTitle']
        assert 'repository source' not in out['runtimeTitle']

    def test_a_turn_renders_skill_thinking_tools_plan_then_the_answer(self):
        out = _run()
        flow = out['turnFlow']
        assert flow['ordered'] is True
        assert flow['skill'] >= 0 and flow['plan'] >= 0
        assert flow['working'] is True

    def test_i18n_answers_whether_a_key_exists(self):
        out = _run()
        assert out['hasKnown'] is True
        assert out['hasUnknown'] is False

    def test_an_unavailable_skill_shows_the_servers_reason(self):
        out = _run()
        assert 'disabled' in out['skillOptions']
        assert 'needs the repository source' in out['skillOptions']

    def test_a_cloud_only_refusal_is_disabled_in_the_provider_picker(self):
        out = _run()
        assert 'value="ollama"' in out['providerOptions']
        assert 'disabled' in out['providerOptions']
        assert 'no local daemon on a cloud host' in out['providerOptions']


class TestWorkspaceRepaintAndDelegation:
    """The workspace against the stub page: repaint must terminate, and every dock control clicks.

    ``harness_ai.mjs`` loads the stream decoder and the renderer, but never a transcript or a
    pointer, so a reopen loop and dead buttons outside the transcript could not fail it.
    """

    def test_reopening_a_saved_conversation_draws_each_row_once(self):
        out = _run_workspace()['repaint']
        assert out['stored'] == 4, 'a repaint recorded a second copy of the transcript'
        assert out['users'] == 2
        assert out['assistants'] == 1
        assert out['escaped'] is True

    def test_controls_outside_the_transcript_reach_the_delegated_handler(self):
        out = _run_workspace()['delegated']
        assert out['sessionRowFound'] and out['disarmRowFound'] and out['refreshRowFound']
        assert out['session'] is True, 'a click on a saved conversation never reached selectConversation'
        assert out['disarm'] is True, '停止监控 in the side panel is inert'
        assert out['context'] is True, '刷新上下文 in the context bar is inert'
        assert out['ignored'] is True, 'a click outside any data-ai target acted'
        assert out['renameRowFound'] and out['deleteRowFound']
        assert out['rename'] is True, '重命名 in the session row is inert'
        assert out['delete'] is True, '删除会话 in the session row is inert'

    def test_the_skill_editor_lists_what_the_server_offers(self):
        out = _run_workspace()['editor']
        assert out['contextChecks'] == ['project', 'run'], out['contextChecks']
        assert out['toolChecks'] == ['run_status'], 'a control tool was offered as a skill tool'

    def test_a_saved_provider_id_is_not_rewritten_in_the_browser(self):
        out = _run_workspace()['provider']
        assert out['stored'] == 'custom_provider'

    def test_the_provider_settings_buttons_reach_their_handlers(self):
        """保存 had no branch in the delegated handler, so typing an API key and clicking it did
        nothing — no toast, no request, no error. The same for 刷新模型 and 测试连接."""
        out = _run_workspace()['settings']
        assert out['found'] == 3, 'the settings page did not render all three buttons'
        assert out['calls'] == ['save', 'models', 'test'], out['calls']

    def test_opening_the_studio_from_outside_opens_the_panel(self):
        """The Python node's 管理脚本 lives outside the aside; opening the studio used to leave the
        panel hidden, so the button looked dead. `_mode` alone is not "open"."""
        out = _run_workspace()['studioOpensPanel']
        assert out['open'] is True, 'openStudio left the workspace closed'
        assert out['hidden'] is False, 'openStudio left the aside hidden'
        assert out['mode'] == 'studio'

    def test_the_python_node_picker_offers_one_empty_placeholder(self):
        out = _run_workspace()['pythonPanel']
        assert out['pickOptions'] == [''], 'the placeholder sentence became an option VALUE (and a script_id)'
        assert out['manage'] is True
        assert out['manageTarget'] == "AIWorkspace.openStudio('python')", out['manageTarget']
