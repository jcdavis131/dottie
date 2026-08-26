---
name: anydoc
description: Unified Document IR + single GFM serializer — stdlib anydoc-py v1.0.0, 12+ formats, honest 503
triggers:
- anydoc
- extract
- document
- docx
- pdf
- parse document
j_space_target: S2
half_life: 300
broadcast_target: 0.22
reportability_target: 0.065
dependencies: []
connectors: []
provider: none
version: 1.0.0
tier: stdlib
---

# anydoc

Unified Document `{meta, blocks, assets}` IR with single GFM serializer, stdlib only, zero-deps.
Content-based detection from bytes, median <50ms target, ThreadPoolExecutor batch preserving order.

Supports: docx, pptx, xlsx, odt, ods, odp, epub, pdf, rtf, html, csv, txt, md, json + ole legacy (503).

Usage:

```python
from bigbang.plugins.extract import anydoc
doc = anydoc.parse(data, filename="report.docx")
md = anydoc.to_markdown(doc)

# batch
docs = anydoc.batch(["a.docx", b"%PDF-...", "notes.html"], jobs=4)
```

Honest 503 for scanned PDF, encrypted PDF, OLE doc/xls/ppt.

Solo personal project, no connection to employer, built with public/free-tier only.
