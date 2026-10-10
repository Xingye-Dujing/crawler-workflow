"""Behaviour tests for the real panel *actions* of workflow.js.

The panels' HTML is asserted elsewhere; what had never been executed was the click
behind the row — 继续 / 重新开始 / 删除 / 详情 on a stored run, download / view /
delete on an export, rename / delete on a dataset, Kill on a process row, and the
three top-bar writes. Each of those is a request body, a confirmation, or a
"which endpoint" decision, so a mistake is silent data loss or a paid re-crawl.

This is also where the resume banner's own defect surfaced: it opened with
`if (!window.canvas) return`, and `canvas` is a top-level `const` — which never
becomes a property of `window` — so the banner was hidden forever and 断点续跑 had
no entry point in the UI. See tests/frontend/harness_panel_actions.mjs.

Skipped when node is not on PATH, like every other frontend harness.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

JS_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_panel_actions.mjs'
FILES = ('canvas.js', 'workflow.js', 'stats.js', 'app.js', 'menu.js')


@pytest.fixture(scope='module')
def pa():
    proc = run_node(str(HARNESS), *[str(JS_DIR / name) for name in FILES])
    assert proc.returncode == 0, f'panel-action harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestResumeBanner:
    """The banner is the only way back into an interrupted run."""

    def test_nothing_is_offered_until_a_canvas_exists_to_match(self, pa):
        assert pa['banner_without_canvas_nodes'] == {'candidate': None, 'hidden': True}

    def test_an_interrupted_run_is_offered_with_what_it_already_paid_for(self, pa):
        shown = pa['banner_shown']
        assert shown['candidate'] == 'abc123'
        assert shown['hidden'] is False, 'the banner must actually appear'
        assert shown['requested'] == [{'url': '/api/runs/resumable', 'method': 'POST'}]
        assert 'abc123' not in shown['text'], 'the user reads a name and a time, not an id'
        assert '2/5' in shown['text'] and '40' in shown['text'], shown['text']

    def test_continue_sends_the_interrupted_runs_id(self, pa):
        """Without the id the backend mints a fresh run and every stored cursor
        dies — the run silently degrades to a cold re-crawl."""
        assert pa['banner_continue']['resumedFrom'] == 'abc123'
        assert '/api/workflow/execute' in pa['banner_continue']['urls']

    def test_restart_discards_the_run_then_starts_fresh(self, pa):
        """Dropping the run has to drop its "already crawled" claims too, or the
        new attempt skips everything the old one fetched."""
        restarted = pa['banner_restart']
        assert restarted['discarded'] == [{'run_id': 'abc123'}]
        assert restarted['started'] is True
        assert restarted['hidden'] is True

    def test_a_refused_lookup_hides_the_banner_rather_than_offering_nothing(self, pa):
        assert pa['banner_failure'] == {'candidate': None, 'hidden': True}

    def test_dismissing_takes_the_candidate_with_it(self, pa):
        assert pa['banner_dismiss'] == {'candidate': None, 'hidden': True}


class TestRunRecordActions:
    def test_a_second_attempt_is_refused_while_a_run_is_going(self, pa):
        """Both buttons close the panel and post; while a run is in flight that is
        a second attempt at the same data."""
        assert pa['busy_continue']['requested'] == 0
        assert pa['busy_continue']['toasts']
        assert pa['busy_restart']['requested'] == 0

    def test_continue_from_the_panel_carries_the_run_id(self, pa):
        assert pa['free_continue']['resume'] == 'r9'

    def test_restart_discards_then_starts_without_a_run_id(self, pa):
        restarted = pa['free_restart']
        assert restarted['discarded'] == 'r9'
        # `execute()` always sends the field; an empty one is what "not a continue"
        # looks like on the wire, and it is also what re-enables queueing.
        assert restarted['startedWithoutResume'] == ''

    def test_a_declined_confirmation_sends_nothing_at_all(self, pa):
        assert pa['restart_declined']['requested'] == 0
        assert pa['remove_declined']['requested'] == 0

    def test_an_interrupted_run_is_discarded_a_finished_one_is_deleted(self, pa):
        """The two answers differ by design: an interrupted run's crawl claims
        should be released so a re-run can fetch again, while a finished run's must
        stay — otherwise deleting its data resurrects every item as unseen."""
        assert pa['remove_resumable']['url'] == '/api/runs/discard'
        assert pa['remove_finished']['url'] == '/api/runs/delete'

    def test_a_refused_delete_says_so(self, pa):
        assert any('failed' in toast.lower() for toast in pa['remove_refused_by_server']['toasts'])

    def test_the_detail_row_fetches_once_and_lists_every_node(self, pa):
        detail = pa['detail_opened']
        assert detail['present'] is True
        assert detail['requested'] == ['/api/runs/r1']
        assert detail['escaped'] is True, "row content is other people's text"

    def test_pressing_detail_again_closes_without_refetching(self, pa):
        assert pa['detail_toggles']['refetched'] == 0

    def test_a_run_that_cannot_be_read_adds_no_row(self, pa):
        assert pa['detail_failure_adds_nothing'] == {'present': False}

    @pytest.mark.parametrize(
        'status, cls, key',
        [
            ('done', 'st-completed', 'runsMgr.node.done'),
            ('restored', 'st-completed', 'runsMgr.node.restored'),
            ('partial', 'st-interrupted', 'runsMgr.node.partial'),
            ('skipped', 'st-skipped', 'runsMgr.node.skipped'),
            ('failed', 'st-failed', 'runsMgr.node.failed'),
            ('running', 'st-running', 'runsMgr.node.running'),
        ],
    )
    def test_each_node_status_has_its_own_badge_and_word(self, pa, status, cls, key):
        assert pa['node_status_map'][status] == {'cls': cls, 'key': key}

    def test_an_unknown_status_is_not_shown_as_success(self, pa):
        """A vocabulary the front end has never seen must not colour itself green —
        the whole point of the badge is that it can be wrong."""
        mystery = pa['node_status_map']['mystery']
        assert mystery['key'] == 'runsMgr.node.done'
        assert pa['node_status_map']['empty']['key'] == 'runsMgr.node.done'


class TestExportActions:
    def test_download_uses_a_hidden_iframe_not_a_navigation(self, pa):
        """Navigating the page to a file URL would lose the canvas the user is
        holding, which is why this is not a plain link."""
        download = pa['export_download']
        assert download['tag'] == 'IFRAME'
        assert download['hidden'] == 'none'
        assert download['src'].startswith('/api/exports/download?name=')

    def test_a_report_opens_through_its_script_free_route(self, pa):
        view = pa['export_view']
        assert view['url'].startswith('/api/report/view?name=')
        assert view['isDownload'] is False

    def test_deleting_an_export_asks_first(self, pa):
        assert pa['export_remove_declined']['requested'] == 0
        assert pa['export_remove']['url'] == '/api/exports/delete'
        assert pa['export_remove']['body'] == {'name': 'a.csv'}

    def test_a_refused_delete_reports_failure_not_success(self, pa):
        toasts = pa['export_remove_refused']['toasts']
        assert toasts == ['Delete failed'], toasts

    def test_sizes_are_readable_not_raw_byte_counts(self, pa):
        assert pa['export_sizing'] == {
            'bytes': '512 B',
            'kilobytes': '2.0 KB',
            'megabytes': '3.0 MB',
            'missing': '0 B',
        }

    def test_a_filename_with_a_quote_survives_the_markup_that_shows_it(self, pa):
        """The row's buttons are built by string concatenation, so the value has to
        escape both the JS literal and the HTML attribute."""
        assert pa['export_quoting']['roundTripSafe'] is True
        assert pa['export_quoting']['quote'] == "it\\'s a \\\\ test"

    def test_a_report_with_nothing_to_say_sends_nothing(self, pa):
        assert pa['report_cancelled']['requested'] == 0

    def test_generating_a_report_posts_the_run_it_describes(self, pa):
        assert pa['report_request']['url'] == '/api/report/generate'
        assert pa['report_request']['body']['run_id'] == 'r1'


class TestDatasetActions:
    def test_renaming_posts_the_new_name(self, pa):
        renamed = pa['dataset_renamed']
        assert renamed['url'] == '/api/data/datasets/ds1/rename'
        assert renamed['body'] == {'name': '新名字'}
        assert renamed['toasts'] == ['Dataset renamed']

    def test_the_rename_button_does_not_carry_its_own_answer(self, pa):
        """A dialog with an input is answered by the INPUT — unless a button says otherwise.

        The real showDialog resolves a clicked button as ``b.value !== undefined ?
        b.value : inputEl.value``. This call site named its confirm button
        ``value: 'ok'``, so the POST body was ``{"name": "ok"}``: the panel said
        已重命名, the row read ``ok``, and the dataset's label was gone (the file
        itself survives because its id is a content hash). The canned dialog answer in
        this harness could never show that, so the SPEC of the dialog is asserted.
        """
        specs = pa['dataset_renamed']['specs']
        assert len(specs) == 1, specs
        spec = specs[0]
        assert spec['hasInput'] is True, 'this dialog collects text, so the input owns the answer'
        confirm = [b for b in spec['buttons'] if b['primary']]
        assert len(confirm) == 1, spec['buttons']
        assert confirm[0]['value'] == '<absent>', (
            f'a primary button with a value token replaces what the user typed: {confirm[0]}'
        )
        # Cancel answering null is the intended shape — it must not be "fixed" away.
        assert [b['value'] for b in spec['buttons'] if not b['primary']] == ['null'], spec['buttons']

    def test_a_cancelled_rename_sends_nothing(self, pa):
        assert pa['dataset_rename_cancelled']['requested'] == 0

    def test_the_server_refusal_is_the_message_the_user_sees(self, pa):
        assert pa['dataset_rename_refused']['toasts'] == ['name taken']

    def test_a_file_a_workflow_still_points_at_is_refused_before_the_request(self, pa):
        blocked = pa['dataset_remove_blocked_locally']
        assert blocked['requested'] == 0
        assert blocked['toasts'], 'a silent refusal reads as a button that does nothing'

    def test_an_unreferenced_dataset_is_deleted_with_the_delete_verb(self, pa):
        removed = pa['dataset_removed']
        assert removed['method'] == 'DELETE'
        assert removed['url'] == '/api/data/datasets/ds1'
        assert removed['toasts'] == ['Dataset deleted']

    def test_a_declined_deletion_sends_nothing(self, pa):
        assert pa['dataset_remove_declined']['requested'] == 0


class TestClearAllButtons:
    """The three bulk 清空 buttons — the only actions here that destroy a whole set.

    Each is pinned on four things, because a bulk delete is the one mistake a user cannot
    spot row by row: it asks first; a declined answer sends nothing; the request carries the
    explicit ``confirm`` the endpoint refuses without; and the panel reloads, so what is on
    screen afterwards is what the server did. The toast's number is asserted too — a clear
    that reports nothing looks exactly like a clear that removed nothing.
    """

    def test_declining_any_of_the_three_sends_no_request_at_all(self, pa):
        assert pa['runs_clear_declined']['requested'] == 0
        assert pa['exports_clear_declined']['requested'] == 0
        assert pa['datasets_clear_declined']['requested'] == 0

    def test_the_run_clear_is_one_bulk_call_that_carries_confirm_and_reloads(self, pa):
        cleared = pa['runs_clear']
        assert cleared['url'] == '/api/runs/clear' and cleared['method'] == 'POST'
        assert cleared['body'] == {'confirm': True}
        assert cleared['clears'] == 1, 'a loop of per-row deletes would leave the claims behind'
        assert cleared['reloaded'] is True
        assert '3' in cleared['toast'], cleared['toast']

    def test_a_refused_run_clear_shows_the_servers_reason_and_still_repaints(self, pa):
        refused = pa['runs_clear_refused']
        assert refused['reloaded'] is True, 'the panel must not keep showing rows the server may have kept'
        assert any('需要 confirm' in line for line in refused['toasts']), refused['toasts']

    def test_the_export_clear_is_one_bulk_call_that_reloads_the_listing(self, pa):
        cleared = pa['exports_clear']
        assert cleared['url'] == '/api/exports/clear'
        assert cleared['body'] == {'confirm': True}
        assert cleared['clears'] == 1
        assert cleared['reloaded'] is True
        assert '2' in cleared['toast'], cleared['toast']

    def test_a_busy_export_folder_is_reported_rather_than_shown_as_emptied(self, pa):
        """The refusal is the case that matters most here: a running crawl writes into this
        directory, and a toast saying 「已清空」 over files still being appended is a lie."""
        assert any('正在运行' in line for line in pa['exports_clear_refused']['toasts'])

    def test_the_dataset_clear_sends_the_boolean_the_endpoint_reads(self, pa):
        """``{'all': '1'}`` and ``{'all': True}`` are not the same request.

        The route reads a switch, and a text '1' from the browser would have answered the
        wipe click with the orphan sweep instead — the panel reloads holding every referenced
        file while the toast claims a clear that never happened.
        """
        cleared = pa['datasets_clear']
        assert cleared['url'] == '/api/data/clear'
        assert cleared['body'] == {'all': True}
        assert cleared['reloaded'] is True
        assert '4' in cleared['toast'], cleared['toast']

    def test_a_refused_dataset_clear_says_so_instead_of_counting_zero_files(self, pa):
        refused = pa['datasets_clear_refused']['toasts']
        assert any('存储不可用' in line for line in refused), refused
        assert not any('cleared' in line or '已清空' in line for line in refused), refused


class TestProcessPanel:
    def test_an_open_panel_reports_every_thread_it_was_given(self, pa):
        fetched = pa['processes']
        assert fetched['fetched'] == ['/api/workflow/processes']
        assert fetched['mentionsEveryThread'] is True

    def test_only_a_killable_thread_offers_the_button(self, pa):
        """MainThread and the run thread are the server itself; a dead thread has
        nothing to kill."""
        assert pa['processes']['killButtons'] == 1

    def test_a_closed_panel_stops_fetching(self, pa):
        assert pa['processes_closed_panel_fetches_nothing']['requested'] == 0

    def test_kill_posts_the_threads_identifier(self, pa):
        kill = pa['kill']
        assert kill['url'] == '/api/workflow/processes/kill'
        assert kill['method'] == 'POST'
        assert kill['body'] == {'ident': 12345}
        assert kill['toasts'] == ['killed']

    def test_a_button_without_an_identifier_sends_nothing(self, pa):
        assert pa['kill_without_ident']['requested'] == 0

    def test_a_refused_kill_says_why(self, pa):
        assert any('permission denied' in toast for toast in pa['kill_refused']['toasts'])


class TestTopBarWrites:
    def test_unpinning_takes_both_the_bar_and_the_button_and_saves_it(self, pa):
        unpinned = pa['unpinned']
        assert unpinned['menuPinned'] is False
        assert unpinned['buttonPinned'] is False
        assert unpinned['aria'] == 'false', 'the button must announce its state'
        assert unpinned['draft'] is False
        assert pa['repinned'] == {'aria': 'true', 'menuPinned': True, 'buttonPinned': True}

    def test_switching_the_background_replaces_the_old_one(self, pa):
        """The old class was only removed by a regex over className; a leftover
        second bg-* class would paint two backgrounds."""
        switched = pa['background_switched']
        assert switched['bodyClasses'] == ['bg-dots']
        assert switched['previousCleared'] is True
        assert switched['nowMarked'] is True
        assert switched['draft'] == 'bg-dots'

    def test_the_language_switch_saves_announces_and_re_labels(self, pa):
        switched = pa['language_switched']
        assert switched['tag'] == 'en'
        assert switched['draft'] == 'en'
        assert switched['toasts'], 'the change must be visible, not just stored'
        assert switched['nodeLabel'] == 'Data Source', 'a node title the user never typed follows the language'

    def test_switching_back_restores_the_other_language(self, pa):
        assert pa['language_back']['tag'] == 'zh'


class TestHistoryRowActions:
    """One recorded run must be deletable on its own.

    ``清空历史`` used to be the only door, so removing one bad run cost the whole
    comparison chart. The row's button is now a decision of its own: what is sent,
    what a decline sends, and what the toast claims when the server says the run
    was already gone.
    """

    def test_every_listed_run_gets_its_own_button(self, pa):
        rows = pa['history_rows']
        assert rows['buttons'] == 2, 'one button per run, not one per metric or one per panel'
        assert rows['ids'] == ['data-run-id="r-keep"', 'data-run-id="r-del"'], (
            f'the id must survive as a plain attribute: {rows["ids"]}'
        )
        assert rows['label'] == '删除', 'the button says what it does, in the catalogue’s own words'

    def test_declining_the_confirmation_sends_nothing(self, pa):
        assert pa['history_declined'] == {'requested': 0, 'toasts': []}

    def test_confirming_posts_the_id_and_redraws_both_halves_of_the_panel(self, pa):
        deleted = pa['history_deleted']
        assert deleted['method'] == 'POST'
        assert deleted['body'] == {'run_id': 'r-del'}
        assert 'r-del' in deleted['askedMessage'], 'the question has to name the run about to vanish'
        assert deleted['reloadedRuns'] == 1 and deleted['reloadedSeries'] == 1, (
            'the row disappears from the table AND from the chart, or the panel shows data the server no longer has'
        )
        assert deleted['toasts'] == ['该运行已从执行历史中删除']

    def test_a_run_that_was_already_gone_is_reported_as_that(self, pa):
        """``deleted: 0`` is not a deletion: the list on screen predates the click,
        and the retention policy can have aged the run out in between."""
        assert pa['history_already_gone']['toasts'] == ['这条运行已不在执行历史里（期间被自动清理）']

    def test_a_refusal_is_shown_and_changes_nothing_on_screen(self, pa):
        refused = pa['history_refused']
        assert refused['reloaded'] == 0, 'a failed delete must not pretend to have refreshed'
        assert refused['toasts'] and refused['toasts'][0].startswith('删除失败'), refused

    def test_an_id_that_is_only_whitespace_does_not_open_a_dialog(self, pa):
        assert pa['history_blank_id'] == {'requested': 0}


class TestOnePressOneToast:
    """The toast element is ONE node whose text is replaced, so a loop over the
    validation errors showed the LAST problem only — the user fixed it, pressed
    执行 again, met the next one, and so on for the length of the list."""

    def test_a_blocked_run_reports_every_problem_in_one_toast(self, pa):
        got = pa['two_problems_one_toast']
        assert got['started'] == 0, 'a canvas with problems must not start a run'
        assert len(got['toasts']) == 1, (
            f'one press produced {len(got["toasts"])} toasts, and only the last is on screen: {got["toasts"]}'
        )
        lines = str(got['toasts'][0]).split('\n')
        header, items = lines[0], lines[1:]
        assert len(items) >= 2, f'two broken nodes must say two things: {got["toasts"]}'
        assert str(len(items)) in header, f'the header has to state how many follow: {header!r}'
        assert items[0].startswith('1. ') and items[1].startswith('2. '), items

    def test_a_single_problem_stays_a_single_sentence(self, pa):
        """The count header exists to explain a LIST. With one problem the message
        already names the node, so numbering it would be scaffolding."""
        toasts = pa['one_problem_plain_toast']['toasts']
        assert len(toasts) == 1, toasts
        assert '\n' not in str(toasts[0]), f'one problem does not need a list: {toasts[0]!r}'


class TestLanguageReachesEveryTable:
    """The 数据集管理 and 执行历史 tables build their header row in JS from the
    catalogue, so `I18n.apply()` — which re-stamps elements carrying `data-i18n` —
    walks right past them. The rest of the page changed language and these two did
    not, until the panel happened to be closed and reopened."""

    def test_the_dataset_table_changes_language_with_the_page(self, pa):
        got = pa['language_reaches_builtin_tables']
        assert '名称' in got['before']['dataset'] and '行数' in got['before']['dataset'], got['before']
        assert 'Name' in got['after']['dataset'] and 'Rows' in got['after']['dataset'], got['after']
        assert '名称' not in got['after']['dataset'], 'the old header is still on screen underneath the new one'

    def test_the_execution_history_table_changes_language_with_the_page(self, pa):
        got = pa['language_reaches_builtin_tables']
        assert '执行 ID' in got['before']['history'], got['before']
        assert 'Run ID' in got['after']['history'] and 'Workflow' in got['after']['history'], got['after']
        assert '执行 ID' not in got['after']['history']

    def test_the_workflow_file_table_changes_language_with_the_page(self, pa):
        got = pa['language_reaches_builtin_tables']
        assert '名称' in got['before']['workflows'] and '节点数' in got['before']['workflows'], got['before']
        assert 'Name' in got['after']['workflows'] and 'Nodes' in got['after']['workflows'], got['after']
        assert '名称' not in got['after']['workflows']


class TestRowButtonEscaping:
    """Every panel row builds `onclick="fn('…')"` out of a name the user chose.

    The escaper has to satisfy two grammars at once — the JavaScript literal and the
    HTML attribute — and the three panels each carried a copy of the JS half only, so
    one double quote in a file name closed its own attribute. That is the same class
    of hole #115 closed on the canvas nodes, so the panels now share one function and
    all three shapes are pinned here.
    """

    def test_a_double_quote_becomes_an_entity_not_an_attribute_end(self, pa):
        assert pa['attrEscaper']['quote'] == 'a&quot;b'

    def test_an_ampersand_is_escaped_exactly_once(self, pa):
        assert pa['attrEscaper']['ampersandOnce'] is True

    def test_a_real_newline_cannot_end_the_literal(self, pa):
        assert pa['attrEscaper']['newline'] == 'a\\nb'

    def test_the_javascript_half_still_holds(self, pa):
        assert pa['attrEscaper']['stillJsSafe'] is True


class TestWorkflowFilePanel:
    """打开 / 重命名 / 删除 on a saved canvas — three ways to lose work if wrong."""

    def test_rename_posts_both_names_and_rebinds_the_canvas(self, pa):
        got = pa['wf_renamed']
        assert got['url'] == '/api/workflow/rename'
        assert got['body'] == {'name': 'old', 'new_name': '新名字'}
        assert got['currentFile'] == '新名字', 'the next 保存 would recreate the file just renamed away'

    def test_the_rename_answer_comes_from_the_input_not_the_button(self, pa):
        """A confirm button carrying its own `value:` replaces whatever was typed —
        the shape that once stored the literal 'ok' as a dataset name."""
        spec = pa['wf_renamed']['specs'][-1]
        assert spec['hasInput'] is True
        assert [b['value'] for b in spec['buttons']] == ['null', '<absent>'], spec['buttons']

    def test_a_cancelled_rename_sends_nothing(self, pa):
        assert pa['wf_rename_cancelled']['requested'] == 0

    def test_an_unchanged_name_sends_nothing(self, pa):
        """The dialog is pre-filled with the current name, so answering it untouched
        is the user pressing the button without editing — not a rename to itself."""
        assert pa['wf_rename_unchanged']['requested'] == 0

    def test_a_refusal_shows_the_servers_reason_and_keeps_the_binding(self, pa):
        got = pa['wf_rename_refused']
        assert got['toasts'] == ['name taken: x'], got['toasts']
        assert got['currentFile'] is None

    def test_opening_a_workflow_over_a_non_empty_canvas_asks_first(self, pa):
        got = pa['wf_open_declined']
        assert got['asked'] == 1 and got['requested'] == 0, 'a decline must not even read the file'

    def test_an_empty_canvas_opens_without_a_dialog(self, pa):
        got = pa['wf_open_empty_canvas']
        assert got['asked'] == 0
        assert got['url'] == '/api/workflow/load?name=saved'
        assert got['currentFile'] == 'saved'

    def test_an_accepted_open_loads_and_remembers_the_name(self, pa):
        got = pa['wf_open_accepted']
        assert got['asked'] == 1
        assert got['urls'] == ['/api/workflow/load?name=saved']
        assert got['currentFile'] == 'saved'

    def test_delete_confirms_then_posts_the_name(self, pa):
        got = pa['wf_removed']
        assert (got['method'], got['url'], got['body']) == ('POST', '/api/workflow/delete', {'name': 'old'})

    def test_a_declined_delete_sends_nothing(self, pa):
        assert pa['wf_remove_declined']['requested'] == 0

    @pytest.mark.parametrize('action', ['wf_open_while_running', 'wf_rename_while_running'])
    def test_all_three_actions_refuse_while_a_run_is_live(self, pa, action):
        """打开 re-keys the ambient name of the live run and 重命名/删除 move or drop
        the file behind it, so the panel says so instead of bouncing a 409."""
        got = pa[action]
        assert got['requested'] == 0, got
        assert len(got['toasts']) == 1 and 'run is live' in str(got['toasts'][0]), got['toasts']


class TestItemLock:
    """#182 — the lock button posts to /api/locks and the row repaints as engaged."""

    def test_toggling_posts_the_panel_key_and_state(self, pa):
        lock = pa['lock']
        assert lock['toggleMethod'] == 'POST', lock
        assert lock['toggleBody'] == {'panel': 'exports', 'key': 'keep.csv', 'locked': True}, lock['toggleBody']

    def test_the_cache_flips_after_toggle(self, pa):
        assert pa['lock']['cacheLocked'] is True

    def test_the_row_repaints_with_the_lock_engaged(self, pa):
        lock = pa['lock']
        assert lock['rowShowsLocked'] is True, 'the row lost its engaged-lock styling'
        assert lock['rowAriaPressed'] is True, 'the lock button does not expose its state'
        # The glyph is a drawn SVG (so it follows the page's grey/accent), never the
        # fixed-colour Unicode padlock — the reason 🔒/🔓 were replaced.
        assert lock['lockedIsSvg'] is True and lock['lockedNoEmoji'] is True, 'locked glyph is still emoji'
        assert lock['unlockedIsSvg'] is True and lock['unlockedNoEmoji'] is True, 'unlocked glyph is still emoji'
        assert lock['lockedClosed'] is True, 'locked must draw a seated shackle'
        assert lock['unlockedOpen'] is True, 'unlocked must draw a swung-open shackle'


class TestDatasetSourceLabels:
    """The dataset 来源 cell stores a CODE (upload / paste / analysis), so the panel must
    show the catalogue label — and an unknown code must fall through as itself rather than
    a made-up translation."""

    def test_each_known_source_code_shows_its_label(self, pa):
        labels = pa['dataset_source_labels']
        assert labels['upload'] == '上传文件'
        assert labels['paste'] == '粘贴文本'
        assert labels['analysis'] == '清洗结果'

    def test_an_unknown_or_blank_code_shows_itself_not_a_fabrication(self, pa):
        labels = pa['dataset_source_labels']
        assert labels['unknown'] == 'mystery', 'an unseen code was translated instead of shown raw'
        assert labels['empty'] == '', 'a blank code became non-blank'

    def test_the_source_label_follows_the_language(self, pa):
        en = pa['dataset_source_labels_en']
        assert en == 'Uploaded file', f'the label did not switch to the English catalogue: {en}'
