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
| drop_null | `op.drop_null` | clean | [docs/capabilities/operators/drop_null.md](../capabilities/operators/drop_null.md) | [技能](skills/operators/drop_null.md) | `tests/unit/capabilities/test_operator_manifests.py` | `e933b2ece48b` |
| fill_null | `op.fill_null` | clean | [docs/capabilities/operators/fill_null.md](../capabilities/operators/fill_null.md) | [技能](skills/operators/fill_null.md) | `tests/unit/capabilities/test_operator_manifests.py` | `1a3e87e9389d` |
| drop_duplicates | `op.drop_duplicates` | clean | [docs/capabilities/operators/drop_duplicates.md](../capabilities/operators/drop_duplicates.md) | [技能](skills/operators/drop_duplicates.md) | `tests/unit/capabilities/test_operator_manifests.py` | `e7d48affccc2` |
| dedupe_similar | `op.dedupe_similar` | clean | [docs/capabilities/operators/dedupe_similar.md](../capabilities/operators/dedupe_similar.md) | [技能](skills/operators/dedupe_similar.md) | `tests/unit/capabilities/test_operator_manifests.py` | `e1a55324cc1a` |
| semantic_dedupe | `op.semantic_dedupe` | clean | [docs/capabilities/operators/semantic_dedupe.md](../capabilities/operators/semantic_dedupe.md) | [技能](skills/operators/semantic_dedupe.md) | `tests/unit/capabilities/test_operator_manifests.py` | `a4eaa794ed98` |
| similar_to | `op.similar_to` | clean | [docs/capabilities/operators/similar_to.md](../capabilities/operators/similar_to.md) | [技能](skills/operators/similar_to.md) | `tests/unit/capabilities/test_operator_manifests.py` | `538a9eeadc94` |
| filter_rows | `op.filter_rows` | clean | [docs/capabilities/operators/filter_rows.md](../capabilities/operators/filter_rows.md) | [技能](skills/operators/filter_rows.md) | `tests/unit/capabilities/test_operator_manifests.py` | `67931a1aa3ff` |
| select_columns | `op.select_columns` | clean | [docs/capabilities/operators/select_columns.md](../capabilities/operators/select_columns.md) | [技能](skills/operators/select_columns.md) | `tests/unit/capabilities/test_operator_manifests.py` | `94d78b3d52a7` |
| rename_columns | `op.rename_columns` | clean | [docs/capabilities/operators/rename_columns.md](../capabilities/operators/rename_columns.md) | [技能](skills/operators/rename_columns.md) | `tests/unit/capabilities/test_operator_manifests.py` | `d1339dce5619` |
| strip_whitespace | `op.strip_whitespace` | clean | [docs/capabilities/operators/strip_whitespace.md](../capabilities/operators/strip_whitespace.md) | [技能](skills/operators/strip_whitespace.md) | `tests/unit/capabilities/test_operator_manifests.py` | `fed917e8b39c` |
| convert_type | `op.convert_type` | clean | [docs/capabilities/operators/convert_type.md](../capabilities/operators/convert_type.md) | [技能](skills/operators/convert_type.md) | `tests/unit/capabilities/test_operator_manifests.py` | `9ad618d0674c` |
| sort_rows | `op.sort_rows` | clean | [docs/capabilities/operators/sort_rows.md](../capabilities/operators/sort_rows.md) | [技能](skills/operators/sort_rows.md) | `tests/unit/capabilities/test_operator_manifests.py` | `b9047c0f66d2` |
| sample_rows | `op.sample_rows` | clean | [docs/capabilities/operators/sample_rows.md](../capabilities/operators/sample_rows.md) | [技能](skills/operators/sample_rows.md) | `tests/unit/capabilities/test_operator_manifests.py` | `44e05d79516d` |
| groupby_agg | `op.groupby_agg` | statistics | [docs/capabilities/operators/groupby_agg.md](../capabilities/operators/groupby_agg.md) | [技能](skills/operators/groupby_agg.md) | `tests/unit/capabilities/test_operator_manifests.py` | `b666ac532539` |
| join_tables | `op.join_tables` | join | [docs/capabilities/operators/join_tables.md](../capabilities/operators/join_tables.md) | [技能](skills/operators/join_tables.md) | `tests/unit/capabilities/test_operator_manifests.py` | `912ee276bccb` |
| anti_join | `op.anti_join` | join | [docs/capabilities/operators/anti_join.md](../capabilities/operators/anti_join.md) | [技能](skills/operators/anti_join.md) | `tests/unit/capabilities/test_operator_manifests.py` | `90004a3b98d7` |
| column_calc | `op.column_calc` | clean | [docs/capabilities/operators/column_calc.md](../capabilities/operators/column_calc.md) | [技能](skills/operators/column_calc.md) | `tests/unit/capabilities/test_operator_manifests.py` | `922ad1a59972` |
| bin_column | `op.bin_column` | clean | [docs/capabilities/operators/bin_column.md](../capabilities/operators/bin_column.md) | [技能](skills/operators/bin_column.md) | `tests/unit/capabilities/test_operator_manifests.py` | `963f79215db0` |
| extract_time | `op.extract_time` | time | [docs/capabilities/operators/extract_time.md](../capabilities/operators/extract_time.md) | [技能](skills/operators/extract_time.md) | `tests/unit/capabilities/test_operator_manifests.py` | `db9bc58b5eab` |
| bin_time | `op.bin_time` | time | [docs/capabilities/operators/bin_time.md](../capabilities/operators/bin_time.md) | [技能](skills/operators/bin_time.md) | `tests/unit/capabilities/test_operator_manifests.py` | `947adf67f75d` |
| suggest_stages | `op.suggest_stages` | time | [docs/capabilities/operators/suggest_stages.md](../capabilities/operators/suggest_stages.md) | [技能](skills/operators/suggest_stages.md) | `tests/unit/capabilities/test_operator_manifests.py` | `f4816920dbb0` |
| topic_model | `op.topic_model` | topic | [docs/capabilities/operators/topic_model.md](../capabilities/operators/topic_model.md) | [技能](skills/operators/topic_model.md) | `tests/unit/capabilities/test_operator_manifests.py` | `cc397ad78de8` |
| topic_by_stage | `op.topic_by_stage` | topic | [docs/capabilities/operators/topic_by_stage.md](../capabilities/operators/topic_by_stage.md) | [技能](skills/operators/topic_by_stage.md) | `tests/unit/capabilities/test_operator_manifests.py` | `987838c41b73` |
| topic_label | `op.topic_label` | topic | [docs/capabilities/operators/topic_label.md](../capabilities/operators/topic_label.md) | [技能](skills/operators/topic_label.md) | `tests/unit/capabilities/test_operator_manifests.py` | `1ac38a48f0d7` |
| cluster_label | `op.cluster_label` | topic | [docs/capabilities/operators/cluster_label.md](../capabilities/operators/cluster_label.md) | [技能](skills/operators/cluster_label.md) | `tests/unit/capabilities/test_operator_manifests.py` | `d9f09cffd9ef` |
| cluster_review | `op.cluster_review` | biblio | [docs/capabilities/operators/cluster_review.md](../capabilities/operators/cluster_review.md) | [技能](skills/operators/cluster_review.md) | `tests/unit/capabilities/test_operator_manifests.py` | `61fa913a4e94` |
| reply_graph | `op.reply_graph` | social | [docs/capabilities/operators/reply_graph.md](../capabilities/operators/reply_graph.md) | [技能](skills/operators/reply_graph.md) | `tests/unit/capabilities/test_operator_manifests.py` | `217642fcea8a` |
| compare_platform | `op.compare_platform` | statistics | [docs/capabilities/operators/compare_platform.md](../capabilities/operators/compare_platform.md) | [技能](skills/operators/compare_platform.md) | `tests/unit/capabilities/test_operator_manifests.py` | `c6661eb99672` |
| topic_map | `op.topic_map` | topic | [docs/capabilities/operators/topic_map.md](../capabilities/operators/topic_map.md) | [技能](skills/operators/topic_map.md) | `tests/unit/capabilities/test_operator_manifests.py` | `8084742549f7` |
| topic_salience | `op.topic_salience` | topic | [docs/capabilities/operators/topic_salience.md](../capabilities/operators/topic_salience.md) | [技能](skills/operators/topic_salience.md) | `tests/unit/capabilities/test_operator_manifests.py` | `d474a8cdcbff` |
| topic_timeline | `op.topic_timeline` | topic | [docs/capabilities/operators/topic_timeline.md](../capabilities/operators/topic_timeline.md) | [技能](skills/operators/topic_timeline.md) | `tests/unit/capabilities/test_operator_manifests.py` | `424a4aba5e2c` |
| topic_flow | `op.topic_flow` | topic | [docs/capabilities/operators/topic_flow.md](../capabilities/operators/topic_flow.md) | [技能](skills/operators/topic_flow.md) | `tests/unit/capabilities/test_operator_manifests.py` | `1ec2438b5f2c` |
| topic_coherence | `op.topic_coherence` | topic | [docs/capabilities/operators/topic_coherence.md](../capabilities/operators/topic_coherence.md) | [技能](skills/operators/topic_coherence.md) | `tests/unit/capabilities/test_operator_manifests.py` | `a00ad042282e` |
| cooccur | `op.cooccur` | topic | [docs/capabilities/operators/cooccur.md](../capabilities/operators/cooccur.md) | [技能](skills/operators/cooccur.md) | `tests/unit/capabilities/test_operator_manifests.py` | `8c9f7cb5d224` |
| sentiment_evolution | `op.sentiment_evolution` | time | [docs/capabilities/operators/sentiment_evolution.md](../capabilities/operators/sentiment_evolution.md) | [技能](skills/operators/sentiment_evolution.md) | `tests/unit/capabilities/test_operator_manifests.py` | `ac68960229df` |
| forecast | `op.forecast` | time | [docs/capabilities/operators/forecast.md](../capabilities/operators/forecast.md) | [技能](skills/operators/forecast.md) | `tests/unit/capabilities/test_operator_manifests.py` | `20091d17f322` |
| alert | `op.alert` | time | [docs/capabilities/operators/alert.md](../capabilities/operators/alert.md) | [技能](skills/operators/alert.md) | `tests/unit/capabilities/test_operator_manifests.py` | `49784cceae22` |

