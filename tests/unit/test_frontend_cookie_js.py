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


def _all_text(report):
    """Every string the harness brought back, in one haystack.

    Used where the claim is 「this sentence is nowhere on the panel」: reading only the cell it
    used to be written into would miss it arriving by another route.
    """
    return json.dumps(report, ensure_ascii=False)


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
            'account': 'default',
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
        # The confirmation names the login it will remove — platform AND account — because
        # one platform now holds several sessions and 「删除知乎的 Cookie」 would not say which.
        assert dialog['message'] == 'dialog.cookieDelete - platform.bilibili@default', dialog
        assert '{' not in dialog['message'], 'a slot reached the screen unfilled'

    def test_confirming_deletes_the_platform_that_is_selected(self, panel):
        requests = panel['deleteConfirmed']['requests']
        posted = [item for item in requests if item['url'] == '/api/cookies/delete']
        assert len(posted) == 1, requests
        assert json.loads(posted[0]['body']) == {'platform': 'bilibili', 'account': 'default'}

    def test_a_deletion_refreshes_the_status_line_it_just_changed(self, panel):
        """The panel shows which platforms hold a cookie; after a delete that answer
        is stale, and a stale 「OK」 beside a removed file is a lie of the same shape as
        the one the delete itself exists to correct."""
        urls = [item['url'] for item in panel['deleteConfirmed']['requests']]
        assert '/api/cookies/status' in urls, urls

    def test_a_confirmed_deletion_re_reads_the_data_source_account_list(self, panel):
        """Which logins exist reaches the data-source node only through /api/capabilities,
        which was fetched once at startup — so after a login is deleted that endpoint must be
        re-read, or the node keeps offering a cookie that no longer exists until a full reload
        (the bug the user reported)."""
        assert panel['deleteConfirmed']['capabilitiesRefetched'] is True

    def test_a_cancelled_deletion_does_not_touch_the_account_list(self, panel):
        """Nothing was removed when the confirmation was dismissed, so the candidate list
        must not be re-fetched — this pins that the refresh rides the SUCCESS path only."""
        assert panel['deleteCancelled']['capabilitiesRefetched'] is False

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

    def test_a_deferred_plant_still_refreshes_the_account_list(self, panel):
        """Even when the browser-profile plant is deferred, the cookie FILE is on disk now,
        so the data-source account box must offer the new login without a page reload — the
        capabilities re-read runs on this branch too, and the deferred sentence is not lost."""
        case = panel['savePlants']
        assert case['capabilitiesRefetched'] is True
        assert 'DEFERRED-PROFILE' in case['statusText'], 'the plant note must survive the refresh'

    def test_the_plant_refresh_updates_the_account_line_too(self, panel):
        """The contradiction the user hit: after a save-into-profile the summary said 「已保存…21 条」
        but the per-account line still read 「还没有保存过 Cookie」 — that branch wrote the plant note
        and skipped re-reading the rows the account line reads. The refresh (updateSummary=false)
        must now flip the account line to saved AND leave the plant note standing."""
        case = panel['savePlants']
        line = case['accountLine']
        assert '21' in line, f'the account line was not refreshed after the plant: {line}'
        assert '还没有保存过' not in line and 'no cookie saved' not in line, line
        assert 'DEFERRED-PROFILE' in case['statusText'], 'the plant note must survive the account refresh'

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

    def test_the_profile_explainer_is_gone_and_the_benefit_lives_on_the_switch(self):
        """What a profile IS stopped being panel copy (user, 2026-09-28).

        ``#cookie-explain`` described how the tool wires an account to a directory — our
        implementation history, not a decision anybody makes at that box. The place a reason
        belongs is next to the switch that turns the feature on, so ``set.useProfileInline``
        now says what opening it buys, in both languages, and the deleted paragraph's key is
        gone rather than kept in case something wants it.
        """
        html = (JS_DIR.parent / 'index.html').read_text(encoding='utf-8')
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        assert 'refreshProfileCookie' not in html, 'the deleted button is wired back in'
        # Asked for the ELEMENT, not the word: the comment that records why it went away
        # names it, and a guard that fires on its own eulogy is a guard nobody can read.
        assert 'id="cookie-explain"' not in html, 'the explainer came back above the paste box'
        assert 'data-i18n="cookies.refreshExplain"' not in html, 'the explainer is back under another id'
        assert "'cookies.refreshExplain'" not in app, 'a key whose only user is gone'
        assert app.count("'set.useProfileInline'") == 2, 'both catalogues carry the switch line'
        # The line says what opening the switch BUYS, which is the one thing worth writing
        # next to a checkbox; a bare restatement of the label teaches nobody anything.
        for benefit in ('weibo', 'xiaohongshu', 'douyin'):
            assert benefit in app, f'the switch line stopped naming the platforms it helps: {benefit}'
        assert "'advice.title': 'What each platform prefers'" in app, 'the en heading carries the note again'
        assert '全部读自采集矩阵' not in app, 'the zh heading tells the user where we read it from'
        for dead in ("'cookies.refresh':", "'cookie.refreshWorking':", "'cookie.refreshed':", "'dialog.cookieRefresh'"):
            assert dead not in app, f'the button is gone but its catalogue entry ({dead}) stayed'


