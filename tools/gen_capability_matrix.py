"""The capability × test matrix: what is declared to prove what, in one page.

``docs/capabilities/index.md`` says what exists. This says what the repository commits to proving:
for every manifest, the contract tests it declares and whether a test FILE is named after it
(``test_<id>_manifest.py`` / ``test_<id>_*.py`` in its own area).

It deliberately does **not** guess coverage from string matches inside test files: ``node.name``
matches Python attribute access as readily as a capability, and a page whose numbers move with a
refactor of unrelated code teaches the reader to ignore it. A capability with only its declared
contract test is listed as such — a fact, not a failure.

Usage (from the repository root): ``python tools/gen_capability_matrix.py`` / ``--check``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'backend') not in sys.path:
    sys.path.insert(0, str(ROOT / 'backend'))
PAGE = ROOT / 'docs' / 'capabilities' / 'matrix.md'
TESTS = ROOT / 'tests'
KINDS = ('node', 'operator', 'chart', 'platform')

#: Where a kind's own capability tests live — the only place a file NAME counts as a dedicated case.
OWN_AREA = {
    'node': 'tests/unit/capabilities',
    'operator': 'tests/unit/capabilities',
    'chart': 'tests/unit/charts',
    'platform': 'tests/unit/crawlers',
}


def _test_files() -> list[str]:
    return [
        path.relative_to(ROOT).as_posix()
        for path in sorted(TESTS.rglob('test_*.py'))
        if '__pycache__' not in path.parts
    ]


def matrix() -> list[dict]:
    from capabilities_kernel import registry

    files = _test_files()
    rows = []
    for kind in KINDS:
        own = OWN_AREA[kind]
        for manifest in registry.manifests(kind):
            ident = manifest.identity.id
            dedicated = [
                path
                for path in files
                if path.startswith(own)
                and (
                    path.rsplit('/', 1)[-1] in (f'test_{ident}.py', f'test_{ident}_manifest.py')
                    or path.rsplit('/', 1)[-1].startswith(f'test_{ident}_')
                )
            ]
            rows.append(
                {
                    'kind': kind,
                    'id': ident,
                    'contracts': list(manifest.tests.contracts),
                    'dedicated': dedicated,
                }
            )
    return rows


def render() -> str:
    rows = matrix()
    dedicated = [row for row in rows if row['dedicated']]
    lines = [
        '# 能力 × 测试矩阵（自动生成）',
        '',
        '> 由 `tools/gen_capability_matrix.py` 从能力清单生成，请勿手改。',
        '> “契约用例”是清单第八段声明的文件；“专属用例”指该能力自己目录下以它命名的测试文件。',
        '> 这里**不**从测试文本里猜覆盖率——`node.name` 会命中 Python 属性访问，那样的数字只会让人忽略这一页。',
        '',
        f'- 能力：**{len(rows)}**（node / operator / chart / platform）',
        f'- 有专属测试文件：**{len(dedicated)}**',
        f'- 只有声明契约用例（由共享门禁覆盖，没有以它命名的文件）：**{len(rows) - len(dedicated)}**',
        '',
    ]
    only_contract = [row for row in rows if not row['dedicated']]
    if only_contract:
        lines += ['## 只有契约用例的能力', '', '| 能力 | 契约用例 |', '|---|---|']
        lines += [
            f'| `{row["kind"]}.{row["id"]}` | {"<br>".join(f"`{path}`" for path in row["contracts"]) or "—"} |'
            for row in only_contract
        ]
        lines.append('')
    for kind in KINDS:
        kind_rows = [row for row in rows if row['kind'] == kind]
        lines += [f'## {kind}', '', '| 能力 | 契约用例 | 专属测试文件 |', '|---|---|---|']
        for row in kind_rows:
            contracts = '<br>'.join(f'`{path}`' for path in row['contracts']) or '—'
            files = '<br>'.join(f'`{path}`' for path in row['dedicated']) or '**—**'
            lines.append(f'| `{row["id"]}` | {contracts} | {files} |')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def check() -> list[str]:
    if not PAGE.is_file():
        return [PAGE.relative_to(ROOT).as_posix() + ': missing']
    if PAGE.read_text(encoding='utf-8') != render():
        return [PAGE.relative_to(ROOT).as_posix() + ': stale']
    return []


def write() -> Path:
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(render(), encoding='utf-8', newline='\n')
    return PAGE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Render the capability × test matrix.')
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
