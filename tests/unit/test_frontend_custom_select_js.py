"""The themed dropdown in ``custom-select.js`` — the machinery behind every select.

``harness_app.mjs`` / ``harness_cookie_gate.mjs`` / ``harness_profiles.mjs`` each load
this file only so ``app.js`` finds ``window.CustomSelect`` at boot: before these
cases nothing had ever called ``enhance``, ``build``, ``open``, ``place``, ``scan``
or ``refreshAll``. Every one of those ~600 lines could have been deleted and the
suite stayed green.

The grid covered here is the one the control actually has to answer, because each
row of it was a bug report or is a red line in ``AGENTS.md``:

  · wiring      — wrapper/trigger/value/menu, the native select kept as the value
    store, and the full text mirrored into ``trigger.title`` (an ellipsised
    control that says nowhere what it cut off);
  · single      — one popup, one choice, one ``change`` per real change, a click on
    the already-current row changing nothing;
  · checklist   — ``<select multiple>`` stays open, reports a count through
    ``dataset.multiLabel``, falls back to ``dataset.placeholder``, and shows the
    "nothing to pick" sentence instead of a count;
  · refusal     — a disabled option row REPORTS its reason (a ``cselect-blocked``
    event that reaches the *document*, where ``zenviz.js`` listens) instead of
    being selected;
  · placement   — the popup stays inside the viewport, flips above the anchor when
    there is no room below, and is capped by ``MENU_MAX_WIDTH``, which must be the
    same number the stylesheet states for ``.cselect-menu max-width``;
  · keyboard    — arrows move the cursor / selection and walk past a refused row,
    Enter and Space tick, Escape closes;
  · dismissal   — opened by *mousedown* (a click can be swallowed when the bar
    re-wraps), and the click paired with that press must not close what it opened;
  · late & language — ``scan`` picks up a control rendered after boot without
    double-wrapping the earlier one, and ``refreshAll`` re-stamps labels after the
    option text is rewritten, and prunes a control that left the page.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
CSS = REPO / 'backend' / 'static' / 'css' / 'style.css'
HARNESS = REPO / 'tests' / 'frontend' / 'harness_custom_select.mjs'


# ─── fixtures: the markup the page really renders ─────────────────────────


def select(id_, options, multiple=False, classes='settings-select', multi_label=None, placeholder=None, disabled=False):
    """A `<select>` in the shape `index.html` and `zenviz.js` write it.

    Boolean attributes carry their own name as the value: the stub's markup parser
    only reads `name=value` (see the harness header), and HTML treats any value of
    a boolean attribute as true.
    """
    attrs = [f'id="{id_}"', f'class="{classes}"']
    if multiple:
        attrs.append('multiple="multiple"')
    if disabled:
        attrs.append('disabled="disabled"')
    if multi_label:
        attrs.append(f'data-multi-label="{multi_label}"')
    if placeholder:
        attrs.append(f'data-placeholder="{placeholder}"')
    rows = []
    for opt in options:
        line = f'<option value="{opt["value"]}"'
        if opt.get('selected'):
            line += ' selected="selected"'
        if opt.get('disabled'):
            line += ' disabled="disabled"'
        for key in ('note', 'reason'):
            if opt.get(key):
                line += f' data-{key}="{opt[key]}"'
        if opt.get('title'):
            line += f' title="{opt["title"]}"'
        rows.append(f'{line}>{opt["text"]}</option>')
    return f'<select {" ".join(attrs)}>{"".join(rows)}</select>'


def opt(value, text=None, **flags):
    return {'value': value, 'text': text if text is not None else value, **flags}


CHOICES = [
    opt('zhihu', '知乎', selected=True),
    opt('weibo', '微博'),
    opt('bilibili', '哔哩哔哩'),
]
# The refusal case, spelled the way `chartStudio` spells it: the row exists, it is
# unusable, and `data-reason` says what to do first.
MIXED = [
    opt('a', 'node a', selected=True),
    opt('b', 'node b', disabled=True, note='0 rows', reason='run node b first'),
    opt('c', 'node c'),
    opt('d', 'node d'),
]
LONG = '一个很长很长会被截断的采集列名称 with a tail'

SCENARIOS = [
    # ── wiring ───────────────────────────────────────────────────────────────
    {
        'id': 'enhance-single',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [],
    },
    {
        'id': 'enhance-ellipsised',
        'html': select('kw', [opt('x', LONG, selected=True)]),
        'ids': ['kw'],
        'steps': [],
    },
    {
        'id': 'enhance-disabled',
        'html': select('kw', CHOICES, disabled=True),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}],
    },
    {
        'id': 'enhance-empty',
        'html': '<select id="none" class="settings-select"></select>',
        'ids': ['none'],
        'steps': [{'do': 'open', 'target': 'none'}],
    },
    # ── single choice ────────────────────────────────────────────────────────
    {
        'id': 'open-single',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}],
    },
    {
        'id': 'pick-row',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'tapRow', 'target': 'kw', 'row': 2}],
    },
    {
        'id': 'pick-current-row',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'tapRow', 'target': 'kw', 'row': 0}],
    },
    {
        'id': 'blocked-single',
        'html': select('kw', MIXED),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'tapRow', 'target': 'kw', 'row': 1}],
    },
    # ── the checklist ────────────────────────────────────────────────────────
    {
        'id': 'multi-open',
        'html': select('src', MIXED, multiple=True, classes='studio-select', multi_label='{n} picked'),
        'ids': ['src'],
        'steps': [{'do': 'open', 'target': 'src'}],
    },
    {
        'id': 'multi-tick-and-untick',
        'html': select('src', MIXED, multiple=True, classes='studio-select', multi_label='{n} picked'),
        'ids': ['src'],
        'steps': [
            {'do': 'open', 'target': 'src'},
            {'do': 'tapRow', 'target': 'src', 'row': 2},
            {'do': 'tapRow', 'target': 'src', 'row': 3},
            {'do': 'tapRow', 'target': 'src', 'row': 2},
        ],
    },
    {
        'id': 'multi-blocked-keeps-list',
        'html': select('src', MIXED, multiple=True, classes='studio-select', multi_label='{n} picked'),
        'ids': ['src'],
        'steps': [{'do': 'open', 'target': 'src'}, {'do': 'tapRow', 'target': 'src', 'row': 1}],
    },
    {
        'id': 'multi-nothing-picked',
        'html': select(
            'src',
            [opt('a', 'node a'), opt('b', 'node b')],
            multiple=True,
            multi_label='{n} picked',
            placeholder='pick at least one',
        ),
        'ids': ['src'],
        'steps': [],
    },
    {
        'id': 'multi-nothing-to-pick',
        # `chartStudio._renderNoSource`: one option, no value, the sentence as text.
        'html': select('src', [opt('', '没有可用的数据源')], multiple=True, multi_label='{n} picked'),
        'ids': ['src'],
        'steps': [],
    },
    {
        'id': 'multi-keyboard',
        'html': select('src', MIXED, multiple=True, multi_label='{n} picked'),
        'ids': ['src'],
        'steps': [
            {'do': 'open', 'target': 'src'},
            # The cursor lands on the ticked row (0); ArrowDown must walk past the
            # refused row 1 and land on 2, where Enter ticks it.
            {'do': 'key', 'target': 'src', 'keys': ['ArrowDown']},
            {'do': 'key', 'target': 'src', 'keys': ['Enter']},
        ],
    },
    {
        'id': 'multi-keyboard-space',
        'html': select('src', MIXED, multiple=True, multi_label='{n} picked'),
        'ids': ['src'],
        'steps': [
            {'do': 'open', 'target': 'src'},
            {'do': 'key', 'target': 'src', 'keys': ['ArrowDown', 'ArrowDown', ' ']},
        ],
    },
    # ── placement ────────────────────────────────────────────────────────────
    {
        'id': 'place-below',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [
            {'do': 'box', 'target': 'kw', 'left': 200, 'top': 300, 'width': 140, 'height': 30},
            {'do': 'open', 'target': 'kw'},
        ],
    },
    {
        'id': 'place-flips-above',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'viewport': {'innerWidth': 1440, 'innerHeight': 800},
        'steps': [
            {'do': 'box', 'target': 'kw', 'left': 200, 'top': 700, 'width': 140, 'height': 30},
            {'do': 'measureMenu', 'target': 'kw', 'height': 200},
            {'do': 'open', 'target': 'kw'},
        ],
    },
    {
        'id': 'place-inside-narrow-viewport',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'viewport': {'innerWidth': 1920, 'innerHeight': 1080},
        'steps': [
            {'do': 'box', 'target': 'kw', 'left': 1780, 'top': 100, 'width': 120, 'height': 30},
            {'do': 'measureMenu', 'target': 'kw', 'width': 340},
            {'do': 'open', 'target': 'kw'},
        ],
    },
    {
        'id': 'place-off-the-left-edge',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [
            {'do': 'box', 'target': 'kw', 'left': -40, 'top': 100, 'width': 120, 'height': 30},
            {'do': 'open', 'target': 'kw'},
        ],
    },
    {
        'id': 'place-width-cap',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [
            {'do': 'box', 'target': 'kw', 'left': 10, 'top': 100, 'width': 120, 'height': 30},
            {'do': 'measureMenu', 'target': 'kw', 'scrollWidth': 5000},
            {'do': 'open', 'target': 'kw'},
        ],
    },
    {
        'id': 'place-width-fits-content',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [
            {'do': 'box', 'target': 'kw', 'left': 10, 'top': 100, 'width': 120, 'height': 30},
            {'do': 'measureMenu', 'target': 'kw', 'scrollWidth': 200},
            {'do': 'open', 'target': 'kw'},
        ],
    },
    # ── keyboard on a single choice ─────────────────────────────────────────
    {
        'id': 'keys-single-arrow-down',
        'html': select('kw', MIXED),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'key', 'target': 'kw', 'keys': ['ArrowDown']}],
    },
    {
        'id': 'keys-single-arrow-up',
        'html': select('kw', MIXED),
        'ids': ['kw'],
        'steps': [
            {'do': 'open', 'target': 'kw'},
            {'do': 'key', 'target': 'kw', 'keys': ['ArrowDown']},
            {'do': 'key', 'target': 'kw', 'keys': ['ArrowUp']},
        ],
    },
    {
        'id': 'keys-single-opens-when-closed',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'key', 'target': 'kw', 'keys': ['ArrowDown']}],
    },
    {
        'id': 'keys-single-escape',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'key', 'target': 'kw', 'keys': ['Escape']}],
    },
    {
        'id': 'keys-closed-escape-is-harmless',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'key', 'target': 'kw', 'keys': ['Enter']}],
    },
    {
        # Measured here, and reported as a product bug: see
        # `test_enter_on_an_open_single_popup_commits_what_is_shown`.
        'id': 'keys-single-enter-when-open',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'key', 'target': 'kw', 'keys': ['Enter']}],
    },
    # ── one popup at a time, and dismissal ──────────────────────────────────
    {
        'id': 'one-at-a-time',
        'html': select('kw', CHOICES) + select('other', [opt('x', 'X', selected=True), opt('y', 'Y')]),
        'ids': ['kw', 'other'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'open', 'target': 'other'}],
    },
    {
        'id': 'closed-by-second-press',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'open', 'target': 'kw'}],
    },
    {
        'id': 'trigger-click-does-not-reopen',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [
            {'do': 'open', 'target': 'kw'},
            {'do': 'tapTrigger', 'target': 'kw'},
        ],
    },
    {
        'id': 'armed-release-keeps-popup',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'docClick'}],
    },
    {
        'id': 'next-click-closes-popup',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'docClick'}, {'do': 'docClick'}],
    },
    {
        'id': 'click-inside-menu-keeps-popup',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'docMousedown'}, {'do': 'docClick', 'inside': 'kw'}],
    },
    {
        'id': 'escape-anywhere-closes',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'escape'}],
    },
    {
        'id': 'close-all',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'open', 'target': 'kw'}, {'do': 'closeAll'}],
    },
    {
        'id': 'owns-popup',
        # The control being edited sits inside the panel the guard protects.
        'html': f'<div id="panel">{select("kw", CHOICES)}</div>'
        + select('other', [opt('x', 'X', selected=True), opt('y', 'Y')]),
        'ids': ['kw', 'other'],
        'steps': [
            {'do': 'open', 'target': 'kw'},
            {'do': 'open', 'target': 'other'},
            {'do': 'ownsPopup', 'target': 'kw', 'other': 'other', 'row': 0, 'panel': 'panel'},
        ],
    },
    # ── scan / refresh ───────────────────────────────────────────────────────
    {
        'id': 'scan-later',
        # Attribute selectors in the stub read `dataset` (see harness_dom's
        # matcher), so the two attributes `scan` itself selects on are spelled
        # twice: the plain attribute the product reads back with `getAttribute`,
        # and the `data-` mirror the selector can see.
        'html': select('kw', CHOICES)
        + '<input id="kw-input" type="text" data-type="text">'
        + '<input id="paste-input" type="text" data-type="text" list="hist-list" data-list="hist-list">',
        'ids': ['kw', 'late'],
        'steps': [
            {
                'do': 'appendMarkup',
                'html': select('late', [opt('p', 'P', selected=True), opt('q', 'Q')])
                + '<datalist id="hist-list"><option value="saved one"></option></datalist>',
            },
            {'do': 'scan'},
        ],
    },
    {
        'id': 'stale-label-before-refresh',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'renameOptions', 'map': {'weibo': 'Weibo', 'zhihu': 'Zhihu'}}],
    },
    {
        'id': 'label-after-refresh',
        'html': select('kw', CHOICES) + select('src', MIXED, multiple=True, multi_label='{n} selected'),
        'ids': ['kw', 'src'],
        'steps': [
            {'do': 'renameOptions', 'map': {'zhihu': 'Zhihu', 'a': 'node A'}},
            {'do': 'refreshAll'},
        ],
    },
    {
        'id': 'refresh-follows-a-dying-control',
        'html': select('kw', CHOICES) + select('gone', [opt('z', 'Z', selected=True)]),
        'ids': ['kw'],
        'steps': [
            {'do': 'remember', 'as': 'goneMenu', 'target': 'gone', 'part': 'menu'},
            {'do': 'removeControl', 'target': 'gone'},
            {'do': 'refreshAll'},
        ],
    },
    {
        'id': 'disabled-state-follows-the-control',
        'html': select('kw', CHOICES),
        'ids': ['kw'],
        'steps': [{'do': 'setDisabled', 'target': 'kw', 'value': True}],
    },
]

SCENARIO_IDS = [sc['id'] for sc in SCENARIOS]


@pytest.fixture(scope='module')
def world(tmp_path_factory):
    """One node run for the whole grid: the module's own state (`INSTANCES`,
    `openInst`) is per context, so every scenario gets a fresh page anyway."""
    tmp = tmp_path_factory.mktemp('custom-select')
    payload = tmp / 'scenarios.json'
    payload.write_text(json.dumps(SCENARIOS, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(HARNESS), str(JS_DIR), str(payload))
    assert proc.returncode == 0, f'harness failed: {proc.stderr}'
    report = json.loads(proc.stdout)
    assert set(report) == set(SCENARIO_IDS), 'a scenario did not report'
    return report


def ctl(world, scenario, id_):
    return world[scenario]['controls'][id_]


def px(value):
    """`'1572px'` -> 1572; `None` stays `None`, so a missing style is a failure."""
    assert value is not None, 'the popup was never placed'
    return float(re.sub(r'px$', '', value))


# ─── wiring ───────────────────────────────────────────────────────────────


class TestWiring:
    def test_the_wrapper_takes_the_controls_own_place_and_class(self, world):
        c = ctl(world, 'enhance-single', 'kw')
        assert c['enhanced'] is True
        assert c['wrapClass'] == ['cselect', 'settings-select'], 'sizing left the wrapper'
        assert c['triggerClass'] == ['cselect-trigger']
        assert c['nativeInsideWrapper'] is True, 'the native select was dropped, not kept'
        assert c['nativeConnected'] is True
        assert c['nativeTabIndex'] == -1, 'the real control is still in the tab order'
        assert c['arrowDrawn'] is True, 'the trigger has no arrow'

    def test_the_current_choice_is_the_label(self, world):
        c = ctl(world, 'enhance-single', 'kw')
        assert c['label'] == '知乎'
        assert c['title'] == '知乎'

    def test_the_popup_is_rendered_into_body_and_remembers_its_control(self, world):
        c = ctl(world, 'open-single', 'kw')
        assert c['menuOnBody'] is True, 'a popup inside its panel is clipped by the panel'
        assert c['popupBelongsToControl'] is True
        assert c['popupCount'] == 1
        assert c['menuClass'] == ['cselect-menu', 'open']

    def test_an_ellipsised_control_mirrors_its_full_text_into_the_title(self, world):
        """The label cuts off inside a control whose width follows its field, so the
        whole sentence has to live somewhere readable — and it has to be there
        *before* the menu is ever opened."""
        c = ctl(world, 'enhance-ellipsised', 'kw')
        assert c['label'] == LONG
        assert c['title'] == LONG, 'a control that was never opened said nowhere what it cut off'

    def test_a_disabled_control_opens_nothing(self, world):
        c = ctl(world, 'enhance-disabled', 'kw')
        assert 'disabled' in c['wrapClass']
        assert 'open' not in c['menuClass'], 'a disabled select answered a press with a popup'
        assert 'open' not in c['wrapClass']

    def test_an_empty_control_is_still_a_control(self, world):
        c = ctl(world, 'enhance-empty', 'none')
        assert c['enhanced'] is True
        assert c['label'] == '—', 'no options and no placeholder has to say something'
        assert 'open' not in c['menuClass']


# ─── the single choice ────────────────────────────────────────────────────


class TestSingleChoice:
    def test_the_menu_lists_every_option_once(self, world):
        rows = ctl(world, 'open-single', 'kw')['rows']
        assert [r['text'] for r in rows] == ['知乎', '微博', '哔哩哔哩']
        assert [r['classes'] for r in rows][0] == ['cselect-option', 'selected']
        assert all('multi' not in r['classes'] for r in rows)

    def test_picking_a_row_moves_the_native_select_and_closes_the_popup(self, world):
        c = ctl(world, 'pick-row', 'kw')
        assert c['selectedIndex'] == 2 and c['value'] == 'bilibili'
        assert c['label'] == '哔哩哔哩' and c['title'] == '哔哩哔哩'
        assert 'open' not in c['menuClass'] and 'open' not in c['wrapClass']

    def test_one_change_event_per_real_change(self, world):
        """The wrapper's promise is that the owner's `onchange` still runs — once.
        A second dispatch would re-enter `updateParam` and re-render the panel."""
        assert world['pick-row']['changes'] == {'kw': 1}

    def test_clicking_the_current_row_changes_nothing_and_says_nothing(self, world):
        c = ctl(world, 'pick-current-row', 'kw')
        assert c['selectedIndex'] == 0 and c['value'] == 'zhihu'
        assert world['pick-current-row']['changes'] == {'kw': 0}
        assert 'open' not in c['menuClass'], 'the popup stayed up over a finished choice'

    def test_a_refused_row_reports_its_reason_to_the_document(self, world):
        """`chartStudio` and the panels own the loud part; the control only has to
        carry the reason out. It is a document-level listener in `zenviz.js`, so
        the event has to bubble and it has to name the row it refused."""
        report = world['blocked-single']
        assert [b['targetId'] for b in report['blocked']] == ['kw']
        assert report['blocked'][0]['detail'] == {
            'value': 'b',
            'label': 'node b',
            'reason': 'run node b first',
        }
        c = ctl(world, 'blocked-single', 'kw')
        chosen = {s['value']: s['selected'] for s in c['optionStates']}
        assert chosen['b'] is False, 'a row the picker disabled was selected anyway'
        assert chosen['a'] is True, 'the current choice was replaced by a refusal'
        assert 'open' not in c['menuClass'], 'a single popup stays open on a row it cannot take'
        assert report['changes'] == {'kw': 0}, 'a refusal fired the owner as if something was picked'

    def test_a_refused_row_still_shows_why_beside_the_label(self, world):
        """`data-reason` is the full sentence the owner reports and the tooltip
        carries; `data-note` is the short figure shown beside the label. Both are
        painted on a row the picker disabled, which is the only place either is
        written at all."""
        rows = ctl(world, 'blocked-single', 'kw')['rows']
        refused = rows[1]
        assert 'disabled' in refused['classes']
        assert refused['note'] == '0 rows'
        assert refused['title'] == 'run node b first', 'the full sentence exists nowhere readable'

    def test_an_option_note_and_a_title_survive_into_the_row(self, world):
        rows = ctl(world, 'open-single', 'kw')['rows']
        assert all(r['note'] is None for r in rows), 'a plain option grew a note'
        assert all(r['title'] == r['text'] for r in rows), 'an ellipsised row lost its full text'


# ─── the checklist ────────────────────────────────────────────────────────


class TestChecklist:
    def test_the_trigger_reports_a_count_not_a_current_row(self, world):
        c = ctl(world, 'multi-open', 'src')
        assert c['label'] == '1 picked', 'the owner asked for this wording, not the control'
        assert c['title'] == '1 picked'

    def test_a_ticked_row_stays_open_and_recounts(self, world):
        """A checklist is used to build a selection: closing after one row would make
        the user press the control again per row, and the count is the only thing
        they can see of it."""
        c = ctl(world, 'multi-tick-and-untick', 'src')
        assert c['selectedOptions'] == ['a', 'd']
        assert c['label'] == '2 picked'
        assert 'open' in c['menuClass'], 'the checklist closed on a tick'
        assert world['multi-tick-and-untick']['changes'] == {'src': 3}, 'one change per tick expected'

    def test_a_checklist_row_carries_a_box_not_an_underline(self, world):
        rows = ctl(world, 'multi-open', 'src')['rows']
        assert all('multi' in r['classes'] for r in rows)
        assert all(r['hasCheck'] for r in rows)
        assert rows[0]['classes'].count('selected') == 1

    def test_a_refused_row_in_a_checklist_keeps_the_list_and_the_selection(self, world):
        report = world['multi-blocked-keeps-list']
        c = ctl(world, 'multi-blocked-keeps-list', 'src')
        assert [b['detail']['reason'] for b in report['blocked']] == ['run node b first']
        assert [s['value'] for s in c['optionStates'] if s['selected']] == ['a']
        assert 'open' in c['menuClass'], 'a refusal closed the list the user was working through'
        assert report['changes'] == {'src': 0}

    def test_nothing_picked_says_so_in_the_owners_words(self, world):
        c = ctl(world, 'multi-nothing-picked', 'src')
        assert c['label'] == 'pick at least one'

    def test_a_lone_valueless_option_shows_the_sentence_not_a_zero(self, world):
        """`chartStudio._renderNoSource` answers "there is nothing to pick" with one
        valueless option; '0 picked' would be a count of a list that has no rows."""
        c = ctl(world, 'multi-nothing-to-pick', 'src')
        assert c['label'] == '没有可用的数据源'

    def test_the_cursor_lands_on_a_ticked_row_when_the_list_opens(self, world):
        rows = ctl(world, 'multi-open', 'src')['rows']
        assert [i for i, r in enumerate(rows) if 'active' in r['classes']] == [0], (
            'the keyboard started nowhere near the user'
        )


# ─── placement ────────────────────────────────────────────────────────────


class TestPlacement:
    def test_a_menu_under_room_sits_under_its_trigger(self, world):
        c = ctl(world, 'place-below', 'kw')
        style = c['menuStyle']
        assert px(style['top']) == 333  # box.bottom (300 + 30) + the 3px gutter
        assert px(style['minWidth']) == 140 and px(style['width']) == 140
        assert px(style['left']) == 200

    def test_a_menu_without_room_below_flips_above_the_anchor(self, world):
        c = ctl(world, 'place-flips-above', 'kw')
        top = px(c['menuStyle']['top'])
        assert top < 700, 'the popup was placed where the anchor already is'
        assert top == 700 - 200 - 3, 'the flip lost its gutter or its height'

    def test_the_popup_stays_inside_a_narrow_viewport(self, world):
        c = ctl(world, 'place-inside-narrow-viewport', 'kw')
        left, width = px(c['menuStyle']['left']), px(c['menuStyle']['width'])
        assert left == 1572
        assert left >= 6 and left + width <= 1920 - 8, 'the popup hangs off the right edge'

    def test_a_control_scrolled_off_the_left_edge_uses_the_screen(self, world):
        left = px(ctl(world, 'place-off-the-left-edge', 'kw')['menuStyle']['left'])
        assert left == 6, f'a popup at left {left} is off-screen and unreachable'

    def test_the_width_is_capped_and_the_cap_is_the_stylesheets_own(self, world):
        """`place()` widens the popup to its content, and the ceiling for that is
        stated twice: `MENU_MAX_WIDTH` here and `.cselect-menu { max-width }` in
        style.css. Two numbers that drift are a popup the CSS clips or a control
        that stops honouring its own ceiling."""
        measured = px(ctl(world, 'place-width-cap', 'kw')['menuStyle']['width'])
        rule = re.search(r'\.cselect-menu\s*\{[^}]*?max-width:\s*(\d+)px', CSS.read_text(encoding='utf-8'))
        assert rule, 'no max-width on .cselect-menu to compare the JS ceiling with'
        assert measured == float(rule.group(1)), (
            f'place() caps the popup at {measured}px but the stylesheet allows {rule.group(1)}px'
        )

    def test_the_cap_is_a_ceiling_not_the_only_width(self, world):
        c = ctl(world, 'place-width-fits-content', 'kw')
        assert px(c['menuStyle']['width']) == 202, 'a popup wider than its anchor by 2px of padding'
        assert px(c['menuStyle']['minWidth']) == 120


# ─── keyboard ─────────────────────────────────────────────────────────────


class TestKeyboard:
    def test_arrows_move_the_choice_and_walk_past_a_refused_row(self, world):
        """`b` is disabled for a reason; landing on it would put the keyboard cursor
        on a row that cannot be taken."""
        c = ctl(world, 'keys-single-arrow-down', 'kw')
        assert c['value'] == 'c' and c['label'] == 'node c'
        assert 'open' in c['menuClass'], 'moving the choice collapsed the popup'
        assert world['keys-single-arrow-down']['changes'] == {'kw': 1}
        assert [r['classes'] for r in c['rows']][2][1] == 'selected'

    def test_arrow_up_returns_to_the_previous_choice(self, world):
        c = ctl(world, 'keys-single-arrow-up', 'kw')
        assert c['value'] == 'a' and world['keys-single-arrow-up']['changes'] == {'kw': 2}

    def test_an_arrow_on_a_closed_control_opens_it_without_choosing(self, world):
        c = ctl(world, 'keys-single-opens-when-closed', 'kw')
        assert c['value'] == 'zhihu'
        assert 'open' in c['menuClass']
        assert world['keys-single-opens-when-closed']['changes'] == {'kw': 0}

    def test_escape_closes_and_reports_no_change(self, world):
        c = ctl(world, 'keys-single-escape', 'kw')
        assert 'open' not in c['menuClass'] and 'open' not in c['wrapClass']
        assert world['keys-single-escape']['changes'] == {'kw': 0}

    def test_a_key_press_while_closed_does_not_move_the_selection(self, world):
        """The trigger opens on the first arrow and *returns*; swallowing Enter as a
        choice would replace the user's selection with the next row."""
        c = ctl(world, 'keys-closed-escape-is-harmless', 'kw')
        assert c['value'] == 'zhihu' and world['keys-closed-escape-is-harmless']['changes'] == {'kw': 0}

    def test_enter_ticks_the_cursor_row_in_a_checklist(self, world):
        c = ctl(world, 'multi-keyboard', 'src')
        assert c['selectedOptions'] == ['a', 'c']
        assert c['label'] == '2 picked'
        assert 'open' in c['menuClass']

    def test_space_ticks_the_same_row_enter_would(self, world):
        """Space is the other half of the checklist contract; only wiring Enter left
        the row untickable from the keyboard."""
        c = ctl(world, 'multi-keyboard-space', 'src')
        assert c['selectedOptions'] == ['a', 'd']
        assert [i for i, r in enumerate(c['rows']) if 'active' in r['classes']] == [3]


