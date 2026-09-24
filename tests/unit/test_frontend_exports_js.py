"""Behaviour tests for the export-artefact panel (workflow.js exportsManager).

Runs the real workflow.js in node (tests/frontend/harness_exports.mjs) against a
fixture payload, because this panel is the one place a filename is both displayed
and handed back to the server — a quoting mistake is not a cosmetic bug there, it
is a request for a different file.

Pinned:
* a non-downloadable entry (a ``.py`` in the export folder) gets NO download
  button, so the UI rule and ``/api/exports/download`` agree;
* a generated report gets 查看 instead, because ``/api/report/view`` is the only
  door an HTML file in that folder can come through;
* a name with a quote or a backslash survives both the HTML attribute and the JS
  string literal the panel embeds it in;
* sizes read as B/KB/MB and the header total is directory-wide, not page-wide;
* an empty folder renders the empty state, not an error;
* the 生成报告 dialog's three outcomes build two different payloads and, when
  cancelled, send nothing at all.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

REPO = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_exports.mjs'
WORKFLOW_JS = REPO / 'backend' / 'static' / 'js' / 'workflow.js'

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

PAYLOAD = {
    'ok': True,
    'files': 4,
    'bytes': 6000,
    'exports': [
        {'name': "it's.csv", 'kind': 'csv', 'size': 2048, 'mtime': 1700000000, 'downloadable': True},
        {'name': 'back\\slash.json', 'kind': 'json', 'size': 512, 'mtime': 1700000100, 'downloadable': True},
        {'name': 'script.py', 'kind': 'other', 'size': 4096, 'mtime': 1700000200, 'downloadable': False},
        {'name': 'report-季度.html', 'kind': 'report', 'size': 9000, 'mtime': 1700000300, 'downloadable': False},
    ],
}


@pytest.fixture(scope='module')
def results(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('exports')
    (tmp / 'payload.json').write_text(json.dumps(PAYLOAD), encoding='utf-8')
    proc = run_node(str(HARNESS), str(WORKFLOW_JS), str(tmp / 'payload.json'))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class TestExportRows:
    def test_every_row_is_rendered(self, results):
        # one header row plus one per file
        assert results['rows'] == len(PAYLOAD['exports']) + 1

    def test_a_non_downloadable_file_gets_no_download_button(self, results):
        assert results['downloads'] == 2, 'only the two downloadable rows may offer a download'
        assert results['deletes'] == 4, 'every row may still be deleted'
        assert 'script.py' in results['html']

    def test_a_filename_is_escaped_for_display(self, results):
        """A crafted file name is the injection point here, so the cell must show
        the entity, not the raw quote — and the display copy must be escaped
        independently of the quoted copy embedded in the handler."""
        assert '&lt;' not in results['html']
        assert 'it&#39;s.csv' in results['html'], 'display text must be HTML-escaped'
        assert "onclick=\"exportsManager.download('it\\'s.csv')" in results['html'], 'handler keeps the JS-escaped name'

    def test_quoting_survives_the_inline_handler(self, results):
        """The handler is a JS string inside an HTML attribute: a quote or a
        backslash that is not doubled terminates the call early and turns the
        button into a request for the wrong file."""
        assert results['quoted'] == ["it\\'s.csv", 'back\\\\slash.csv', 'a"b.csv']

    def test_sizes_are_human_readable(self, results):
        assert results['size'] == ['0 B', '999 B', '2.0 KB', '5.0 MB']

    def test_the_header_counts_the_directory_not_the_page(self, results):
        assert '4 file(s)' in results['html'] and '5.9 KB' in results['html']

    def test_an_empty_folder_is_empty_not_broken(self, results):
        assert results['empty'] == '<div class="runs-mgr-empty">EMPTY</div>'

    def test_the_download_link_url_encodes_the_name(self, results):
        assert results['dlHref'] == "/api/exports/download?name=ENC(it's.csv)"


class TestDeleteDialog:
    """Deleting a file is confirmed by the app's dialog, not by the browser's.

    The three destructive buttons in this app used to answer `window.confirm`, which
    cannot follow the interface language, cannot be styled with the page, and hands back
    a bare true/false that says nothing about what is about to be lost.
    """

    def test_canceling_asks_and_sends_nothing(self, results):
        assert results['cancelledPosts'] == [], 'a closed dialog must not delete the file'
        assert results['cancelledDialog'] == [['CANCEL', None, False], ['Delete', 'go', False]]

    def test_the_confirmation_names_the_action_it_is_asked_about(self, results):
        """The button says 删除, not 确认: an irreversible row action should be readable
        as itself, which is the thing a native confirm dialog cannot do."""
        assert [label for label, _value, _wi in results['deletedDialog']] == ['CANCEL', 'Delete']

    def test_confirming_deletes_exactly_that_file(self, results):
        assert len(results['deletedPosts']) == 1, results['deletedPosts']
        post = results['deletedPosts'][0]
        assert post['url'] == '/api/exports/delete'
        assert post['body'] == {'name': 'ok.csv'}


class TestReportRow:
    def test_a_report_is_offered_as_a_view_and_never_as_a_download(self, results):
        """The file is .html, and the download route refuses that extension on
        purpose — so a download button on this row would be a dead end the panel
        made with its own hands."""
        assert results['views'] == 1
        assert "exportsManager.view('report-季度.html')" in results['html']
        assert "exportsManager.download('report-季度.html')" not in results['html']


class TestReportButton:
    def test_the_dialog_offers_three_outcomes_and_remembers_the_typed_title(self, results):
        first = results['dialogs'][0]
        assert first['hasInput'] is True
        # Cancel throws its answer away; the two creating buttons must not, or
        # the title the user typed would be lost to the choice they made.
        assert first['buttons'] == [['CANCEL', None, False], ['CREATE-AI', 'ai', True], ['CREATE', 'go', True]]

    def test_creating_from_the_page_sends_the_canvas_titles_and_no_run_id(self, results):
        body = results['posts'][0]['body']
        assert body['title'] == '季度报告', 'the typed title must be trimmed and sent'
        assert body['include_conclusion'] is True
        assert 'run_id' not in body
        # A node with no title of its own travels as its id, which is the only
        # name the backend has for it.
        assert body['nodes'] == [{'id': 'node-1', 'title': '数据源'}, {'id': 'node-2', 'title': 'node-2'}]

    def test_creating_from_a_stored_run_sends_the_run_id_instead(self, results):
        body = results['posts'][1]['body']
        assert body['run_id'] == 'run-7'
        assert 'nodes' not in body, 'a stored run must not be described by this canvas'
        assert body['include_conclusion'] is False
        assert body['title'] == '', 'an empty title lets the server name it after the workflow'

    def test_the_request_language_travels_twice_as_every_other_call_does(self, results):
        for post in results['posts']:
            assert post['url'] == '/api/report/generate'
            assert post['method'] == 'POST'
            assert post['lang'] == 'en'
            assert post['body']['lang'] == 'en'

    def test_cancel_requests_nothing(self, results):
        assert len(results['posts']) == 2, 'the cancelled dialog must not have POSTed'
        assert len(results['dialogs']) == 3

    def test_a_written_report_is_opened_and_the_panel_refreshed(self, results):
        assert results['opens'] == ['/api/report/view?name=ENC(report-x.html)'] * 2
        assert results['toasts'] == ['DONE', 'DONE']
