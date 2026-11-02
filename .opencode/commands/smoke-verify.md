---
description: Verify backend changes — pytest fast suite, ruff lint, headless Flask boot, GET endpoint smoke test, clean shutdown.
---

Load the `smoke-verify` skill with the `skill` tool (`id: smoke-verify`) and follow its steps in
order, stopping at the first failure. This command exists so the `/smoke-verify` entry point the
repo's docs (AGENTS.md, docs/agent_practices.md) refer to still works after the move from Qoder
skills to OpenCode skills.
