"""Every inline handler in ``index.html`` has to land on a function that exists.

The page wires its buttons with ``onclick="…"`` strings — about a hundred attributes
and seventy distinct roots, from ``canvas.undo`` to ``chartStudio.loadSelected``.
An attribute is not checked by anything at load time: rename the function, move it
inside a module, typo the object, and the page still renders, still boots, and the
button simply does nothing when it is pressed. That is the "dead button" class of
bug, and until now the suite had a test for the *payload* names that reach an
inline handler (``test_frontend_contract.py``) but none for the handlers themselves.

So this module does two things:

1. statically, it inventories the attributes out of ``index.html`` and refuses a
   handler whose body is not a plain call — the extractor's one blind spot, and a
   shape change here must be noticed rather than silently skipped;
2. at runtime, it loads the product's own JS files **in the order the page lists
   them** into the same zero-dependency sandbox the frontend harnesses use, and
   asks ``typeof (<root>)`` for each root: ``'function'`` or nothing else.

The runtime half answers from the real bindings, so it catches a method that moved,
an object that stopped being global (the top-level ``const`` trap in AGENTS.md is
about `window.X`, but the same rename that hides a function from `window` hides it
from an attribute handler too, which runs against the global scope), and an
attribute that names a function nobody defines. A generated driver script is used
rather than a checked-in ``harness_*.mjs`` because this check owns no page state:
it asks one question of the loaded world and reports, and the answer must name the
offending handler and its line when it fails.
"""

import html
import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / 'backend' / 'static' / 'js'
INDEX = REPO / 'backend' / 'static' / 'index.html'
HARNESS_DOM = REPO / 'tests' / 'frontend' / 'harness_dom.mjs'

#: Every `on<event>="…"` attribute, whatever the event. A new kind of inline handler
#: in the page is covered by construction instead of by remembering to widen a list.
HANDLER_ATTR = re.compile(r'\son([a-zA-Z]+)\s*=\s*"([^"]*)"')

#: The leading call of one statement: `name`, `a.b`, or `a.b.c` followed by `(`.
CALL_ROOT = re.compile(r'^([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(')

#: Words that can begin a statement without being a function anybody declares.
NOT_A_CALL = {'if', 'while', 'for', 'switch', 'return', 'typeof', 'new', 'delete', 'void', 'do', 'else'}

ATTR_BODY = re.compile(r'<script\s+[^>]*src="([^"]+)"', re.I)


def _page_text() -> str:
    return INDEX.read_text(encoding='utf-8')


def _handlers() -> list:
    """`(event, line_number, attribute_body)` for every inline handler on the page."""
    found = []
    for number, line in enumerate(_page_text().splitlines(), start=1):
        for event, body in HANDLER_ATTR.findall(line):
            found.append((event.lower(), number, html.unescape(body)))
    return found


def _statements(body: str) -> list:
    return [part.strip() for part in body.split(';') if part.strip()]


def _roots_of(statement: str) -> list:
    """The call root of one statement, or nothing when the statement is not a call."""
    match = CALL_ROOT.match(statement)
    if not match or match.group(1) in NOT_A_CALL:
        return []
    return [match.group(1)]


def _script_files() -> list:
    """The page's own script list, in the page's own order.

    A handler's root is only a function once the file that defines it has run, and
    several of these files read each other's bindings at load, so the order is
    taken from `index.html` rather than kept as a copy here.
    """
    files = [re.sub(r'^/js/', '', src) for src in ATTR_BODY.findall(_page_text()) if '/js/' in src]
    return files


# ─── the inventory (no node needed: this half must fail even without it) ────


class TestHandlerInventory:
    def test_the_page_still_wires_its_buttons_with_attributes(self):
        """The sweep below is only worth anything while there is something to sweep:
        a count pinned here is what tells a rewritten page from a deleted test."""
        found = _handlers()
        assert len(found) >= 90, f'only {len(found)} inline handlers were found'
        roots = {r for _e, _n, body in found for statement in _statements(body) for r in _roots_of(statement)}
        assert len(roots) >= 60, f'the sweep resolved to only {len(roots)} roots'

    def test_every_handler_is_a_plain_call_or_a_sequence_of_them(self):
        """The extractor reads the leading call of each `;`-separated statement. A
        handler that guards (`if (x) y()`), composes, or reads a chain it built
        itself would be skipped in silence — this refuses the silence."""
        skipped = []
        for event, number, body in _handlers():
            for statement in _statements(body):
                if not _roots_of(statement):
                    skipped.append(f'on{event} at index.html:{number} -> {statement!r}')
        assert not skipped, 'inline handlers the sweep cannot read: ' + '; '.join(skipped)

    def test_the_page_lists_the_scripts_that_answer_those_handlers(self):
        files = _script_files()
        assert {'canvas.js', 'workflow.js', 'app.js'} <= set(files), files
        for name in files:
            assert (JS_DIR / name).exists(), f'index.html asks for /js/{name}, which is not there'


