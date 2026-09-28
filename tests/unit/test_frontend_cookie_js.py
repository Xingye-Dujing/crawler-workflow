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
            'account': '',
        }

    def test_the_typed_account_is_sent_with_the_login_request(self, panel):
        """One platform, several logins: the panel's account box decides WHICH file the
        browser writes, so the request that opens it has to carry that name. The blank
        is the default account — the shape every cookie had before multi-account — and a
        typed name must reach the backend verbatim (lowercased) or the login is saved
        under the wrong session and the crawl that picks it comes up empty."""
        body = _body(panel['account'], '/api/cookies/generate')
        assert body['account'] == 'work', panel['account']

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
        so the two values are the whole contract.

        The message is checked as a RENDERED sentence because this test used to assert the
        bare key — and the stub answered with the key too, so the dialog shipped a literal
        ``{platform}`` (its template names the platform twice and ``.replace`` filled one)
        while this line stayed green.
        """
        dialog = panel['deleteCancelled']['dialog']
        assert dialog['values'] == ['delete', 'null'], dialog
        assert dialog['message'] == 'dialog.cookieDelete - platform.bilibili', dialog
        assert '{' not in dialog['message'], 'a slot reached the screen unfilled'

    def test_confirming_deletes_the_platform_that_is_selected(self, panel):
        requests = panel['deleteConfirmed']['requests']
        posted = [item for item in requests if item['url'] == '/api/cookies/delete']
        assert len(posted) == 1, requests
        assert json.loads(posted[0]['body']) == {'platform': 'bilibili', 'account': ''}

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


class TestSavePlantsItsOwnProfile:
    """Saving a cookie IS the plant (#108's button, deleted).

    One cookie, one profile: the paste is the newest session there is, so the browser that
    crawls with that account takes it in on the spot — no second button, and no second
    request the app could get wrong. The one case the server cannot do immediately (that
    profile is held) has to reach the screen, because 「已保存」 alone would hide it.
    """

    def test_saving_asks_no_refresh_route_at_all(self, panel):
        urls = panel['savePlants']['urls']
        assert '/api/cookies/save' in urls, urls
        assert not any('refresh' in url for url in urls), f'the old button is back: {urls}'

    def test_the_save_names_the_account_it_was_planted_for(self, panel):
        posted = panel['savePlants']['saveBody']
        assert posted == [
            {'platform': 'weibo', 'account': 'work', 'cookies': [{'name': 'SUB', 'value': 'v', 'domain': '.weibo.com'}]}
        ], 'a paste must say which account it belongs to, or it overwrites the default login'

    def test_the_servers_plant_sentence_stands_on_the_status_line(self, panel):
        case = panel['savePlants']
        assert 'DEFERRED-PROFILE' in case['statusText'], case
        assert case['toasts'] == ['toast.cookiesSaved - platform.weibo@work'], case

    def test_a_refused_save_is_the_servers_word_not_a_success_toast(self, panel):
        assert panel['saveRefused']['toasts'] == ['cookie.failed - BAD-JSON'], panel['saveRefused']

    def test_the_hint_appears_only_when_the_server_measured_a_newer_file(self, panel):
        """The panel never guesses which file a Chrome profile was planted from."""
        stale = panel['hintWhenStale']
        assert 'cookie.refreshHint' in stale, stale
        assert 'PURPOSE' in stale and 'STEP-1' in stale, f'the hint replaced the guidance: {stale}'
        current = panel['hintWhenCurrent']
        assert 'cookie.refreshHint' not in current, current
        assert current == ['PURPOSE', 'STEP-1'], current

    def test_the_panel_explains_the_profile_without_advertising_a_button(self):
        """The sentence under the paste box explains what a profile IS, in the page rather
        than in a dialog — and it must no longer tell the user to press anything, because
        the button it described is gone.
        """
        html = (JS_DIR.parent / 'index.html').read_text(encoding='utf-8')
        assert 'refreshProfileCookie' not in html, 'the deleted button is wired back in'
        note = html.index('data-i18n="cookies.refreshExplain"')
        assert note < html.index('id="cookie-job-actions"'), 'the note moved off the paste area it explains'
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        assert app.count("'cookies.refreshExplain'") == 2, 'both catalogues must carry the sentence'
        for dead in ("'cookies.refresh':", "'cookie.refreshWorking':", "'cookie.refreshed':", "'dialog.cookieRefresh'"):
            assert dead not in app, f'the button is gone but its catalogue entry ({dead}) stayed'


class TestAccountCandidatesAndManager:
    """The account box, its candidates, and the list of what this machine holds.

    One platform carries several logins, so the panel has to say WHICH ones exist in the
    words a user reads, answer for the account currently typed without asking the server
    again per keystroke, and delete the login a row names rather than the one last typed.
    """

    def test_a_candidate_is_said_in_the_users_words(self, panel):
        cases = panel['candidates']
        assert [case['text'] for case in cases] == [
            'cookies.accountDefault',
            'cookies.accountDefaultNumbered - 2',
            'work',
        ], cases
        # The label is wording; the ACCOUNT is the argument. A chip that carried its own
        # label would save under 「默认账号」 — a name the backend would reject as a path.
        assert [case['onclick'] for case in cases] == [
            "pickCookieAccount('')",
            "pickCookieAccount('default2')",
            "pickCookieAccount('work')",
        ], cases

    def test_the_summary_never_prints_an_empty_account_name(self, panel):
        """Joined raw, the default account came out as a hole in the brackets."""
        line = panel['summaryLine']
        assert '(,' not in line and ', )' not in line, line
        assert 'cookies.accountDefault' in line and 'work' in line, line

    def test_the_line_under_the_box_follows_what_is_typed(self, panel):
        saved = panel['lineForDefault']
        assert 'cookies.accountStatusSaved - 12 | 2026-09-28 10:00' in saved, saved
        ghost = panel['lineForGhost']
        assert 'ghost' in ghost and 'cookies.accountStatusNone' in ghost, ghost
        assert 'cookies.accountStatusSaved' not in ghost, ghost
        # Typed in mixed case and matched anyway: the box is normalized, the file is not.
        work = panel['lineForWork']
        assert 'work' in work and 'cookies.profileUnused' in work, work
        assert 'cookies.accountStatusSessionOnly - 2' in work, work

    def test_the_live_line_cost_no_second_request(self, panel):
        """Three different accounts were answered from the one status read."""
        assert panel['rowsAskedAgain'] == 1, panel['rowsAskedAgain']

    def test_a_candidate_fills_the_box_every_action_sends(self, panel):
        case = panel['afterPick']
        assert case['box'] == 'default2', case
        assert 'cookies.accountStatusSaved - 4' in case['line'], case
        # The card list says what only the server knows: this profile holds an OLDER
        # cookie than the file, which is the one state no user can see from outside.
        assert case['profileWord'] is True, case

    def test_a_row_deletes_its_own_login_not_the_boxes(self, panel):
        """The box said `default2` when the `work` card was clicked.

        A per-row delete that reused the panel's own selection would remove a login the
        user never pointed at, which on this panel is the difference between tidying up
        and losing a session.
        """
        case = panel['rowDelete']
        assert case['posted'] == [{'platform': 'zhihu', 'account': 'work'}], case
        assert case['boxStill'] == 'default2', case

    def test_nothing_saved_offers_nothing(self, panel):
        """An empty candidate area is the honest answer when no file exists; a 「默认账号」
        chip for a missing file is how a node ends up naming a login that is not here."""
        case = panel['nothingSaved']
        assert case['chips'] == [], case
        assert 'cookies.noneSaved' in case['manager'], case

    def test_being_sent_here_lands_on_the_broken_login(self, panel):
        assert panel['openedOnAccount'] == {'platform': 'weibo', 'box': 'work'}, panel['openedOnAccount']

    def test_opening_the_panel_from_the_toolbar_keeps_the_box(self, panel):
        """No account named, nothing rewritten: the toolbar button is a toggle, not a
        navigation, and wiping the box would change which login the next click means."""
        assert panel['openedWithoutAccount']['box'] == 'keepme', panel['openedWithoutAccount']

    def test_a_platform_the_panel_does_not_hold_moves_nothing(self, panel):
        """Half a landing — one select still on its old platform with the new account in
        the box — is a delete pointed at somebody else's session."""
        assert panel['openedOnUnknownPlatform'] == {'platform': 'weibo', 'box': 'keepme'}, panel

    def test_the_box_repaints_the_line_and_the_hosts_are_wired(self):
        """The wiring is half the feature: an unwired handler is a panel that answers the
        last fetch instead of the last keystroke."""
        html = (JS_DIR.parent / 'index.html').read_text(encoding='utf-8')
        account_input = html[html.index('id="cookie-account"') : html.index('id="cookie-account-candidates"')]
        assert 'oninput="renderCookieAccountStatus()"' in account_input, account_input
        for host in ('id="cookie-account-candidates"', 'id="cookie-account-status"', 'id="cookie-manager"'):
            assert host in html, host
        # The datalist is gone rather than left empty: two candidate mechanisms, one of
        # which can only ever show the default account as a blank row, is two answers.
        assert 'cookie-account-options' not in html, 'the datalist came back beside the chips'

    def test_the_profile_word_asks_the_marker_not_the_directory(self, panel):
        """A named account's device lives one level inside the platform's directory, so the
        default account has a path the moment any sibling was opened. Reading ``exists``
        first would tell the user a device had been built for a login that never had one.
        """
        words = panel['profileWords']
        assert words['off'] == 'cookies.profileOff', words
        assert words['neverOpened'] == 'cookies.profileUnused', words
        assert words['existsButUnused'] == 'cookies.profileUnused', words
        assert words['openedNoLogin'] == 'cookies.profileNoLogin', words
        assert words['stale'] == 'cookies.profileStale', words
        assert words['current'] == 'cookies.profileCurrent', words
