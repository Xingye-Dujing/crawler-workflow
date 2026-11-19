---
name: crawler-platform
description: Add, change or debug one social-platform crawler in 采析绘 — its capability entry, modes and fields, list/comment walks, session needs, pacing, cloud/OS gates, row columns and tests. Use when a platform selector changes, a site returns a login wall or risk page, a new platform is added, or a crawl result looks silently empty.
---

# Crawler platform work

Read first: `AGENTS.md` → crawler rules pointer, `docs/crawler_rules.md`, the platform's section in
`docs/crawler_notes.md`, and `backend/capabilities/platforms/<id>.py`. Measurements live in the
notes, not in guesses.

## File map

```text
backend/capabilities/platforms/<id>.py   # ONE matrix entry: modes, fields, engines, requirements
backend/capabilities/fields.py           # shared field atoms and mode factories
backend/crawlers/platforms/<id>/crawler.py  # Selenium list/mode walk; one class per mode family
backend/crawlers/platforms/<id>/comments.py # comment walk (if the site supports comments)
backend/crawlers/platforms/<id>/rows.py / overlay.py / dialogs.py
backend/crawlers/__init__.py             # get_crawler / crawler_class / is_crawlable
backend/nodes/executors/source.py        # source/comments node calls the matrix + crawler
backend/crawlers/core/                   # browser, faults, pacing, shared contract
```

## Invariants that bite

- **The matrix is the only description of what a platform can do.** A mode the matrix lacks is
  refused by name; never add a select option or a branch in the node that the matrix does not have.
- **The engine dimension is real.** Selenium and CatBus have different cells, columns and login
  gates; a CatBus-only mode must not offer `@pool` or a Selenium session. Declare `engines` in the
  matrix and let the panel grey an unavailable one with its reason.
- **A field's option list may be runtime data** (account names); a value the user typed is shown
  as typed, not looked up in i18n.
- **Empty is not a result.** Distinguish no results, a login wall, a risk/verification wall, a
  redirect-to-home, a missing panel and a stopped crawl. Each names itself and settles the node
  `partial`/`failed`, never a green empty table.
- **A comment cursor records what the walk PROVED.** Write `url_index` only after that link's rows
  land; stop at the first hole. A short list is legal only at the site's own end marker or the
  user's comment cap; otherwise name the shortfall.
- **A comment's identity is (`平台`, `评论ID`)** when the site prints one, else a stable
  article+author+body-head key; never `楼层` (a fresh walk renumbers it).
- **Cloud/OS gates are server facts.** A Windows-only desktop player is refused by name and hidden
  in the panel; a cloud host has no local Chrome/daemon.
- **Pacing is the nine global scales**, not a private `time.sleep` in a platform. The platform may
  keep a measured baseline; it may not keep a private switch.
- **No Windows-only fact** in `backend/`: drive letters, `.exe`, `taskkill`, code-page console.

## AI 工作区路由：用户要采集数据时

内置 `crawl` / `catbus` 技能（`backend/ai/skills.py`）面对"我要爬数据"时，先 `ask_user_question`
问清两条路：**建画布节点（第二后端选 catbus）** 还是 **AI 直接调 catbus 指令运行**，不替用户选。
执行前先 `catbus_status`（只读工具）探测本机 Node + 采析绘适配器与全局 `catbus` CLI，有就不新装；
缺哪一样就点名哪一样，安装由用户决定。权威 catbus 用法文档在 `docs/catbus/`（从
catbus 的 `.claude/skills/catbus/` 复制），`docs_search` 按任务取其中一两个文件，不要整本塞进上下文。

## Recipe: a new list mode

1. Add the mode to `capabilities/platforms/<id>.py` with its fields, engines and requirements.
2. Implement the walk in `crawlers/platforms/<id>/crawler.py`; return rows through the shared
   contract, not a bespoke dict.
3. Make the node's `emit_columns`/`read_columns` agree with the matrix and the row builder.
4. Add the mode's login requirement; if it needs a session, the preflight will ask.
5. Add rows/columns labels to both i18n domains (`crawl`/`settings` as owned).
6. Add a unit case for the matrix + a mocked walk; add a real-site case only with the user's
   network direction and permission.

## Recipe: a new comment walk

1. Confirm the site exposes a stable comment id; if not, use the content identity fallback.
2. Drive the site's own "more/reply" control; never synthesize a click on a hidden node.
3. Reconcile against the site's displayed total; name any shortfall except the site's end marker.
4. Persist rows through the comment executor's ledger; write the cursor after the link's rows.
5. Add `父楼层`/`评论ID`/`评论时间` columns only if the site really provides them.

## Verification

```bash
.venv/Scripts/python.exe -m pytest -q tests/unit/crawlers tests/api/test_capabilities.py
.venv/Scripts/python.exe -m pytest -q tests/unit/analysis/test_node_plugins.py
```

For a real platform, a device/live case needs `CRAWLER_REQUIRE_BROWSER=1`, this machine's
`CIXI_DRIVER_PATH`, and the user's explicit network/login direction. Never run `live_*` unattended.

## Common failures

- Added a select option but not a matrix mode → the node stores a value it cannot run.
- Filled an empty table after a login wall → looks successful, loses the run.
- Used a fixed sleep / a private timeout → bypasses the global pace and the tests.
- Wrote the comment cursor before the rows → a refused tail becomes “继续” with a hole.
- Added a field label only in Chinese → `test_frontend_contract` / i18n parity fails.