class TestAccountCandidatesAndManager:
    """The account box, its candidate dropdown, and the docked table of saved logins.

    One platform carries several logins, so the panel has to say WHICH ones exist, answer for
    the account currently typed without asking the server again per keystroke, and rename or
    delete the login a row NAMES rather than the one the box last held. Every account has a
    name, the platform's own included (user, 2026-09-28: 「哪有同一个东西不同规范的」), so the
    box shows ``default`` instead of going blank.
    """

    def test_a_candidate_is_said_in_the_users_words(self, panel):
        cases = panel['candidates']
        assert [case['text'] for case in cases] == [
            'cookies.accountDefault',
            'cookies.accountDefaultNumbered - 2',
            'work',
        ], cases
        # The label is wording; the ACCOUNT is what a pick must carry — and the default one
        # carries a name now, not an empty string.
        assert [case['account'] for case in cases] == ['default', 'default2', 'work'], cases
        assert all(case['open'] is True for case in cases), 'the popup was built but never opened'

    def test_typing_narrows_the_offers_to_what_is_left(self, panel):
        """One box, two jobs: type a name nobody has and the list empties (the next save
        BORN that login); type a name that exists and it is offered again."""
        assert panel['ghostCandidates'] == [], panel['ghostCandidates']
        assert [case['account'] for case in panel['workCandidates']] == ['work'], panel['workCandidates']

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
        assert 'work' in work and 'cookies.accountStatusSaved - 2' in work, work

    def test_the_saved_logins_say_nothing_about_browsers_or_window_closing(self, panel):
        """The two sentences were deleted, and this is the pin that keeps them out.

        An account, its cookie file and its browser directory are one thing in this tool, and
        since #148 every crawl runs headless behind a desktop fingerprint — so 「它的浏览器里
        就是这份 Cookie」 and 「其中 N 条关窗口即失效」 described states the user neither
        chooses nor can act on. The row's own cells are what would re-appear if the copy came
        back, so they are read, not assumed away.
        """
        rows = panel['managerRows']
        assert len(rows) == 3, rows
        for row in rows:
            assert row['hasStateCell'] is False, row
            assert 'profile' not in row['account'].lower(), row
            for button in row['buttons']:
                # A cookie row may carry exactly the three actions, keyed — not free text. The
                # removed profile-STATE chips (cookies.profileCurrent/Stale/Off/…) described a
                # state the user cannot act on and stay banned; 「删除 Profile」 is different, it
                # is a real action, and a stray un-keyed chip would still fail this line.
                assert button['label'] in ('cookies.renameOne', 'cookies.deleteOne', 'cookies.deleteProfileOne'), row
                assert '失效' not in button['label'], row
        for key in (
            'cookies.profileCurrent',
            'cookies.profileStale',
            'cookies.profileNoLogin',
            'cookies.profileUnused',
            'cookies.profileOff',
            'cookies.rowSessionOnly',
            'cookies.accountStatusSessionOnly',
        ):
            assert key not in _all_text(panel), f'{key} is still being printed somewhere'

    def test_the_deleted_keys_left_both_catalogues(self):
        """A sentence nobody renders must not stay in the word list either — a dead key is
        how a removed feature gets resurrected by the next person who finds it."""
        app = (JS_DIR / 'app.js').read_text(encoding='utf-8')
        for key in (
            "'cookies.profileOff'",
            "'cookies.profileUnused'",
            "'cookies.profileNoLogin'",
            "'cookies.profileStale'",
            "'cookies.profileCurrent'",
            "'cookies.rowSessionOnly'",
            "'cookies.accountStatusSessionOnly'",
        ):
            assert key not in app, key

    def test_the_live_line_cost_no_second_request(self, panel):
        """Three different accounts were answered from the one status read."""
        assert panel['rowsAskedAgain'] == 1, panel['rowsAskedAgain']

    def test_a_candidate_click_fills_the_box_every_action_sends(self, panel):
        """Reached through the button's own listener, not by calling the function.

        The candidate is a real element now; a popup whose buttons never got attached would
        still answer `pickCookieAccount('work')` when a test calls it by hand, and the user
        would see nothing happen.
        """
        assert panel['workChipSeen'] is True, panel
        case = panel['afterCandidateClick']
        assert case['box'] == 'work', case
        assert case['popupClosed'] is True, f'the popup stayed open over the panel: {case}'
        picked = panel['afterPick']
        assert picked['box'] == 'default2' and 'cookies.accountStatusSaved - 4' in picked['line'], picked

    def test_the_default_login_is_offered_by_name_and_picks_by_name(self, panel):
        """「它也要填值」 — the default account is a login like any other, so its candidate carries
        ``default`` and clicking it lands that word in the box instead of a blank.

        The pick is reached through the chip's own listener: a popup whose buttons were never
        attached would still answer a hand-called ``pickCookieAccount('default')`` while the
        user saw the box stay empty.
        """
        assert panel['defaultChipSeen'] is True, panel
        case = panel['afterDefaultPick']
        assert case['box'] == 'default', case
        assert case['toast'] == ['cookies.chosen - platform.zhihu | cookies.accountDefault'], case

    def test_a_named_row_renames_the_login_it_was_clicked_on(self, panel):
        """A rename is the one row action that can point at the wrong session (a delete that
        reused the box would just destroy a different login), so the name the row was BUILT
        with is what is sent — not whatever the box happens to hold — and the answer says so.

        The box follows the new name: leaving it on the old one would make the next action
        address a login that no longer exists."""
        case = panel['renamed']
        assert case['posted'] == [{'platform': 'zhihu', 'account': 'work', 'to': 'office'}], case
        assert case['box'] == 'office', case
        assert case['toasts'] == ['RENAMED'], case

    def test_the_default_row_shows_a_rename_that_refuses_in_place(self, panel):
        """The default row does not hide its rename — it shows 「重命名」 dead, with the reason as
        the title and again when pressed.

        A silent absence is how a disabled control reads as broken; this is the same lesson the
        「打开」 button taught (the refusal must be spoken), applied to a row that legitimately
        cannot be renamed because its browser directory IS the platform's.
        """
        rename = panel['rowButtons']['defaultRow'][0]
        assert rename['label'] == 'cookies.renameOne', rename
        assert rename['disabled'] is True, rename
        assert rename['title'] == 'cookies.renameDefaultRefused', rename
        # Pressing it is refused before anything goes to the server.
        refused = panel['renameDefault']
        assert refused['posted'] == 0, refused
        assert refused['toasts'] == ['cookies.renameDefaultRefused'], refused

    def test_the_delete_profile_button_tracks_the_profile_and_the_account(self, panel):
        """「删除 Profile」 appears exactly where it can do something, and is honest where it cannot.

        A row with no profile directory has no device to retire, so it gets no button (not a dead
        one). A named account whose profile exists gets a live one. The 默认账号 row shows the
        button greyed with the shared-root reason as its title — its browser data IS the platform
        folder, so deleting it there would silently wipe every sibling, and a greyed control that
        says why beats a missing button that leaves the user hunting for it (the same lesson the
        rename default teaches).
        """
        rows = {r['key']: r for r in panel['managerRows']}

        def prof(key):
            return [b for b in rows[key]['buttons'] if b['label'] == 'cookies.deleteProfileOne']

        assert prof('work') == [], 'the work row has profile_exists false, so it must offer nothing'
        named = prof('default2')
        assert len(named) == 1 and named[0]['disabled'] is False, 'a named account with a profile can retire it'
        default = prof('default')
        assert len(default) == 1, default
        assert default[0]['disabled'] is True, 'the default device is the platform root — not deletable here'
        assert default[0]['title'] == 'cookies.profileDeleteDefaultRefused', default

    def test_typing_the_same_name_back_sends_no_round_trip(self, panel):
        """Renaming to the name it already has moves nothing, so the panel says so locally
        rather than POSTing a success the disk never earned."""
        same = panel['renameSame']
        assert same['posted'] == 0, same
        assert same['toasts'] == ['cookies.renameSame'], same

    def test_the_list_docks_in_the_bottom_slot_with_the_other_five(self, panel):
        """One bottom slot, and opening it has to shut the others (the user asked for it
        互斥 with 控制台/历史记录), and it reads the server rather than the dialog's cache."""
        case = panel['docked']
        assert case['cookiesOpen'] is True, case
        assert case['othersLeftOpen'] == [], f'two docked panels opened at once: {case}'
        assert case['asked'] == 1, case
        assert case['rows'] == 3, case
        assert panel['dockedAfterClose'] == {'cookiesOpen': False, 'height': ''}, panel['dockedAfterClose']

    def test_switching_language_rewrites_the_dock_without_a_second_request(self, panel):
        """#30: the dock is built entirely by JS from catalogue keys, so ``I18n.apply()`` never
        reached it — a switch left English words on a panel that had just turned Chinese.

        The harness tags every word with the language it was read in (the shipped ``t`` answers
        with a bare, language-blind key, so a repaint would otherwise be invisible here); the
        assertion is that the tags moved AND that no second ``/api/cookies/status`` was bought —
        a language change is not new information about the disk.
        """
        case = panel['languageRepaint']
        assert case['before']['platform'].endswith('@en'), case
        assert case['after']['platform'].endswith('@zh'), 'the platform word was not re-read'
        assert all(label.endswith('@zh') for label in case['after']['buttons']), case['after']['buttons']
        assert case['askedDuringSwitch'] == 0, case

    def test_a_row_deletes_its_own_login_not_the_boxes(self, panel):
        """The box said `default2` when the `work` card's button was clicked.

        A per-row delete that reused the panel's own selection would remove a login the
        user never pointed at, which on this panel is the difference between tidying up
        and losing a session.
        """
        assert panel['workCardFound'] is True, 'the card was not built, so nothing below was measured'
        case = panel['rowDelete']
        assert case['posted'] == [{'platform': 'zhihu', 'account': 'work'}], case
        assert case['boxStill'] == 'default2', case

    def test_nothing_saved_offers_nothing(self, panel):
        """An empty candidate area is the honest answer when no file exists; a 「默认账号」
        chip for a missing file is how a node ends up naming a login that is not here.
        The docked table shows a single note row, not a header over zero rows."""
        case = panel['nothingSaved']
        assert case['chips'] == [], case
        assert case['manager'] == [], case
        assert case['note'] == ['cookies.noneSaved'], case

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
        last fetch instead of the last keystroke.

        The candidates open on focus, click and typing — and close on blur — because the
        popup lives on ``<body>``: a list permanently under the field is what this replaced.
        """
        html = (JS_DIR.parent / 'index.html').read_text(encoding='utf-8')
        account_input = html[html.index('id="cookie-account"') : html.index('/>', html.index('id="cookie-account"'))]
        assert 'oninput="renderCookieAccountStatus(); renderCookieAccounts(true)"' in account_input, account_input
        for handler in (
            'onfocus="renderCookieAccounts(true)"',
            'onclick="renderCookieAccounts(true)"',
            'onblur="hideCookieAccountCandidates()"',
        ):
            assert handler in account_input, handler
        assert 'id="cookie-account-status"' in html and 'id="cookies-mgr-body"' in html, (
            'a host the panel writes to is gone'
        )
        # The flat chip row and the in-dialog list are deleted, not merely unused: two
        # candidate mechanisms is two answers to one question.
        for gone in ('id="cookie-account-candidates"', 'id="cookie-manager"', 'cookies.refreshExplain'):
            assert gone not in html, f'{gone} came back'
        assert 'cookie-account-options' not in html, 'the datalist came back beside the dropdown'
