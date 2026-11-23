# node.tokenize

分词 turns one text column into a word table: word/frequency pairs, bare words, or a single space-joined line. The upstream rows are the corpus; the node never reads a file itself.

## When to use

When a later step needs word frequencies or one word per row: word cloud, bar chart, corpus statistics. Use the process node for cleaning-only passes.

Do not use it when:

- Cleaning or one text operation belongs on node.process.
- Corpus statistics belong on node.analysis.

## Prerequisites

- An upstream table with a text column.

## Steps

1. Wire a node that produces text rows into 分词.
2. Pick the text column and an output mode.
3. For word_freq, optionally cap the table with top_n (blank means the executor default).

## Examples

```json
{
  "type": "tokenize",
  "params": {
    "text_column": "正文",
    "top_n": "120",
    "output_mode": "word_freq"
  }
}
```

## Template JSON

```json
{
  "type": "tokenize",
  "params": {
    "text_column": "正文",
    "top_n": "120",
    "output_mode": "word_freq"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `text_column` | string |  | yes |  |
| `top_n` | string |  |  |  |
| `output_mode` | string | `word_freq` |  | word_freq, words_only, csv_line |

## Failure modes

- No text column configured: refuses before the run with engine.tokenize_no_column.
- The column is absent from the upstream table: the executor names the column and the columns it saw.
- No upstream rows: the executor refuses instead of settling an empty table DONE.

## Acceptance

- The word table has word/frequency columns and no blank words.
- An absent text column is named with the columns seen.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/tokenize.md`
Skill page: `docs/capabilities/skills/nodes/tokenize.md`
Contract tests: `tests/unit/capabilities/test_tokenize_manifest.py`
