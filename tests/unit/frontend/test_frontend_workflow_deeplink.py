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
    assert 'this.execute(' in source, 'autorun must go through the normal execute gates'


def test_query_loader_can_auto_layout_before_running():
    source = (JS / 'workflow.js').read_text(encoding='utf-8')
    assert "params.get('layout') === '1'" in source
    assert 'canvas.runAutoLayout()' in source, 'must reuse the menu action, not a second layout'
    assert source.index('canvas.runAutoLayout()') < source.index('await this.execute('), 'layout before run'


def test_query_loader_can_reveal_the_node_trace_conversation():
    source = (JS / 'workflow.js').read_text(encoding='utf-8')
    # Every run opens the trace dock per the ai_trace_tier setting — not behind a demo-only flag.
    assert 'AppSettings._values.ai_trace_tier' in source
    assert "tier !== 'off'" in source
    assert '_revealRunTrace(result.run_id)' in source, 'the reveal must be scoped to THIS run'
    # The old global session scan opened a stale trace from an earlier run; the per-run route does
    # not. It must not wait for "2 messages" either: a traditional trace has only its intro until
    # settlement.
    assert "'/api/ai/traces/'" in source
    assert 'message_count' not in source, 'a quiet traditional trace never reaches 2 messages'
    # The workspace must be opened onto that specific conversation, not the remembered one.
    workspace = (JS / 'ai-workspace.js').read_text(encoding='utf-8')
    assert 'opts.conversation' in workspace
    assert 'this.selectConversation(wanted)' in workspace
    # The follow pump must repaint when a NEW row's Q&A lands, or only the first of the 3 rows
    # would ever be visible in the recorded transcript.
    assert 'pumpTraceStream' in workspace
    assert 'isNew' in workspace and 'await this.selectConversation(conversationId)' in workspace
    # A quiet poll is NOT the end: multi-batch runs have gaps between rows, so only the closing
    # trace_result may stop the pump. It must also yield to a user-owned turn/selection.
    assert 'if (closed) break;' in workspace
    assert '(!stillStreaming && !isNew)' not in workspace
    assert 'this._sending || (adopted' in workspace
    # The deep link widens the AI workspace for ONE take, without persisting the width.
    assert "params.get('ai_width')" in source
    assert 'AIWorkspace.setRunWidth(aiWidth)' in source
    assert 'AISettings.save({ width:' not in source, "a link must not change the user's saved width"
    # A bare link must not spend money: autorun is gated on a server capability the recorder sets.
    assert 'demo_autorun' in source
    assert 'history.replaceState' in source, 'a refresh must not silently re-run the demo'


def test_app_boots_the_deep_link_after_restoring_the_remembered_file():
    source = (JS / 'app.js').read_text(encoding='utf-8')
    assert "boot('workflowDeepLink'" in source
    assert source.index("boot('openFile'") < source.index("boot('workflowDeepLink'")
    # boot() does not await async steps; the deep link waits on the captured restore promise so a
    # late remembered-file response cannot overwrite the linked canvas before autorun.
    assert 'workflow._reloadPromise = workflow.reloadOpenFile()' in source
    workflow_js = (JS / 'workflow.js').read_text(encoding='utf-8')
    assert 'await this._reloadPromise' in workflow_js


def test_recorder_clears_history_and_draws_no_cursor():
    tools = ROOT / 'tools'
    recorder = (tools / 'record_demo.py').read_text(encoding='utf-8')
    capture = (tools / 'demo_capture.py').read_text(encoding='utf-8')
    assert '/api/runs/clear' in recorder, 'run records must be cleared before each take'
    assert "'/api/ai/conversations/" in recorder, 'AI chat history must be cleared too'
    assert 'DELETE FROM llm_cache' in recorder, 'cached LLM answers must be cleared so nodes really run'
    assert "'-draw_mouse', '0'" in capture, 'the cursor must not flicker in the recording'
    assert 'keybd_event(0x12' not in capture, 'no synthetic ALT press — it flickers the UI'
    # The recorder must never kill a browser the user opened while a take was running; matching the
    # unique profile marker is the only safe way to identify its own processes.
    assert 'profile_marker' in recorder, 'browser cleanup must match the recorder profile'
    assert 'raise TimeoutError' in recorder, 'a hung demo run must not be reported as settled'
    assert 'CIXI_FRAME_STDDEV_FLOOR' in recorder, 'the blank-frame heuristic must report its floor'
    # No timed re-select that repaints the whole transcript (reads as a flicker on video).
    trace_src = (JS / 'workflow.js').read_text(encoding='utf-8')
    # A one-shot re-select at reveal time is fine; a TIMED re-select inside the reveal helper is the
    # flicker this guard exists to prevent. (setInterval elsewhere in workflow.js is the run poll.)
    reveal = trace_src[trace_src.index('async _revealRunTrace') : trace_src.index('restoreOpenFile()')]
    assert 'setInterval' not in reveal, 'reveal must not keep repainting the trace'
