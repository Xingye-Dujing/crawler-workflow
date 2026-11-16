# 账号池与出口池（IP 池）

平台把一组登录与出口拦下时，池记住“谁被拦过、到什么时候”，下一次运行直接跳过它；轮换只是这份记忆的下游动作。

## 状态

| 实体 | 是什么 |
|---|---|
| 账号 | 一份已保存的 Cookie（账号树下的 `cookies/<平台>_cookies.json`，多账号为 `<平台>@<账号>_cookies.json`），不另建清单 |
| 出口 | 一条代理（`http`/`https`/`socks5`，可选用户名密码），可限定适用平台 |
| 绑定 | 某个 `(平台, 账号)` 固定从哪个出口出去，**粘性**：只有出口被冷却才换出口，且仍用同一个登录（换 IP 不换号） |
| 健康 | 每条 `(account 或 exit, 平台, 主体)` 的状态：`ok` / `cooling`（到某时刻）/ `disabled`（人工停用） |

状态持久化在账号树的 `pool.db`（托管模式 `data/users/<id>/pool.db`），重启后冷却依然有效。读取时用当前时间比较
`cool_until`，到点自动回到 `ok`，没有后台线程。手动停用不会自动过期。每个账号/出口一条 health 行（含 `cool_until`、
`strikes`、最近尝试与成功时刻），每次尝试另记一条事件行，即面板的“最近记录”。

## 失败归因：只冷却有证据的一方

| 失败信号 | 冷却账号 | 冷却出口 |
|---|---|---|
| `login_wall` | `pool_cooldown_seconds`（默认 7200） | 不冷却（会话死了，出口通常无罪） |
| `risk_blocked`（验证码/风控） | 先 10 分钟；同一账号再次风控则全程 | `pool_cooldown_seconds`（风控首先怀疑出口） |
| `unreachable` / 网络报错 | 不冷却 | `pool_network_cooldown_seconds`（默认 300；机器或线路问题） |
| 采得不足、0 行、普通超时 | 不冷却 | 不冷却（没有证据，冷却谁都是猜） |
| 用户停止 | 不冷却 | 不冷却（立刻结束，不再开浏览器） |

打开 `pool_escalate` 后，冷却按 strikes 指数放大（上限一周）。预检的 `unknown` 与这里的“不冷却”是同一条规则的两面。

## 轮换

- **数据源节点**：只在**本次尝试零行**且站点回答 `login_wall`/`risk_blocked` 时换下一组（`SessionBlockedError`，
  `crawlers/core/faults.py`）。已有行落库时走“保留行、结算 PARTIAL、继续”，不换号。
- **评论节点**：按链接换号。当前链接被拦 → 冷却 → 丢掉该平台的会话 → 用下一组**重走同一条链接**；
  `url_index` 只记已证明的连续前缀，这条链接本来没被证明，游标不动。
- 每次尝试重新拿 `gate.hold(..., account=该次真实账号)`：lane 按账号分，用哨兵 `@pool` 拿 lane 会把池内并行串成一队。
- 上限 `pool_max_attempts`（默认 3）；用完抛一条按名列出每个账号与冷却时间的拒绝，而不是“Cookie 已失效”。
- 池模式跳过同账号退避重试（`pool_skip_wall_backoff`，默认开）：刚测出来的墙再撞一次正是要避免的花费。
- CatBus 不参与：它的登录在自己的账号目录里，`@pool` 对它按名拒绝。

## 预检

- 冷却中的账号不开浏览器，直接按台账回答 `cooling`（阻塞）。
- 池节点按**池**回答：只要还有一个可用 `(账号, 出口)` 就不拦；全部冷却或未保存登录才拦，并区分
  “池里没有登录”与“现在全在冷却”。
- 默认只读状态（`pool_preflight_live` 关）；打开后才真的用第一个候选验证一次并写回台账。
- 保存/重取 Cookie 是新的会话：清掉该账号的冷却与 strikes，并让预检缓存失效；手动“解冻/验证”同理。
- 状态、冷却时刻与可用数量由 `/api/pool/state` 一次给全；解冻/停用、出口增删改与批量导入、绑定分别走
  `/api/pool/account/reset`、`/api/pool/account/disable`、`/api/pool/exit/save|delete|import`、`/api/pool/bind`。

## 出口

| 出口类型 | 做法 |
|---|---|
| 无认证 | `--proxy-server=http://host:port` + `--force-webrtc-ip-handling-policy=disable_non_proxied_udp`（堵住 WebRTC 用 UDP 泄漏本机地址） |
| 有认证 HTTP | `crawlers/core/proxy.py` 起只监听 `127.0.0.1` 的 CONNECT 中继，给上游加 `Proxy-Authorization`；凭据不进 argv、不进日志；中继与 driver 同生共死 |
| 带认证 SOCKS5 | 按名拒绝（不做一半的 SOCKS5 握手） |

- 出口解析收敛在 `crawlers/__init__.py::get_crawler`：采集、登录窗口、验证、预检四条路走同一个出口。
- 出口全冷却且 `pool_allow_direct_fallback` 关（默认）时宁可拒绝也不直连：直连会暴露代理想藏起来的地址。
- 凭据只存在 `pool.db`，接口只回 `has_auth`；面板与日志只能看到名称和 `host:port`。

## 不变量

- **一个节点一份账本、一个游标**：换号不移动 `item:` 作用域，也不让游标越过没证明的空洞。
- **指纹**：`account='@pool'` 原样进指纹（池模式与固定账号是两次不同的采集）；`@` 不是合法账号字符，
  永远不会与用户起的账号名撞车，也永远不能交给 `CookieManager.path_for`。
- **前端不做判断**：状态、冷却时间、可用数量全部由 `/api/pool/state` 给出，面板只格式化。
- 托管模式下出口与账号的增删改限管理员；读取对当前登录账号开放。

## 面板

Cookie 底栏三个页签：**账号**（表格 + 状态/冷却至/出口/解冻/停用）、**出口**（清单、表单、批量导入）、
**最近记录**（每次成功/失败、账号、出口、行数、运行 id）。功能关闭时底栏与原来一致。

## 配置

| 键 | 默认 | 作用 |
|---|---|---|
| `pool_enabled` | 关 | 池模式总开关；关闭时底栏与原来一致 |
| `pool_cooldown_seconds` | 7200 | `login_wall` / 风控的冷却时长（60–604800） |
| `pool_network_cooldown_seconds` | 300 | 网络失败的出口冷却时长（0–86400） |
| `pool_max_attempts` | 3 | 一个节点最多尝试几组登录（1–10），用完按名拒绝 |
| `pool_escalate` | 关 | 按 strikes 指数放大冷却，上限一周 |
| `pool_allow_direct_fallback` | 关 | 出口全冷却时是否允许直连（默认宁可拒绝） |
| `pool_skip_wall_backoff` | 开 | 池模式跳过同账号退避重试 |
| `pool_preflight_live` | 关 | 预检是否真的用第一个候选验证一次并写回台账 |

逐项说明见 [config.md](config.md)。
