Solo personal project, no connection to employer, built with public/free-tier only

# Frontier Benchmark Spec — Ava AGI Factory v6.4 Extension
## Inspired by Samaya FrontierFinance

### FrontierFinance Summary (source: FrontierFinance LinkedIn post + research page + image)
- **220 tasks**, **11,543 expert-crafted rubrics** (avg 52.46 rubrics/task, median 16-17 in PRBench subset)
- **Criteria Eval methodology**: each task has many fine-grained rubrics, LLM judge (o4-mini) evaluates response against each criterion, produces weighted score clipped 0-1
- **11 evaluation categories** (PRBench + FrontierFinance extended):
  1. Financial Accuracy
  2. Process Transparency & Auditability
  3. Risk & Ethical Disclosure
  4. Coverage Comprehensiveness
  5. Attribution Correctness
  6. Numerical Accuracy
  7. Logical Coherence
  8. Citation Grounding
  9. Instruction Following
  10. Edge Case Handling
  11. Client-Ready Polish
- **Validation**: Rubric validation 93.9% expert agreement on clarity/validity, Judge IRA 80.2% agreement o4-mini vs human, human-human 79.6% (on par)
- **Workflow**: Screening & Discovery, Company Research, Sector/Industry/Macro, Earnings & Events, Coverage & Catalyst Monitoring
- **Human baseline**: ~18 hours skilled labor per task, expert still beats SOTA models on client-ready
- **Results**: Samaya ACP 50.8% SOTA at 4x lower cost than Claude Fable 5 49.2%, Opus 4.8 45%, GPT 5.5 43.5%

### Expansion to 6 New Domains — arXiv as Source of Truth
Goal: reuse rumbric pattern for long-horizon research tasks, replace SEC filings with arXiv papers as ground truth + free public APIs.

| Domain | arXiv Categories | Ground-Truth Sources (free/public) | Why Frontier |
|---|---|---|---|
| finance | q-fin.GN, q-fin.CP, econ.GN | SEC 10-K/Q (EDGAR free), earnings call transcripts public, FRED, arXiv q-fin | catalyst ambiguity, multi-doc |
| bio | q-bio.BM, q-bio.OT, q-bio.GN | arXiv q-bio, PubMed abstracts (E-utilities free), UniProt, ClinicalTrials.gov | target ID needs cross-paper synthesis |
| climate | physics.ao-ph, physics.soc-ph, eess.SP | arXiv ao-ph, IPCC AR6 WG1 public summary, NOAA CPC free tier | scenario uncertainty |
| materials | cond-mat.mtrl-sci, cond-mat.mes-hall, physics.chem-ph | arXiv mtrl-sci, Materials Project (free API key), PubChem | inverse design, long synth |
| code research | cs.SE, cs.LG, cs.CL, cs.RO | arXiv cs.*, GitHub public repos, PapersWithCode | repo-level long horizon |
| law | cs.CL, stat.ML + legal | arXiv + CourtListener RECAP free, US Code public | case synthesis + risk disclosure |
| macro | econ.GN, econ.EM, q-fin.ST, stat.AP | arXiv econ, FRED API free, World Bank | causal modeling, tariff→GDP |

#### Sample Tasks (2 per domain)

**Finance:**
- FF-SD-001: Screen small-cap biotech cash runway >2y, Ph2 catalyst <90d, insider buying 30d
- FF-ER-002: Earnings revision synthesis for semiconductor: 3 10-Qs + guidance, produce street vs model delta table

**Bio:**
- BIO-001: KRAS G12C covalent inhibitor scaffold proposal from AlphaFold3 arXiv:2406.12345 — binding rationale + off-target
- BIO-002: Base editing durability risk memo from arXiv:2405.07892 sickle cell long-term follow-up

**Climate:**
- CLI-001: AMOC tipping probability under SSP2-4.5 cross arXiv:2407.01234 + IPCC AR6 Ch4 — confidence intervals table
- CLI-002: Cool-roof cost-benefit Phoenix albedo arXiv:2403.04567 + NOAA degree-days

**Materials:**
- MAT-001: Solid-state electrolyte >5 mS/cm + >4.5V stability from arXiv:2408.00123 perovskite + Materials Project
- MAT-002: MOF for CO2 capture ML force field accuracy comparison arXiv:2402.09876

**Code Research:**
- CODE-001: RepoAgent memory leak detection across 3 files per arXiv:2405.03456 — fix + test
- CODE-002: Design tool-use code LM eval harness per scaling laws arXiv:2406.11111 — process transparency rubric

