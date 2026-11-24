"""What the test suite proves, as data: one inventory row per test file.

The suite is large and grew per defect, so "why does this case exist" is only in someone's memory.
This tool reads the tests with ``ast`` and reports, per file: how many cases it declares, which of
them assert nothing (a test that only calls a function is a smoke test only if it SAYS so), which
skip unconditionally, and which are expected failures. ``docs/testing/value-inventory.md`` is the
rendered answer and ``tests/unit/gates/test_test_inventory.py`` refuses a stale copy.

Usage (from the repository root): ``python tools/test_inventory.py`` / ``--check``.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'tests'
PAGE = ROOT / 'docs' / 'testing' / 'value-inventory.md'

#: A test that asserts nothing may still be a real test (a golden file, a harness-driven case, a
#: "this call must not raise" case), and the reason has to be written down here — otherwise
#: "no assert" is an accident, not a decision. The gate refuses any no-assert test not listed.
NO_ASSERT_ALLOWED = {
    'tests/api/test_nodes_execution.py': 'a null crawler is a no-op: the claim is "does not raise"',
    'tests/api/test_run_races.py': 'a settlement failure must stay readable: the claim is "returns, does not raise"',
    'tests/integration/test_ui_layout.py': 'the browser-measured claim lives in the assertion helper it calls',
    'tests/live_site/test_live_bilibili.py': 'live case: numbers derived from the crawl, asserted in a helper',
    'tests/live_site/test_live_x.py': 'live case: the shape claims are asserted in the shared row helper',
    'tests/unit/analysis/test_anomaly.py': 'determinism: two runs compared inside the test body',
    'tests/unit/analysis/test_clustering.py': 'non-mutation: the frame is compared to a copy',
    'tests/unit/analysis/test_correlation.py': 'non-mutation: the frame is compared to a copy',
    'tests/unit/analysis/test_keyword_analyzer.py': 'non-mutation: the frame is compared to a copy',
    'tests/unit/analysis/test_lexicon_store.py': 'a named refusal is asserted through pytest.raises in a helper',
    'tests/unit/analysis/test_significance.py': 'non-mutation: the frame is compared to a copy',
    'tests/unit/crawlers/test_browser_health.py': 'shutdown must be silent: the claim is "logs nothing"',
    'tests/unit/crawlers/test_browser_profiles.py': 'releasing an unheld profile must not raise',
    'tests/unit/crawlers/test_catbus_capability_dimension.py': 'JSON-readiness asserted through the encoder',
    'tests/unit/crawlers/test_platform_rules.py': 'the byte cut is compared to the re-joined original',
    'tests/unit/desktop/test_desktop_packaging.py': 'off-Windows must not attempt a dialog: the claim is "no call"',
    'tests/unit/desktop/test_native_window.py': 'the refusal path must not call startfile',
    'tests/unit/foundation/test_utils.py': 'round-trip: the reparsed table is compared to the original',
    'tests/unit/frontend/test_frontend_page_markup.py': 'the checks report through a problems list the test asserts',
    'tests/unit/gates/test_live_acceptance_record_shape.py': 'the record shape is compared to expected component names',
    'tests/unit/runs/test_run_postcheck.py': 'an unknown node type must not raise',
    'tests/unit/sessions/test_cookie_manager.py': 'deleting a missing login must not raise',
    'tests/unit/test_update_feed_signature.py': 'no key means unsigned, and the payload is compared in the test body',
    'tests/unit/tools/test_publish_gitee.py': 'an already-attached name is skipped: the claim is "no upload call"',
}

#: The suite's no-assert count, pinned. A new case that asserts nothing (anywhere, including a listed
#: file) changes this number and fails the gate, so the author must either assert something or add a
#: reason above and move the number — the decision is reviewed instead of inherited.
NO_ASSERT_TOTAL = 33


class Case:
    def __init__(self, path: Path, name: str, node, decorators: list[str], doc: str):
        self.path = path
        self.name = name
        self.node = node
        self.decorators = decorators
        self.doc = doc

    @property
    def asserts(self) -> bool:
        for child in ast.walk(self.node):
            if isinstance(child, ast.Assert):
                return True
            if isinstance(child, ast.With):
                for item in child.items:
                    call = item.context_expr
                    text = ast.unparse(call.func) if isinstance(call, ast.Call) else ''
                    if text in ('pytest.raises', 'pytest.warns', 'pytest.deprecated_call'):
                        return True
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in ('raises', 'warns')
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == 'pytest'
            ):
                return True
        return False

    @property
    def skip(self) -> str:
        marks = [item for item in self.decorators if re.search(r'pytest\.mark\.skip(if)?\b', item)]
        return '; '.join(marks)

    @property
    def xfail(self) -> bool:
        return any('xfail' in item for item in self.decorators)


def _decorators(node) -> list[str]:
    out = []
    for decorator in getattr(node, 'decorator_list', ()):
        try:
            out.append(ast.unparse(decorator))
        except Exception:  # a decorator ast.unparse cannot render is still a decorator
            out.append('<decorator>')
    return out


def _doc(node) -> str:
    text = ast.get_docstring(node) or ''
    return text.strip().splitlines()[0].strip() if text.strip() else ''


def _cases(path: Path) -> list[Case]:
    tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
    found: list[Case] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
            found.append(Case(path, node.name, node, _decorators(node), _doc(node)))
        elif isinstance(node, ast.ClassDef):
            class_marks = _decorators(node)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith('test_'):
                    found.append(
                        Case(path, f'{node.name}.{child.name}', child, class_marks + _decorators(child), _doc(child))
                    )
    return found


def inventory() -> dict:
    rows = []
    totals = {'files': 0, 'cases': 0, 'no_assert': 0, 'skips': 0, 'xfail': 0}
    for path in sorted(TESTS.rglob('test_*.py')):
        if '__pycache__' in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        cases = _cases(path)
        if not cases:
            continue
        no_assert = [case.name for case in cases if not case.asserts]
        skips = [f'{case.name}: {case.skip}' for case in cases if case.skip]
        xfails = [case.name for case in cases if case.xfail]
        totals['files'] += 1
        totals['cases'] += len(cases)
        totals['no_assert'] += len(no_assert)
        totals['skips'] += len(skips)
        totals['xfail'] += len(xfails)
        rows.append(
            {
                'file': relative,
                'cases': len(cases),
                'no_assert': no_assert,
                'skips': skips,
                'xfail': xfails,
            }
        )
    flagged = [
        {'file': row['file'], 'names': row['no_assert']}
        for row in rows
        if row['no_assert'] and row['file'] not in NO_ASSERT_ALLOWED
    ]
    return {'totals': totals, 'rows': rows, 'flagged_no_assert': flagged}


def render() -> str:
    data = inventory()
    totals = data['totals']
    lines = [
        '# 测试价值清单（自动生成）',
        '',
        '> 由 `tools/test_inventory.py` 用 `ast` 读出，请勿手改。`python tools/test_inventory.py --check` 比较字节；',
        '> `tests/unit/gates/test_test_inventory.py` 在 CI 里跑同一份检查，并拒绝“没有断言又没写理由”的用例。',
        '',
        f'- 文件：**{totals["files"]}**',
        f'- 用例（定义数，参数化会展开成更多次运行）：**{totals["cases"]}**',
        f'- 无断言的用例：**{totals["no_assert"]}**（每一条都必须在 `tools/test_inventory.py` 的豁免表里写明理由）',
        f'- 带 skip/skipif 标记的用例：**{totals["skips"]}**（环境型 skip 由 `CRAWLER_REQUIRE_*` 变成失败）',
        f'- xfail：**{totals["xfail"]}**',
        '',
        '## 无断言的用例',
        '',
    ]
    flagged = data['flagged_no_assert']
    if not flagged:
        lines.append('（无）')
    else:
        lines.append('| 文件 | 用例 |')
        lines.append('|---|---|')
        lines += [f'| `{row["file"]}` | {", ".join(row["names"])} |' for row in flagged]
    lines += ['', '## 逐文件', '', '| 文件 | 用例 | 无断言 | skip | xfail |', '|---|---|---|---|---|']
    for row in data['rows']:
        counts = f'{len(row["no_assert"])} | {len(row["skips"])} | {len(row["xfail"])}'
        lines.append(f'| `{row["file"]}` | {row["cases"]} | {counts} |')
    lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def check() -> list[str]:
    if not PAGE.is_file():
        return [f'{PAGE.relative_to(ROOT).as_posix()}: missing']
    if PAGE.read_text(encoding='utf-8') != render():
        return [f'{PAGE.relative_to(ROOT).as_posix()}: stale']
    return []


def write() -> Path:
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(render(), encoding='utf-8', newline='\n')
    return PAGE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Render the test value inventory.')
    parser.add_argument('--check', action='store_true', help='compare instead of write; exit 1 when stale')
    args = parser.parse_args(argv)
    if args.check:
        stale = check()
        for line in stale:
            print(line)
        return 1 if stale else 0
    print(f'wrote {write().relative_to(ROOT).as_posix()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
