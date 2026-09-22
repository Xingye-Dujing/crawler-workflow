"""Behaviour tests for the export-artefact panel (workflow.js exportsManager).

Runs the real workflow.js in node (tests/frontend/harness_exports.mjs) against a
fixture payload, because this panel is the one place a filename is both displayed
and handed back to the server — a quoting mistake is not a cosmetic bug there, it
is a request for a different file.

Pinned:
* a non-downloadable entry (a ``.py`` in the export folder) gets NO download
  button, so the UI rule and ``/api/exports/download`` agree;
* a name with a quote or a backslash survives both the HTML attribute and the JS
  string literal the panel embeds it in;
* sizes read as B/KB/MB and the header total is directory-wide, not page-wide;
* an empty folder renders the empty state, not an error.
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
        assert results['deletes'] == 3, 'every row may still be deleted'
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
