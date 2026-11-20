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
        assert 'data-ai-preview-artifact="a1"' in out['artifact'], 'a previewable card has no preview door'


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

    def test_the_inspector_reports_how_many_secrets_were_scrubbed(self):
        """A scrub is a fact about what the model received: the panel must show the count by name,
        and show nothing when no redaction happened. Only the count may travel, never the value."""
        out = _run_workspace()['redactionNote']
        assert out['shown'] is True, 'a redacted context showed no note'
        assert out['hidden'] is True, 'a context with no redactions still claimed some were removed'
        assert out['total'] is True, 'the note did not sum the per-source counts'
        assert out['noSecretValue'] is True, 'a secret value leaked into the inspector'

    def test_the_redaction_key_is_translated_in_both_languages(self):
        catalog = (JS_DIR / 'i18n' / 'ai.js').read_text(encoding='utf-8')
        assert catalog.count("'ai.contextRedacted':") == 2, 'the key needs one en and one zh wording'

    def test_a_preview_applies_only_the_selected_nodes(self):
        """The preview door is additive, asks the SERVER, and merges only the ticked nodes into the
        live canvas — the primary button's full apply path is untouched."""
        out = _run_workspace()['artifactPreview']
        assert out['button'] is True and out['clicked'] is True, 'the card button did not reach the handler'
        request = out['request']
        assert request and request['url'] == '/api/ai/artifacts/preview'
        assert request['body']['kind'] == 'workflow_draft'
        assert request['body']['current']['nodes'][0]['params']['workflow_name'] == 'current'
        assert out['toggles'] == ['ai-preview-0', 'ai-preview-1']
        applied = out['applied']
        assert applied and applied['run'] is False
        ids = [node['id'] for node in applied['payload']['nodes']]
        assert ids == ['n1', 'n2'], ids
        # The overwritten n1 stayed at its CURRENT value; only the new n2 was taken from the draft.
        assert applied['payload']['nodes'][0]['params']['workflow_name'] == 'current'
        assert applied['payload']['nodes'][1]['type'] == 'analysis'
        # n1→n2 survives (both endpoints exist); n2→n3 does not (n3 was never brought in).
        assert applied['payload']['connections'] == [{'from': 'n1', 'to': 'n2'}], (
            'connections to excluded nodes must be dropped'
        )

    def test_the_manual_monitor_builder_uses_the_servers_event_names(self):
        """The builder offers only names the matcher knows, and arms through the same endpoint the
        artifact card uses — the page holds no second event table."""
        out = _run_workspace()['monitorBuilder']
        assert out['button'] is True and out['clicked'] is True, 'the sidebar has no working builder door'
        assert '/api/ai/monitors/catalog' in out['urls'], 'the builder did not ask the server for names'
        assert out['eventOptions'] == ['run.started', 'run.finished']
        arm = out['arm']
        assert arm and arm['conversation_id'] == 'c-new'
        assert arm['auto_analyze'] is True
        assert arm['spec']['events'] == ['run.finished']
        assert arm['spec']['statuses'] == ['failed', 'partial']
        assert arm['spec']['run_id'] == 'run-9'
        assert out['armed'] is True

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

    def test_a_context_source_cannot_break_out_of_the_checkbox_attribute(self):
        html = _run_workspace()['editorEscaped']['html']
        assert '" onfocus="alert(1)"' not in html, 'a source reached the attribute as raw markup'
        assert '&quot; onfocus=&quot;alert(1)' in html

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

    def test_the_search_default_is_adopted_once_and_never_over_a_choice(self):
        """联网搜索 is on by default (DeepSeek's server-side search/fetch tool calls are free);
        adopting the server default must not undo a click either — a switched-off browser was being
        turned back on by the next refresh."""
        out = _run_workspace()['searchDefault']
        assert out['browserDefault'] is True, 'a fresh browser did not start with 联网搜索 on'
        assert out['adopted'] is True, 'a browser that never chose did not adopt the server default'
        assert out['kept'] is False, 'a click on 联网搜索 was reverted by the next bootstrap'

    def test_the_provider_settings_buttons_reach_their_handlers(self):
        """保存 had no branch in the delegated handler, so typing an API key and clicking it did
        nothing — no toast, no request, no error. The same for 刷新模型 and 测试连接."""
        out = _run_workspace()['settings']
        assert out['found'] == 3, 'the settings page did not render all three buttons'
        assert out['calls'] == ['save', 'models', 'test'], out['calls']

    def test_the_session_list_offers_pin_archive_export_and_server_search(self):
        """Five controls on a row, and the search must reach `_refreshConversations` (the server)
        rather than filter the 80-row page in memory."""
        out = _run_workspace()['sessions']
        assert out['search'] is True, 'the session search box is missing'
        assert out['pin'] and out['archive'] and out['export'], out
        assert out['archivedToggle'] is True, 'the archived switch did not re-query with archived=1'
        assert out['searchRows'] == 4, out['searchRows']

    def test_the_memory_tab_lists_and_deletes_what_was_confirmed(self):
        out = _run_workspace()['memoryTab']
        assert out['cards'] == 1, out['cards']
        assert '默认账号是 default' in out['text']
        assert out['add'] is True and out['delete'] is True, out
        assert out['count'] is True, 'the count did not show the server limit'

    def test_a_memory_artifact_has_its_own_apply_button(self):
        """A proposal is not a write: the card carries 记住这条, which posts to /api/ai/memories."""
        out = _run_workspace()['memoryArtifact']
        assert out['button'] is True, 'a memory artifact drew no apply button'
        assert out['applied'] is True, 'the button did not reach _applyMemoryArtifact'

    def test_a_chart_spec_has_a_render_button(self):
        """A chart proposal is not copy-only: its one action goes through the delegated selector."""
        out = _run_workspace()['chartArtifact']
        assert out['button'] is True, 'a chart_spec artifact drew no render button'
        assert out['applied'] is True, 'the button did not reach _applyChartArtifact'

    def test_a_monitor_cards_auto_button_arms_analysis(self):
        """The primary monitor button must pass armed=true — it used to be a bare `return`, leaving
        the only reachable arm path the watch-only ghost button."""
        out = _run_workspace()['monitorArtifact']
        assert out['autoButton'] is True, 'the monitor card drew no auto-arm button'
        assert out['watchButton'] is True, 'the monitor card drew no watch-only button'
        assert out['calls'] == [['mon_art', True], ['mon_art', False]], out['calls']

    def test_a_multi_file_pick_uploads_each_and_drop_and_paste_share_the_path(self):
        out = _run_workspace()['upload']
        assert out['requests'] == 2, out['requests']
        assert out['attachments'] == 2, out['attachments']
        assert out['files'] == ['a.txt', 'b.txt'], out['files']
        assert out['dropActive'] is True, 'a file drag over the panel showed no drop target'
        assert out['dropped'] is True, 'a dropped file did not enter the upload path'
        assert out['dropCleared'] is True, 'the drop highlight stayed after the drop'
        assert out['pasted'] is True, 'a pasted screenshot did not enter the upload path'

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

    def test_the_approval_card_shows_the_exact_target_and_diff(self):
        """A one-line summary is not enough to approve a file write: the card carries the facts
        and the coloured diff, and a reloaded transcript still shows the path that was allowed."""
        approval = _run_workspace()['cards']['approval']
        assert approval['preview'] is True, 'the approval card has no preview block'
        assert approval['path'] is True, 'the target fact has no translated label'
        assert approval['added'] == 2 and approval['removed'] == 2, approval
        assert _run_workspace()['storedEvidence']['approvalPreviews'] >= 1

    def test_a_panel_entry_opens_a_fresh_chat_with_context_and_prefills(self):
        out = _run_workspace()['askAbout']
        assert out['contexts'] == [{'context': {'run_id': 'run-42'}}], out['contexts']
        assert out['fresh'] == 1, 'the entry did not start a new conversation'
        assert out['runId'] == 'run-42', 'the run id did not reach the manual context'
        assert out['prompt'] == 'explain run-42', 'the question was not prefilled'

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

    def test_an_open_turn_always_says_it_is_generating(self):
        """The line under a live turn, measured on the REAL workspace with a pinned clock.

        Three things used to be wrong at once, and each one made a working turn look broken:
        the line was painted only when the last block was not text (so a finished paragraph
        followed by a silent minute read as a complete answer), it never changed (so "still
        working" and "the stream died" looked the same), and the tool clock was written but
        never started (so a three-minute command showed one static label).
        """
        out = _run_workspace()['liveLine']
        assert out['afterText']['visible'] is True, 'no live line under a turn that is still open'
        assert out['afterText']['ticks'] == 1, 'the turn clock never started'
        assert out['afterText']['text'] == out['expected']['generating'], out
        assert out['afterText']['clock'] == ' · ' + out['expected']['clock'], out
        assert out['stalled'] == out['expected']['stalled'], out
        assert out['waitingApp'] == out['expected']['waitingApp'], out
        assert '65s' in out['toolClock'], out['toolClock']
        assert out['hiddenAfterDone'] is True, 'the live line outlived its turn'

    def test_a_stream_that_ends_without_its_ending_says_it_was_cut(self):
        """`_stream` RESOLVES when the server dies or a proxy drops the connection: no `done`, no
        error. The bubble kept a half answer that read as a finished one. One note, once."""
        out = _run_workspace()['cutStream']
        assert out['notes'] == [out['expected']], out
        assert out['again'] == 1, 'the cut was reported twice'

    def test_a_reopened_turn_that_never_ended_says_which_fact_it_is(self):
        """`streaming` may still be running in another page; `interrupted` is the server's verdict.
        Reopening the conversation used to show a half answer with no word about either."""
        out = _run_workspace()['reloadNotes']
        assert out['notes'] == [out['expected']['interrupted'], out['expected']['live']], out

    def test_switching_conversations_mid_answer_does_not_paint_into_the_new_one(self):
        """The dock stays usable while an answer streams, so one click reached this: the rest of the
        old answer appeared under the new conversation's question."""
        out = _run_workspace()['switchGuard']
        assert out['dropped'] == 0, "the previous conversation's answer was painted into the new one"
        assert out['painted'] == 1, 'the owning conversation lost its own answer'

    def test_local_only_refuses_a_paid_provider_before_sending(self):
        """The switch makes "only the free local model" enforceable, not a hope."""
        out = _run_workspace()['localOnly']
        assert out['refused'] is True, out
        assert 'Ollama' in out['toast'] or '本机' in out['toast'] or 'Local' in out['toast'], out

    def test_a_local_turn_does_not_think_unless_the_switch_is_on(self):
        """qwen3.5 thinks by default; a batch call must not pay for a thought trace it never asked
        for. A paid provider keeps its own choice."""
        out = _run_workspace()['thinking']
        assert out['localDefault'] is False, out
        assert out['localOn'] is True, 'the local switch did not turn thinking on'
        assert out['paidDefault'] is True, out

    def test_choosing_an_option_on_a_multi_question_card_shows_it(self):
        """The card submits only when every question is answered; the first click must still show
        that it registered (selected style + how many are left), or it reads as a dead button."""
        out = _run_workspace()['answerClick']
        assert out['selected'] is True, out
        assert '2' in out['hint'], out
        # `_maybeAnswer` is CALLED on every click; it must not have replaced the card with the
        # “answered” row while two questions are still open (the hint proves the card is still there).
        assert out['submitted'] <= 1, out

    def test_a_stored_artifact_still_draws_its_card_and_a_running_tool_says_what_it_does(self):
        """Reloading dropped the artifact card (only the tool row survived), and a running
        present_artifact said “读取中…”, which reads as a stalled turn."""
        out = _run_workspace()
        assert out['storedArtifact']['cards'] == 1, out['storedArtifact']
        assert out['storedArtifact']['inExtras'] is True, out['storedArtifact']
        assert 'Generating the artifact' in out['runningLabel'], out['runningLabel']
        assert '读取中' not in out['runningLabel'], out['runningLabel']

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

    def test_the_context_inspector_names_what_was_left_out(self):
        """A context cut by the budget — by the replay cap that keeps one turn's block bounded, or by
        the model's window — must say so; silence reads as “the model saw everything”."""
        out = _run_workspace()
        notes, words = out['contextNotes'], out['contextWords']
        assert words['omitted'] in notes, f'{words["omitted"]!r} not in the inspector'
        assert words['replay'] in notes, f'{words["replay"]!r} not in the inspector'
        assert words['history'] in notes, f'{words["history"]!r} not in the inspector'
        assert words['memories'] in notes, f'{words["memories"]!r} not in the inspector'

    def test_the_turns_last_row_carries_its_verdict(self):
        """Two provider rounds are two stored rows. Taking the FIRST row's `stop_reason` would call a
        recovered answer truncated and hide a real cut behind a finished first round."""
        out = _run_workspace()['turnVerdict']
        assert out['recovered'] == 0, 'a round that recovered from max_tokens still said “cut off”'
        assert out['cutLast'] == 1, out

    def test_a_stopped_turn_is_a_note_not_an_error(self):
        """Stop used to store status='error', so a reload painted a red error line over a turn the
        user ended on purpose."""
        out = _run_workspace()['storedStop']
        assert 'Stopped' in out['note'], out
        assert out['errors'] == 0, out

    def test_the_composer_stays_usable_while_a_turn_runs(self):
        out = _run_workspace()['sendingInput']
        assert out['disabled'] is False, out

    def test_a_truncated_answer_says_so_live_and_after_a_reload(self):
        """`stop_reason == 'max_tokens'` means the provider CUT the answer. It was painted as a
        finished one, so a half sentence looked like a complete thought."""
        out = _run_workspace()['truncation']
        assert 'cut off' in out['live'], out
        assert out['stored'] == out['live'], out

    def test_every_tool_family_and_a_stop_have_visible_guidance(self):
        """No generation step may be a silent tool card: reads, peeks and plans each say what they
        are doing, an unknown (plugin) tool is NAMED, and a stopped turn says it stopped."""
        out = _run_workspace()['guidance']
        assert 'Reading the file' in out['read'], out
        assert 'first rows' in out['peek'], out
        assert 'plan' in out['plan'].lower(), out
        assert 'plugin_tool_x' in out['unknown'], out
        assert out['stoppedNote'] == 1, out
        assert 'Stopped' in out['stoppedText'], out

    def test_a_stop_is_reported_once_even_when_the_server_also_answers(self):
        """The server answers the aborted stream with `done`+cancelled while the stop button's own
        call is in flight: two notes for one stop read as two separate failures."""
        assert _run_workspace()['stopDedupe'] == 1

    def test_the_jump_button_is_a_pill_above_the_composer(self):
        """It used to be a 26px circle filled with the sentence “回到最新消息”, which wrapped into a
        vertical stack and sat on the composer's own buttons. The anchor now follows the composer's
        measured height; the button keeps its arrow and carries the sentence as a label."""
        out = _run_workspace()['jumpButton']
        assert out['composerVar'].endswith('px'), out
        html = (ROOT / 'backend' / 'static' / 'index.html').read_text(encoding='utf-8')
        start = html.index('id="ai-jump"')
        end = html.index('</button>', start)
        tag = html[start:end]
        assert '↓' in tag, 'the button lost its arrow'
        assert 'data-i18n="ai.jumpLatest"' not in tag, 'the sentence is the button text again'
        assert 'data-i18n-title="ai.jumpLatest"' in tag

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
