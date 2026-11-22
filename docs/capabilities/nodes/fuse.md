# 文献融合（fuse）

文献融合把多张来源表合成**一张规范记录表**。它读父节点的 DICT 结果（知道每行来自哪张表），而不是扁平化的
fan-in。每个角色（实体、年份、题名、作者、单位、正文、参考文献、来源）声明候选列名，第一张真正拥有该列的
来源表回答这个角色。

- 清单：`backend/capabilities_kernel/nodes/fuse/manifest.py`
- 行为：`backend/nodes/executors/fuse.py`
- 契约测试：`tests/unit/capabilities/test_fuse_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `entity_columns` | 关键词,话题,主题,主题词,标签 | 实体角色的候选列；至少一个候选要能找到。 |
| `year_columns` | 年份,发布时间,发表日期,日期 | 年份候选列。 |
| `title_columns` | 题名,标题,内容,正文 | 题名候选列。 |
| `author_columns` | 作者,用户名,昵称,发布者 | 作者候选列。 |
| `affiliation_columns` | 作者单位,机构 | 单位候选列。 |
| `text_columns` | 摘要,正文,内容 | 正文候选列。 |
| `reference_columns` | 参考文献,引文 | 参考文献候选列。 |
| `source_columns` | 平台,来源 | 来源候选列。 |
| `source_labels` | 空 | 来源标签映射（`平台=标签`），可替代 source 列。 |
| `keep_undated` | `true` | 是否保留无年份记录。 |
| `export_files` | `false` | 是否按来源导出文件。 |

## 校验

- `fuse.no_input`：没有输入表。
- `fuse.needs_entity`：没有任何实体候选列（无法构图）。

## 典型画布

```text
CNKI 导出 → 文献融合 ─┐
知乎帖子   → 文献融合 ─┼→ 文献分析 → 可视化
```

融合后的输出是固定规范列（`services/biblio/fuse.OUTPUT_COLUMNS`），下游文献节点无需重映射。
