"""Mutation sweep: does this suite notice when the code is wrong?

A green suite answers "did anything fail?". Mutation testing answers the harder question: **would
it have failed if the behaviour changed?** One module at a time, the sweep breaks ONE decision — a
comparison's direction, an ``and``→``or``, a dropped ``not``, a number off by one next to a
comparison — and runs the test file that owns the module. A mutant those tests still pass is a
blind spot, named by the original file and line; a mutant they catch is the suite doing its job.

It is deliberately **not** part of pytest and **not** a gate. It is slow (one pytest run per
mutant), and a survivor is a reading rather than a failure: some mutants are equivalent (a reversed
comparison no real input can distinguish). `docs/testing/mutation.md` explains how to read a sweep
and what to fix in the test, not in the code.

    python tools/mutation_sweep.py                     # every declared target
    python tools/mutation_sweep.py --limit 6           # six mutants per target (a smoke)
    python tools/mutation_sweep.py --target backend/core/values.py=tests/unit/foundation/test_utils.py
    python tools/mutation_sweep.py --out reports/mutation.md --json reports/mutation.json

A mutant is applied to a **copy**: the sweep builds one throwaway tree (backend/, tests/, docs/,
pytest.ini, …), mutates a file there, runs pytest there, and deletes the tree at the end. That is
slower than editing in place and it is the only version whose crash cannot leave the checkout
carrying a mutant. The checkout is only ever read.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: ``(module, owning test file)`` — a module and the tests that are supposed to notice it breaking.
#: The pair is a claim, not a coverage measurement: a survivor means "the tests named here do not
#: check this decision", and a module whose behaviour is tested from five files belongs with the
#: file that owns the rule (see `docs/testing/mutation.md`).
DEFAULT_TARGETS: tuple[tuple[str, str], ...] = (
    ('backend/core/values.py', 'tests/unit/foundation/test_values.py'),
    ('backend/sessions/verdict.py', 'tests/unit/sessions/test_session_verdict.py'),
    ('backend/nodes/schema.py', 'tests/unit/analysis/test_node_schema.py'),
)

#: Copied into the throwaway tree. A target whose tests read something outside this set is not a
#: valid target — the sweep says so by failing its run, not by pretending the mutant was caught.
TREE = ('backend', 'tests', 'docs', 'tools', 'vendor', 'pytest.ini', 'requirements.txt')

#: The comparison mutation: negate the decision instead of nudging its boundary, because a
#: negation is what a hollow test misses (``>=`` and ``>`` differ on one input; ``==`` and ``!=``
#: differ on almost every input).
_FLIP_CMP: dict[type, type] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.LtE: ast.Gt,
    ast.Gt: ast.LtE,
    ast.GtE: ast.Lt,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}

_FLIP_BOOL = {ast.And: ast.Or, ast.Or: ast.And}


@dataclass(frozen=True)
class Mutation:
    """One behavioural change: what it is, and where in the original source it lives."""

    lineno: int
    column: int
    description: str

    def as_dict(self) -> dict:
        return {'line': self.lineno, 'column': self.column, 'mutation': self.description}


@dataclass
class TargetResult:
    module: str
    tests: str
    mutations: list[Mutation] = field(default_factory=list)
    survivors: list[Mutation] = field(default_factory=list)
    killed: int = 0
    timed_out: int = 0
    error: str = ''
    seconds: float = 0.0

    @property
    def total(self) -> int:
        return len(self.mutations)

    def as_dict(self) -> dict:
        return {
            'module': self.module,
            'tests': self.tests,
            'total': self.total,
            'killed': self.killed,
            'survived': len(self.survivors),
            'timed_out': self.timed_out,
            'error': self.error,
            'seconds': round(self.seconds, 1),
            'survivors': [item.as_dict() for item in self.survivors],
        }


# ─── What can be mutated ───


class _Collector(ast.NodeVisitor):
    """Every mutation site in one module, in a stable order.

    Only decisions that change BEHAVIOUR for ordinary input are collected: a comparison's
    negation, an ``and``↔``or``, a ``not`` that disappears, and a number that sits next to a
    comparison (``tolerance > 0`` → ``> 1``). Cosmetic edits — a docstring, a log line, a type
    annotation — are left alone, because a survivor there says nothing about the tests.
    """

    def __init__(self) -> None:
        self.sites: list[Mutation] = []

    def visit_Compare(self, node: ast.Compare) -> None:
        for op in node.ops:
            flipped = _FLIP_CMP.get(type(op))
            if flipped is not None:
                self.sites.append(
                    Mutation(node.lineno, node.col_offset, f'{type(op).__name__} -> {flipped.__name__}'),
                )
        for comparator in node.comparators:
            if (
                isinstance(comparator, ast.Constant)
                and isinstance(comparator.value, (int, float))
                and not isinstance(comparator.value, bool)
            ):
                self.sites.append(
                    Mutation(
                        comparator.lineno,
                        comparator.col_offset,
                        f'{comparator.value!r} -> {comparator.value + 1!r}',
                    ),
                )
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        flipped = _FLIP_BOOL.get(type(node.op))
        if flipped is not None:
            self.sites.append(Mutation(node.lineno, node.col_offset, f'{type(node.op).__name__} -> {flipped.__name__}'))
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if isinstance(node.op, ast.Not):
            self.sites.append(Mutation(node.lineno, node.col_offset, 'not -> (dropped)'))
        self.generic_visit(node)


class _Applier(ast.NodeTransformer):
    """Applies exactly one site, found by the same traversal the collector used.

    A ``NodeTransformer`` (not a ``NodeVisitor``) because dropping a ``not`` replaces a node with
    its operand, and only a transformer hands the replacement back to the parent.
    """

    def __init__(self, index: int) -> None:
        self.index = index
        self.applied = False
        self.sites: list[Mutation] = []

    def _claim(self) -> bool:
        """Whether the next site is the wanted one (and records it as applied)."""
        if self.applied or len(self.sites) != self.index:
            return False
        self.applied = True
        return True

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        for position, op in enumerate(node.ops):
            flipped = _FLIP_CMP.get(type(op))
            if flipped is not None:
                if self._claim():
                    node.ops[position] = flipped()
                    return node
                self.sites.append(Mutation(node.lineno, node.col_offset, ''))
        for position, comparator in enumerate(node.comparators):
            if (
                isinstance(comparator, ast.Constant)
                and isinstance(comparator.value, (int, float))
                and not isinstance(comparator.value, bool)
            ):
                if self._claim():
                    node.comparators[position] = ast.Constant(value=comparator.value + 1)
                    return node
                self.sites.append(Mutation(comparator.lineno, comparator.col_offset, ''))
        self.generic_visit(node)
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        flipped = _FLIP_BOOL.get(type(node.op))
        if flipped is not None:
            if self._claim():
                node.op = flipped()
                return node
            self.sites.append(Mutation(node.lineno, node.col_offset, ''))
        self.generic_visit(node)
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        if isinstance(node.op, ast.Not):
            if self._claim():
                return node.operand
            self.sites.append(Mutation(node.lineno, node.col_offset, ''))
        self.generic_visit(node)
        return node


def mutations(source: str) -> list[Mutation]:
    """Every mutation site in *source*, in the order :func:`mutate` applies them."""
    collector = _Collector()
    collector.visit(ast.parse(source))
    return collector.sites


def mutate(source: str, index: int) -> str:
    """*source* with mutation number *index* applied; everything else is untouched.

    The result is re-printed from the AST, so comments and blank lines inside the module are lost.
    That is fine for a mutant (it is compiled and run, never read) and it keeps the transform
    independent of the formatter.
    """
    tree = ast.parse(source)
    applier = _Applier(index)
    tree = applier.visit(tree)
    if not applier.applied:
        raise IndexError(f'mutation {index} is out of range (the module has {len(applier.sites)} sites)')
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + '\n'


# ─── Running one target ───


def _prepare_tree(root: Path, destination: Path) -> None:
    """One throwaway copy of the parts a target's tests read; the checkout is never touched."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in TREE:
        source = root / name
        if not source.exists():
            continue
        if source.is_dir():
            shutil.copytree(
                source,
                destination / name,
                ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '*.pyc'),
                dirs_exist_ok=True,
            )
        else:
            shutil.copy2(source, destination / name)


