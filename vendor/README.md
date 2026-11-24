# vendor/

Committed dependency artifacts, for a package that has no index release.

## `agent_workspace-0.1.27-py3-none-any.whl`

| | |
|---|---|
| distribution | `agent-workspace` 0.1.27 |
| built from | the agent-workspace framework checkout, `pip wheel --no-deps -w dist .` |
| sha256 | `bddd5e25977b2fb344a4631625a335df3ba8fc17e03aae74d58abf36c24b6d2d` |

`requirements.txt` names this file by a path relative to the repository root, so `pip install -r
requirements.txt` installs exactly these bytes. A development checkout of the framework can shadow
it in one venv with `pip install -e <framework checkout>`.

**Rebuild deliberately, never silently.** After a framework change, rebuild the wheel, replace the
file (do not add a second one), update the sha256 above, and bump the version in `pyproject.toml`
when the public surface changes. `tests/unit/gates/test_requirements_pinned.py` refuses a wheel
whose filename and METADATA disagree, an undeclared wheel left in this directory, and the same
distribution pinned twice.
