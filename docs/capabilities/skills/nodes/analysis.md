# node.analysis

数据分析 runs an ordered pipeline of operators over one table: filter/select/rename/join/group, statistics, text analysis (keyword/topic/LDA) and chart-ready aggregates. Each operator declares the columns it reads and the columns it emits.

## When to use

When rows need a multi-step table transformation; a single text operation belongs on 处理.

Do not use it when:

- One text operation belongs on node.process; a chart belongs on node.visualize.

## Prerequisites

- An upstream table.
- Every column a step reads exists upstream; the step refuses by name otherwise.

## Steps

1. Add steps in order; each step is {op, ...params}.
2. A step that reads a column refuses by name when the column is absent upstream.
3. The analysis node emits the columns of the last step plus passthrough columns.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "drop_null",
    "steps": "[{\"op\": \"drop_null\", \"columns\": \"正文\"}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "drop_null",
    "steps": "[{\"op\": \"drop_null\", \"columns\": \"正文\"}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `operation` | string | `drop_null` |  |  |
| `columns` | string |  |  |  |
| `column` | string |  |  |  |
| `value` | string |  |  |  |
| `op` | string | `eq` |  |  |
| `dtype` | string | `str` |  |  |
| `rename_from` | string |  |  |  |
| `rename_to` | string |  |  |  |

## Failure modes

- No steps and no operation: engine.analysis_no_op.
- An unknown operator/parameter: data_analysis.validate_step names it with the allowed values.
- A missing input column: the step refuses by name rather than guessing.

## Acceptance

- The output carries the last step’s columns.
- A zero-row result from non-empty input is reported as engine.empty_output.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/analysis.md`
Skill page: `docs/capabilities/skills/nodes/analysis.md`
Contract tests: `tests/unit/capabilities/test_analysis_manifest.py`
