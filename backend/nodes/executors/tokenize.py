"""Tokenize node: segment a free-text column and emit word-frequency pairs.

Data always comes from the upstream connection — a file reaches it by sitting behind an Upload node,
not by being configured here. Every refusal RAISES rather than returning []: an empty list settles
the node DONE, so the run reads green and the one sentence that explained it carries no node name.
"""

import pandas as pd
from api.http import _safe_int
from runtime.state import add_log

from i18n import t
from nodes.context import NodeCall, columns_from_params, node_params
from services.charts.visualizer import VisualizationService

NODE_TYPE = 'tokenize'

#: What a tokenize node emits, per ``output_mode``. The table is the node's own contract: the
#: ``emit_columns`` below is its only reader — the lineage view asks this plugin rather
#: than keeping a second copy of the table.
OUTPUT_COLUMNS: dict[str, tuple[str, ...]] = {
    'word_freq': ('word', 'frequency'),
    'words_only': ('word',),
    'csv_line': ('words',),
}

#: The one column it reads from its input.
READ_PARAMS = ('text_column',)


def emit_columns(node: dict, _merged: list[str] | None) -> list[str]:
    """What this node emits, per ``output_mode`` — the table above is the whole answer."""
    mode = str(node_params(node).get('output_mode') or 'word_freq')
    return list(OUTPUT_COLUMNS.get(mode, ()))


def read_columns(node: dict) -> list[str]:
    return columns_from_params(node_params(node), READ_PARAMS)


def _tokenize_dataframe(df: pd.DataFrame, params: dict) -> pd.DataFrame | None:
    """Apply tokenization to a DataFrame and return the result, or None if the column is missing."""
    column = params.get('text_column', '')
    if column not in df.columns:
        return None
    output_mode = str(params.get('output_mode') or 'word_freq').strip()
    top_n = params.get('top_n', '')
    # One of the three shapes, refused by name otherwise: the last branch of this
    # function is 词频+次数, so an unrecognised mode used to produce that table and the
    # console then announced the name the caller had written — a log line describing a
    # shape the file does not have.
    if output_mode not in ('word_freq', 'words_only', 'csv_line'):
        raise ValueError(
            t(
                'analysis.bad_option',
                op='tokenize',
                param='output_mode',
                value=output_mode,
                allowed='word_freq, words_only, csv_line',
            )
        )
    kwargs = {}
    if output_mode == 'word_freq' and top_n:
        kwargs['top_n'] = _safe_int(top_n, 120, minimum=1)
    labels, values = VisualizationService.tokenize_frequency(df, column, **kwargs)
    if not labels:
        return pd.DataFrame()
    if output_mode == 'words_only':
        return pd.DataFrame([{'word': w} for w in labels])
    if output_mode == 'csv_line':
        return pd.DataFrame([{'words': ' '.join(labels)}])
    return pd.DataFrame([{'word': w, 'frequency': v} for w, v in zip(labels, values, strict=True)])


def execute_tokenize_node(node: dict, current_input: list):
    params = node.get('params', {})
    column = params.get('text_column', '')
    output_mode = params.get('output_mode', 'word_freq')
    if not column:
        raise ValueError(t('wf.tokenize_no_column'))
    if not current_input:
        raise ValueError(t('wf.tokenize_no_input'))
    df = pd.DataFrame(current_input)
    result_df = _tokenize_dataframe(df, params)
    if result_df is None:
        raise ValueError(t('wf.tokenize_no_col', col=column, cols=list(df.columns)))
    add_log(t('wf.tokenize_done', mode=output_mode, col=column, n=len(result_df)))
    return result_df.to_dict('records')


def run(node: dict, call: NodeCall) -> list:
    return execute_tokenize_node(node, call.current_input)
