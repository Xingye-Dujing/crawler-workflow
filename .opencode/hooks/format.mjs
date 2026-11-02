#!/usr/bin/env node
/**
 * Ruff shim for OpenCode's `formatter` step (converted from the `.qoder/hooks/format.py`
 * PostToolUse hook). OpenCode runs it after `write`/`edit`/`patch` with the touched file
 * as `$FILE`, and it does exactly what the Qoder hook did: `ruff format`, then
 * `ruff check --fix`, scoped to that one file.
 *
 * Why node rather than the venv's python: the hook is one static command array, while the
 * virtualenv layout differs per OS (`.venv/Scripts/ruff.exe` on Windows, `.venv/bin/ruff`
 * elsewhere). Node is the interpreter this repo already needs, so it can pick the binary.
 *
 * Exits 0 unconditionally: a lint failure must never block the edit that triggered it.
 */

import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')

const RUFF = [
  join(ROOT, '.venv', 'Scripts', 'ruff.exe'),
  join(ROOT, '.venv', 'bin', 'ruff'),
].find((candidate) => existsSync(candidate))

const file = process.argv[2]
if (!file || !RUFF || !existsSync(file)) process.exit(0)

for (const args of [['format', file], ['check', '--fix', file]]) {
  spawnSync(RUFF, args, { cwd: ROOT, stdio: 'ignore' })
}
