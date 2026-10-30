# docs/archive — 已完成的流程记录

这里放的是**过程**，不是现行规则：一个已完成项目的阶段账本、当次评审记录、当时的测量流水。
它不随代码演进，也不被 `tests/unit/gates/test_doc_paths.py` 扫描（那份守卫只检查现行
`docs/*.md` 引用的路径是否仍存在）；里面的路径可能指向已改名或已删除的文件，那是历史，不是缺陷。

现行文档在上一级目录：

- 规则（改代码前必读）：[`AGENTS.md`](../../AGENTS.md)、[`docs/crawler_rules.md`](../crawler_rules.md)
- 规则为什么这样定（实测证据）：[`docs/agent_practices.md`](../agent_practices.md)
- 各平台真机测量：[`docs/crawler_notes.md`](../crawler_notes.md)
- 真机验收怎么跑：[`docs/live_test_plan.md`](../live_test_plan.md)

| 文件 | 是什么 | 归档于 |
|---|---|---|
| [`refactor_plan_2026-10.md`](refactor_plan_2026-10.md) | 全项目重构（Stage 0–11）的总纲与逐刀账本：目标目录树、每阶段交付与钉住它的门禁、当时 CI 现状、收尾时明确写下的剩余表面。**已完成**（2026-10-29，commit `70f3344`）。 | 2026-10-30 |

新增归档只放**已结束**的流程记录，并且必须在现行文档里留一句指针；仍在使用的规则与实测数字
不进这里。
