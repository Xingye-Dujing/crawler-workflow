"""The analysis operations, one module per op, registered in ONE table.

``pipeline.DataAnalysisService`` attaches each function as a static method, so
``run_pipeline`` (and every caller that names an op directly) keeps the same names.
"""

from services.analysis.ops.alert import alert
from services.analysis.ops.bin_column import bin_column
from services.analysis.ops.bin_time import bin_time
from services.analysis.ops.cluster_label import cluster_label
from services.analysis.ops.cluster_review import cluster_review
from services.analysis.ops.column_calc import column_calc
from services.analysis.ops.compare_platform import compare_platform
from services.analysis.ops.convert_type import convert_type
from services.analysis.ops.cooccur import cooccur
from services.analysis.ops.dedupe_similar import dedupe_similar
from services.analysis.ops.drop_duplicates import drop_duplicates
from services.analysis.ops.drop_null import drop_null
from services.analysis.ops.extract_time import extract_time
from services.analysis.ops.fill_null import fill_null
from services.analysis.ops.filter_rows import filter_rows
from services.analysis.ops.forecast import forecast
from services.analysis.ops.groupby_agg import groupby_agg
from services.analysis.ops.join_tables import join_tables
from services.analysis.ops.rename_columns import rename_columns
from services.analysis.ops.reply_graph import reply_graph
from services.analysis.ops.sample_rows import sample_rows
from services.analysis.ops.select_columns import select_columns
from services.analysis.ops.sentiment_evolution import sentiment_evolution
from services.analysis.ops.sort_rows import sort_rows
from services.analysis.ops.strip_whitespace import strip_whitespace
from services.analysis.ops.suggest_stages import suggest_stages
from services.analysis.ops.topic_by_stage import topic_by_stage
from services.analysis.ops.topic_coherence import topic_coherence
from services.analysis.ops.topic_flow import topic_flow
from services.analysis.ops.topic_label import topic_label
from services.analysis.ops.topic_map import topic_map
from services.analysis.ops.topic_model import topic_model
from services.analysis.ops.topic_salience import topic_salience
from services.analysis.ops.topic_timeline import topic_timeline

OPS = {
    'drop_null': drop_null,
    'fill_null': fill_null,
    'drop_duplicates': drop_duplicates,
    'dedupe_similar': dedupe_similar,
    'filter_rows': filter_rows,
    'select_columns': select_columns,
    'rename_columns': rename_columns,
    'strip_whitespace': strip_whitespace,
    'convert_type': convert_type,
    'sort_rows': sort_rows,
    'sample_rows': sample_rows,
    'groupby_agg': groupby_agg,
    'join_tables': join_tables,
    'column_calc': column_calc,
    'bin_column': bin_column,
    'extract_time': extract_time,
    'bin_time': bin_time,
    'suggest_stages': suggest_stages,
    'topic_model': topic_model,
    'topic_by_stage': topic_by_stage,
    'topic_label': topic_label,
    'cluster_label': cluster_label,
    'cluster_review': cluster_review,
    'reply_graph': reply_graph,
    'compare_platform': compare_platform,
    'topic_map': topic_map,
    'topic_salience': topic_salience,
    'topic_timeline': topic_timeline,
    'topic_flow': topic_flow,
    'topic_coherence': topic_coherence,
    'cooccur': cooccur,
    'sentiment_evolution': sentiment_evolution,
    'forecast': forecast,
    'alert': alert,
}
