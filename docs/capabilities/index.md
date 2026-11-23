# 能力目录（自动生成）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/` 的清单生成，请勿手改。
> 机器可读版本：`backend/capabilities_kernel/generated/catalog.json`。

## node

| id | 标题键 | 分组 | 文档 | 技能 | 契约测试 | digest |
|---|---|---|---|---|---|---|
| name | `nodeType.name` | meta | [docs/capabilities/nodes/name.md](../capabilities/nodes/name.md) | [技能](skills/nodes/name.md) | `tests/unit/capabilities/test_name_manifest.py` | `96a1b3525068` |
| source | `nodeType.source` | data | [docs/capabilities/nodes/source.md](../capabilities/nodes/source.md) | [技能](skills/nodes/source.md) | `tests/unit/capabilities/test_source_manifest.py` | `5ba1b35907fb` |
| upload | `nodeType.upload` | data | [docs/capabilities/nodes/upload.md](../capabilities/nodes/upload.md) | [技能](skills/nodes/upload.md) | `tests/unit/capabilities/test_upload_manifest.py` | `5afa5214398e` |
| resume | `nodeType.resume` | data | [docs/capabilities/nodes/resume.md](../capabilities/nodes/resume.md) | [技能](skills/nodes/resume.md) | `tests/unit/capabilities/test_resume_manifest.py` | `c7bb4e75b181` |
| comment | `nodeType.comment` | data | [docs/capabilities/nodes/comment.md](../capabilities/nodes/comment.md) | [技能](skills/nodes/comment.md) | `tests/unit/capabilities/test_comment_manifest.py` | `ccde31b5a472` |
| process | `nodeType.process` | process | [docs/capabilities/nodes/process.md](../capabilities/nodes/process.md) | [技能](skills/nodes/process.md) | `tests/unit/capabilities/test_process_manifest.py` | `fc2e6f89c41e` |
| python | `nodeType.python` | process | [docs/capabilities/nodes/python.md](../capabilities/nodes/python.md) | [技能](skills/nodes/python.md) | `tests/unit/capabilities/test_python_manifest.py` | `d83ae2671245` |
| analysis | `nodeType.analysis` | analysis | [docs/capabilities/nodes/analysis.md](../capabilities/nodes/analysis.md) | [技能](skills/nodes/analysis.md) | `tests/unit/capabilities/test_analysis_manifest.py` | `daff9c02c318` |
| tokenize | `nodeType.tokenize` | process | [docs/capabilities/nodes/tokenize.md](../capabilities/nodes/tokenize.md) | [技能](skills/nodes/tokenize.md) | `tests/unit/capabilities/test_tokenize_manifest.py` | `e599c14e8027` |
| biblio | `nodeType.biblio` | biblio | [docs/capabilities/nodes/biblio.md](../capabilities/nodes/biblio.md) | [技能](skills/nodes/biblio.md) | `tests/unit/capabilities/test_biblio_manifest.py` | `6a1f467932ea` |
| verify | `nodeType.verify` | process | [docs/capabilities/nodes/verify.md](../capabilities/nodes/verify.md) | [技能](skills/nodes/verify.md) | `tests/unit/capabilities/test_verify_manifest.py` | `1318897d6762` |
| fuse | `nodeType.fuse` | biblio | [docs/capabilities/nodes/fuse.md](../capabilities/nodes/fuse.md) | [技能](skills/nodes/fuse.md) | `tests/unit/capabilities/test_fuse_manifest.py` | `02493c3b2b5c` |
| accumulate | `nodeType.accumulate` | data | [docs/capabilities/nodes/accumulate.md](../capabilities/nodes/accumulate.md) | [技能](skills/nodes/accumulate.md) | `tests/unit/capabilities/test_accumulate_manifest.py` | `159c8c6764d6` |
| visualize | `nodeType.visualize` | visualize | [docs/capabilities/nodes/visualize.md](../capabilities/nodes/visualize.md) | [技能](skills/nodes/visualize.md) | `tests/unit/capabilities/test_visualize_manifest.py` | `44d61a0290e8` |
| compile | `nodeType.compile` | visualize | [docs/capabilities/nodes/compile.md](../capabilities/nodes/compile.md) | [技能](skills/nodes/compile.md) | `tests/unit/capabilities/test_compile_manifest.py` | `6258074515de` |
| output | `nodeType.output` | output | [docs/capabilities/nodes/output.md](../capabilities/nodes/output.md) | [技能](skills/nodes/output.md) | `tests/unit/capabilities/test_output_manifest.py` | `f8853869317d` |

## operator

