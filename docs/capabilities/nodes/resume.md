# 断点续采（resume）

断点续采把**之前运行已经写入 runs.db 的行**接进当前画布，用于原数据源已经退出登录、被风控或成本太高、
但行已经付费拿到的场景。它没有上游：它读的是运行存储。

- 清单：`backend/capabilities_kernel/nodes/resume/manifest.py`
- 行为：`backend/nodes/executors/resume.py`
- 契约测试：`tests/unit/capabilities/test_resume_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `resume_run_id` | 空 | 要采纳的运行 id。空表示自动选择。 |
| `resume_node_id` | 空 | 该运行里的节点 id。空表示选行数最多的节点。 |
| `resume_limit` | 0 | 最多采纳多少行；0=不限。 |

## 自动选择

`resume_run_id` 为空时，执行器在**同形状工作流**的可恢复运行里找最新的一个（排除当前正在写的运行），
再取该运行中行数最多的节点。两个 id 都空也允许：这正是“继续”按钮的路径。找不到运行/行时打印
`resume.no_run`/`resume.empty` 并返回空，不会伪造数据。

## 典型画布

```text
断点续采（run-2026…, node-3, limit=0）→ 清洗 → 分词 → 保存
```
