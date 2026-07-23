# Plan — Agentic research curriculum (STEM + causal PDFs)

## Goal
Expand training data/curriculum for agentic assistants with open-licensed math,
statistics, psychology, physics, and causal-factor material — ingestable via the
existing collector→curator→pack path.

## Locked decisions
1. No pdfcoffee / upload-mirror scraping; operator inbox + catalog only.
2. New sources land at weight 0; activate by shaving same-phase mass.
3. Reuse DOC_KEYS + synthetic generators; no new trainer mix keys in v1.
4. Wiki PDF ingest (`tools/pdf_wiki_ingest`) stays separate from training track.

## Done this pass
- [x] `docs/AGENTIC_CURRICULUM.md`
- [x] `configs/research_pdf_catalog.yaml`
- [x] `causal_reason` + `research_pdf` generators
- [x] `scripts/ingest_research_pdfs.py`
- [x] staged `sources.yaml` entries
- [x] offline tests

## Next
- [ ] Operator downloads OpenStax / DOE seeds into `data/research_inbox/<domain>/`
- [ ] Activate small P2/P3/P5 weights after nano packed smoke
- [ ] Optional: HF open textbooks as `kind: hf` once schema-verified
