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
