"""The comment-region pre-run notice gate — ``_hasCommentCrawl`` / ``_confirmCommentRegionBeforeRun``.

Some platforms/videos publish no IP region in comments, so the 「评论地区」 column can come
back blank; the app warns once before a run that crawls comments so that blank is not read as
a bug. This drives the two workflow.js methods directly (not the full ``execute()``, which would
also raise the profile/serial dialogs and blur what is asserted): it must interrupt only a canvas
that really crawls comments — a dedicated 「评论」 node or a source switched to comments mode —
and stay silent for a plain search canvas; pressing 「知道了」 lets the run through, while
dismissing the notice does not.

The dialog wording is compared against the sandbox's own ``I18n.t(...)`` for those keys, never a
pasted sentence — so it tracks the catalog and would notice if the key were renamed or dropped.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_comment_region_notice.mjs'

_COMMENT_URL = {'urls': 'https://www.douyin.com/video/7653009893066067242'}

SCENARIOS = [
    {'id': 'comment-node-fires', 'nodes': {'n1': {'type': 'comment', 'params': _COMMENT_URL}}},
    {
        'id': 'source-in-comments-mode-fires',
        'nodes': {'n1': {'type': 'source', 'params': {'platform': 'douyin', 'mode': 'comments', 'urls': 'x'}}},
    },
    {
        'id': 'search-only-is-silent',
        'nodes': {'n1': {'type': 'source', 'params': {'platform': 'zhihu', 'mode': 'posts', 'author': 'k'}}},
    },
    {'id': 'empty-canvas-is-silent', 'nodes': {}},
    {
        'id': 'dismissed-blocks-the-run',
        'nodes': {'n1': {'type': 'comment', 'params': _COMMENT_URL}},
        'answers': {'comment': None},
    },
]


@pytest.fixture(scope='module')
def report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('comment-region-gate')
    payload = tmp / 'scenarios.json'
    payload.write_text(json.dumps(SCENARIOS, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR), str(payload))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    return json.loads(proc.stdout)


def case(report, id_):
    return report[id_]


class TestCommentRegionGate:
    def test_a_comment_node_interrupts_once_before_the_run(self, report):
        r = case(report, 'comment-node-fires')
        assert r['hasComment'] is True
        assert r['confirm'] is True, '「知道了」 presses the only button → the run proceeds'
        assert len(r['dialogs']) == 1, 'the notice fired exactly once'
        # The dialog text is the catalog's own notice, not a pasted string: it resolves and matches.
        assert r['noticeText'] and r['noticeText'] != 'dialog.commentRegionNotice', 'the i18n key is missing'
        assert r['dialogs'][0]['message'] == r['noticeText']

    def test_a_source_switched_to_comments_mode_also_counts_as_a_comment_crawl(self, report):
        r = case(report, 'source-in-comments-mode-fires')
        assert r['hasComment'] is True
        assert len(r['dialogs']) == 1

    def test_a_plain_search_canvas_is_never_interrupted(self, report):
        """The notice is about a column only a comment crawl fills; a search canvas has no such
        column, so popping it there would be noise the user learns to ignore."""
        r = case(report, 'search-only-is-silent')
        assert r['hasComment'] is False
        assert r['confirm'] is True, 'silent pass-through, no dialog to answer'
        assert r['dialogs'] == []

    def test_an_empty_canvas_is_silent(self, report):
        r = case(report, 'empty-canvas-is-silent')
        assert r['hasComment'] is False and r['dialogs'] == []

    def test_dismissing_the_notice_does_not_start_the_run(self, report):
        """The gate returns false when the user closes it, so execute() stops — a notice the
        user declines must not be bulldozed past into a crawl they meant to hold off on."""
        r = case(report, 'dismissed-blocks-the-run')
        assert r['hasComment'] is True
        assert r['confirm'] is False
        assert r['dialogs'][0]['labels'] and r['okText'] in r['dialogs'][0]['labels']
