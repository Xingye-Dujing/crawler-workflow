# vendor/

Committed dependency artifacts, for a package that has no index release.

## `agent_workspace-0.1.12-py3-none-any.whl`

| | |
|---|---|
| distribution | `agent-workspace` 0.1.12 |
| built from | the agent-workspace framework checkout, `pip wheel --no-deps -w dist .` |
| sha256 | `9ac8a3da377f79f6a7a0256be832253126214ff5e614a68bea2ab5b768e97257` |

`requirements.txt` names this file by a path relative to the repository root, so `pip install -r
requirements.txt` installs exactly these bytes. A development checkout of the framework can shadow
it in one venv with `pip install -e <framework checkout>`.

**Rebuild deliberately, never silently.** After a framework change, rebuild the wheel, replace the
file (do not add a second one), update the sha256 above, and bump the version in `pyproject.toml`
when the public surface changes. `tests/unit/gates/test_requirements_pinned.py` refuses a wheel
whose filename and METADATA disagree, an undeclared wheel left in this directory, and the same
distribution pinned twice.