| id | 标题键 | 分组 | 文档 | 技能 | 契约测试 | digest |
|---|---|---|---|---|---|---|
| drop_null | `op.drop_null` | clean | [docs/capabilities/operators/drop_null.md](../capabilities/operators/drop_null.md) | [技能](skills/operators/drop_null.md) | `tests/unit/capabilities/test_operator_manifests.py` | `33ad591b8c7d` |
| fill_null | `op.fill_null` | clean | [docs/capabilities/operators/fill_null.md](../capabilities/operators/fill_null.md) | [技能](skills/operators/fill_null.md) | `tests/unit/capabilities/test_operator_manifests.py` | `bf42193e91fc` |
| drop_duplicates | `op.drop_duplicates` | clean | [docs/capabilities/operators/drop_duplicates.md](../capabilities/operators/drop_duplicates.md) | [技能](skills/operators/drop_duplicates.md) | `tests/unit/capabilities/test_operator_manifests.py` | `a4073d9e59e0` |
| dedupe_similar | `op.dedupe_similar` | clean | [docs/capabilities/operators/dedupe_similar.md](../capabilities/operators/dedupe_similar.md) | [技能](skills/operators/dedupe_similar.md) | `tests/unit/capabilities/test_operator_manifests.py` | `5b94a936e6ac` |
| semantic_dedupe | `op.semantic_dedupe` | clean | [docs/capabilities/operators/semantic_dedupe.md](../capabilities/operators/semantic_dedupe.md) | [技能](skills/operators/semantic_dedupe.md) | `tests/unit/capabilities/test_operator_manifests.py` | `e21eb4799cae` |
| similar_to | `op.similar_to` | clean | [docs/capabilities/operators/similar_to.md](../capabilities/operators/similar_to.md) | [技能](skills/operators/similar_to.md) | `tests/unit/capabilities/test_operator_manifests.py` | `5378b5a137e2` |
| filter_rows | `op.filter_rows` | clean | [docs/capabilities/operators/filter_rows.md](../capabilities/operators/filter_rows.md) | [技能](skills/operators/filter_rows.md) | `tests/unit/capabilities/test_operator_manifests.py` | `66bd60e30e98` |
| select_columns | `op.select_columns` | clean | [docs/capabilities/operators/select_columns.md](../capabilities/operators/select_columns.md) | [技能](skills/operators/select_columns.md) | `tests/unit/capabilities/test_operator_manifests.py` | `0699d43f727f` |
| rename_columns | `op.rename_columns` | clean | [docs/capabilities/operators/rename_columns.md](../capabilities/operators/rename_columns.md) | [技能](skills/operators/rename_columns.md) | `tests/unit/capabilities/test_operator_manifests.py` | `4aecc0d250e8` |
| strip_whitespace | `op.strip_whitespace` | clean | [docs/capabilities/operators/strip_whitespace.md](../capabilities/operators/strip_whitespace.md) | [技能](skills/operators/strip_whitespace.md) | `tests/unit/capabilities/test_operator_manifests.py` | `6f04f7602aae` |
| convert_type | `op.convert_type` | clean | [docs/capabilities/operators/convert_type.md](../capabilities/operators/convert_type.md) | [技能](skills/operators/convert_type.md) | `tests/unit/capabilities/test_operator_manifests.py` | `df4dee455914` |
| sort_rows | `op.sort_rows` | clean | [docs/capabilities/operators/sort_rows.md](../capabilities/operators/sort_rows.md) | [技能](skills/operators/sort_rows.md) | `tests/unit/capabilities/test_operator_manifests.py` | `60cad9c6c8df` |
| sample_rows | `op.sample_rows` | clean | [docs/capabilities/operators/sample_rows.md](../capabilities/operators/sample_rows.md) | [技能](skills/operators/sample_rows.md) | `tests/unit/capabilities/test_operator_manifests.py` | `ee2fcb788228` |
| groupby_agg | `op.groupby_agg` | statistics | [docs/capabilities/operators/groupby_agg.md](../capabilities/operators/groupby_agg.md) | [技能](skills/operators/groupby_agg.md) | `tests/unit/capabilities/test_operator_manifests.py` | `47dc9b86dfc9` |
| join_tables | `op.join_tables` | join | [docs/capabilities/operators/join_tables.md](../capabilities/operators/join_tables.md) | [技能](skills/operators/join_tables.md) | `tests/unit/capabilities/test_operator_manifests.py` | `f3166099388d` |
| anti_join | `op.anti_join` | join | [docs/capabilities/operators/anti_join.md](../capabilities/operators/anti_join.md) | [技能](skills/operators/anti_join.md) | `tests/unit/capabilities/test_operator_manifests.py` | `b1f798949899` |
| column_calc | `op.column_calc` | clean | [docs/capabilities/operators/column_calc.md](../capabilities/operators/column_calc.md) | [技能](skills/operators/column_calc.md) | `tests/unit/capabilities/test_operator_manifests.py` | `5b54ca8dbfc8` |
| bin_column | `op.bin_column` | clean | [docs/capabilities/operators/bin_column.md](../capabilities/operators/bin_column.md) | [技能](skills/operators/bin_column.md) | `tests/unit/capabilities/test_operator_manifests.py` | `6632f9f07050` |
| extract_time | `op.extract_time` | time | [docs/capabilities/operators/extract_time.md](../capabilities/operators/extract_time.md) | [技能](skills/operators/extract_time.md) | `tests/unit/capabilities/test_operator_manifests.py` | `f764644233de` |
| bin_time | `op.bin_time` | time | [docs/capabilities/operators/bin_time.md](../capabilities/operators/bin_time.md) | [技能](skills/operators/bin_time.md) | `tests/unit/capabilities/test_operator_manifests.py` | `859206644c1f` |
| suggest_stages | `op.suggest_stages` | time | [docs/capabilities/operators/suggest_stages.md](../capabilities/operators/suggest_stages.md) | [技能](skills/operators/suggest_stages.md) | `tests/unit/capabilities/test_operator_manifests.py` | `73fb7c7e5c28` |
| topic_model | `op.topic_model` | topic | [docs/capabilities/operators/topic_model.md](../capabilities/operators/topic_model.md) | [技能](skills/operators/topic_model.md) | `tests/unit/capabilities/test_operator_manifests.py` | `94dcf300a69f` |
| topic_by_stage | `op.topic_by_stage` | topic | [docs/capabilities/operators/topic_by_stage.md](../capabilities/operators/topic_by_stage.md) | [技能](skills/operators/topic_by_stage.md) | `tests/unit/capabilities/test_operator_manifests.py` | `cdae59e1fc25` |
| topic_label | `op.topic_label` | topic | [docs/capabilities/operators/topic_label.md](../capabilities/operators/topic_label.md) | [技能](skills/operators/topic_label.md) | `tests/unit/capabilities/test_operator_manifests.py` | `408939354ae5` |
| cluster_label | `op.cluster_label` | topic | [docs/capabilities/operators/cluster_label.md](../capabilities/operators/cluster_label.md) | [技能](skills/operators/cluster_label.md) | `tests/unit/capabilities/test_operator_manifests.py` | `4f28e21f18b2` |
| cluster_review | `op.cluster_review` | biblio | [docs/capabilities/operators/cluster_review.md](../capabilities/operators/cluster_review.md) | [技能](skills/operators/cluster_review.md) | `tests/unit/capabilities/test_operator_manifests.py` | `995839a36a4d` |
| reply_graph | `op.reply_graph` | social | [docs/capabilities/operators/reply_graph.md](../capabilities/operators/reply_graph.md) | [技能](skills/operators/reply_graph.md) | `tests/unit/capabilities/test_operator_manifests.py` | `ca107995d738` |
| compare_platform | `op.compare_platform` | statistics | [docs/capabilities/operators/compare_platform.md](../capabilities/operators/compare_platform.md) | [技能](skills/operators/compare_platform.md) | `tests/unit/capabilities/test_operator_manifests.py` | `4fdf0c60b93e` |
| topic_map | `op.topic_map` | topic | [docs/capabilities/operators/topic_map.md](../capabilities/operators/topic_map.md) | [技能](skills/operators/topic_map.md) | `tests/unit/capabilities/test_operator_manifests.py` | `a6b80cce0527` |
| topic_salience | `op.topic_salience` | topic | [docs/capabilities/operators/topic_salience.md](../capabilities/operators/topic_salience.md) | [技能](skills/operators/topic_salience.md) | `tests/unit/capabilities/test_operator_manifests.py` | `acb3482c7356` |
| topic_timeline | `op.topic_timeline` | topic | [docs/capabilities/operators/topic_timeline.md](../capabilities/operators/topic_timeline.md) | [技能](skills/operators/topic_timeline.md) | `tests/unit/capabilities/test_operator_manifests.py` | `fdabdd4d9135` |
| topic_flow | `op.topic_flow` | topic | [docs/capabilities/operators/topic_flow.md](../capabilities/operators/topic_flow.md) | [技能](skills/operators/topic_flow.md) | `tests/unit/capabilities/test_operator_manifests.py` | `d33a69350a99` |
| topic_coherence | `op.topic_coherence` | topic | [docs/capabilities/operators/topic_coherence.md](../capabilities/operators/topic_coherence.md) | [技能](skills/operators/topic_coherence.md) | `tests/unit/capabilities/test_operator_manifests.py` | `25f55f27b2ca` |
| cooccur | `op.cooccur` | topic | [docs/capabilities/operators/cooccur.md](../capabilities/operators/cooccur.md) | [技能](skills/operators/cooccur.md) | `tests/unit/capabilities/test_operator_manifests.py` | `04a489e097a2` |
| sentiment_evolution | `op.sentiment_evolution` | time | [docs/capabilities/operators/sentiment_evolution.md](../capabilities/operators/sentiment_evolution.md) | [技能](skills/operators/sentiment_evolution.md) | `tests/unit/capabilities/test_operator_manifests.py` | `2538499f3b94` |
| forecast | `op.forecast` | time | [docs/capabilities/operators/forecast.md](../capabilities/operators/forecast.md) | [技能](skills/operators/forecast.md) | `tests/unit/capabilities/test_operator_manifests.py` | `42edd1977234` |
| alert | `op.alert` | time | [docs/capabilities/operators/alert.md](../capabilities/operators/alert.md) | [技能](skills/operators/alert.md) | `tests/unit/capabilities/test_operator_manifests.py` | `feb98169f594` |