# ─── dismissal ────────────────────────────────────────────────────────────


class TestDismissal:
    def test_one_popup_at_a_time(self, world):
        a, b = ctl(world, 'one-at-a-time', 'kw'), ctl(world, 'one-at-a-time', 'other')
        assert 'open' not in a['menuClass'], 'two popups were on screen at once'
        assert 'open' in b['menuClass']

    def test_a_second_press_on_the_trigger_closes_it(self, world):
        c = ctl(world, 'closed-by-second-press', 'kw')
        assert 'open' not in c['menuClass'] and 'open' not in c['wrapClass']

    def test_the_release_of_the_opening_press_does_not_close_the_popup(self, world):
        """The control opens on *mousedown*, so the menu is already under the cursor
        when it is released; that release arrives as a click on <body>, and treating
        it as "clicked away" is the classic "needs two clicks" bug."""
        c = ctl(world, 'armed-release-keeps-popup', 'kw')
        assert 'open' in c['menuClass'], 'the popup closed itself the instant it opened'

    def test_the_next_outside_press_closes_it(self, world):
        c = ctl(world, 'next-click-closes-popup', 'kw')
        assert 'open' not in c['menuClass']

    def test_a_press_and_click_inside_the_popup_keeps_it(self, world):
        c = ctl(world, 'click-inside-menu-keeps-popup', 'kw')
        assert 'open' in c['menuClass']

    def test_the_trigger_owns_its_click(self, world):
        """The trigger's own click handler only stops propagation; if the guard also
        saw it, a press would open and immediately close."""
        c = ctl(world, 'trigger-click-does-not-reopen', 'kw')
        assert 'open' in c['menuClass']

    def test_escape_anywhere_closes_the_open_popup(self, world):
        assert 'open' not in ctl(world, 'escape-anywhere-closes', 'kw')['menuClass']

    def test_the_owner_can_close_everything_it_owns(self, world):
        assert 'open' not in ctl(world, 'close-all', 'kw')['menuClass']

    def test_the_popup_counts_as_inside_the_panel_being_edited(self, world):
        """Both popups render into `<body>`, so a panel's own `contains()` test says
        "clicked away" while the user is picking an option — which is how editing a
        node used to discard the pick. The answer has to stay specific: a popup is
        only *that* container's, never a stranger's."""
        probe = [p for p in world['owns-popup']['probes'] if 'ownsPopup' in p][0]['ownsPopup']
        assert probe['ownRow'] is True
        assert probe['ownRowInsidePanel'] is True
        assert probe['rowOfOtherControl'] is False
        assert probe['otherRowInsidePanel'] is False, 'a stranger popup was claimed by this panel'
        assert probe['body'] is False


