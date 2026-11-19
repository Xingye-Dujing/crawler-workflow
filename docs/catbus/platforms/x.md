# X（x）

| | |
|---|---|
| id / 别名 | `x` · `twitter` |
| `item` 是 | 推文 |
| 登录 | **只能 cookie 导入**（x.com 的 Cookie，要有 `auth_token` 和 `ct0`） |

## 能做

- **读**：`item search` / `get` / `media` / `download`；`user get` / `search` / `items`；`comment list`（回复）；`feed list`（推荐）；`msg list`（最近 20 个会话）/ `history`（端到端加密，只有占位）。
- **写**：`item publish`（支持 `--quote` 引用、`--thread` 发串推）/ `delete`；`item like` / `unlike` / `collect` / `uncollect`（书签）/ `repost` / `unrepost`；`comment add` / `delete` / `like` / `unlike`；`user follow` / `unfollow`；扩展命令 `article publish` / `delete`（Premium 长文）；`media upload`。

## 做不到

`msg send` / `listen`（私信加密）、`notice`、`keyword`、`user likes` / `followers` / `following`、`comment replies`、`feed list --kind following`、收藏夹。

## 参数

- 推文：数字 ID，或 `x.com/<用户名>/status/<id>`（`twitter.com` 也行）。
- 用户：用户名（`elonmusk` 或 `@elonmusk`）、主页链接、数字用户 ID 或 `me`。**纯数字按用户 ID 处理**，全数字的用户名写成 `@123`。
- 评论：回复推文的 ID（`comment list` 输出的 `id`）。

## 筛选

`item search`：`--sort general|latest`，`--type all|video|image`；`--type video|image` 不能和 `--sort latest` 一起用。

## 坑

- **发布只能公开**（`--visibility public`），发之前把内容给用户确认。正文超过 280 权重（中文算 2）会自动发长推，需要 Premium；`article publish` 也要 Premium。最多 4 张图，图片和视频不能同时用。
- `--thread <text>` 可重复：`--text` 是第一条，后面每条依次回复上一条；返回第一条。
- 还没有做过真机验证：请求与上游一致，但字段取值和风控表现还没在真账号上确认。结果异常时照实告诉用户。
- 国内网络需要代理（`catbus config set x.proxy <url>`）。

## 示例

```bash
catbus x user get elonmusk
catbus x user items elonmusk --limit 50 -o jsonl
catbus x item search "claude code" --sort latest --limit 20
catbus x comment list "https://x.com/<user>/status/<id>" --limit 100
catbus x item publish --text "hello" --image a.jpg
```