def _pytest_env() -> dict:
    """A child that cannot write bytecode into the copy and inherits no stray import path."""
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'PYTHONHOME'}}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def run_target(
    root: Path,
    module: str,
    tests: str,
    tree: Path,
    *,
    limit: int = 0,
    timeout: float = 180.0,
    python: str = sys.executable,
) -> TargetResult:
    """Mutate *module* one site at a time and run *tests* against each mutant."""
    result = TargetResult(module=module, tests=tests)
    started = time.monotonic()
    source_path = root / module
    test_path = root / tests
    if not source_path.is_file():
        result.error = f'no such module: {module}'
        return result
    if not test_path.exists():
        result.error = f'no such test: {tests}'
        return result
    source = source_path.read_text(encoding='utf-8')
    try:
        result.mutations = mutations(source)
    except SyntaxError as exc:
        result.error = f'{module} does not parse: {exc}'
        return result
    if limit:
        result.mutations = result.mutations[:limit]

    target_copy = tree / module
    command = [
        python,
        '-m',
        'pytest',
        '-x',
        '-q',
        '--no-header',
        '-p',
        'no:cacheprovider',
        tests,
    ]

    def _run() -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            cwd=tree,
            env=_pytest_env(),
            capture_output=True,
            timeout=timeout,
            text=True,
            check=False,
            encoding='utf-8',
            errors='replace',
        )

    # The unmutated run is the sweep's own premise. A test file that already fails would "kill"
    # every mutant and report a perfect suite that proves nothing — the exact inversion this tool
    # exists to catch. So a red baseline is a broken TARGET, named before any mutant runs.
    try:
        baseline = _run()
    except subprocess.TimeoutExpired:
        result.error = f'the target tests did not finish unmutated within {timeout:.0f}s'
        return result
    if baseline.returncode != 0:
        result.error = f'the target tests do not pass unmutated (pytest exited {baseline.returncode})'
        return result

    for index, mutation in enumerate(result.mutations):
        target_copy.write_text(mutate(source, index), encoding='utf-8')
        try:
            answer = _run()
        except subprocess.TimeoutExpired:
            result.timed_out += 1
            continue
        finally:
            target_copy.write_text(source, encoding='utf-8')
        if answer.returncode == 0:
            result.survivors.append(mutation)
        elif answer.returncode == 1:
            result.killed += 1
        else:
            # 2 = interrupted/collect error, 5 = no tests ran. A mutant that cannot run its own
            # tests proves nothing either way, so the sweep names the harness, not a survivor.
            result.error = f'pytest exited {answer.returncode} on {module}:{mutation.lineno}'
            break
    result.seconds = time.monotonic() - started
    return result