**Law:**
- LAW-001: SaaS agreement clause risk: indemnity + change-of-control, cite arXiv contract ambiguity detection
- LAW-002: Fair-use memo for training on arXiv abstracts — attribution + risk

**Macro:**
- MAC-001: Tariff pass-through impact 15% tariff on US GDP per arXiv:2404.05678 causal model + FRED import
- MAC-002: Oil shock + EV adoption 3 scenarios from arXiv:2401.01111 supply chain causal

### Task Schema JSON

```json
{
  "id": "FF-2026-SD-001",
  "domain": "finance",
  "subdomain": "Screening & Discovery",
  "question": "Screen US small-cap biotech with cash runway >2y...",
  "context_docs": [
    {"type": "sec_filing", "ticker": "MRK", "form": "10-Q", "page": "12", "snippet": "cash $142M..."},
    {"type": "arxiv", "id": "2406.12345", "category": "q-bio.BM", "abstract": "AlphaFold3...", "citation_span": "Sec 3.2 lines 45-60"}
  ],
  "expected_workflow": ["planner: identify criteria", "executor: query SEC+arxiv", "memory: track tickers", "reasoning: valuation+risk", "attribution: cite spans"],
  "rubrics": [{"$ref": "Rubric schema"}],
  "human_baseline_hours": 18.2,
  "ground_truth": "expert memo..."
}
```

### Rubric Schema JSON

```json
{
  "id": "R-FF-SD-001-07",
  "task_id": "FF-2026-SD-001",
  "category": "Financial Accuracy",
  "criterion": "Cash runway uses (cash+ST)/burn_last_Q with correct quarterly burn",
  "weight": 0.08,
  "eval_instructions": "Judge: check numeric calc within 10% of ground truth and cites 10-Q page. If missing citation 0.5 max, if wrong formula 0.",
  "ground_truth_ref": "MRK 10-Q p12: 160M/22M=7.27q",
  "citation_span": "doc0 lines 120-135",
  "required": true
}
```

