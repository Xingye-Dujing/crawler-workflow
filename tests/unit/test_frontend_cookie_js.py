"""Behaviour tests for the real cookie panel (workflow.js) under node.

The panel answers "which page do I log in on?", and which platforms appear
there is a product decision: only ``CookieManager.PLATFORMS`` has a row, so the
samples below are real login platforms (bilibili takes a pasted entry link,
zhihu does not). WeChat is not among them — its article bodies are served to
anyone — and the guard for that absence lives in tests/unit/test_wechat_diagnose.py.
Its logic — fetch the flow, render it per selected platform, carry the pasted
entry link into the request, keep the login buttons out of a verification — is
JS, so the Python suite cannot see it. This module runs the untouched file.

Skipped when node is not on PATH, like every other frontend harness.
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = pytest.mark.unit

JS_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'js'
HARNESS = Path(__file__).resolve().parents[1] / 'frontend' / 'harness_cookie.mjs'


@pytest.fixture(scope='module')
def panel():
    if shutil.which('node') is None:
        pytest.skip('node not on PATH')
    proc = run_node(HARNESS, JS_DIR / 'workflow.js')
    assert proc.returncode == 0, f'harness failed: {proc.stdout[-2000:]}'
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
        report = panel['guideBilibiliFirstCall']
        assert report['guideLines'] == ['PURPOSE-BILIBILI', 'STEP-ONE', 'STEP-TWO']

    def test_the_flow_is_fetched_once_and_then_served_from_cache(self, panel):
        """Two tables behind the guide — the per-platform steps and the profile state that
        decides whether to advertise 「把 Cookie 更新进 Profile」 — and each is fetched once,
        including while both are still in flight (the guide repaints when either lands).

        ``report()`` accumulates every call the panel made, so the interesting half is
        that the second render's list is **the same length** as the first: nothing new
        was bought by repainting.
        """
        fetched = ['/api/browser/profiles', '/api/cookies/flow']
        assert _urls(panel['guideBilibiliFirstCall']) == fetched
        assert _urls(panel['guideBilibiliSecondCall']) == fetched

    def test_re_rendering_replaces_the_list_instead_of_appending(self, panel):
        """A panel that grew a second copy of the steps on every platform switch
        would be unreadable — and the bug only shows in a browser-faithful DOM."""
        assert panel['guideBilibiliSecondCall']['guideLines'] == ['PURPOSE-BILIBILI', 'STEP-ONE', 'STEP-TWO']

    def test_switching_platform_switches_the_whole_explanation(self, panel):
        report = panel['guideZhihu']
        assert report['guideLines'] == ['PURPOSE-ZHIHU', 'Z-STEP']

    def test_the_entry_field_is_prefilled_with_that_platforms_login_page(self, panel):
        assert panel['guideBilibiliFirstCall']['entryPlaceholder'] == 'https://www.bilibili.com/'
        assert panel['guideZhihu']['entryPlaceholder'] == 'https://www.zhihu.com/'


class TestGenerate:
    def test_the_pasted_link_is_sent_along_with_the_wait_time(self, panel):
        body = _body(panel['generate'], '/api/cookies/generate')
        assert body == {
            'platform': 'bilibili',
            'wait_seconds': 45,
            'url': 'https://www.bilibili.com/video/BV1xx411c7mD',
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
        assert body['url'] == 'https://www.bilibili.com/video/BV1xx411c7mD'
        assert body['platform'] == 'bilibili'

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


class TestDeleteCookie:
    """The panel's 「删除已存 Cookie」 button, one of the few places in this app where
    a click destroys something the user cannot rebuild without a real login."""

    def test_the_button_asks_before_it_sends_anything(self, panel):
        case = panel['deleteCancelled']
        assert case['calls'] == [], f'a refusal of the confirmation still deleted: {case["calls"]}'
        assert case['toasts'] == []

    def test_the_confirmation_is_a_two_button_dialog_not_an_input(self, panel):
        """An input dialog is answered by its input; a confirm button that carries a
        ``value`` would replace whatever the user typed. Here there is nothing to type,
        so the two values are the whole contract."""
        dialog = panel['deleteCancelled']['dialog']
        assert dialog['values'] == ['delete', 'null'], dialog
        assert dialog['message'] == 'dialog.cookieDelete'

    def test_confirming_deletes_the_platform_that_is_selected(self, panel):
        requests = panel['deleteConfirmed']['requests']
        posted = [item for item in requests if item['url'] == '/api/cookies/delete']
        assert len(posted) == 1, requests
        assert json.loads(posted[0]['body']) == {'platform': 'bilibili'}

    def test_a_deletion_refreshes_the_status_line_it_just_changed(self, panel):
        """The panel shows which platforms hold a cookie; after a delete that answer
        is stale, and a stale 「OK」 beside a removed file is a lie of the same shape as
        the one the delete itself exists to correct."""
        urls = [item['url'] for item in panel['deleteConfirmed']['requests']]
        assert '/api/cookies/status' in urls, urls

    def test_a_server_refusal_is_shown_rather_than_left_silent(self, panel):
        case = panel['deleteRefused']
        assert case['posted'] == 1
        assert case['statusText'] == 'NOTHING-STORED'
        assert case['toasts'] == [], 'a refusal is not a success, so it must not toast as one'

    def test_the_profile_caveat_reaches_the_user(self, panel):
        """The server says whether the platform's browser profile still holds the
        session — the one thing the user is certain to assume wrongly — and the panel
        passes the whole two-line answer through instead of its own shorter phrase."""
        case = panel['deleteWithCaveat']
        assert case['askedPlatforms'] == ['zhihu']
        assert len(case['toasts']) == 1, case['toasts']
        assert 'profile' in case['toasts'][0] and 'logged in' in case['toasts'][0], case['toasts']


class TestRefreshProfileCookie:
    """「把 Cookie 更新进 Profile」 (#108) — the button that re-plants a saved cookie
    into the browser profile that crawls with it.

    The panel imports a cookie file once, so this is the only way a re-taken session
    reaches a live profile, and it is also the only place the app can *overwrite* a
    session the site has already refreshed. Both halves are why the button asks first
    and why the hint that advertises it has to come from the server.
    """

    def test_the_button_asks_before_it_overwrites_anything(self, panel):
        case = panel['refreshCancelled']
        assert case['calls'] == [], f'a refused confirmation still planted: {case["calls"]}'

    def test_the_confirmation_names_the_risk_it_carries(self, panel):
        dialog = panel['refreshCancelled']['dialog']
        assert dialog['values'] == ['refresh', 'null'], dialog
        assert dialog['message'] == 'dialog.cookieRefresh'
        assert dialog['labels'] == ['dialog.cookieRefreshYes', 'dialog.cancel'], dialog

    def test_confirming_plants_the_selected_platform(self, panel):
        requests = panel['refreshConfirmed']['requests']
        posted = [item for item in requests if item['url'] == '/api/cookies/refresh-profile']
        assert len(posted) == 1, requests
        assert json.loads(posted[0]['body']) == {'platform': 'weibo'}

    def test_a_successful_plant_re_reads_the_profile_table(self, panel):
        """The profile now holds a different session, so the answer behind the hint is
        stale — and a hint that keeps offering the button after it succeeded is the panel
        contradicting something it just caused."""
        urls = [item['url'] for item in panel['refreshConfirmed']['requests']]
        assert '/api/browser/profiles' in urls, urls

    def test_the_server_word_is_what_the_user_sees(self, panel):
        case = panel['refreshConfirmed']
        assert case['toasts'] == ['PLANTED-3'], case
        assert case['statusText'] == 'PLANTED-3'

    def test_a_refusal_is_not_toasted_as_a_success(self, panel):
        case = panel['refreshRefused']
        assert case['statusText'] == 'BUSY-PROFILE'
        assert case['toasts'] == [], case

    def test_the_hint_appears_only_when_the_server_measured_a_newer_file(self, panel):
        stale = panel['hintWhenStale']
        assert 'cookie.refreshHint' in stale, stale
        assert 'PURPOSE' in stale and 'STEP-1' in stale, f'the hint replaced the guidance: {stale}'
        current = panel['hintWhenCurrent']
        assert 'cookie.refreshHint' not in current, current
        assert current == ['PURPOSE', 'STEP-1'], current
