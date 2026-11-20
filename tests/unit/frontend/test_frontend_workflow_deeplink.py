"""The demo deep link reuses the panel's own loader and runs through execute()."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / 'backend' / 'static' / 'js'


def test_workflow_has_a_query_loader_that_uses_the_saved_file_route():
    source = (JS / 'workflow.js').read_text(encoding='utf-8')
    assert 'loadFromQuery()' in source
    assert "params.get('workflow')" in source
    assert 'this._loadByName(name)' in source, 'a second loader would disagree with the panel'
    assert 'this.execute()' in source, 'autorun must go through the normal execute gates'


def test_query_loader_can_auto_layout_before_running():
    source = (JS / 'workflow.js').read_text(encoding='utf-8')
    assert "params.get('layout') === '1'" in source
    assert 'canvas.runAutoLayout()' in source, 'must reuse the menu action, not a second layout'
    assert source.index('canvas.runAutoLayout()') < source.index('this.execute()'), 'layout before run'


def test_query_loader_can_reveal_the_node_trace_conversation():
    source = (JS / 'workflow.js').read_text(encoding='utf-8')
    # Every run opens the trace dock per the ai_trace_tier setting — not behind a demo-only flag.
    assert 'AppSettings._values.ai_trace_tier' in source
    assert "tier !== 'off'" in source
    assert '_revealRunTrace()' in source
    assert "c.skill === 'node_trace'" in source, 'must pick a node trace, not a user chat'
    # The workspace must be opened onto that specific conversation, not the remembered one.
    workspace = (JS / 'ai-workspace.js').read_text(encoding='utf-8')
    assert 'opts.conversation' in workspace
    assert 'this.selectConversation(wanted)' in workspace
    # The follow pump must repaint when a NEW row's Q&A lands, or only the first of the 3 rows
    # would ever be visible in the recorded transcript.
    assert 'pumpTraceStream' in workspace
    assert 'isNew' in workspace and 'await this.selectConversation(conversationId)' in workspace
    # The deep link widens the AI workspace so the trace transcript is legible on video.
    assert "params.get('ai_width')" in source
    assert 'AISettings.save({ width:' in source


def test_app_boots_the_deep_link_after_restoring_the_remembered_file():
    source = (JS / 'app.js').read_text(encoding='utf-8')
    assert "boot('workflowDeepLink'" in source
    assert source.index("boot('openFile'") < source.index("boot('workflowDeepLink'")


def test_recorder_clears_history_and_draws_no_cursor():
    tools = ROOT / 'tools'
    recorder = (tools / 'record_demo.py').read_text(encoding='utf-8')
    capture = (tools / 'demo_capture.py').read_text(encoding='utf-8')
    assert '/api/runs/clear' in recorder, 'run records must be cleared before each take'
    assert "'/api/ai/conversations/" in recorder, 'AI chat history must be cleared too'
    assert 'DELETE FROM llm_cache' in recorder, 'cached LLM answers must be cleared so nodes really run'
    assert "'-draw_mouse', '0'" in capture, 'the cursor must not flicker in the recording'
    assert 'keybd_event(0x12' not in capture, 'no synthetic ALT press — it flickers the UI'
    # No timed re-select that repaints the whole transcript (reads as a flicker on video).
    trace_src = (JS / 'workflow.js').read_text(encoding='utf-8')
    assert 'selectConversation(conv.id)' not in trace_src, 'reveal must paint the trace once'
