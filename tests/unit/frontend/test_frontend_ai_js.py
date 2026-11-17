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

    def test_a_pipe_inside_code_or_escaped_does_not_split_a_table_cell(self):
        """The model's own rows: `a|b` and `\\|` stay inside one cell, and every row keeps 2 cells."""
        out = _run()['tablePipes']
        assert out.count('<td>') == 4, out
        assert 'a|b' in out, 'a pipe inside inline code was treated as a column break'
        assert '用 | 连接' in out, out
        assert '不会展开' in out

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
        # The assistant bubble plus the standalone row a stored `tool` message draws (a row with no
        # inline card of its own belongs to the assistant's column, so it is an article too).
        assert out['assistants'] == 2, out
        assert out['escaped'] is True

    def test_a_stored_tool_row_does_not_draw_a_second_detached_card(self):
        """The misaligned card above every "AI" label: the bubble already drew this call."""
        out = _run_workspace()['storedToolRow']
        assert out['cards'] == 1, out
        assert out['insideBubble'] is True, 'the tool card was painted outside a message body'

    def test_a_stored_turn_is_one_bubble_like_the_live_one(self):
        """Two provider rounds are two stored assistant rows; the reopened transcript must still be
        one bubble (the live view's picture), not one bubble per round."""
        out = _run_workspace()['storedTwoRounds']
        assert out['bubbles'] == 1, out
        assert out['skills'] == 1, out
        assert out['tools'] == 1, out
        assert out['detached'] == 0, 'a standalone tool row appeared beside the bubble'
        assert out['details'] == 1, 'the stored card lost its result, so it could not be opened'

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

    def test_a_slash_command_runs_and_never_leaks_into_a_message(self):
        out = _run_workspace()['commands']
        assert out['ids'] == ['retry'], out['ids']
        assert out['handled'] is True
        assert out['calls'] == ['retry'], out['calls']
        assert out['cleared'] is True
        assert out['closed'] is True

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

    def test_the_failed_node_and_approval_cards_carry_their_actions(self):
        """A monitor's failure answer offers the rerun, and an approval question shows all three
        choices in the danger card. The session grant itself is reused server-side
        (tests/api/test_ai_approval_turn.py::test_a_session_approval_is_reused_by_the_resumed_turn)."""
        out = _run_workspace()['cards']
        assert out['rerun']['button'] is True, 'the failed-node card has no rerun button'
        assert out['rerun']['run'] == 'r1'
        assert out['rerun']['workflow'] == 'wf'
        assert out['rerun']['clicked'] == [['r1', 'n2', 'wf']], out['rerun']['clicked']
        assert out['rerun']['startedText'] is True, 'a started rerun is not marked on the card'
        assert out['approval']['danger'] is True
        assert out['approval']['options'] == ['Allow once', 'Allow for this session', 'Deny']
        assert out['approval']['badge'] is True
        assert out['runStatus'] == ['n2', 'n9'], 'a run_status answer did not name its failed node'

    def test_a_reloaded_transcript_keeps_the_error_and_the_question(self):
        """Both used to live only in the live DOM, so a refresh left a silent gap."""
        out = _run_workspace()['storedEvidence']
        assert 'unresolved tool call' in out['error'], out['error']
        assert out['asked'] == 'Which dataset?', out['asked']
        assert 'Dataset A' in out['answered'], out['answered']

    def test_the_folder_picker_reaches_the_other_disks(self):
        out = _run_workspace()['folderPicker']
        assert out['roots'] == ['C:/', 'D:/'], out['roots']
        assert out['native'] is True, 'the system dialog button is missing'
        assert out['opened'] == ['D:/'], out['opened']
        assert out['picked'] == ['pick'], out['picked']

    def test_the_spend_block_names_the_model_and_the_numbers(self):
        """Which model answered this chat, its tokens, the cache hit rate and the estimated money."""
        out = _run_workspace()['spend']
        assert out['sessionModel'] == 'deepseek / deepseek-v4-pro', out['sessionModel']
        numbers = out['numbers']
        assert '¥110.25' in numbers, numbers
        assert 'deepseek / deepseek-flash' in numbers, numbers
        assert '1000' in numbers and '100' in numbers, numbers
        assert '80%' in numbers, numbers
        assert any(value.startswith('¥0.0006') for value in numbers), numbers

    def test_a_running_command_shows_a_live_seconds_counter(self):
        """A batch command can run for minutes: "运行中 52s" tells "working" from "stuck"."""
        out = _run_workspace()['toolClock']
        assert out['running'] == 1, out
        assert out['after'] == 0, out

    def test_local_only_refuses_a_paid_provider_before_sending(self):
        """The switch makes "only the free local model" enforceable, not a hope."""
        out = _run_workspace()['localOnly']
        assert out['refused'] is True, out
        assert 'Ollama' in out['toast'] or '本机' in out['toast'] or 'Local' in out['toast'], out

    def test_a_plan_artifact_offers_an_action_too(self):
        """Only workflow drafts had a button, so a plan or chart spec card looked dead. Its button
        hands the proposal back to the assistant (which has the validated tools)."""
        out = _run_workspace()['artifactAction']
        assert out['hasButton'] is True, out
        assert out['asked'] is True, 'the button did not ask the assistant to build it'

    def test_clicking_a_finished_tool_row_opens_it_and_a_skill_row_loads(self):
        """Both were dead clicks: the tool row was not wired, and `data-ai-skill` was missing from
        the delegated selector so the skill branch could never be reached."""
        out = _run_workspace()['clicks']
        assert out['toolOpened'] is True, 'a finished tool card did not open on click'
        assert out['skillLoads'] == 1, 'the skill row never asked for its detail'

    def test_the_pin_keeps_the_panel_open_on_an_outside_click(self):
        out = _run_workspace()['pin']
        assert out['pinnedStayedOpen'] is True, 'a pinned panel closed on an outside press'
        assert out['ariaPressed'] == 'true', out
        assert out['unpinnedClosed'] is True, 'unpinned, an outside press did not close it'

    def test_a_local_daemons_real_models_replace_the_static_one(self):
        out = _run_workspace()['localModels']
        assert out['ids'] == ['qwen3.5:4b', 'qwen3.5:9b'], out['ids']
        assert out['model'] == 'qwen3.5:4b', 'a stored choice the daemon still has was rewritten'
        assert out['missingFallsBackTo'] == 'qwen3.5:4b', 'a model the daemon no longer has stayed selected'

    def test_an_older_bootstrap_answer_cannot_revert_the_picker(self):
        """Switching provider/model refetches; the older answer must lose the race, or the chip and
        the request name different models (and a local turn opened the key prompt)."""
        out = _run_workspace()['staleBootstrap']
        assert out == 'ollama', out

    def test_one_turn_with_a_tool_round_shows_one_skill_row_and_one_bubble(self):
        """Each provider round opens with its own meta (and the skill it used). Pushing that row per
        round printed the skill twice and made one answer read as two."""
        out = _run_workspace()['twoRounds']
        assert out['bubbles'] == 1, out
        assert out['skills'] == 1, out
        assert out['tools'] == 1, out

    def test_a_reload_reopens_the_conversation_that_was_open(self):
        out = _run_workspace()
        assert out['restoreConversation'] == 'c-saved', out['restoreConversation']
        assert out['clearedAfterNewChat'] == '', 'a new chat kept the old conversation id'

    def test_an_answer_box_can_reference_a_file_too(self):
        """The question card's own answer box takes `@`: menu, chip, and the reference in the answer."""
        out = _run_workspace()['answerRefs']
        assert out['targetOk'] is True, 'the @ menu did not attach to the answer box'
        assert out['chips'] == ['Corpus'], out['chips']
        assert out['custom'] == '用这个', out['custom']
        assert out['refs'] == [{'kind': 'dataset', 'id': 'd1'}], out['refs']

    def test_an_open_disclosure_survives_the_streaming_repaint(self):
        """Thinking and tool-result details stay open while the answer keeps streaming, and an
        unchanged picture is not rebuilt at all."""
        out = _run_workspace()['openDetails']
        assert out['thinking'] is True, 'the streaming repaint closed the thinking block'
        assert out['tool'] is True, 'the streaming repaint closed the tool result'
        assert out['sameNode'] is True, 'an unchanged paint rebuilt the DOM'
