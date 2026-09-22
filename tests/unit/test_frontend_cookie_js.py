"""Behaviour tests for the real cookie panel (workflow.js) under node.

The panel is where "which page do I log in on?" gets answered, and for WeChat
that answer is the difference between crawling comments and not. Its logic —
fetch the flow, render it per selected platform, carry the pasted entry link
into the request, keep the login buttons out of a verification — is JS, so the
Python suite cannot see it. This module runs the untouched file.

Skipped when node is not on PATH, like every other frontend harness.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

JS_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_cookie.mjs'


@pytest.fixture(scope='module')
def panel():
    if shutil.which('node') is None:
        pytest.skip('node not on PATH')
    proc = subprocess.run(
        ['node', str(HARNESS), str(JS_DIR / 'workflow.js')],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
    )
    assert proc.returncode == 0, f'harness failed: {proc.stderr[-2000:]}'
    return json.loads(proc.stdout)


def _urls(report):
    return [call['url'] for call in report['calls']]


def _body(report, url):
    for call in report['calls']:
        if call['url'] == url:
            return call['body']
    raise AssertionError(f'{url} was never called in {report["calls"]}')


class TestGuide:
    def test_the_selected_platforms_steps_are_rendered_in_order(self, panel):
        report = panel['guideWechatFirstCall']
        assert report['guideLines'] == ['PURPOSE-WECHAT', 'STEP-ONE', 'STEP-TWO']

    def test_the_flow_is_fetched_once_and_then_served_from_cache(self, panel):
        assert _urls(panel['guideWechatFirstCall']) == ['/api/cookies/flow']
        assert _urls(panel['guideWechatSecondCall']) == ['/api/cookies/flow']

    def test_re_rendering_replaces_the_list_instead_of_appending(self, panel):
        """A panel that grew a second copy of the steps on every platform switch
        would be unreadable — and the bug only shows in a browser-faithful DOM."""
        assert panel['guideWechatSecondCall']['guideLines'] == ['PURPOSE-WECHAT', 'STEP-ONE', 'STEP-TWO']

    def test_switching_platform_switches_the_whole_explanation(self, panel):
        report = panel['guideZhihu']
        assert report['guideLines'] == ['PURPOSE-ZHIHU', 'Z-STEP']

    def test_the_entry_field_is_prefilled_with_that_platforms_login_page(self, panel):
        assert panel['guideWechatFirstCall']['entryPlaceholder'] == 'https://mp.weixin.qq.com/'
        assert panel['guideZhihu']['entryPlaceholder'] == 'https://www.zhihu.com/'


class TestGenerate:
    def test_the_pasted_link_is_sent_along_with_the_wait_time(self, panel):
        body = _body(panel['generate'], '/api/cookies/generate')
        assert body == {
            'platform': 'wechat',
            'wait_seconds': 45,
            'url': 'https://mp.weixin.qq.com/s?pass_ticket=P#rd',
        }

    def test_a_rejected_link_is_toasted_not_swallowed(self, panel):
        """The window opens on the platform page instead; silence here would let
        the user log into the wrong thing believing their link was used."""
        assert 'ENTRY-REJECTED' in panel['generate']['toasts']

    def test_a_started_login_locks_the_panel_and_offers_its_buttons(self, panel):
        report = panel['generate']
        assert report['job']['active'] is True and report['job']['kind'] == 'login'
        assert report['actionsDisplay'] == 'flex'


class TestVerify:
    def test_verification_sends_the_same_entry_link(self, panel):
        body = _body(panel['verifyRunning'], '/api/cookies/verify')
        assert body['url'] == 'https://mp.weixin.qq.com/s?pass_ticket=P#rd'
        assert body['platform'] == 'wechat'

    def test_a_running_verification_hides_the_login_buttons(self, panel):
        """Done/Cancel resolve a login window. Showing them over a probe invites
        a click that means nothing."""
        report = panel['verifyRunning']
        assert report['job']['kind'] == 'verify'
        assert report['actionsDisplay'] == 'none'
        assert report['statusText'] == 'cookie.verifying'

    def test_the_verdict_lines_are_printed_in_full(self, panel):
        report = panel['verifyDone']
        assert report['statusText'] == 'LINE-ONE\nLINE-TWO'
        assert report['job']['active'] is False

    def test_a_busy_server_still_adopts_the_running_job(self, panel):
        """Another window is open (this tab or an earlier one): the panel must
        follow it rather than dead-end on the refusal."""
        report = panel['verifyBusy']
        assert report['statusText'] == 'BUSY'
        assert report['job']['active'] is True

    def test_reopening_the_dialog_adopts_a_running_verification(self, panel):
        report = panel['adoptedOnOpen']
        assert panel['dialogOpen'] is True
        assert report['job'] == {'active': True, 'kind': 'verify', 'platform': 'zhihu'}
        assert report['actionsDisplay'] == 'none'
