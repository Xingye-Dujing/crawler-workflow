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

#: The suite's no-assert count, pinned at zero: a case that asserts nothing (anywhere) changes this
#: number and fails the gate, so the author must either assert something or add a reason above and
#: move the number — the decision is reviewed instead of inherited. The mapping above is empty today
#: because every such case was rewritten to assert its claim; a new exception belongs there WITH a
#: reason, and the total grows by exactly that many.
NO_ASSERT_ALLOWED: dict[str, str] = {}
NO_ASSERT_TOTAL = 0


class Case:
    def __init__(self, path: Path, name: str, node, decorators: list[str], doc: str):
        self.path = path
        self.name = name
        self.node = node
        self.decorators = decorators
        self.doc = doc

    @property
    def asserts(self) -> bool:
        """A test proves something when it asserts, expects an exception, or calls an
        ``assert_*`` helper (``pd.testing.assert_frame_equal``, ``_assert_real_rows``)."""
        for child in ast.walk(self.node):
            if isinstance(child, ast.Assert):
                return True
            if isinstance(child, ast.Raise) and child.exc is not None:
                text = ast.unparse(child.exc)
                if 'AssertionError' in text:
                    return True
            if isinstance(child, ast.With):
                for item in child.items:
                    call = item.context_expr
                    text = ast.unparse(call.func) if isinstance(call, ast.Call) else ''
                    if text in ('pytest.raises', 'pytest.warns', 'pytest.deprecated_call'):
                        return True
            if isinstance(child, ast.Call) and _assert_call(child):
                return True
        return False

    @property
    def skip(self) -> str:
        marks = [item for item in self.decorators if re.search(r'pytest\.mark\.skip(if)?\b', item)]
        return '; '.join(marks)

    @property
    def xfail(self) -> bool:
        return any('xfail' in item for item in self.decorators)


def _assert_call(node: ast.Call) -> bool:
    """Whether this call is an assertion: ``assert_*``/``assert*_equal`` or ``pytest.fail``."""
    func = node.func
    name = (func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')).lstrip('_')
    if name.startswith('assert'):
        return True
    return name == 'fail' and isinstance(func, ast.Attribute) and getattr(func.value, 'id', '') == 'pytest'


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
