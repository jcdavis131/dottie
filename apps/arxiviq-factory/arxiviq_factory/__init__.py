"""arxiviq-factory: training-ready System One decision datasets from arXiv papers.

Stdlib only. Stages: harvest -> enrich -> families (+ Nimble mined pairs) ->
teacher (LLM-written paper questions) -> curate (validate, holdout, manifest).
Every row carries where its label came from; see README.md.
"""

SCHEMA_ID = "jev-decision-schema-1.0.0"
PACK_VERSION = "arxiviq-pack-1"
