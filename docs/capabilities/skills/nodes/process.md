# node.process

处理 runs one operation over the upstream text column: cleaning, tokenize, word frequency, TF-IDF/TextRank, sentiment/emotion/tendency, NER, clustering, correlation and the qualitative coding operations. The operation selects both the result columns and the required inputs.

## When to use

After a crawl/upload when the rows need cleaning or one text/algorithm operation.

Do not use it when:

- A multi-step table pipeline belongs on node.analysis.
- A reusable procedural step belongs on node.python.

## Prerequisites

- An upstream table with a text column.
- For BERT operations: a model that is installed and runnable; an unrunnable one is refused by name.

## Steps

1. Pick the operation; the panel shows only that operation’s fields.
2. Pick the text column (正文 is the usual crawl column).
3. For BERT operations choose one model, or several for the comparison table.

## Examples

```json
{
  "type": "process",
  "params": {
    "operation": "clean",
    "text_column": "正文",
    "format": "csv"
  }
}
```

```json
{
  "type": "process",
  "params": {
    "operation": "tokenize",
    "text_column": "正文",
    "output_mode": "word_freq"
  }
}
```

## Template JSON

```json
{
  "type": "process",
  "params": {
    "operation": "clean",
    "text_column": "正文",
    "format": "csv"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `operation` | string | `clean` |  | clean, tokenize, emotion, tendency, sentiment, keyword, cluster, ner, zero_shot, qualitative_code, content_analysis, aggression, bot, anomaly, correlation, significance |
| `text_column` | string | `正文` |  |  |
| `topic` | string |  |  |  |
| `live_export` | boolean | `False` |  |  |
| `format` | string | `csv` |  |  |

## Failure modes

- No operation: engine.process_no_op.
- Tokenize without a text column: engine.tokenize_no_column.
- An unknown operation/param value: the executor refuses with analysis.bad_option and the allowed values.

## Acceptance

- Validate is green and the emitted columns are the operation’s own.
- A missing text column is named with the columns the table has.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/process.md`
Skill page: `docs/capabilities/skills/nodes/process.md`
Contract tests: `tests/unit/capabilities/test_process_manifest.py`
