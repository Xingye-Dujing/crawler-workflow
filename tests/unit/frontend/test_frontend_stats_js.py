"""Behaviour tests for the real stats panel module (backend/static/js/stats.js).

The two sentiment pies are drawn by a library that arrives from a CDN, on a tool
that is routinely opened offline. Until now stats.js was loaded by some harnesses
and executed by none: ``init``/``refresh``/``loadEmotion``/``renderPie``/``switchTab``
had zero executed coverage, which is how an unguarded ``echarts.init`` in the page's
single DOMContentLoaded body came to take the capability fetch, the dataset re-link,
the autosave and the resume banner down with it.

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

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_stats.mjs'


@pytest.fixture(scope='module')
def stats(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('js-stats')
    scenarios = [
        {'id': 'with_library', 'echarts': True, 'call': 'init'},
        {'id': 'without_library', 'echarts': False, 'call': 'init'},
        {'id': 'refresh_without_library', 'echarts': False, 'call': 'refresh'},
        {'id': 'pie_options', 'echarts': True, 'call': 'renderPie', 'stats': {'labels': ['Joy'], 'values': [3]}},
        {'id': 'pie_without_library', 'echarts': False, 'call': 'renderPie'},
    ]
    sc = tmp / 'scenarios.json'
    sc.write_text(json.dumps(scenarios, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR / 'stats.js'), str(sc))
    assert proc.returncode == 0, f'stats harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


class TestMissingChartLibrary:
    def test_init_survives_a_library_that_never_arrived(self, stats):
        """No CDN must not be an exception — and no exception must end the page.

        This throw used to sit inside the ONE DOMContentLoaded body that boots the
        app, so it also skipped CustomSelect.init, Capabilities.load,
        dataNodes.reconcileDatasets, the 30-second autosave and resumeBar.refresh.
        """
        r = stats['without_library']
        assert r['threw'] is None, r['threw']
        assert r['unavailable'] is True
        assert r['charts'] == 0

    def test_the_panel_says_the_library_is_missing_instead_of_looking_empty(self, stats):
        r = stats['without_library']
        # The message is a catalogue key here because the harness stubs I18n — what
        # is pinned is that a note is rendered at all, as an element, in BOTH boxes.
        assert 'i18n:stats.noChartLibrary' in r['note'], r
        assert r['noteIsElement'] is True, 'text in a child element, never a markup string'
        assert r['children'] == 1, r

    def test_the_other_entry_points_decline_quietly_too(self, stats):
        assert stats['refresh_without_library']['threw'] is None
        assert stats['refresh_without_library']['charts'] == 0
        assert stats['pie_without_library']['threw'] is None, (
            'renderPie guards its chart: a resize on a chart that was never built is the next throw waiting'
        )
        assert stats['pie_without_library']['charts'] == 0
        assert stats['pie_without_library']['emotionChartNull'] is True

    def test_the_work_is_still_done_when_the_library_is_there(self, stats):
        assert stats['with_library']['threw'] is None
        assert stats['with_library']['unavailable'] is False
        assert stats['with_library']['charts'] == 2, 'one pie per sentiment axis'
        assert stats['with_library']['emotionChartNull'] is False


class TestPieOptions:
    def test_pie_labels_read_the_page_theme_not_a_hardcoded_dark_grey(self, stats):
        """A dark-theme leftover on a light card is unreadable, not just ugly.

        The background colour is a user setting (the menu offers several), so the
        colours come from the CSS custom properties like historyPanel's chart does.
        """
        option = stats['pie_options']['option']
        assert option, stats['pie_options']
        label = option['series'][0]['label']
        assert label['color'] == 'var(--text-dim)', label
        assert 'JetBrains Mono' not in label['fontFamily'], 'a font the page never loads'
        assert option['series'][0]['data'] == [{'name': 'Joy', 'value': 3, 'itemStyle': {'color': '#f1c40f'}}]
