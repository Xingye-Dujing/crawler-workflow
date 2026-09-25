"""The press of 执行 between "the canvas is valid" and "the run started".

``tests/frontend/harness_cookie_gate.mjs`` loads the real workflow.js and app.js and
drives ``workflow.execute()`` per scenario, so what fails here is the shipped code.
The rules this pins:

* a canvas that crawls nothing asks nothing, and a 继续 is never blocked twice
  (the user is already inside "refresh the cookie and carry on");
* the platforms asked about are the ones this canvas crawls — a source node's own
  platform, and for a comment node the domain of every link, deduped in node order;
* 「已失效」 refuses the run: no ``/api/workflow/execute`` leaves the page, the dialog
  names the platform and quotes the server's own sentence, and it offers no
  「我确定，照样跑」 — that button is the hole this feature exists to close;
* 「无法核对」 does *not* refuse: risk control, a timeout or a profile held by a live
  crawl says nothing about the session, and blocking there would send the user to
  re-log in a cookie that is fine;
* a gate that could not run says so and lets the run start, rather than inventing a
  failure the site never reported;
* the block dialog opens the Cookie panel on the broken platform only when the user
  asked for it, and never closes a panel that was already open;
* with 自动验证 off nothing is asked at all — the old 「执行前确认 Cookie」 fallback
  was deleted, an off switch means off;
* the per-run profile answer travels to the check, so the probe tests the browser the
  run will use — and absence stays absence rather than becoming a global "off".
"""

import json
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

import crawl_capabilities as capabilities

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which('node') is None, reason='node not installed'),
]

ROOT = Path(__file__).resolve().parents[2]
JS_DIR = ROOT / 'backend' / 'static' / 'js'
HARNESS = ROOT / 'tests' / 'frontend' / 'harness_cookie_gate.mjs'

MATRIX = capabilities.as_dict()

#: The gate is a run-gate: it is reached only after the canvas validates, and a
#: source node missing the field its mode requires is refused before any request is
#: built. So the fixtures carry what the panel would have filled in.
DEFAULT_MODE = {entry['platform']: entry['modes'][0]['key'] for entry in MATRIX['platforms']}


def _source(node_id, platform, mode=None):
    return {
        node_id: {
            'id': node_id,
            'type': 'source',
            'title': f'采集 {platform}',
            'params': {'platform': platform, 'keyword': '三亚', 'collect': mode or DEFAULT_MODE[platform]},
        }
    }


def _comment(node_id, urls):
    return {node_id: {'id': node_id, 'type': 'comment', 'title': '评论', 'params': {'urls': urls}}}


def _upload(node_id='u1', dataset='d1'):
    return {
        node_id: {
            'id': node_id,
            'type': 'upload',
            'title': '文件',
            'params': {'dataset_id': dataset, 'dataset_name': 'a.csv', 'row_count': 4},
        }
    }


def _output(node_id='o1'):
    return {
        node_id: {
            'id': node_id,
            'type': 'output',
            'title': '导出',
            'operation': 'save',
            'params': {'operation': 'save', 'filename': 'out'},
        }
    }


def _chain(index, platform, kind='source', urls=None, mode=None):
    """One complete workflow: a crawler node wired into an output node.

    A crawler with nothing downstream is refused by ``validate()`` before the gate is
    ever reached, so a scenario built that way would report 「the gate let it run」 for
    a run the canvas had already rejected — an assertion that passes on its own
    absence.
    """
    src_id, out_id = f'w{index}-s', f'w{index}-o'
    src = _source(src_id, platform, mode) if kind == 'source' else _comment(src_id, urls)
    return {**src, **_output(out_id)}, [{'from': src_id, 'to': out_id}]


def _canvas(*chains):
    nodes, connections = {}, []
    for part in chains:
        nodes.update(part[0])
        connections.extend(part[1])
    return {'nodes': nodes, 'connections': connections}


def _verdict(platform, state, *, blocking, text):
    return {'platform': platform, 'state': state, 'blocking': blocking, 'text': text, 'probed': True}


def _matrix_without_region(platform):
    """The live matrix with one platform's region blanked.

    Built from the matrix dumped out of Python rather than from a copy, so the only
    thing the scenario varies is the missing classification.
    """
    stripped = json.loads(json.dumps(MATRIX, ensure_ascii=False))
    for entry in stripped['platforms']:
        if entry['platform'] == platform:
            entry['region'] = ''
    return stripped


