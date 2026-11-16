---
name: release-desktop
description: Build and release 采析绘 — version.json/APP_VERSION sync, Windows PyInstaller + Inno installer, macOS .app/DMG on GitHub runners, source snapshot, UPX/prune, model packs and the release checklist. Use when bumping a version, building a desktop package, or changing packaging/CI.
---

# Release and desktop packaging

Read first: `docs/release.md`, `docs/installer.md`, `desktop/README.md`,
`.github/workflows/release-windows.yml`, `.github/workflows/macos-build.yml`.

## The one version

- `backend/services/version.py::APP_VERSION` and root `version.json::version` must match. Format is
  date + build (`2026.11.11.2`). One side only means either no update prompt or a prompt for a
  version that never arrives.
- The build scripts take a three-part `-Version`; `tools/check_release_version.py` refuses a value
  that is not an `APP_VERSION` prefix.
- A release uses a **new tag**; never replace an attachment byte under an existing tag (the digest
  in `version.json` is the contract).

## Windows

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1 -Clean -Installer -Version 2026.11.11
```

Produces `dist\CaiXiHui-Setup.exe` and `dist\CaiXiHui-win64.zip`; record size + SHA-256, then shard
both at 99,614,720 B for Gitee. PyInstaller collects backend packages by name
(`desktop/caixihui.spec`), plus a read-only `source/` snapshot
(`frozen_modules.source_snapshot_datas`) so the packaged AI can cite code. UPX runs only after the
prune, verifies each file, and restores a file it cannot pack.

## macOS

- Built only on GitHub's macOS runners (`desktop/build_macos.py`, `.github/workflows/macos-build.yml`);
  this checkout has never executed it.
- Payloads are per-CPU: `darwin-arm64` / `darwin-x64` catalogue keys. The DMG is mounted and copied
  with `ditto`; never unzip a `.app` (symlinks/exec bits are lost).
- WebView2/pythonnet are Windows-only and never collected; the window is pywebview's Cocoa backend.

## Before building

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check backend/ tests/
.venv\Scripts\ruff.exe format --check backend/ tests/
.venv\Scripts\python.exe tools\ci_lint_tiers.py product
.venv\Scripts\python.exe tools\ci_lint_tiers.py tests
```

A failure means no build and no release. Device tier when crawling/LLM/resume changed. `live_*`
never in a release job.

## After building

1. Upload to the new release tag (Gitee sharded, GitHub full).
2. Update `version.json` (`platforms.win32` / `darwin-arm64` / `darwin-x64`): URL, size, SHA-256.
3. Update the release notes, commit/push `version.json` + docs last.
4. The in-app updater and the online installer both read `version.json`; a missing platform entry
   refuses by name instead of installing the wrong architecture.

## Common failures

- A new top-level backend package not added to the spec tuple → startup `ModuleNotFoundError`;
  `tests/unit/desktop/test_desktop_packaging.py` is the gate.
- A Python node/script feature shipped without the `ai`/`services` packages or the source snapshot.
- A macOS payload built on Linux, or an `.app` unzipped instead of `ditto`-copied.
- `version.json` updated before the assets exist → every client sees an update it cannot download.
