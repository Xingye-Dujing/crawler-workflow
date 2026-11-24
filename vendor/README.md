# vendor/

Committed dependency artifacts, for a package that has no index release.

## `agent_workspace-0.2.0-py3-none-any.whl`

| | |
|---|---|
| distribution | `agent-workspace` 0.2.0 |
| built from | the agent-workspace framework checkout, `pip wheel --no-deps -w dist .` |
| sha256 | `e7b84dd15461acfef98447e77d0d9ead2b1c75c51d658f2b23df60ac4ad2f30a` |

`requirements.txt` names this file by a path relative to the repository root, so `pip install -r
requirements.txt` installs exactly these bytes. A development checkout of the framework can shadow
it in one venv with `pip install -e <framework checkout>`.

**Rebuild deliberately, never silently.** After a framework change, rebuild the wheel, replace the
file (do not add a second one), update the sha256 above, and bump the version in `pyproject.toml`
when the public surface changes. `tests/unit/gates/test_requirements_pinned.py` refuses a wheel
whose filename and METADATA disagree, an undeclared wheel left in this directory, and the same
distribution pinned twice.