def sweep(
    root: Path = REPO,
    targets: tuple[tuple[str, str], ...] = DEFAULT_TARGETS,
    *,
    limit: int = 0,
    timeout: float = 180.0,
    python: str = sys.executable,
) -> list[TargetResult]:
    """Every target, inside ONE throwaway tree (a copy is 100 MB; copying per mutant is not)."""
    results: list[TargetResult] = []
    with tempfile.TemporaryDirectory(prefix='cixi_mutation_') as folder:
        tree = Path(folder)
        _prepare_tree(root, tree)
        for module, tests in targets:
            results.append(run_target(root, module, tests, tree, limit=limit, timeout=timeout, python=python))
    return results


# ─── The report ───


def render(results: list[TargetResult], moment: str = '') -> str:
    """The markdown page a sweep leaves behind: one row per target, then every survivor."""
    lines = [
        '# 变异扫描（mutation sweep）',
        '',
        '一次读数的快照，不是门禁。数字说明“把这一行改坏，点名的测试会不会红”；'
        '存活 = 那些测试没有检查这个决定。重跑：`python tools/mutation_sweep.py`。',
        '',
    ]
    if moment:
        lines.extend([f'日期：{moment}', ''])
    lines.extend(
        [
            '| 模块 | 测试 | 变异 | 捕获 | 存活 | 超时 | 用时 |',
            '|---|---|---|---|---|---|---|',
        ],
    )
    for item in results:
        if item.error:
            lines.append(f'| `{item.module}` | `{item.tests}` | - | - | - | - | 失败：{item.error} |')
            continue
        lines.append(
            f'| `{item.module}` | `{item.tests}` | {item.total} | {item.killed} | '
            f'{len(item.survivors)} | {item.timed_out} | {item.seconds:.0f}s |',
        )
    survivors = [(item, mutation) for item in results for mutation in item.survivors]
    lines.extend(['', '## 存活的变异', ''])
    if not survivors:
        lines.append('无：点名的测试捕获了每一个变异。')
    for item, mutation in survivors:
        lines.append(f'- `{item.module}:{mutation.lineno}` — {mutation.description}')
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run a bounded mutation sweep over declared targets.')
    parser.add_argument('--target', action='append', default=[], metavar='MODULE=TESTS')
    parser.add_argument('--limit', type=int, default=0, help='mutants per target (0 = all)')
    parser.add_argument('--timeout', type=float, default=180.0, help='seconds per mutant')
    parser.add_argument('--out', default='', help='write the markdown report here')
    parser.add_argument('--json', default='', help='write the machine-readable result here')
    parser.add_argument('--root', default=str(REPO), help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)

    targets = DEFAULT_TARGETS
    if arguments.target:
        targets = tuple(
            (entry.split('=', 1)[0], entry.split('=', 1)[1]) if '=' in entry else (entry, '')
            for entry in arguments.target
        )
        if any(not tests for _module, tests in targets):
            parser.error('--target takes MODULE=TESTS')
    results = sweep(Path(arguments.root), targets, limit=arguments.limit, timeout=arguments.timeout)
    page = render(results, moment=time.strftime('%Y-%m-%d'))
    print(page)
    if arguments.out:
        destination = Path(arguments.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(page, encoding='utf-8')
    if arguments.json:
        destination = Path(arguments.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps([item.as_dict() for item in results], ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
    # A survivor is a reading; a target that could not run is a broken sweep.
    return 1 if any(item.error for item in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
