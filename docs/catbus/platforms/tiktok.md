# TikTok（tiktok）

| | |
|---|---|
| id / 别名 | `tiktok` · `tt` |
| `item` 是 | 视频（也包括图文 photo） |
| 登录 | **只能导入**：cookie 字符串（只读）或浏览器会话 JSON（读写） |

## 能做

- **读**：`item search` / `get` / `related` / `media` / `download` / `list`；`user get` / `items` / `collects` / `reposts` / `followers` / `following`；`comment list` / `replies`；`feed list`；`product get`；`live get` / `list`（关注的人在播，可能为空）/ `search` / `categories` / `listen` / `history` / `rank` / `gifts` / `media`；`keyword suggest`；`notice list` / `count`；`msg list` / `history` / `listen`；`folder list` / `items`；`series list`；`poi search`。
- **写**（需要会话 JSON）：`user follow` / `unfollow`；`item like` / `unlike` / `collect` / `uncollect` / `publish`；`comment add`；`live send` / `like`；`msg send`；`folder create` / `update` / `add`；`media upload`。

## 做不到

`user search`、`user likes`、`item delete`、`item repost`、`keyword hot`、`msg read` / `revoke` / `delete`、`folder delete`。

## 参数

- 视频：`tiktok.com/@<用户名>/video/<id>`（图文 `/photo/<id>`）、分享短链（`vt.tiktok.com`、`vm.tiktok.com`），或数字 ID。
- 用户：**用户名**（`tiktok` 或 `@tiktok`）、主页链接、数字 uid 或 `me`。只给 `secUid` 时 `user get` 取不到完整资料，会报 `USAGE`。
- 直播间：主播用户名或主页链接（自动查房间号），或数字房间号。
- 收藏夹：`folder list` 输出的 `id`。

## 坑

- **写操作要浏览器会话 JSON**：只导入 cookie 时，写操作会在本地被拦下（`AUTH_REQUIRED`，hint 提示重新导入）。会话 JSON 的格式让用户看项目的登录指南，不要替他去浏览器里取。
- 私信只能发文本，只能发给已有会话的人。
- `folder add <folder> <item>`：只能把**已收藏**的视频加进收藏夹，先 `item collect`。`folder create` 默认私密。
- 视频发布必须带 `--cover`，只读 MP4；`--visibility` 支持 `public` / `private` / `friends`。私有选项 `--allow-comment` / `--allow-duet` / `--allow-stitch` 等见 `--help`。
- 国内网络需要代理（`catbus config set tiktok.proxy <url>`）。

## 示例

```bash
catbus tiktok item search cats --limit 20
catbus tiktok user get @tiktok
catbus tiktok user items @tiktok --limit 50 -o jsonl
catbus tiktok comment list "<视频 url>" --limit 100
catbus tiktok live listen @<主播> --duration 10m
```
