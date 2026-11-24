# 快测性能预算（2026-11-24 实测）

> 本文件是 P8 的性能记录。数字来自 `python -m pytest -q --durations=15`，本机（Windows，
> Windows 11，Python 3.11，`-q` 默认 marker 过滤：fast tier 12234 passed / 7 skipped /
> 386 deselected）。

## 预算

| 层 | 预算 | 现状 | 判定 |
|---|---|---|---|
| fast tier（`python -m pytest -q`） | **≤ 12 分钟** | **10:36 ～ 12:37**（同一天连测两次，同一台机器、同一份代码） | **骑线**：一次达标、一次超 37 秒 |
| fast tier 原始目标 | ≤ 8 分钟 | 10:36 | **未达标，原因见下，不接受用 xdist 掩盖** |
| device（`-m "integration or live_ollama"`） | ≤ 20 分钟 | 未测（需真 Chrome/Ollama） | 待测 |

**“骑线”是真的骑线，不是取其中好看的一次。** 2026-11-24 W0/W1/W2 收官批：第一次全量
`12234 passed / 7 skipped / 386 deselected in 757.26s (0:12:37)`，紧接着带 `--durations=15`
重跑同一份代码 `in 636.71s (0:10:36)`，差 2 分 01 秒。也就是说本机同一套用例的跑动时间有
**±10% 的抖动**，而最慢的那些用例全是“等满一个真实超时”：机器一忙（并行跑着别的进程），
这些超时就从“刚好等满”变成“等满再排队”。结论：**12 分钟这条线目前只能算擦边通过，不能
宣称有 1 分钟的余量**；要真正拿到余量，还是得给等待路径加时钟接缝（见下节）。

8 分钟的目标没有达到，也不打算用并行执行（`pytest-xdist`）去“达到”：那是新增依赖并改变
测试的隔离假设，而不是把慢用例修好。剩下的差距是**假驱动里的真实等待**：

| 用例 | 秒 | 为什么还在等 |
|---|---|---|
| `unit/frontend/test_frontend_console_js.py::TestConsoleCursor::test_the_first_answer_renders_every_line_offered`（setup） | 19.1 | 每个 console 用例重新加载整页 JS（setup 的代价，随测试数线性叠加） |
| `unit/i18n/test_i18n.py::TestKeyReachability::test_the_quote_inspection_is_actually_needed` | 15.4 | 遍历全仓文本做引号统计 |
| `unit/crawlers/test_xhs_crawler.py`（2 例） | 15.0 / 10.0 | 详情页就绪探针（`.title, #detail-title`）与基类 `open()` 的就绪探针各等满一次；已让假驱动回答 `.title` 与 `body`（一个加载完成的页面两样都有），其中一例 15 s → 10 s，剩余仍卡在基类探针 |
| `integration/test_douyin_crawler.py`（3 例） | 14.0 ×3 | 同一形状：假驱动的栅格永远“还没到”，等满超时；未改 |
| `unit/update/test_update.py::test_a_helper_that_never_writes_its_receipt_is_refused` | 10.1 | 真子进程等回执超时 |
| `api/test_source_dispatch_matrix.py`（2 例） | 8.0 / 7.2 | 光标前缀的两条契约各等满一次墙重试窗口 |
| `unit/crawlers/test_hongguo_harvest.py`（2 例） | 5.0 ×2 | 收尾计数的等待窗口 |

要再往下走，需要给这些路径加一个**时钟/等待接缝**：`WebDriverWait` 的超时来自基类 `open()` 与平台
探针，测试能替换的只有“假驱动答不答”，一旦探针本身没被回答，真实超时就是唯一结局。接缝应当加在
`crawlers/engine/` 的就绪探针上（可注入的 `wait_for_ready`），再用假时钟跑这些用例；这是下一步，不是
本片的范围。把假驱动改成“回答探针”能省掉一部分，但省不干净——xhs 的实测就是例子。

## 本片修掉的（14:23 → 11:36，省 2 分 47 秒）

| 用例 / 文件 | 之前 | 之后 | 原因与修法 |
|---|---|---|---|
| `api/test_collision_retry.py`（整个文件） | 94.0 s | 3.6 s | 产品早已从 `Config.WALL_RETRY_BACKOFF` 改为读设置 `wall_retry_backoff`，测试还在打补丁旧常量 → 真实 45 s 退避被完整等待。改为补丁 `source.get_setting`。 |
| `unit/crawlers/test_hongguo_harvest.py::TestWalk::test_has_more_false_with_a_larger_total_is_not_site_end` | 78.7 s | 3.5 s | `has_more=false` 时仍在向站点要下一页，每页等满 10 s 窗口。让假 UI 的 `scroll_drawer` 返回 False：断言（kept < total → UNDER_TARGET）不变，等待消失。 |

**教训（已写进 `docs/agent_practices.md`）**：一个仍在给**已废弃常量**打补丁的测试会继续“通过”，
代价是把真实超时等满。看到 10 秒以上的单例，先查它补丁的对象是否还是产品真正读的那个。

## 怎么复测

```bash
python -m pytest -q --durations=15          # 总时长 + 最慢 15 例
python -m pytest --collect-only -q          # 只有收集/导入：约 12 s
```

收集不是瓶颈（12 s），耗时在用例本身；因此优化对象永远是**具体用例**，不是 conftest 的导入。