#: A refused run and an empty one look identical unless the verdict carries the
#: sentence the server rendered for it.
DEAD = {
    'ok': True,
    'results': {'weibo': _verdict('weibo', 'expired', blocking=True, text='WEIBO-COOKIE-IS-DEAD')},
    'blocked': ['weibo'],
    'unclear': [],
    'probed': True,
}


CLEAN = {'ok': True, 'results': {}, 'blocked': [], 'unclear': [], 'probed': True}

#: Turning the check off is the baseline every other scenario is read against: the
#: run starts with nothing asked and nothing said — there is no fallback prompt any
#: more, an off switch means off.
NO_GATE = {
    'cookie_preflight_before_run': False,
    'warn_mixed_region': False,
}
AUTO = {
    'cookie_preflight_before_run': True,
    'warn_mixed_region': True,
}

SCENARIOS = [
    {
        'id': 'nothing-to-crawl',
        'settings': AUTO,
        'nodes': {**_upload(), **_output()},
        'connections': [{'from': 'u1', 'to': 'o1'}],
        'preflight': CLEAN,
    },
    {
        'id': 'silent-pass',
        'settings': AUTO,
        **_canvas(_chain(1, 'zhihu')),
        'preflight': {
            'ok': True,
            'results': {'zhihu': _verdict('zhihu', 'valid', blocking=False, text='The stored zhihu cookie works')},
            'blocked': [],
            'unclear': [],
            'probed': True,
        },
    },
    {
        # 微博热搜 is measured answering an anonymous browser, so a canvas whose only
        # crawl is that board must not have its run refused for a missing weibo cookie.
        # The gate asks per platform AND per mode, so this must not send the request.
        'id': 'board-needs-no-cookie',
        'settings': AUTO,
        **_canvas(_chain(1, 'weibo', mode='hot')),
        'preflight': {
            'ok': True,
            'results': {'weibo': _verdict('weibo', 'invalid', blocking=True, text='The stored weibo cookie is dead')},
            'blocked': ['weibo'],
            'unclear': [],
            'probed': True,
        },
    },
    {
        # The zhihu board is the opposite answer (401 without a session), so the same
        # mode on the next platform still asks — exempting weibo must not become
        # exempting 热榜.
        'id': 'board-needs-a-cookie',
        'settings': AUTO,
        **_canvas(_chain(1, 'zhihu', mode='hot')),
        'preflight': {
            'ok': True,
            'results': {'zhihu': _verdict('zhihu', 'invalid', blocking=True, text='The stored zhihu cookie is dead')},
            'blocked': ['zhihu'],
            'unclear': [],
            'probed': True,
        },
    },
    {
        # Both on one canvas: the probe runs for the platform that needs it and the
        # request names only that one. A filter that dropped the whole canvas, or
        # none of it, both fail here.
        'id': 'board-mixed-with-post',
        'settings': AUTO,
        **_canvas(_chain(1, 'weibo', mode='hot'), _chain(2, 'zhihu')),
        'preflight': CLEAN,
    },
    {
        'id': 'expired-blocks-the-run',
        'settings': AUTO,
        **_canvas(_chain(1, 'weibo')),
        'preflight': DEAD,
        'answers': {'expired': 'update'},
    },
    {
        'id': 'cancel-still-blocks',
        'settings': AUTO,
        **_canvas(_chain(1, 'weibo')),
        'preflight': DEAD,
        'answers': {'expired': None},
    },
    {
        'id': 'panel-already-open',
        'settings': AUTO,
        **_canvas(_chain(1, 'weibo')),
        'panelOpen': True,
        'preflight': DEAD,
        'answers': {'expired': 'update'},
    },
    {
        'id': 'no-answer-does-not-block',
        'settings': AUTO,
        **_canvas(_chain(1, 'zhihu')),
        'preflight': {
            'ok': True,
            'results': {'zhihu': _verdict('zhihu', 'unknown', blocking=False, text='ZHIHU-COULD-NOT-BE-CHECKED')},
            'blocked': [],
            'unclear': ['zhihu'],
            'probed': True,
        },
    },
    {
        'id': 'gate-refused',
        'settings': AUTO,
        **_canvas(_chain(1, 'zhihu')),
        'preflight': {'ok': False, 'error': 'nope'},
    },
    {'id': 'gate-unreachable', 'settings': AUTO, **_canvas(_chain(1, 'zhihu')), 'preflightThrows': True},
    {
        'id': 'resume-skips',
        'settings': AUTO,
        **_canvas(_chain(1, 'zhihu')),
        'opts': {'resumeRunId': 'r-int'},
        'preflight': CLEAN,
    },
    {'id': 'both-off', 'settings': NO_GATE, **_canvas(_chain(1, 'zhihu')), 'preflight': CLEAN},
    {
        'id': 'links-name-the-platforms',
        'settings': AUTO,
        **_canvas(
            _chain(
                1,
                None,
                kind='comment',
                urls='https://www.zhihu.com/question/1\nhttps://weibo.com/123\nnot-a-link\nhttps://www.zhihu.com/x',
            )
        ),
        'preflight': CLEAN,
    },
    {
        'id': 'same-platform-twice',
        'settings': {'cookie_preflight_before_run': True, 'use_browser_profile': True},
        **_canvas(_chain(1, 'douyin'), _chain(2, 'douyin')),
        'canvasSettings': {'mode': 'parallel'},
        'preflight': CLEAN,
        'answers': {'clash': 'skip'},
    },
    {
        'id': 'profile-kept',
        'settings': {'cookie_preflight_before_run': True, 'use_browser_profile': True},
        **_canvas(_chain(1, 'douyin'), _chain(2, 'douyin')),
        'canvasSettings': {'mode': 'parallel'},
        'preflight': CLEAN,
        'answers': {'clash': 'use'},
    },
    {
        # weibo is serial-only: two of its crawls are NOT the profile fork (they queue
        # whatever this answer says), so the clash dialog is filtered out — and the
        # serial warning takes its place, naming weibo and cancelling on refusal.
        'id': 'weibo-serial-warn-proceeds',
        'settings': {'cookie_preflight_before_run': True, 'use_browser_profile': True, 'warn_mixed_region': False},
        **_canvas(_chain(1, 'weibo'), _chain(2, 'weibo')),
        'canvasSettings': {'mode': 'parallel'},
        'preflight': CLEAN,
        'answers': {'serial': 'serial'},
    },
    {
        'id': 'weibo-serial-warn-refuses',
        'settings': {'cookie_preflight_before_run': True, 'use_browser_profile': True, 'warn_mixed_region': False},
        **_canvas(_chain(1, 'weibo'), _chain(2, 'weibo')),
        'canvasSettings': {'mode': 'parallel'},
        'preflight': CLEAN,
        'answers': {'serial': None},
    },
    {
        # One weibo crawl is not a queue: no warning, the run starts.
        'id': 'weibo-single-runs-quiet',
        'settings': {'cookie_preflight_before_run': True, 'warn_mixed_region': False},
        **_canvas(_chain(1, 'weibo')),
        'canvasSettings': {'mode': 'parallel'},
        'preflight': CLEAN,
    },
    {
        'id': 'mixed-networks-refuses-to-run',
        'settings': AUTO,
        **_canvas(_chain(1, 'douyin'), _chain(2, 'youtube')),
        'preflight': CLEAN,
        'answers': {'mixed': None},
    },
    {
        'id': 'mixed-networks-continued',
        'settings': AUTO,
        **_canvas(_chain(1, 'douyin'), _chain(2, 'youtube')),
        'preflight': CLEAN,
        'answers': {'mixed': 'go'},
    },
    {
        'id': 'mixed-warning-off',
        'settings': {
            'cookie_preflight_before_run': True,
            'warn_mixed_region': False,
        },
        **_canvas(_chain(1, 'douyin'), _chain(2, 'youtube')),
        'preflight': CLEAN,
    },
    {
        'id': 'mixed-network-silent',
        'settings': AUTO,
        **_canvas(_chain(1, 'douyin'), _chain(2, 'weibo')),
        'preflight': CLEAN,
    },
    {
        # A platform the matrix says nothing about is left out of both groups rather
        # than guessed at: 「it might be overseas」 is not a fact to interrupt a run with.
        'id': 'mixed-without-a-region',
        'settings': AUTO,
        'matrix': _matrix_without_region('youtube'),
        **_canvas(_chain(1, 'douyin'), _chain(2, 'youtube')),
        'preflight': CLEAN,
    },
    {
        'id': 'server-wording-carries-the-detail',
        'settings': AUTO,
        **_canvas(_chain(1, 'zhihu'), _chain(2, 'weibo')),
        'preflight': {
            'ok': True,
            'results': {
                'zhihu': _verdict('zhihu', 'expired', blocking=True, text='ZHIHU-DEAD'),
                'weibo': _verdict('weibo', 'expired', blocking=True, text='WEIBO-DEAD'),
            },
            'blocked': ['zhihu', 'weibo'],
            'unclear': [],
            'probed': True,
        },
        'answers': {'expired': 'update'},
    },
]