## chart

| id | 标题键 | 分组 | 文档 | 技能 | 契约测试 | digest |
|---|---|---|---|---|---|---|
| bar | `chart.bar` | console | [docs/capabilities/charts/bar.md](../capabilities/charts/bar.md) | [技能](skills/charts/bar.md) | `tests/unit/capabilities/test_chart_manifests.py` | `f5a2c7c9b387` |
| line | `chart.line` | console | [docs/capabilities/charts/line.md](../capabilities/charts/line.md) | [技能](skills/charts/line.md) | `tests/unit/capabilities/test_chart_manifests.py` | `16f82fbe2a04` |
| dual_line | `chart.dual_line` | console | [docs/capabilities/charts/dual_line.md](../capabilities/charts/dual_line.md) | [技能](skills/charts/dual_line.md) | `tests/unit/capabilities/test_chart_manifests.py` | `15dfbb068f8b` |
| stack_pct | `chart.stack_pct` | console | [docs/capabilities/charts/stack_pct.md](../capabilities/charts/stack_pct.md) | [技能](skills/charts/stack_pct.md) | `tests/unit/capabilities/test_chart_manifests.py` | `b53a6aa65303` |
| topic_map | `chart.topic_map` | console | [docs/capabilities/charts/topic_map.md](../capabilities/charts/topic_map.md) | [技能](skills/charts/topic_map.md) | `tests/unit/capabilities/test_chart_manifests.py` | `dcd1865be089` |
| topic_terms | `chart.topic_terms` | console | [docs/capabilities/charts/topic_terms.md](../capabilities/charts/topic_terms.md) | [技能](skills/charts/topic_terms.md) | `tests/unit/capabilities/test_chart_manifests.py` | `90d141bbc159` |
| pie | `chart.pie` | console | [docs/capabilities/charts/pie.md](../capabilities/charts/pie.md) | [技能](skills/charts/pie.md) | `tests/unit/capabilities/test_chart_manifests.py` | `3702656cbf3a` |
| scatter | `chart.scatter` | console | [docs/capabilities/charts/scatter.md](../capabilities/charts/scatter.md) | [技能](skills/charts/scatter.md) | `tests/unit/capabilities/test_chart_manifests.py` | `feb519763932` |
| histogram | `chart.histogram` | console | [docs/capabilities/charts/histogram.md](../capabilities/charts/histogram.md) | [技能](skills/charts/histogram.md) | `tests/unit/capabilities/test_chart_manifests.py` | `74d4789a884b` |
| box | `chart.box` | console | [docs/capabilities/charts/box.md](../capabilities/charts/box.md) | [技能](skills/charts/box.md) | `tests/unit/capabilities/test_chart_manifests.py` | `83e0d5d7dd9c` |
| heatmap | `chart.heatmap` | console | [docs/capabilities/charts/heatmap.md](../capabilities/charts/heatmap.md) | [技能](skills/charts/heatmap.md) | `tests/unit/capabilities/test_chart_manifests.py` | `23aabaf58f11` |
| model_agreement | `chart.model_agreement` | console | [docs/capabilities/charts/model_agreement.md](../capabilities/charts/model_agreement.md) | [技能](skills/charts/model_agreement.md) | `tests/unit/capabilities/test_chart_manifests.py` | `f7e0c5420283` |
| sankey | `chart.sankey` | console | [docs/capabilities/charts/sankey.md](../capabilities/charts/sankey.md) | [技能](skills/charts/sankey.md) | `tests/unit/capabilities/test_chart_manifests.py` | `1177d4f686c9` |
| network | `chart.network` | console | [docs/capabilities/charts/network.md](../capabilities/charts/network.md) | [技能](skills/charts/network.md) | `tests/unit/capabilities/test_chart_manifests.py` | `61f27bc55c9f` |
| knowledge_graph | `chart.knowledge_graph` | biblio | [docs/capabilities/charts/knowledge_graph.md](../capabilities/charts/knowledge_graph.md) | [技能](skills/charts/knowledge_graph.md) | `tests/unit/capabilities/test_chart_manifests.py` | `a40752bedbcd` |
| cluster_timeline | `chart.cluster_timeline` | biblio | [docs/capabilities/charts/cluster_timeline.md](../capabilities/charts/cluster_timeline.md) | [技能](skills/charts/cluster_timeline.md) | `tests/unit/capabilities/test_chart_manifests.py` | `8b3fab742eb7` |
| burst | `chart.burst` | biblio | [docs/capabilities/charts/burst.md](../capabilities/charts/burst.md) | [技能](skills/charts/burst.md) | `tests/unit/capabilities/test_chart_manifests.py` | `0f2263a0960b` |
| timezone | `chart.timezone` | biblio | [docs/capabilities/charts/timezone.md](../capabilities/charts/timezone.md) | [技能](skills/charts/timezone.md) | `tests/unit/capabilities/test_chart_manifests.py` | `874082a60bd9` |
| circular | `chart.circular` | biblio | [docs/capabilities/charts/circular.md](../capabilities/charts/circular.md) | [技能](skills/charts/circular.md) | `tests/unit/capabilities/test_chart_manifests.py` | `be1debc4f123` |
| landscape | `chart.landscape` | biblio | [docs/capabilities/charts/landscape.md](../capabilities/charts/landscape.md) | [技能](skills/charts/landscape.md) | `tests/unit/capabilities/test_chart_manifests.py` | `cc9838239c4f` |
| biblio_heatmap | `chart.biblio_heatmap` | biblio | [docs/capabilities/charts/biblio_heatmap.md](../capabilities/charts/biblio_heatmap.md) | [技能](skills/charts/biblio_heatmap.md) | `tests/unit/capabilities/test_chart_manifests.py` | `a738bbbc50a1` |
| graph3d | `chart.graph3d` | biblio | [docs/capabilities/charts/graph3d.md](../capabilities/charts/graph3d.md) | [技能](skills/charts/graph3d.md) | `tests/unit/capabilities/test_chart_manifests.py` | `27f56092dfc3` |
| variation | `chart.variation` | biblio | [docs/capabilities/charts/variation.md](../capabilities/charts/variation.md) | [技能](skills/charts/variation.md) | `tests/unit/capabilities/test_chart_manifests.py` | `0d564fae27ad` |
| dual_map | `chart.dual_map` | biblio | [docs/capabilities/charts/dual_map.md](../capabilities/charts/dual_map.md) | [技能](skills/charts/dual_map.md) | `tests/unit/capabilities/test_chart_manifests.py` | `1bb070b72102` |
| geo_map | `chart.geo_map` | biblio | [docs/capabilities/charts/geo_map.md](../capabilities/charts/geo_map.md) | [技能](skills/charts/geo_map.md) | `tests/unit/capabilities/test_chart_manifests.py` | `c2c291d0e58b` |
| sentiment_overlay | `chart.sentiment_overlay` | biblio | [docs/capabilities/charts/sentiment_overlay.md](../capabilities/charts/sentiment_overlay.md) | [技能](skills/charts/sentiment_overlay.md) | `tests/unit/capabilities/test_chart_manifests.py` | `3c752e14dc68` |
| topic_overlay | `chart.topic_overlay` | biblio | [docs/capabilities/charts/topic_overlay.md](../capabilities/charts/topic_overlay.md) | [技能](skills/charts/topic_overlay.md) | `tests/unit/capabilities/test_chart_manifests.py` | `75ffffeed5b6` |
| concentric | `chart.concentric` | biblio | [docs/capabilities/charts/concentric.md](../capabilities/charts/concentric.md) | [技能](skills/charts/concentric.md) | `tests/unit/capabilities/test_chart_manifests.py` | `7851e664cceb` |
| wordcloud | `chart.wordcloud` | console | [docs/capabilities/charts/wordcloud.md](../capabilities/charts/wordcloud.md) | [技能](skills/charts/wordcloud.md) | `tests/unit/capabilities/test_chart_manifests.py` | `937cdc660045` |
| map | `chart.map` | console | [docs/capabilities/charts/map.md](../capabilities/charts/map.md) | [技能](skills/charts/map.md) | `tests/unit/capabilities/test_chart_manifests.py` | `0106a27109a4` |

