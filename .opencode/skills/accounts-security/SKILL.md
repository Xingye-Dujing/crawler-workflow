---
name: accounts-security
description: Work on 采析绘's login gate, accounts, per-account data trees, sessions/cookies, account and exit pools, and egress binding — password/lockout semantics, authorization before touching a target, cloud bind refusal, rotation rules. Use when touching auth, account deletion, cookie/preflight, pool rotation or any path under data/users.
---

# Accounts, sessions and security

Read first: `AGENTS.md` → "Sessions, cookies and run gating", "账号池与出口池", "Data root,
single-run ownership"; `docs/account_pool.md`; `docs/agent_practices.md` → "Multi-account and data
scopes".

## File map

```text
backend/services/accounts/security.py   # scrypt, token compare, failure window, lockout, address key
backend/services/accounts/store.py      # accounts.db rows and migrations
backend/services/accounts/service.py    # create/verify/change/delete, tree move + compensating move-back
backend/api/auth.py                     # login/logout/refresh/change-password routes
backend/api/accounts.py                 # admin account list/create/delete
backend/web_auth.py                     # request gate, session cookie, public paths
backend/runtime/paths.py                # active()/for_user(): the ONE account path resolver
backend/runtime/account_context.py      # binding a thread/run to an account
backend/sessions/                       # cookies, flow, profiles, preflight, template, routes
backend/services/pool/                  # health (cool_until), selector, egress, store, routes
backend/crawlers/core/proxy.py          # loopback relay for authenticated exits
```

## Invariants that bite

- **A wrong password answers one sentence.** Verify BEFORE the lock/status check; a distinct
  "locked"/"disabled" answer for a wrong password is a username oracle.
- **The failure window is keyed `address|username` and bounded by size.** Pruning only the touched
  key leaked one entry per abandoned username.
- **The counter increments IN THE ROW** (`UPDATE … failed_attempts = failed_attempts + 1`, read
  back, then arm `locked_until` guarded on that count). Read-modify-write made a burst count as one.
- **Every guess at a secret shares the window**, including 改密's `current_password`.
- **Token comparisons are on bytes** (`hmac.compare_digest` raises `TypeError` on non-ASCII `str`);
  a `next` value is rejected for control characters *before* `redirect()` creates the session.
- **The gate exists only while the registry does.** A non-loopback `HOST` with no accounts refuses
  to boot by name (`public_bind_refusal`). A desktop/local run may have no login at all.
- **Account paths resolve at CALL time** (`runtime.paths.active()`). Never cache a path in a module
  constant or store default; `tests/unit/gates/test_account_paths_resolve_at_call.py` fails it.
- **Authorize BEFORE touching the target.** Return the target's run id / close its stores only after
  `_require_admin`; prove "no live run" inside `execute_lock`.
- **Deleting an account revokes sessions before the tree moves.** A request during `shutil.move`
  would rebuild stores and mint an ownerless `data/users/<id>/`. A failed move-back reports where
  the tree actually is (checked on disk), never a guessed path.
- **Replacing the process singleton closes the store it replaced** — one SQLite handle, and Windows
  locks its directory while open.
- **One account = one cookie jar file and one Chrome profile**; blank IS `默认账号`, folded to
  `default` at `CookieManager.key`/`path_segment`. A node's preselection and the candidate list both
  come from `CookieManager.accounts_in_order`.
- **Preflight refuses a login wall, never blocks on "无法核对"**; turning preflight off/resume/crawl-free
  asks nothing. A cookie write drops the cached verdict.

## Pools

- `data/pool.db` keeps `cool_until` per `(account|exit, 平台, 主体)`, compared at read time; manual
  停用 never expires; saving a login clears that account's term.
- Rotate **only** at a zero-row, attributable failure: this attempt stored no row and the site said
  `login_wall`/`risk` (`SessionBlockedError`). Rows already stored keep PARTIAL-and-continue. Never
  rotate on stop, network faults, under-target or unknown failures.
- Each attempt takes `gate.hold(account=<real login>)`; `@pool` is a sentinel that may never reach
  `CookieManager.path_for` and stays in the fingerprint. CatBus refuses it by name.
- An exit is sticky to `(platform, account)`; only a benched exit is replaced. Credentials travel
  only in the loopback relay, never argv or logs.

## Recipe: add an auth-touching route

1. Decide the surface: public (login), authenticated, or admin. Public paths are an allow-list, not
   a prefix guess.
2. `_require_admin` (or the session guard) first; the target lookup after.
3. Answer in the envelope the panel parses (`{ok, error}`), never HTML.
4. If it mutates storage, hold the right lock and use the compensating path on failure.
5. Add a test for the refusal (wrong password, foreign account, ownerless tree), not only the happy
   path. Patch both sides of a platform gate rather than faking one.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest -q tests/unit/accounts tests/unit/sessions tests/unit/gates/test_account_paths_resolve_at_call.py
.venv\Scripts\python.exe -m pytest -q tests/api/test_auth.py tests/api/test_accounts.py tests/api/test_sessions.py
```

Never exercise a real login against a live site in a test; a cookie jar is a fixture.

## Common failures

- A distinct message for a locked account with a wrong password.
- Read-modify-write on failed attempts.
- A path cached before the account was bound; two accounts share one `ai.db`.
- Deleting the tree before revoking the sessions (or without a move-back).
- Rotating on a timeout, or using `@pool` as a path segment.
- Copying a proxy password into argv, a log line, or the run fingerprint.