#: Every scenario needs the crawl matrix: the canvas validates required fields
#: against it, and a gate tested against a panel that could not validate would be
#: testing a refusal that has nothing to do with a cookie.
for _scenario in SCENARIOS:
    _scenario.setdefault('matrix', MATRIX)
    _scenario.setdefault('nodes', {})


@pytest.fixture(scope='module')
def gate(tmp_path_factory):
    file = tmp_path_factory.mktemp('cookie-gate') / 'scenarios.json'
    file.write_text(json.dumps(SCENARIOS, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR), str(file))
    assert proc.returncode == 0, f'cookie-gate harness failed: {proc.stderr[-2500:]} {proc.stdout[-800:]}'
    return json.loads(proc.stdout)


class TestWhoIsAsked:
    def test_a_canvas_that_crawls_nothing_asks_nothing(self, gate):
        case = gate['nothing-to-crawl']
        assert case['asked'] is False
        assert case['ran'] is True, 'an upload-and-export canvas is not a cookie question'

    def test_a_resume_is_never_blocked_by_the_gate(self, gate):
        """The user is already inside "refresh the cookie and continue": the run they
        are resuming is the one that just told them the cookie died."""
        case = gate['resume-skips']
        assert case['asked'] is False
        assert case['ran'] is True

    def test_a_comment_node_is_asked_about_the_platform_of_every_link(self, gate):
        """A Comment node carries no platform selector — each link is dispatched by
        its own domain — so the gate that only looked at source nodes would probe
        nothing and block nothing while a dead weibo session waited inside it."""
        body = gate['links-name-the-platforms']['askedBody']
        assert body['platforms'] == ['zhihu', 'weibo'], 'node order, deduped, junk lines dropped'

    def test_two_workflows_on_one_platform_ask_once(self, gate):
        body = gate['same-platform-twice']['askedBody']
        assert body['platforms'] == ['douyin'], body

    def test_the_platform_of_the_canvas_is_queried_not_the_platform_of_the_panel(self, gate):
        body = gate['silent-pass']['askedBody']
        assert body['platforms'] == ['zhihu']