# ─── scan and refresh ─────────────────────────────────────────────────────


class TestScanAndRefresh:
    def test_scan_wraps_a_control_rendered_after_boot_without_double_wrapping(self, world):
        """The node settings panel is re-injected with innerHTML on every parameter
        change, so `scan` runs over the page again and again. Re-enhancing a control
        that already has a wrapper would give it a second popup and a second
        trigger, and the first one would keep answering."""
        report = world['scan-later']
        assert report['controls']['late']['enhanced'] is True, 'a late control was never picked up'
        assert report['controls']['late']['label'] == 'P'
        assert report['controls']['late']['popupCount'] == 1
        kw = report['controls']['kw']
        assert kw['wrapClass'] == ['cselect', 'settings-select'], 'the earlier control was wrapped twice'
        assert kw['popupCount'] == 1, 'the earlier control grew a second popup'
        assert kw['label'] == '知乎'

    def test_a_datalist_input_is_taken_over_and_detached_from_the_browser(self, world):
        """The OS suggestion popup is the second thing this module exists to replace,
        and leaving `list` on the input would let both popups open."""
        cand = {row['id']: row for row in world['scan-later']['candInputs']}
        assert cand['paste-input']['keptList'] == 'hist-list'
        assert cand['paste-input']['attributeGone'] is True

    def test_a_plain_text_input_never_offers_the_browsers_saved_values(self, world):
        """The third thing the module does: `autocomplete="off"` on every text
        field, so the OS autofill list — which cannot be themed at all — never
        opens over a form the rest of which can."""
        marked = {row['id']: row for row in world['scan-later']['autofill']}
        assert marked['kw-input']['autocomplete'] == 'off'
        # The stub stores attributes as the string the writer passed, which is what
        # a browser's reflection of `spellcheck="false"` also is.
        assert marked['kw-input']['spellcheck'] == 'false'

    def test_the_label_keeps_the_language_it_was_drawn_with_until_refreshed(self, world):
        """Pinned as the contrast to the next case: rewriting `option.textContent`
        alone changes nothing visible, so `refreshAll` is what a language flip
        needs (and `setLang` calls it for exactly this)."""
        assert ctl(world, 'stale-label-before-refresh', 'kw')['label'] == '知乎'

    def test_refresh_re_stamps_every_control_from_the_new_option_text(self, world):
        c = ctl(world, 'label-after-refresh', 'kw')
        assert c['label'] == 'Zhihu' and c['title'] == 'Zhihu'
        multi = ctl(world, 'label-after-refresh', 'src')
        assert multi['label'] == '1 selected', "the count template is the owner's, re-read on refresh"

    def test_refresh_prunes_a_control_that_left_the_page_and_its_popup_with_it(self, world):
        """The popup is a body child, so nothing else would ever remove it: a panel
        redraw would leak one orphan popup per discarded control."""
        gone = world['refresh-follows-a-dying-control']['remembered']['goneMenu']
        assert gone['stillInPage'] is False and gone['connected'] is False

    def test_the_wrapper_follows_a_disabled_flag_flipped_after_boot(self, world):
        """A source list starts empty and fills in later; `sel.disabled` flips over
        the session, so the wrapper has to follow it, not just sample it."""
        assert 'disabled' in ctl(world, 'disabled-state-follows-the-control', 'kw')['wrapClass']
