# 变异扫描（mutation sweep）

一套绿的测试只回答“有没有东西失败”。变异扫描回答更难的那个问题：**如果这一行的行为变了，它会不会失败？**
工具是 `tools/mutation_sweep.py`，读数写在一次运行里（`reports/mutation.md`，git 忽略），夜间工作流
`.github/workflows/nightly.yml` 每天跑一次。

```bash
python tools/mutation_sweep.py                       # 三个声明目标，全量（约 5-8 分钟）
python tools/mutation_sweep.py --limit 6             # 每个目标先扫 6 个，做冒烟
python tools/mutation_sweep.py --target backend/core/values.py=tests/unit/foundation/test_utils.py
python tools/mutation_sweep.py --out reports/mutation.md --json reports/mutation.json
```

## 它改什么，不改什么

只改**决定**，因为只有决定能被测试看出来：

| 变异 | 例子 | 为什么是它 |
|---|---|---|
| 比较取反 | `a >= b` → `a < b`，`x in y` → `x not in y` | 空心测试最常漏的就是边界/否定 |
| 布尔运算互换 | `A and B` → `A or B` | 两个条件都在、却从没同时为真过 |
| 去掉 `not` | `if not rows:` → `if rows:` | 反向分支从未执行 |
| 比较旁的常数 +1 | `tolerance > 0` → `> 1` | 差一错误是否被断言 |
| 不改 | 文档字符串、日志文案、类型注解、普通算术 | 改了也不改变可观察行为，存活说明不了测试好坏 |

每个变异只改**一处**，在 AST 上做，然后 `ast.unparse` 成模块跑测试。

## 一个“存活”是什么意思

**存活的变异 = 点名的那个测试文件没有检查这个决定。** 处理顺序是先问“这是不是一个等价的变异”：

1. **等价变异**（反过来的比较没有任何输入能区分，或者那条分支不可达）→ 在目标表里给它留一行理由，
   不必改测试。
2. **真的没检查**（分支存在、输入可达）→ 在**测试**里补一条正反两面的用例，不要改产品代码——
   产品代码是对的，缺的是证据。
3. **测试文件选错了**（这个规则其实由另一个文件拥有）→ 改 `DEFAULT_TARGETS` 的配对，别让一个
   不拥有它的文件背锅。

## 为什么不是门禁

一次扫描要为每个变异跑一遍 pytest，这比全量 fast tier 还慢；而且“存活”里天然混着等价变异。
它和 `docs/testing/value-inventory.md` 一样是**读数**：清单页由工具生成、由门禁盯着新鲜度；
变异页则按运行生成、由夜间工作流上传，从不进仓库（幸存者随代码移动，钉住一份旧页面只会误导人）。

## 目前的三个目标

| 模块 | 谁的测试 | 为什么是它 |
|---|---|---|
| `backend/core/values.py` | `tests/unit/foundation/test_values.py` | 到处都是的纯转换（`safe_int`/`optional_float`…），错一位就影响全站 |
| `backend/sessions/verdict.py` | `tests/unit/sessions/test_session_verdict.py` | 登录判定词表与 TTL 槽位，纯函数、规则密集 |
| `backend/nodes/schema.py` | `tests/unit/analysis/test_node_schema.py` | 列契约的图遍历，错了会让“缺列”静默消失 |

配对是一句**断言**（“这个文件的测试负责这个模块”），不是覆盖率测量。加目标时要保证：该测试文件
在 `cp -r backend tests docs tools vendor pytest.ini requirements.txt` 的副本里能独立跑绿——工具只复制
这几项，读到别处的测试不是合格目标。工具会先跑一次**未变异**的基线；基线红就是目标声明陈旧，
按名字报出来，不会假装“所有变异都被捕获”。

## 第一次跑出来什么（2026-11-25）

第一次全量 34 个变异，**只有 11 个被捕获**，两个目标暴露了真问题：

- `core/values.py` **0/10**：配对一开始写成 `tests/unit/foundation/test_utils.py`，而它测的是
  `core/refs.py`；`safe_int`/`optional_float` 这些“到处都是的数值读取”**一个单元测试都没有**——它们的
  `is None` 守卫全绿只是因为没人调用。补了 `tests/unit/foundation/test_values.py`（30 条，按文档里那
  三条生产事故写：不可解析/`inf`/`nan`、空 ≠ 0、阈值 0 是答案），配对改到该文件 → **10/10**。
- `nodes/schema.py` **7/20 捕获**（13 个存活）：列规则本身有测试，**喂它的那次图遍历没有**——扇入并集里重复的列、
  指向画布外地节点的一根线、环、以及“插件没有 `param_errors` 钩子”都活了下来。在
  `test_node_schema.py::TestTheGraphWalk` 补了五条 → **20/20**。
- `sessions/verdict.py` **4/4**：TTL 边界与判定词表原本就钉得很紧，这条不需要动。

修完再跑：三个目标 **34/34**，总耗时约 1.5 分钟（每个变异一次 pytest，Windows 上 2–4 秒）。这就是
扫描页该有的用法：先读，再把真缺口补成测试，然后数字才有意义。