class TestHardBlock:
    def test_a_refused_cookie_starts_no_run(self, gate):
        case = gate['expired-blocks-the-run']
        assert case['asked'] is True
        assert case['ran'] is False, 'the whole feature is this one assertion'

    def test_the_dialog_names_the_platform_and_quotes_the_servers_sentence(self, gate):
        dialog = gate['expired-blocks-the-run']['dialogs'][-1]
        assert 'Weibo' in dialog['message'], 'the user reads a name, not a storage key'
        assert 'weibo' not in dialog['message']
        assert 'WEIBO-COOKIE-IS-DEAD' in dialog['message'], 'the reason was measured, so it is shown'

    def test_the_refusal_offers_no_way_to_run_anyway(self, gate):
        """Every other gate in this file has an escape hatch because a guess may be
        wrong. This one does not, because the answer is not a guess."""
        dialog = gate['expired-blocks-the-run']['dialogs'][-1]
        assert dialog['values'] == ['update', 'null'], dialog
        assert 'go' not in dialog['values']

    def test_canceling_the_dialog_blocks_exactly_as_hard(self, gate):
        case = gate['cancel-still-blocks']
        assert case['ran'] is False
        assert case['cookiePanelOpen'] is False, '「取消」 means "not now", not "show me the panel"'

    def test_going_to_update_lands_on_the_broken_platform(self, gate):
        """The panel opens on whoever was last picked otherwise, and a user hunting
        for the platform that just failed is being sent to do the hunt."""
        case = gate['expired-blocks-the-run']
        assert case['cookiePanelOpen'] is True
        assert case['cookiePlatform'] == 'weibo'

    def test_an_already_open_panel_stays_open_and_changes_platform(self, gate):
        """The toolbar button toggles this panel; a refusal must not. Closing the panel
        over the answer the user was sent to read would be worse than not opening it."""
        case = gate['panel-already-open']
        assert case['ran'] is False
        assert case['cookiePlatform'] == 'weibo'
        assert case['cookiePanelOpen'] is True

    def test_every_refused_platform_is_listed(self, gate):
        case = gate['server-wording-carries-the-detail']
        message = case['dialogs'][-1]['message']
        assert 'ZHIHU-DEAD' in message and 'WEIBO-DEAD' in message
        assert '2' in case['dialogs'][-1]['message'].split('\n')[0], 'the header says how many were refused'
        assert case['cookiePlatform'] == 'zhihu', 'the panel opens on the first refusal'