### Scoring
- Per-rubric score s_i in [0,1] by LLM judge
- Weighted overall = clip(sum_i w_i * s_i, 0,1)
- Free-tier mock judge = keyword overlap + numeric presence + length heuristic (no API)
- Real judge options: LocalHFJudge (transformers pipeline if present) or MetaMuseJudge (Muse Spark 1.1 public API personal account, env META_API_KEY, endpoint META_MUSE_API_URL default https://api.meta.ai/v1, $1.25 in/$4.25 out, $20 free credits, US-only preview, uses PUBLIC endpoint only, zero work resources)

### Integration into Ava v6.4
- Phase 3 Reasoning & Phase 5 Anneal: use frontier tasks as long-context (16-32k) anneal with reward>0.8 verifier = CriteriaJudge
- eval_branch_harness.py: add --frontier flag calling eval_frontier_rubric.evaluate_all
- shards: data/streaming_shards/frontier_rubric/manifest.jsonl + shard_*.jsonl.gz with concatenated docs

### Appendix B — Judge Options: Cost Comparison (Home-Lab, Public Endpoints Only)

#### Muse Spark 1.1 (previous)
- Model: Meta Muse Spark 1.1 coding & agentic, public preview US
- Pricing: $1.25/M input, $4.25/M output, $20 free credits
- Endpoint: https://api.meta.ai/v1 (placeholder public preview)
- Issue: $1.25/$4.25 relatively expensive for 7-task x 6-rubric x long docs = ~100k tokens/eval = ~$0.55/eval
- Home-lab: personal META_API_KEY only, zero work resources, mock fallback

#### GLM-5.2 (Z.ai / Zhipu) — Cheaper than Muse but still API cost
- Model: **GLM-5.2**, flagship 753B MoE (40B active, 744B variant reported), 1M context window (model id `glm-5.2[1m]`), 131k max output, IndexShare cuts FLOPs 2.9x at 1M, MIT open weights (allows free self-host on HF ZeroGPU/Runpod later), thinking toggle + reasoning effort High/Max.
- Pricing:
  - Z.ai official API: ~$1.40/M input $4.40/M output, **cached input $0.26/M** (huge win for rubric judge where same rubrics reused)
  - CometAPI proxy: $1.12/M input $3.528/M output
  - Coding Plan subscription (Claude Code / Cline / OpenCode / Roo compatible):
    - Lite: ~$18/mo (400 prompts/week) ~$12.60/yr annual (~$0.045/prompt)
    - Pro: ~$72/mo 2000/week, Max: ~$160/mo 8000/week — makes heavy eval ~10x cheaper than pay-go
- Endpoints (all public):
  - Anthropic-compatible (recommended, supports Claude Code): `https://api.z.ai/api/anthropic` -> env `ANTHROPIC_BASE_URL` or `ZAI_BASE_URL`
  - Coding PaaS: `https://api.z.ai/api/coding/paas/v4`
  - OpenAI-compatible: `https://api.z.ai/api/paas/v4/chat/completions` -> `ZAI_OPENAI_URL`
- Model IDs: `glm-5.2` (default), `glm-5.2[1m]` (1M), `glm-5.2-thinking`, `glm-5.2[1m]-thinking`
- Why cheaper for Frontier:
  1. Cached $0.26/M vs $1.25 — rubrics repeated across tasks, cache hit 70%+
  2. $18/mo Lite = 1600 prompts/mo ~ heavy eval for <$0.02/eval vs $0.55
  3. MIT weights → future free local self-host, fully free-tier
- Home-lab compliance:
  - Uses public endpoint only via personal `ZAI_API_KEY` (preferred) or `GLM_API_KEY` or `ANTHROPIC_API_KEY` fallback
  - Env `GLM_MODEL` controls model variant, `ZAI_BASE_URL` controls endpoint, `GLM_THINKING=1`, `GLM_EFFORT=high|max`
  - If no key, logs "[GLM 5.2] no ZAI_API_KEY, fallback to mock" and returns mock+0.07, never fails, keeps free-tier runnable
- Usage:
  ```bash
  export ZAI_API_KEY=personal_key_from_z.ai
  export ZAI_BASE_URL=https://api.z.ai/api/anthropic
  export GLM_MODEL=glm-5.2[1m]
  python eval_frontier_rubric.py --judge glm --domain all --mode mock
  ```

#### Ollama Local — SOTA for Free (Current Recommendation)
- Goal: zero API cost, fully offline, MIT/Apache weights via Ollama on user machine.
- Recommended models (all `ollama pull` free):
  - `qwen3:32b` (default) — best balanced coding/rubric judge, 32B fits 24GB VRAM Q4, Qwen2.5 family strong instruction following
  - `qwen2.5-coder:32b` — best code-specific judge for Repo tasks
  - `deepseek-r1:32b` or `deepseek-r1:14b` — best reasoning judge (chain-of-thought, excels at Financial Accuracy/Numerical)
  - `llama3.3:70b` — best generalist, stronger NLU than qwen3 but needs ~40GB Q4, highest quality if VRAM allows
  - `glm4:9b-chat` — small GLM family that DOES run in Ollama vs 753B GLM-5.2 which needs 241GB 2-bit min (docs say 241-280GB total memory), so use distill for local
  - Fallback: `qwen3:8b` / `llama3.1:8b` if low VRAM
- Architecture:
  - Env `OLLAMA_HOST` default `http://localhost:11434`, `OLLAMA_MODEL` default `qwen3:32b`
  - Code detects `/api/tags` via urllib (stdlib) then requests fallback, lists local models
  - Calls `POST /api/chat` non-streaming with `temperature 0.1`, `num_predict 128`, truncates rubric+output to 3000 chars for speed
  - Parses `{"score":0.x}` JSON, fallback to regex float, else mock+0.06
  - If not reachable, logs "Ollama not reachable, fallback to mock" and returns mock scoring — never fails, keeps CI/VMS free
- Why free SOTA:
  - No network beyond localhost, no API key, no $/token
  - MIT/Apache weights, fully offline, cache persists
  - Can run on M1/M2/M3 Mac, or 24GB 4090/3090, or CPU if needed
  - Future-proof: when GLM-5.2 1-bit GGUF improves (≈76% accuracy at 86% smaller), could run locally too
- Limitations vs API:
  - 753B GLM-5.2 too big for Ollama (241-280GB min), not recommended for laptop
  - Local inference slower but okay for 7-task demo (~1-2 min per task on 32B)
- Home-lab compliance:
  - Solo personal project, no connection to employer, built with public/free-tier only
  - Public/free-tier only: Ollama binaries + open weights, zero work resources
- Usage:
  ```bash
  ollama serve &
  ollama pull qwen3:32b        # or deepseek-r1:32b / llama3.3:70b / qwen2.5-coder:32b
  export OLLAMA_HOST=http://localhost:11434
  export OLLAMA_MODEL=qwen3:32b
  python eval_frontier_rubric.py --judge ollama --domain finance --mode mock
  python eval_frontier_rubric.py --judge ollama --domain all --mode mock
  ```

