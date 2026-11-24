# 能力 × 测试矩阵（自动生成）

> 由 `tools/gen_capability_matrix.py` 从能力清单生成，请勿手改。
> “契约用例”是清单第八段声明的文件；“专属用例”指该能力自己目录下以它命名的测试文件。
> 这里**不**从测试文本里猜覆盖率——`node.name` 会命中 Python 属性访问，那样的数字只会让人忽略这一页。

- 能力：**93**（node / operator / chart / platform）
- 有专属测试文件：**21**
- 只有声明契约用例（由共享门禁覆盖，没有以它命名的文件）：**72**

## 只有契约用例的能力

| 能力 | 契约用例 |
|---|---|
| `operator.drop_null` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.fill_null` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.drop_duplicates` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.dedupe_similar` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.semantic_dedupe` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.similar_to` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.filter_rows` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.select_columns` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.rename_columns` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.strip_whitespace` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.convert_type` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.sort_rows` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.sample_rows` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.groupby_agg` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.join_tables` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.anti_join` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.column_calc` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.bin_column` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.extract_time` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.bin_time` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.suggest_stages` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.topic_model` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.topic_by_stage` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.topic_label` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.cluster_label` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.cluster_review` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.reply_graph` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.compare_platform` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.topic_map` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.topic_salience` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.topic_timeline` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.topic_flow` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.topic_coherence` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.cooccur` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.sentiment_evolution` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.forecast` | `tests/unit/capabilities/test_operator_manifests.py` |
| `operator.alert` | `tests/unit/capabilities/test_operator_manifests.py` |
| `chart.bar` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.line` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.dual_line` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.stack_pct` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.topic_map` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.topic_terms` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.pie` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.scatter` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.histogram` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.box` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.heatmap` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.model_agreement` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.sankey` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.network` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.knowledge_graph` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.cluster_timeline` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.burst` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.timezone` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.circular` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.landscape` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.biblio_heatmap` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.graph3d` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.variation` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.dual_map` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.geo_map` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.sentiment_overlay` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.topic_overlay` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.concentric` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.wordcloud` | `tests/unit/capabilities/test_chart_manifests.py` |
| `chart.map` | `tests/unit/capabilities/test_chart_manifests.py` |
| `platform.xiaohongshu` | `tests/unit/capabilities/test_platform_manifests.py` |
| `platform.douyin` | `tests/unit/capabilities/test_platform_manifests.py` |
| `platform.cnki` | `tests/unit/capabilities/test_platform_manifests.py` |
| `platform.youtube` | `tests/unit/capabilities/test_platform_manifests.py` |
| `platform.twitter` | `tests/unit/capabilities/test_platform_manifests.py` |

## node

| 能力 | 契约用例 | 专属测试文件 |
|---|---|---|
| `name` | `tests/unit/capabilities/test_name_manifest.py` | `tests/unit/capabilities/test_name_manifest.py` |
| `source` | `tests/unit/capabilities/test_source_manifest.py` | `tests/unit/capabilities/test_source_manifest.py` |
| `upload` | `tests/unit/capabilities/test_upload_manifest.py` | `tests/unit/capabilities/test_upload_manifest.py` |
| `resume` | `tests/unit/capabilities/test_resume_manifest.py` | `tests/unit/capabilities/test_resume_manifest.py` |
| `comment` | `tests/unit/capabilities/test_comment_manifest.py` | `tests/unit/capabilities/test_comment_manifest.py` |
| `process` | `tests/unit/capabilities/test_process_manifest.py` | `tests/unit/capabilities/test_process_manifest.py` |
| `python` | `tests/unit/capabilities/test_python_manifest.py` | `tests/unit/capabilities/test_python_manifest.py` |
| `analysis` | `tests/unit/capabilities/test_analysis_manifest.py` | `tests/unit/capabilities/test_analysis_manifest.py` |
| `tokenize` | `tests/unit/capabilities/test_tokenize_manifest.py` | `tests/unit/capabilities/test_tokenize_manifest.py` |
| `biblio` | `tests/unit/capabilities/test_biblio_manifest.py` | `tests/unit/capabilities/test_biblio_manifest.py` |
| `verify` | `tests/unit/capabilities/test_verify_manifest.py` | `tests/unit/capabilities/test_verify_manifest.py` |
| `fuse` | `tests/unit/capabilities/test_fuse_manifest.py` | `tests/unit/capabilities/test_fuse_manifest.py` |
| `accumulate` | `tests/unit/capabilities/test_accumulate_manifest.py` | `tests/unit/capabilities/test_accumulate_manifest.py` |
| `visualize` | `tests/unit/capabilities/test_visualize_manifest.py` | `tests/unit/capabilities/test_visualize_manifest.py` |
| `compile` | `tests/unit/capabilities/test_compile_manifest.py` | `tests/unit/capabilities/test_compile_manifest.py` |
| `output` | `tests/unit/capabilities/test_output_manifest.py` | `tests/unit/capabilities/test_output_manifest.py` |

## operator

| 能力 | 契约用例 | 专属测试文件 |
|---|---|---|
| `drop_null` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `fill_null` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `drop_duplicates` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `dedupe_similar` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `semantic_dedupe` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `similar_to` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `filter_rows` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `select_columns` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `rename_columns` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `strip_whitespace` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `convert_type` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `sort_rows` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `sample_rows` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `groupby_agg` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `join_tables` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `anti_join` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `column_calc` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `bin_column` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `extract_time` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `bin_time` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `suggest_stages` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `topic_model` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `topic_by_stage` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `topic_label` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `cluster_label` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `cluster_review` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `reply_graph` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `compare_platform` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `topic_map` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `topic_salience` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `topic_timeline` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `topic_flow` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `topic_coherence` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `cooccur` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `sentiment_evolution` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `forecast` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |
| `alert` | `tests/unit/capabilities/test_operator_manifests.py` | **—** |

## chart

| 能力 | 契约用例 | 专属测试文件 |
|---|---|---|
| `bar` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `line` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `dual_line` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `stack_pct` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `topic_map` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `topic_terms` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `pie` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `scatter` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `histogram` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `box` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `heatmap` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `model_agreement` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `sankey` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `network` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `knowledge_graph` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `cluster_timeline` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `burst` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `timezone` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `circular` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `landscape` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `biblio_heatmap` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `graph3d` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `variation` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `dual_map` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `geo_map` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `sentiment_overlay` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `topic_overlay` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `concentric` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `wordcloud` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |
| `map` | `tests/unit/capabilities/test_chart_manifests.py` | **—** |

## platform

| 能力 | 契约用例 | 专属测试文件 |
|---|---|---|
| `zhihu` | `tests/unit/capabilities/test_platform_manifests.py` | `tests/unit/crawlers/test_zhihu_resume_hole.py` |
| `weibo` | `tests/unit/capabilities/test_platform_manifests.py` | `tests/unit/crawlers/test_weibo_search_cursor.py` |
| `xiaohongshu` | `tests/unit/capabilities/test_platform_manifests.py` | **—** |
| `wechat` | `tests/unit/capabilities/test_platform_manifests.py` | `tests/unit/crawlers/test_wechat_diagnose.py`<br>`tests/unit/crawlers/test_wechat_search_cursor.py` |
| `bilibili` | `tests/unit/capabilities/test_platform_manifests.py` | `tests/unit/crawlers/test_bilibili_watermark.py` |
| `douyin` | `tests/unit/capabilities/test_platform_manifests.py` | **—** |
| `hongguo` | `tests/unit/capabilities/test_platform_manifests.py` | `tests/unit/crawlers/test_hongguo_comments.py`<br>`tests/unit/crawlers/test_hongguo_crawler.py`<br>`tests/unit/crawlers/test_hongguo_harvest.py` |
| `cnki` | `tests/unit/capabilities/test_platform_manifests.py` | **—** |
| `youtube` | `tests/unit/capabilities/test_platform_manifests.py` | **—** |
| `twitter` | `tests/unit/capabilities/test_platform_manifests.py` | **—** |