class TestNoAnswerIsNotAnAnswer:
    def test_a_platform_that_could_not_be_checked_still_runs(self, gate):
        """Risk control, a timeout, a profile held by a live crawl: none of them is
        evidence about the cookie, and refusing on one would waste the very session
        the user is being told to refresh."""
        case = gate['no-answer-does-not-block']
        assert case['ran'] is True
        assert case['dialogs'] == [], 'a refusal needs a fact, not an absence'

    def test_the_unchecked_case_is_said_out_loud(self, gate):
        """Silence would read as "verified, fine" — the one misreading that costs a
        re-login nobody needed."""
        joined = '\n'.join(gate['no-answer-does-not-block']['toasts'])
        assert 'Zhihu' in joined
        assert 'zhihu' not in joined, 'a storage key printed where a platform name belongs'
        assert 'could not' in joined.lower() or '无法核对' in joined

    def test_a_gate_that_cannot_be_reached_is_reported_and_skipped(self, gate):
        for scenario in ('gate-refused', 'gate-unreachable'):
            case = gate[scenario]
            assert case['ran'] is True, f'{scenario}: a check that failed is not a wall the site reported'
            joined = '\n'.join(case['toasts'])
            assert 'Zhihu' in joined, f'{scenario} must say which platforms went unchecked'
            assert 'zhihu' not in joined, f'{scenario} printed the storage key at the user'
            assert 'not a pass' in joined or '不是「有效」' in joined, f'{scenario} must not imply a pass'


class TestTheCheckOffMeansOff:
    def test_with_both_switches_off_nothing_is_asked_at_all(self, gate):
        """The old 「执行前确认 Cookie」 prompt used to sit on this branch and ask the
        user to guess; an off switch now genuinely asks and blocks nothing."""
        case = gate['both-off']
        assert case['asked'] is False
        assert case['dialogs'] == []
        assert case['ran'] is True


class TestWhichBrowserIsProbed:
    def test_the_per_run_profile_answer_travels_to_the_check(self, gate):
        """The two are different sessions: a run that gave up the profile plants the
        saved file into a new browser, and that is the browser whose cookie matters."""
        assert gate['same-platform-twice']['askedBody']['use_profile'] is False
        assert gate['profile-kept']['askedBody']['use_profile'] is True

    def test_a_run_with_nothing_to_decide_sends_no_answer(self, gate):
        """Absence means "follow the setting". Writing false here because no dialog
        appeared would turn one press into a global override."""
        assert 'use_profile' not in gate['silent-pass']['askedBody']


class TestSerialOnlyPlatforms:
    """weibo queues by the site's rule, and the user hears it before paying for it."""

    def test_two_weibo_crawls_are_announced_before_the_run(self, gate):
        case = gate['weibo-serial-warn-proceeds']
        warn = [dialog for dialog in case['dialogs'] if 'serial' in dialog['values']]
        assert len(warn) == 1, f'one press, one warning: {case["dialogs"]}'
        assert 'Weibo' in warn[0]['message'], "the warning names the platform in the user's word"
        assert 'weibo' not in warn[0]['message'], 'a storage key printed where a platform name belongs'
        assert case['asked'] is True and case['ran'] is True, 'answering 继续 queues the crawls without losing the run'

    def test_weibo_never_gets_the_profile_fork(self, gate):
        """The fork offers 本次不用 = true parallelism, which weibo cannot deliver;
        asking would promise a thing the gate will not do."""
        case = gate['weibo-serial-warn-proceeds']
        fork = [dialog for dialog in case['dialogs'] if 'use' in dialog['values'] and 'skip' in dialog['values']]
        assert fork == [], f'the clash question came back for a platform that queues anyway: {case["dialogs"]}'

    def test_refusing_the_warning_starts_nothing(self, gate):
        case = gate['weibo-serial-warn-refuses']
        assert case['ran'] is False
        assert case['asked'] is False, 'a run the user just cancelled should not have paid for cookie probes'

    def test_one_weibo_crawl_is_not_a_queue(self, gate):
        case = gate['weibo-single-runs-quiet']
        serial = [dialog for dialog in case['dialogs'] if 'serial' in dialog['values']]
        assert serial == [], 'one crawl queues behind nobody — the warning would be noise'
        assert case['ran'] is True


