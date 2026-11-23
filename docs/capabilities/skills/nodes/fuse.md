# node.fuse

文献融合 merges several source tables into one canonical record table: each role (entity, year, title, author, affiliation, text, reference, source) declares candidate column names, and the first candidate a source really has answers the role.

## When to use

When CNKI/platform tables from different sources should become one record set.

Do not use it when:

- Comment rows are not bibliographic records; use node.accumulate for repeated appends of one shape.

## Prerequisites

- One or more source tables.
- At least the entity role must find a column; the other roles may stay empty.

## Steps

1. Wire every source table in.
2. Keep or edit the candidate column lists per role; at least the entity role must find a column.
3. Choose whether undated records are kept and whether per-source files are exported.

## Examples

```json
{
  "type": "fuse",
  "params": {
    "entity_columns": "关键词,话题,主题,主题词,标签",
    "title_columns": "题名,标题,内容,正文",
    "keep_undated": true
  }
}
```

## Template JSON

```json
{
  "type": "fuse",
  "params": {
    "entity_columns": "关键词,标题",
    "title_columns": "标题",
    "keep_undated": true
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `entity_columns` | string | `关键词,话题,主题,主题词,标签` |  |  |
| `year_columns` | string | `年份,发布时间,发表日期,日期` |  |  |
| `title_columns` | string | `题名,标题,内容,正文` |  |  |
| `author_columns` | string | `作者,用户名,昵称,发布者` |  |  |
| `affiliation_columns` | string | `作者单位,机构` |  |  |
| `text_columns` | string | `摘要,正文,内容` |  |  |
| `reference_columns` | string | `参考文献,引文` |  |  |
| `source_columns` | string | `平台,来源` |  |  |
| `source_labels` | string |  |  |  |
| `keep_undated` | boolean | `True` |  |  |
| `export_files` | boolean | `False` |  |  |

## Failure modes

- No input table: fuse.no_input.
- No entity candidate found: fuse.needs_entity names the node.
- Differing source columns are normalized per role; a missing role is left empty, never guessed.

## Acceptance

- One canonical table exists with a source column and the declared roles.
- No entity candidate is refused as fuse.needs_entity.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/fuse.md`
Skill page: `docs/capabilities/skills/nodes/fuse.md`
Contract tests: `tests/unit/capabilities/test_fuse_manifest.py`
