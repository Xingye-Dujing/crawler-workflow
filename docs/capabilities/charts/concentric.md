# concentric（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/concentric.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

同心环图：按节点首次出现年份分环，环上扇区表示各年出现量。

## 何时使用

要看“新词何时进入、老词何时退场”的首现结构。

不要用于：

- 逐节点看年份用时间线/时区图更直接。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`年份序列`、`频次`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