class TestTheGateFollowsTheModeNotJustThePlatform:
    """A cookie is a fact about a session; whether this crawl needs one is a fact about
    the MODE. Measured on the live site: weibo's 热搜 endpoint returns the same board to
    an anonymous browser, while zhihu's answers it 401. Probing the first would refuse a
    run the site would have served, and tell the user to log in for nothing."""

    def test_a_board_that_needs_no_session_is_never_probed(self, gate):
        case = gate['board-needs-no-cookie']
        assert case['asked'] is False, f'the gate probed a crawl that needs no cookie: {case["askedBody"]}'
        assert case['ran'] is True, 'and the run was still started'

    def test_the_same_board_on_a_session_platform_still_asks(self, gate):
        case = gate['board-needs-a-cookie']
        assert case['asked'] is True, 'exempting weibo must not exempt 热榜 as a word'
        assert case['askedBody']['platforms'] == ['zhihu'], case['askedBody']

    def test_a_mixed_canvas_probes_only_the_platform_that_needs_it(self, gate):
        case = gate['board-mixed-with-post']
        assert case['asked'] is True
        assert case['askedBody']['platforms'] == ['zhihu'], (
            f'the weibo 热搜 node was carried into the probe: {case["askedBody"]}'
        )
        assert case['ran'] is True


class TestNothingIsSaidTwice:
    def test_a_silent_pass_prints_no_warning(self, gate):
        case = gate['silent-pass']
        joined = '\n'.join(case['toasts'])
        assert 'could not' not in joined.lower(), case['toasts']
        assert 'refused' not in joined.lower(), case['toasts']
        assert case['ran'] is True


class TestMixedNetworks:
    """One canvas, two networks — and the machine is only ever on one of them.

    Measured by the user: with a VPN up douyin answers 502, and without one x.com never
    loads. So the halves have to be run apart, and the only question worth asking is
    whether the user meant that. It is asked BEFORE the cookie check, because that check
    opens a browser per platform and a run about to be cancelled should not have paid.
    """

    def test_a_two_network_canvas_is_asked_before_anything_else(self, gate):
        case = gate['mixed-networks-refuses-to-run']
        assert len(case['dialogs']) == 1, case['dialogs']
        message = case['dialogs'][0]['message']
        assert 'Douyin' in message and 'YouTube' in message, 'the question has to name both halves'
        assert 'douyin' not in message, 'the domestic half was a key, not a word'
        assert case['asked'] is False, 'the cookie probe is not bought for a run that was about to be split'
        assert case['ran'] is False

    def test_continuing_runs_both_halves_and_still_checks_the_cookies(self, gate):
        """The answer is the user's, because a machine with split routing genuinely can
        serve both — this page cannot tell that machine from one with a VPN on, so it
        asks rather than forbidding."""
        case = gate['mixed-networks-continued']
        assert len(case['dialogs']) == 1
        assert case['asked'] is True
        assert sorted(case['askedBody']['platforms']) == ['douyin', 'youtube']
        assert case['ran'] is True

    def test_the_two_buttons_are_continue_and_back_away(self, gate):
        dialog = gate['mixed-networks-refuses-to-run']['dialogs'][0]
        assert dialog['values'] == ['go', 'null'], dialog

    def test_one_network_is_left_alone(self, gate):
        """The profile notice still fires (douyin is a platform a throwaway browser
        fails on) — what must not fire is the routing question, whose two buttons are
        继续 plus a cancel and nothing else."""
        case = gate['mixed-network-silent']
        asked_about_networks = [dialog for dialog in case['dialogs'] if dialog['values'] == ['go', 'null']]
        assert asked_about_networks == [], f'two domestic crawls are not a routing question: {case["dialogs"]}'
        assert case['asked'] is True and case['ran'] is True

    def test_a_platform_the_matrix_has_no_region_for_is_not_guessed_at(self, gate):
        """Blanking youtube's region must not produce a warning built on an assumption,
        and equally must not lose the run: an unknown classification is nobody's fault."""
        case = gate['mixed-without-a-region']
        assert case['dialogs'] == [], case['dialogs']
        assert case['asked'] is True
        assert case['ran'] is True

    def test_the_switch_hides_the_question_and_nothing_else(self, gate):
        """Same run, same platforms, same cookie check: only the asking is switched."""
        case = gate['mixed-warning-off']
        assert case['dialogs'] == []
        assert case['asked'] is True, 'turning the warning off must not turn the cookie check off too'
        assert case['ran'] is True