# ─── the world the handlers actually run in ───────────────────────────────

DRIVER = """
/* Generated by tests/unit/test_frontend_handlers_exist.py — see that file. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { pathToFileURL } from 'node:url';

const [jsDir, askPath, domPath] = process.argv.slice(2);
const { files, roots } = JSON.parse(fs.readFileSync(askPath, 'utf8'));
const { baseSandbox, fixWindow } = await import(pathToFileURL(domPath).href);

const sandbox = { ...baseSandbox() };
vm.createContext(sandbox);
fixWindow(vm, sandbox);
const loadErrors = [];
for (const file of files) {
    try {
        vm.runInContext(fs.readFileSync(path.join(jsDir, file), 'utf8'), sandbox, { filename: file });
    } catch (error) {
        /* A file that throws at load takes its bindings with it, which would show
           up below as seventy missing functions. Say which one died instead. */
        loadErrors.push(file + ': ' + error.message);
        break;
    }
}

const answers = {};
for (const root of roots) {
    const head = root.split('.')[0];
    let type = null;
    let note = null;
    try {
        type = vm.runInContext('typeof (' + root + ')', sandbox);
    } catch (error) {
        note = error.message;
    }
    answers[root] = { type, headType: vm.runInContext('typeof ' + head, sandbox), note };
}
process.stdout.write(JSON.stringify({ loadErrors, answers }));
"""


@pytest.fixture(scope='module')
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('handlers')
    driver = tmp / 'driver.mjs'
    driver.write_text(DRIVER, encoding='utf-8')
    roots = sorted({r for _e, _n, body in _handlers() for statement in _statements(body) for r in _roots_of(statement)})
    ask = tmp / 'ask.json'
    ask.write_text(json.dumps({'files': _script_files(), 'roots': roots}, ensure_ascii=False), encoding='utf-8')
    proc = run_node(str(driver), str(JS_DIR), str(ask), str(HARNESS_DOM))
    assert proc.returncode == 0, f'driver failed: {proc.stderr}'
    report = json.loads(proc.stdout)
    assert report['loadErrors'] == [], 'the page scripts do not load: ' + ' | '.join(report['loadErrors'])
    return report['answers'], roots


def _places() -> dict:
    """`root -> the attribute that calls it`, so a failure names the button."""
    places = {}
    for event, number, body in _handlers():
        for statement in _statements(body):
            for root in _roots_of(statement):
                places.setdefault(root, f'on{event}="{statement}" at backend/static/index.html:{number}')
    return places


class TestHandlerRootsResolve:
    def test_the_sweep_asked_about_every_root_it_found(self, world):
        _answers, roots = world
        assert len(roots) >= 60, f'only {len(roots)} roots were asked about'

    def test_every_handler_names_a_function_that_exists(self, world):
        answers, roots = world
        places = _places()
        broken = []
        for root in roots:
            answer = answers[root]
            where = places.get(root, root)
            head = root.split('.')[0]
            if answer['headType'] not in ('object', 'function'):
                broken.append(f'{where}: `{head}` is {answer["headType"]}, so `{root}` cannot be reached')
            elif answer['type'] != 'function':
                broken.append(f'{where}: `{root}` is {answer["type"] or answer["note"]}')
        assert not broken, 'dead inline handlers -> ' + '; '.join(broken)

    def test_a_method_root_is_reached_through_the_object_the_page_has(self, world):
        """`canvas.undo` is only wired while `canvas` is that same object the canvas
        module exposes. An attribute handler runs against the global scope, so the
        object has to be a global of it — and `typeof (canvas.undo)` alone would
        pass on a `window.canvas` that is a string."""
        answers, roots = world
        dotted = sorted(root for root in roots if '.' in root)
        assert len(dotted) >= 20, f'only {len(dotted)} dotted roots, so this sweep has thinned out'
        for root in dotted:
            # `headType` is `typeof <the object the attribute walks through>`.
            assert answers[root]['headType'] == 'object', (
                f'{root} is reached through a {root.split(".")[0]} that is {answers[root]["headType"]}'
            )

    def test_the_functions_behind_the_run_and_save_buttons_are_callable_now(self, world):
        """Not merely declared: the press has to reach code. `workflow.execute` is
        the button the whole tool exists for, and it is a method on an object the
        page reaches through an attribute, so it is the shape most likely to rot."""
        answers, _roots = world
        for root in ('workflow.execute', 'workflow.save', 'canvas.undo', 'dataPreview.nextPage'):
            assert answers[root]['type'] == 'function', f'{root} -> {answers[root]}'
