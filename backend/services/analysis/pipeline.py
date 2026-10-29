import hashlib
import logging

import pandas as pd

from i18n import t
from services.analysis.contracts import (
    LLM_OPS,
    STEP_PARAMS,
    normalize_step_params,
    validate_step,
)
from services.analysis.kernels import (
    UnknownOperationError,
    _stable_seed,
    _to_datetime,
)
from services.analysis.ops import OPS
from services.analysis.topic_kernels import (
    COOCCUR_WORD_CAP,
    _mds_2d,
    _stage_order,
)

# Re-exported for the callers that name THIS module: the analysis plugin reads ``STEP_PARAMS``,
# ``nodes/executors/comment.py`` reads ``_to_datetime``, and the tests read the guards. Stage 9
# moved the bodies out; the entry points stay where they always were.
__all__ = [
    'COOCCUR_WORD_CAP',
    'DataAnalysisService',
    'LLM_OPS',
    'STEP_PARAMS',
    'UnknownOperationError',
    '_mds_2d',
    '_stable_seed',
    '_stage_order',
    '_to_datetime',
    'normalize_step_params',
    'validate_step',
]

logger = logging.getLogger(__name__)


class DataAnalysisService:
    """Stateless helpers for cleaning/transforming a DataFrame, plus a
    pipeline runner that chains several steps and reports what changed."""

    # ── The ops that live in ``services.analysis.ops`` (one module per op) ────
    #
    # Bound as real class attributes rather than by a ``setattr`` loop: the loop worked at run
    # time but left every caller invisible to static analysis (pylint read ``D.drop_null`` as
    # no-member), and a registry that the type checker cannot see is a registry half the repo
    # cannot ask about. These lines and ``ops/__init__.py`` are the only two places a moved op
    # is named; ``_operations()`` reads ``OPS`` so the registry stays the one table.
    drop_null = staticmethod(OPS['drop_null'])
    fill_null = staticmethod(OPS['fill_null'])
    drop_duplicates = staticmethod(OPS['drop_duplicates'])
    dedupe_similar = staticmethod(OPS['dedupe_similar'])
    filter_rows = staticmethod(OPS['filter_rows'])
    select_columns = staticmethod(OPS['select_columns'])
    rename_columns = staticmethod(OPS['rename_columns'])
    strip_whitespace = staticmethod(OPS['strip_whitespace'])
    convert_type = staticmethod(OPS['convert_type'])
    sort_rows = staticmethod(OPS['sort_rows'])
    sample_rows = staticmethod(OPS['sample_rows'])
    groupby_agg = staticmethod(OPS['groupby_agg'])
    join_tables = staticmethod(OPS['join_tables'])
    column_calc = staticmethod(OPS['column_calc'])
    bin_column = staticmethod(OPS['bin_column'])
    extract_time = staticmethod(OPS['extract_time'])
    bin_time = staticmethod(OPS['bin_time'])
    suggest_stages = staticmethod(OPS['suggest_stages'])
    topic_model = staticmethod(OPS['topic_model'])
    topic_by_stage = staticmethod(OPS['topic_by_stage'])
    topic_label = staticmethod(OPS['topic_label'])
    cluster_label = staticmethod(OPS['cluster_label'])
    cluster_review = staticmethod(OPS['cluster_review'])
    reply_graph = staticmethod(OPS['reply_graph'])
    compare_platform = staticmethod(OPS['compare_platform'])
    topic_map = staticmethod(OPS['topic_map'])
    topic_salience = staticmethod(OPS['topic_salience'])
    topic_timeline = staticmethod(OPS['topic_timeline'])
    topic_flow = staticmethod(OPS['topic_flow'])
    topic_coherence = staticmethod(OPS['topic_coherence'])
    cooccur = staticmethod(OPS['cooccur'])
    sentiment_evolution = staticmethod(OPS['sentiment_evolution'])
    forecast = staticmethod(OPS['forecast'])
    alert = staticmethod(OPS['alert'])

    # ── Individual, composable operations ───────────────────────

    @staticmethod
    def inspect(df: pd.DataFrame) -> dict:
        return {
            'rows': int(len(df)),
            'columns': list(df.columns),
            'dtypes': {c: str(t) for c, t in df.dtypes.items()},
            'null_counts': {c: int(n) for c, n in df.isna().sum().items()},
            'duplicate_rows': int(df.duplicated().sum()),
        }

    @staticmethod
    def _row_hashes(df: pd.DataFrame, cols: list) -> list:
        """A stable per-row fingerprint over the given columns. Falls back to a
        textual sha1 when a cell is unhashable (a column of lists/dicts), so the
        same rows always hash the same bytes and the diff never crashes on shape."""
        sub = df[cols]
        try:
            return [int(h) for h in pd.util.hash_pandas_object(sub, index=False).to_numpy()]
        except (TypeError, ValueError):
            return [
                hashlib.sha1(repr(row).encode('utf-8', 'replace')).hexdigest()
                for row in sub.astype(str).values.tolist()
            ]

    @staticmethod
    def diff(a_df: pd.DataFrame, b_df: pd.DataFrame, key: str | None = None, limit: int = 200) -> dict:
        """Row-level comparison of two tables, with NO guessing about identity.

        Rows are aligned by a per-row hash over the columns the two tables SHARE, so a
        renamed/added column is reported as a column difference rather than silently
        turning every row into "changed". ``added``/``removed`` are the honest multiset
        answer (``*_count`` carries duplicates; the emitted samples are de-duplicated and
        capped at ``limit``). ``changed`` is only produced when the caller NAMES a ``key``
        column that is unique in both — matching a whole row by an auto-picked column
        would choose data, which this codebase refuses to do.
        """
        from collections import Counter

        cols_a = list(a_df.columns)
        cols_b = list(b_df.columns)
        set_a, set_b = set(cols_a), set(cols_b)
        common = [c for c in cols_a if c in set_b]
        result = {
            'columns_a': cols_a,
            'columns_b': cols_b,
            'columns_added': [c for c in cols_b if c not in set_a],
            'columns_removed': [c for c in cols_a if c not in set_b],
            'columns_common': common,
            'row_count_a': int(len(a_df)),
            'row_count_b': int(len(b_df)),
            'row_delta': int(len(b_df)) - int(len(a_df)),
        }

        if not common:
            # Nothing shared to align on: every row of each side is, by definition,
            # unmatched. Report that rather than an empty diff that reads as "identical".
            result.update(
                {
                    'added': b_df.head(limit).to_dict('records'),
                    'removed': a_df.head(limit).to_dict('records'),
                    'added_count': int(len(b_df)),
                    'removed_count': int(len(a_df)),
                    'changed': [],
                    'changed_count': 0,
                    'key_used': None,
                    'truncated': bool(len(b_df) > limit or len(a_df) > limit),
                }
            )
            # A key was asked for but there is no shared column to hold it — name that
            # refusal instead of silently returning an empty changed set.
            if key is not None:
                result['key_error'] = t('api.diffKeyMissing', name=key)
            return result

        ha = DataAnalysisService._row_hashes(a_df, common)
        hb = DataAnalysisService._row_hashes(b_df, common)
        ca, cb = Counter(ha), Counter(hb)
        removed_counter = ca - cb
        added_counter = cb - ca

        # Representative sample per distinct hash, in table order, capped at limit.
        first_a = {}
        for idx, h in enumerate(ha):
            first_a.setdefault(h, idx)
        first_b = {}
        for idx, h in enumerate(hb):
            first_b.setdefault(h, idx)

        removed_hashes = sorted(removed_counter)
        added_hashes = sorted(added_counter)
        a_common = a_df[common]
        b_common = b_df[common]
        removed_rows = [a_common.iloc[first_a[h]].to_dict() for h in removed_hashes[:limit] if h in first_a]
        added_rows = [b_common.iloc[first_b[h]].to_dict() for h in added_hashes[:limit] if h in first_b]

        result.update(
            {
                'added': added_rows,
                'removed': removed_rows,
                'added_count': int(sum(added_counter.values())),
                'removed_count': int(sum(removed_counter.values())),
            }
        )

        result['changed'] = []
        result['changed_count'] = 0
        result['key_used'] = None
        if key is not None:
            if key not in common:
                result['key_error'] = t('api.diffKeyMissing', name=key)
            else:
                ka = a_df[key].tolist()
                kb = b_df[key].tolist()
                if len(set(ka)) != len(ka) or len(set(kb)) != len(kb):
                    result['key_error'] = t('api.diffKeyNotUnique', name=key)
                else:
                    # key -> (row index, hash) on each side; the index is used to emit the
                    # exact row for that key, never a first-match scan that a duplicate
                    # hash could misattribute.
                    result['key_used'] = key
                    a_key = {ka[i]: (i, ha[i]) for i in range(len(ka))}
                    b_key = {kb[i]: (i, hb[i]) for i in range(len(kb))}
                    changed = []
                    for k in set(a_key) & set(b_key):
                        ai, ah = a_key[k]
                        bi, bh = b_key[k]
                        if ah != bh:
                            changed.append(
                                {'key': k, 'a': a_common.iloc[ai].to_dict(), 'b': b_common.iloc[bi].to_dict()}
                            )
                    result['changed'] = changed[:limit]
                    result['changed_count'] = len(changed)

        result['truncated'] = bool(
            len(added_hashes) > limit or len(removed_hashes) > limit or result['changed_count'] > limit
        )
        return result

    # ── Operation registry + pipeline runner ────────────────────

    @classmethod
    def _operations(cls) -> dict:
        # Every analysis op now lives in ``services.analysis.ops`` (one module per op); ops/__init__
        # is the ONE table. This method stays because callers and tests ask the service.
        return dict(OPS)

    @classmethod
    def run_pipeline(cls, df: pd.DataFrame, steps: list, llm=None, cancel=None, store=None) -> tuple:
        """Run the steps in order and report what each one did to the table.

        ``llm``, ``cancel`` and ``store`` reach only the steps in :data:`LLM_OPS`, and only as call
        arguments: the report echoes every step's ``params`` into the console and the run
        record, so a client object in there would be a live object written into a durable
        ledger — and the checkpoint/reuse machinery keys on those params.
        """
        operations = cls._operations()
        report = []
        current = df
        for step in steps or []:
            op = step.get('op')
            params = normalize_step_params(op, step.get('params', {}))
            func = operations.get(op)
            if func is None:
                raise UnknownOperationError(f'Unknown analysis operation: {op}')
            validate_step(current, op, params)
            before = len(current)
            # Only the steps in LLM_OPS are handed the run's client, Stop flag and answer store;
            # every other step is deterministic and gets the table alone.
            injected = {'llm': llm, 'cancel': cancel, 'store': store} if op in LLM_OPS else {}
            current = func(current, **injected, **params)
            report.append(
                {
                    'op': op,
                    'params': params,
                    'rows_before': before,
                    'rows_after': len(current),
                    'rows_removed': before - len(current),
                }
            )
        return current, report
