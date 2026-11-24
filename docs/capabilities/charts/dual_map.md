# dual_map（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/dual_map.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

双层图：左右两层各自成簇，中间用流量连线表示跨层对应。

## 何时使用

把“施引/被引”或“方法/主题”两层结构放在一张图里。

不要用于：

- 只有一层结构时用知识图谱。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`map`、`source`、`target`、`weight`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
