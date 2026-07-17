> **MOCK BLUEPRINT OUTPUT — not measurements.** Every number in this report is a
> hardcoded illustrative blueprint value (see docs/blueprint/README.md). For real,
> checkpoint-derived measurements run `python -m evals.run_harness` and read
> `reports/REPORT_REAL.md`.

Solo personal project, no connection to employer, built with public/free-tier only

# Frontier Eval Report — Ava v6.4

Judge: ollama Mode: mock | Total tasks: 7

Metrics: weighted clipped 0-1 per Samaya FrontierFinance Criteria Eval (11 cats), mock uses keyword overlap

| Task | Domain | Overall | Cats |
|---|---|---|---|
| FF-2026-SD-001 | finance | 0.625 | 6 |
| BIO-001 | bio | 0.621 | 6 |
| CLI-001 | climate | 0.549 | 6 |
| MAT-001 | materials | 0.502 | 6 |
| CODE-001 | code | 0.634 | 6 |
| LAW-001 | law | 0.692 | 6 |
| MAC-001 | macro | 0.499 | 6 |

## Per-task details

### FF-2026-SD-001 (finance) overall 0.625
- R-FF-2026-SD-001-01 Financial Accuracy: 0.683 w=0.1667
- R-FF-2026-SD-001-02 Process Transparency & Auditability: 0.767 w=0.1667
- R-FF-2026-SD-001-03 Risk & Ethical Disclosure: 0.65 w=0.1667
- R-FF-2026-SD-001-04 Coverage Comprehensiveness: 0.5 w=0.1667
- R-FF-2026-SD-001-05 Attribution Correctness: 0.6 w=0.1667
- R-FF-2026-SD-001-06 Numerical Accuracy: 0.55 w=0.1667

### BIO-001 (bio) overall 0.621
- R-BIO-001-01 Financial Accuracy: 0.683 w=0.1667
- R-BIO-001-02 Process Transparency & Auditability: 0.72 w=0.1667
- R-BIO-001-03 Risk & Ethical Disclosure: 0.7 w=0.1667
- R-BIO-001-04 Coverage Comprehensiveness: 0.44 w=0.1667
- R-BIO-001-05 Attribution Correctness: 0.5 w=0.1667
- R-BIO-001-06 Numerical Accuracy: 0.683 w=0.1667

### CLI-001 (climate) overall 0.549
- R-CLI-001-01 Financial Accuracy: 0.295 w=0.1667
- R-CLI-001-02 Process Transparency & Auditability: 0.65 w=0.1667
- R-CLI-001-03 Risk & Ethical Disclosure: 0.58 w=0.1667
- R-CLI-001-04 Coverage Comprehensiveness: 0.6 w=0.1667
- R-CLI-001-05 Attribution Correctness: 0.58 w=0.1667
- R-CLI-001-06 Numerical Accuracy: 0.59 w=0.1667

### MAT-001 (materials) overall 0.502
- R-MAT-001-01 Financial Accuracy: 0.225 w=0.1667
- R-MAT-001-02 Process Transparency & Auditability: 0.72 w=0.1667
- R-MAT-001-03 Risk & Ethical Disclosure: 0.58 w=0.1667
- R-MAT-001-04 Coverage Comprehensiveness: 0.3 w=0.1667
- R-MAT-001-05 Attribution Correctness: 0.738 w=0.1667
- R-MAT-001-06 Numerical Accuracy: 0.45 w=0.1667

### CODE-001 (code) overall 0.634
- R-CODE-001-01 Financial Accuracy: 0.683 w=0.1667
- R-CODE-001-02 Process Transparency & Auditability: 0.767 w=0.1667
- R-CODE-001-03 Risk & Ethical Disclosure: 0.58 w=0.1667
- R-CODE-001-04 Coverage Comprehensiveness: 0.44 w=0.1667
- R-CODE-001-05 Attribution Correctness: 0.65 w=0.1667
- R-CODE-001-06 Numerical Accuracy: 0.683 w=0.1667

### LAW-001 (law) overall 0.692
- R-LAW-001-01 Financial Accuracy: 0.683 w=0.1667
- R-LAW-001-02 Process Transparency & Auditability: 0.8 w=0.1667
- R-LAW-001-03 Risk & Ethical Disclosure: 0.738 w=0.1667
- R-LAW-001-04 Coverage Comprehensiveness: 0.533 w=0.1667
- R-LAW-001-05 Attribution Correctness: 0.65 w=0.1667
- R-LAW-001-06 Numerical Accuracy: 0.75 w=0.1667

### MAC-001 (macro) overall 0.499
- R-MAC-001-01 Financial Accuracy: 0.295 w=0.1667
- R-MAC-001-02 Process Transparency & Auditability: 0.65 w=0.1667
- R-MAC-001-03 Risk & Ethical Disclosure: 0.58 w=0.1667
- R-MAC-001-04 Coverage Comprehensiveness: 0.3 w=0.1667
- R-MAC-001-05 Attribution Correctness: 0.58 w=0.1667
- R-MAC-001-06 Numerical Accuracy: 0.59 w=0.1667

## Integration
- Phase 3-5 anneal reward>0.8 verifier = CriteriaJudge
- shards: data/streaming_shards/frontier_rubric/
- MetaMuseJudge: reads META_API_KEY, endpoint META_MUSE_API_URL default https://api.meta.ai/v1 placeholder public preview $1.25 in $4.25 out $20 free credits, US-only, personal account only, zero work resources.
- Glm52Judge: reads ZAI_API_KEY (pref) / GLM_API_KEY, endpoint https://api.z.ai/api/anthropic (Anthropic-compatible) or https://api.z.ai/api/paas/v4/chat/completions (OpenAI), model GLM_MODEL default glm-5.2 / glm-5.2[1m] / glm-5.2-thinking, 753B MoE 40B active, 1M context, MIT open weights, 131k output, IndexShare 2.9x FLOPs. Pricing $1.40/M in $4.40/M out, cached $0.26/M, CometAPI $1.12/$3.528, or Lite $18/mo (400/wk) $12.60 annual, Pro $72/mo, Max $160/mo. Cheaper for heavy eval via cache+sub + future free self-host via MIT. Public endpoint only, free-tier mock fallback.
- OllamaJudge: reads OLLAMA_HOST default http://localhost:11434, OLLAMA_MODEL default qwen3:32b (alternatives llama3.3:70b best general, deepseek-r1:32b best reasoning, qwen2.5-coder:32b best coding, glm4:9b small GLM). 100% offline free SOTA via Ollama MIT/Apache. 753B GLM-5.2 too big for Ollama (241GB 2-bit min), so use small distill locally. Detects /api/tags, calls /api/chat non-streaming, extracts JSON score, falls back to mock+0.06 if unreachable. Zero cost, local only.
