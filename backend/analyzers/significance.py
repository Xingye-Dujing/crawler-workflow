import logging

import numpy as np
import pandas as pd
from scipy import stats

from i18n import t

logger = logging.getLogger(__name__)


class SignificanceAnalyzer:
    """Compare one numeric column across the groups of one categorical column.

    Four tests, paired parametric / non-parametric by the number of groups:

      - ``ttest``: **Welch's** t-test — exactly two groups. Welch (not Student) because
        the two samples' variances are not assumed equal; for a sentiment score split by
        phase that assumption is exactly what fails. The statistic is ``t``.
      - ``anova``: one-way ANOVA — two or more groups. Statistic ``F``.
      - ``mannwhitney``: Mann-Whitney U — exactly two groups, the rank-based partner of
        the t-test. Statistic ``U``.
      - ``kruskal``: Kruskal-Wallis H — two or more groups, the partner of ANOVA.
        Statistic ``H``.

    p-values come from the real scipy distribution CDFs, never a numpy approximation, so
    a column labelled "p_value" is the honest number. A comparison that cannot be made is
    refused BY NAME rather than answered with an empty table — an empty table would settle
    the node DONE and hand downstream nodes a silently-absent answer.
    """

    #: The result table's columns. This name set is a downstream chart/preview input
    #: contract, so it is stated once and reused for the returned row.
    OUTPUT_COLUMNS = (
        'method',
        'group_column',
        'value_column',
        'statistic',
        'p_value',
        'n_groups',
        'group_sizes',
        'significant_005',
    )

    #: The two-group tests and the two-or-more-group tests. Kept as data so the panel,
    #: the group-count refusal and the doc all read the same rule.
    TWO_GROUP_METHODS = ('ttest', 'mannwhitney')
    MULTI_GROUP_METHODS = ('anova', 'kruskal')

    @staticmethod
    def analyze_dataframe(
        df: pd.DataFrame,
        group_column: str = None,
        value_column: str = None,
        sig_method: str = 'ttest',
    ) -> pd.DataFrame:
        group_column = str(group_column or '').strip()
        value_column = str(value_column or '').strip()
        if not group_column:
            raise ValueError(t('sig.no_group_column'))
        if not value_column:
            raise ValueError(t('sig.no_value_column'))
        columns = [str(c) for c in df.columns]
        if group_column not in columns:
            raise ValueError(t('sig.group_column_missing', col=group_column))
        if value_column not in columns:
            raise ValueError(t('sig.value_column_missing', col=value_column))

        # Coerce the value column to numbers; a column that is entirely non-numeric is a
        # wrong-column pick, not "no difference", so it refuses by name rather than returning
        # an empty result the node would settle DONE over.
        values = pd.to_numeric(df[value_column], errors='coerce')
        labels = df[group_column]
        if values.isna().all():
            raise ValueError(t('sig.value_not_numeric', col=value_column))

        groups = _collect_groups(labels, values)
        n_groups = len(groups)
        if n_groups == 0:
            raise ValueError(t('sig.no_usable_rows', col=group_column))
        if sig_method in SignificanceAnalyzer.TWO_GROUP_METHODS and n_groups != 2:
            raise ValueError(t('sig.two_groups_only', method=sig_method, n=n_groups))
        if sig_method in SignificanceAnalyzer.MULTI_GROUP_METHODS and n_groups < 2:
            raise ValueError(t('sig.two_groups_required', method=sig_method, n=n_groups))

        ordered = sorted(groups, key=lambda label: str(label))
        arrays = [np.asarray(groups[label], dtype=float) for label in ordered]
        group_sizes = ', '.join(str(len(a)) for a in arrays)

        statistic, p_value = _run_test(sig_method, arrays)
        # A test that cannot be evaluated (a single observation, a zero-variance group) comes
        # back NaN from scipy; that is an unanswerable question, not a p of zero — refuse, so
        # the run says so instead of writing a blank that reads like "not significant".
        if not (np.isfinite(statistic) and np.isfinite(p_value)):
            raise ValueError(t('sig.degenerate', method=sig_method))

        row = {
            'method': sig_method,
            'group_column': group_column,
            'value_column': value_column,
            'statistic': round(float(statistic), 4),
            # p is kept as the full float, not rounded to a fixed place: a p of 1e-30 rounded
            # to 6 places prints 0.0, which claims a certainty the test never produced.
            'p_value': float(p_value),
            'n_groups': n_groups,
            'group_sizes': group_sizes,
            'significant_005': bool(p_value < 0.05),
        }
        total = sum(len(a) for a in arrays)
        logger.info(t('sig.done', method=sig_method, n_groups=n_groups, n=total, statistic=row['statistic'], p=p_value))
        return pd.DataFrame([row], columns=list(SignificanceAnalyzer.OUTPUT_COLUMNS))


def _collect_groups(labels, values) -> dict:
    """label -> list of numeric values, dropping a row whose group label is blank or whose
    value did not coerce to a number. Groups are keyed by the raw label so a person can read
    which bucket is which in ``group_sizes`` order."""
    groups: dict = {}
    for label, value in zip(list(labels), list(values), strict=False):
        if label is None or (isinstance(label, float) and np.isnan(label)):
            continue
        if str(label).strip() == '':
            continue
        if value is None or (isinstance(value, float) and np.isnan(value)):
            continue
        groups.setdefault(label, []).append(float(value))
    return groups


def _run_test(sig_method: str, arrays: list) -> tuple:
    """Dispatch the chosen scipy test and return ``(statistic, p_value)``. Every result is
    read from the result object's ``.statistic`` / ``.pvalue``, so a scipy release that
    reshapes the return type still yields the same two numbers by name."""
    if sig_method == 'ttest':
        result = stats.ttest_ind(arrays[0], arrays[1], equal_var=False)
    elif sig_method == 'anova':
        result = stats.f_oneway(*arrays)
    elif sig_method == 'mannwhitney':
        result = stats.mannwhitneyu(arrays[0], arrays[1], alternative='two-sided')
    elif sig_method == 'kruskal':
        result = stats.kruskal(*arrays)
    else:
        raise ValueError(t('sig.unknown_method', method=sig_method))
    return float(result.statistic), float(result.pvalue)
