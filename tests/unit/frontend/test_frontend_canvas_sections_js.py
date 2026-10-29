"""The canvas object is one global made of five files — pin the shape of that arrangement.

``canvas.js`` used to be a single 3,487-line object literal. On 2026-10-29 four thematic sections
were cut out of it, and the only way a later script can add methods to a top-level ``const`` object
is ``Object.assign(canvas, { … })``. That mechanism has two silent failure modes this module closes:

· a section that stops being a member block (renamed target, lost wrapper) adds **nothing** to the
  object, and every caller of those members dies at first use;
· a member declared in two sections is not an error in JS — the later ``Object.assign`` silently
  replaces the earlier one, which is the same accident as a duplicate key inside one literal, spread
  over two files where no side-by-side diff would show it.

Each section is therefore loaded against a bare object in its own context (so it cannot borrow a
member from another file), and the surfaces are compared with the whole family's. Driven only when
node is on PATH, like every other frontend case.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from node_runner import run_node
from static_assets import INDEX, JS_DIR, page_js

pytestmark = [pytest.mark.unit, pytest.mark.skipif(shutil.which('node') is None, reason='node not on PATH')]

REPO = Path(__file__).resolve().parents[3]
OWNER = 'canvas.js'
SECTIONS = ('canvas-view.js', 'canvas-snapshot.js', 'canvas-visuals.js', 'canvas-auto-layout.js')
FAMILY = (OWNER,) + SECTIONS

_OPENER = 'Object.assign(canvas, {'


class TestTheCanvasIsOneObjectAcrossFiveFiles:
    def test_only_the_owner_binds_canvas_on_the_workbench(self):
        """The workbench binds ``canvas`` exactly once and every other module mutates that binding.

        A second ``const canvas`` is a redeclaration in the shared global lexical scope, which kills
        every script after it; a ``var``/``window.canvas`` re-assignment swaps the object the panels
        already hold references to. The studio page owns its own ``canvas`` inside its own IIFE and is
        out of scope because that document never loads these modules — so the question is asked of the
        page that does, not of the directory.
        """
        bound = []
        for path in page_js(INDEX):
            text = path.read_text(encoding='utf-8')
            if re.search(r'^\s*(?:const|var|let)\s+canvas\s*=', text, re.M):
                bound.append(path.name)
        assert bound == [OWNER], f'workbench modules that bind `canvas`: {bound}'

    def test_every_section_file_keeps_the_member_block_shape(self):
        """One opener, one closer, nothing after it: the form IS the contract.

        A section that grew a second ``Object.assign`` block would silently replace the members of
        its own first one, so the file is read as a whole rather than checked for the opener only.
        """
        problems = []
        for name in SECTIONS:
            lines = (JS_DIR / name).read_text(encoding='utf-8').split('\n')
            opens = [index for index, line in enumerate(lines) if line == _OPENER]
            if len(opens) != 1:
                problems.append(f'{name} does not hold exactly one `{_OPENER}` statement line')
                continue
            tail = [line for line in lines[opens[0] + 1 :] if line.strip()]
            if tail[-1] != '});':
                problems.append(f'{name} does not close its assign block last: {tail[-3:]}')
        assert problems == [], '\n'.join(problems)

    def test_the_sections_add_members_with_no_overlap(self, tmp_path):
        """No member is declared twice, and the family's surface is exactly the owner's plus theirs."""
        driver = tmp_path / 'driver.mjs'
        dom = (REPO / 'tests' / 'frontend' / 'harness_dom.mjs').as_posix()
        files = [str((JS_DIR / name).as_posix()) for name in FAMILY]
        driver.write_text(
            'import vm from "node:vm";\n'
            'import { readFileSync } from "node:fs";\n'
            'import { pathToFileURL } from "node:url";\n'
            f'const {{ baseSandbox, fixWindow }} = await import(pathToFileURL({dom!r}).href);\n'
            f'const files = {json.dumps(files)};\n'
            'const world = () => {\n'
            '    const sandbox = { ...baseSandbox(), console: { log() {}, warn() {}, error() {} } };\n'
            '    vm.createContext(sandbox);\n'
            '    fixWindow(vm, sandbox);\n'
            '    return sandbox;\n'
            '};\n'
            'const perFile = {};\n'
            'for (const file of files) {\n'
            '    const sandbox = world();\n'
            '    const src = readFileSync(file, "utf8");\n'
            '    if (file.endsWith("canvas.js")) {\n'
            '        vm.runInContext(src + "\\n;globalThis.__c = canvas;", sandbox);\n'
            '    } else {\n'
            "        /* a bare object: a section must contribute its own members and no one else's */\n"
            '        vm.runInContext("var canvas = {};\\n" + src + "\\n;globalThis.__c = canvas;", sandbox);\n'
            '    }\n'
            '    perFile[file.split("/").pop()] = Object.keys(sandbox.__c);\n'
            '}\n'
            'const family = world();\n'
            'for (const file of files) vm.runInContext(readFileSync(file, "utf8"), family, { filename: file });\n'
            'vm.runInContext("globalThis.__c = canvas;", family);\n'
            'process.stdout.write(JSON.stringify({ perFile, family: Object.keys(family.__c) }));\n',
            encoding='utf-8',
        )
        answer = run_node(str(driver))
        assert answer.returncode == 0, answer.stderr[-800:]
        facts = json.loads(answer.stdout)
        per_file = facts['perFile']
        surface = set(facts['family'])
        assert set(per_file) == set(FAMILY), sorted(per_file)
        declared = {}
        for name, keys in per_file.items():
            for key in keys:
                assert key not in declared, f'{key} is declared by both {declared[key]} and {name}'
                declared[key] = name
        assert declared.keys() == surface, (
            f'only on the family: {sorted(surface - set(declared))}; only in a file: {sorted(set(declared) - surface)}'
        )
        assert len(surface) >= 150, f'the canvas surface shrank to {len(surface)} members'
