"""The Console's phase-timing strip: real ``panels/phase-log.js`` over a stubbed transport.

It is the answer to “the window opened and nothing happened”, so the assertions are about
the numbers a person reads (how long the browser/search one link took, what it settled on)
and about the two ways such a strip usually goes wrong: repainting every poll, and letting
a note URL reach the DOM as markup.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

HERE = Path(__file__).resolve().parents[2] / 'frontend'
JS_DIR = Path(__file__).resolve().parents[3] / 'backend' / 'static' / 'js'


@pytest.fixture(scope='module')
def phase_log():
    proc = run_node(
        str(HERE / 'harness_phase_log.mjs'),
        str(JS_DIR / 'panels' / 'phase-log.js'),
    )
    assert proc.returncode == 0, f'phase-log harness failed: {proc.stderr[-2000:]}: {proc.stdout[-2000:]}'
    return json.loads(proc.stdout)


def test_an_empty_answer_says_so_instead_of_a_blank_box(phase_log):
    assert phase_log['empty']['url'] == '/api/run/phases'
    assert 'No timings yet' in phase_log['empty']['text']
    assert '<table' not in phase_log['empty']['text']


def test_rows_carry_seconds_the_status_and_the_row_count(phase_log):
    html = phase_log['rows']['html']
    assert 'Browser start' in html
    assert '1.2s' in html, 'the launch time is the number the strip exists for'
    assert '55.0s' in html and 'Crawl' in html
    assert '11.5s' in html and 'Comment walk' in html
    assert '3 rows' in html and 'ok' in html
    assert 'Xiaohongshu' in html, 'the platform reaches the row as a word, not a key'


def test_an_unchanged_payload_does_not_repaint(phase_log):
    assert phase_log['unchanged']['kept'] is True, 'the strip rewrote the DOM on an unchanged poll'


def test_a_note_url_and_label_are_escaped(phase_log):
    html = phase_log['escaped']
    assert '<img src=x' not in html, 'the label reached the DOM as markup'
    assert '<b>x</b>' not in html, 'the note URL reached the DOM as markup'
    assert '&lt;img' in html
    assert '3 rows' not in html, 'premise: this payload carries zero rows'


def test_a_running_phase_shows_its_elapsed_instead_of_silence(phase_log):
    html = phase_log['running']
    assert 'running' in html
    assert re.search(r'7[0-9]\.\ds', html), html


def test_a_closed_console_is_not_polled(phase_log):
    assert phase_log['closed']['fetched'] == 0, 'a hidden panel still asked the server'
