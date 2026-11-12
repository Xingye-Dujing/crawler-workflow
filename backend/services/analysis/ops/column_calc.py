"""The ``column_calc`` step, one module of the analysis op registry (see ops/__init__.py)."""

import ast
import re

import pandas as pd

from i18n import t
from services.analysis.kernels import UnknownOperationError

#: Operators an expression may use. Attribute access, calls, subscripts, lambdas and the
#: ``@`` variable syntax are refused: they are not arithmetic, and ``DataFrame.eval`` runs
#: the expression inside this process.
_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_UNARY_OPS = (ast.UAdd, ast.USub)

#: A long or deeply nested expression is a denial-of-service knob, not a formula.
_MAX_LENGTH = 500
_MAX_NODES = 200
_MAX_EXPONENT = 64

#: pandas writes a column whose name is not a Python identifier between backticks. The
#: whitelist parses that form too, replacing each span with a plain placeholder.
_BACKTICKED = re.compile(r'`[^`]*`')


def _check_expression(expr: str) -> None:
    """Refuse anything that is not column arithmetic, BEFORE it reaches ``DataFrame.eval``.

    The panel offered ``列计算`` as "a formula"; handing the string to ``eval`` also offered
    the server's own objects (``@name``), attribute chains and calls. A formula needs names,
    numbers and ``+ - * / // % **`` with parentheses, so that is the whole grammar.
    """
    if len(expr) > _MAX_LENGTH:
        raise ValueError(t('analysis.calc_rejected'))
    index = 0

    def _placeholder(_match):
        nonlocal index
        index += 1
        return f'column_{index}'

    try:
        tree = ast.parse(_BACKTICKED.sub(_placeholder, expr), mode='eval')
    except SyntaxError as e:
        raise ValueError(t('analysis.calc_rejected')) from e
    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_NODES:
        raise ValueError(t('analysis.calc_rejected'))
    for node in nodes:
        if isinstance(
            node,
            (
                ast.Expression,
                ast.Load,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.FloorDiv,
                ast.Mod,
                ast.Pow,
                ast.UAdd,
                ast.USub,
            ),
        ):
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, _BIN_OPS):
            if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
                power = node.right.value
                if isinstance(power, (int, float)) and abs(power) > _MAX_EXPONENT:
                    raise ValueError(t('analysis.calc_rejected'))
            continue
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _UNARY_OPS):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool) or abs(node.value) > 1e15:
                raise ValueError(t('analysis.calc_rejected'))
            continue
        if isinstance(node, ast.Name) and not node.id.startswith('__'):
            continue
        raise ValueError(t('analysis.calc_rejected'))


def column_calc(df: pd.DataFrame, new_col: str, expr: str) -> pd.DataFrame:
    """Add a computed column, or refuse with the expression that could not run.

    This used to log a warning and hand the table back UNCHANGED, which is the one
    outcome this project forbids everywhere else: the node settled DONE, the column the
    user named was never created, and the only trace was a line in ``logs/``. A
    mistyped column name then surfaced two nodes later as a chart with nothing in it —
    on a run that had already paid for its crawl.

    The column name inside an expression is the reason this could not simply be added
    to :data:`STEP_PARAMS`: no table of column names can validate a formula, so the
    check has to be the evaluation itself. Which means the refusal has to BE the
    evaluation's failure, carrying the expression the user typed.
    """
    if not new_col or not expr:
        return df
    work = df.copy()
    try:
        _check_expression(expr)
        work[new_col] = work.eval(expr)
    except Exception as e:
        raise UnknownOperationError(t('analysis.calc_failed', col=new_col, expr=expr, err=e)) from e
    return work
