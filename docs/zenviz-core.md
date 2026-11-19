# Chart studio single source

`backend/static/zenviz.html` and its `css/zenviz.css`, `js/zenviz-page.js`,
`js/zenviz-parse.js` are **generated files**. The shared implementation lives in
the git submodule `third_party/zenviz-core` (also used by OMM-ZEN).

## Editing

Change files under `third_party/zenviz-core/core/` (or a `profiles/` overlay
for genuinely product-only code), then regenerate:

```bash
python third_party/zenviz-core/build.py --product caixihui --root .
```

`tests/unit/gates/test_zenviz_core_sync.py` regenerates into a temp directory
and compares every artifact byte-for-byte, so hand-editing a generated file (or
forgetting to regenerate) fails the suite.

The submodule points at https://github.com/Xingye-Dujing/zenviz-core and the CI
checkout steps already use `with: submodules: true`, so the guard runs in CI.