## platform

| id | 标题键 | 分组 | 文档 | 技能 | 契约测试 | digest |
|---|---|---|---|---|---|---|
| zhihu | `platform.zhihu` | cn | [docs/capabilities/platforms/zhihu.md](../capabilities/platforms/zhihu.md) | [技能](skills/platforms/zhihu.md) | `tests/unit/capabilities/test_platform_manifests.py` | `38438ce0f99d` |
| weibo | `platform.weibo` | cn | [docs/capabilities/platforms/weibo.md](../capabilities/platforms/weibo.md) | [技能](skills/platforms/weibo.md) | `tests/unit/capabilities/test_platform_manifests.py` | `0082fe165b64` |
| xiaohongshu | `platform.xiaohongshu` | cn | [docs/capabilities/platforms/xiaohongshu.md](../capabilities/platforms/xiaohongshu.md) | [技能](skills/platforms/xiaohongshu.md) | `tests/unit/capabilities/test_platform_manifests.py` | `ef5c7331cc69` |
| wechat | `platform.wechat` | cn | [docs/capabilities/platforms/wechat.md](../capabilities/platforms/wechat.md) | [技能](skills/platforms/wechat.md) | `tests/unit/capabilities/test_platform_manifests.py` | `37144fd11856` |
| bilibili | `platform.bilibili` | cn | [docs/capabilities/platforms/bilibili.md](../capabilities/platforms/bilibili.md) | [技能](skills/platforms/bilibili.md) | `tests/unit/capabilities/test_platform_manifests.py` | `ff835752b320` |
| douyin | `platform.douyin` | cn | [docs/capabilities/platforms/douyin.md](../capabilities/platforms/douyin.md) | [技能](skills/platforms/douyin.md) | `tests/unit/capabilities/test_platform_manifests.py` | `712f3cc90e76` |
| hongguo | `platform.hongguo` | cn | [docs/capabilities/platforms/hongguo.md](../capabilities/platforms/hongguo.md) | [技能](skills/platforms/hongguo.md) | `tests/unit/capabilities/test_platform_manifests.py` | `13c4328dc031` |
| cnki | `platform.cnki` | cn | [docs/capabilities/platforms/cnki.md](../capabilities/platforms/cnki.md) | [技能](skills/platforms/cnki.md) | `tests/unit/capabilities/test_platform_manifests.py` | `068edf53f029` |
| youtube | `platform.youtube` | overseas | [docs/capabilities/platforms/youtube.md](../capabilities/platforms/youtube.md) | [技能](skills/platforms/youtube.md) | `tests/unit/capabilities/test_platform_manifests.py` | `a6f4bfeed47c` |
| twitter | `platform.twitter` | overseas | [docs/capabilities/platforms/twitter.md](../capabilities/platforms/twitter.md) | [技能](skills/platforms/twitter.md) | `tests/unit/capabilities/test_platform_manifests.py` | `2bd9f4ac2afe` |
