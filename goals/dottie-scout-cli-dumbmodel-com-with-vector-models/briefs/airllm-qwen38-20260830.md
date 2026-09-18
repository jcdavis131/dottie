# airLLM + Qwen3.8-27B — Ideas for Dottie Swarm

**Source:** Feed unit 367a5dd1 (Aug 30 morning) — airLLM streams one transformer layer at a time, VRAM = layer size not total params. Qwen3.8-27B at 3.33GB VRAM on RTX 3090, Flash-Next 5.95GB on 4090, transformers 5.8+.

**Relevance:** You ran Qwen3.8-27B yesterday as 4090-fit coding agent. This drops same model to 3.3GB — enables local swarm ahead of Monday Launched.

**Constraint:** Dottie is zero-deps / stdlib-first, honest 503. `pip install airllm` breaks that. So treat airLLM as *optional isolated sidecar*, never forced.

---

## Idea A: Optional Local Inference Backend — "Memory-Constrained Mode"

**What:** Add `scout infer --backend airllm` as optional tier. Keeps existing `scout infer` (stdlib, TieredCache LRU 128 + mmap) as default. airLLM path only loads if user explicitly opts in.

**How it works:**
- `pip install airllm` lives in `apps/scout-rtx` or `apps/ava-factory` venv (already heavy, pinned deps), not root uv workspace
- Same `scout infer run --model Qwen/Qwen3.8-27B --prompt "hi"` API, but routes to airLLM when flag set
- Placement probe already exists (`/proc/meminfo` + `nvidia-smi`) — extend to report `airllm_available: true/false` and `vram_mode: 3.3GB`
- Fail-closed: if airLLM missing, honest `IO_MISSING: airllm not installed — run pip install airllm in scout-rtx venv`

**Why it matters for Launched:**
- 27B in 3.3GB means a 3090/4090 can run 2-3 agents in parallel (swarm) instead of 1
- Your 5 daily vector games need models as central engine — 27B gives better reasoning for ship decisions without cloud cost
- Keeps zero-deps promise: default path untouched, optional path isolated

**Next step:**
- Prototype in `apps/scout-rtx`: `AutoModel.from_pretrained("Qwen/Qwen3.8-27B")` with airLLM wrapper, measure latency vs memory tradeoff (block-wise 4bit/8bit = up to 3x speedup)
- Add `scout models list` entry: `qwen3.8-27b-airllm | 3.33GB VRAM | optional | 3090+`

---

## Idea B: Flash-Next File-Mapped N-Gram for Planning Mode

**What:** Dottie v2 has planning mode (DAG plan → execute). Qwen3.8-Flash-Next (125B MoE / 51B active, 5.95GB VRAM) uses file-mapped n-gram table on host for fast speculation.

**How it fits:**
- Planning mode already breaks goals into steps. Flash-Next n-gram = fast draft of plan steps without full forward pass
- File-mapped means host RAM holds table, not VRAM — good for your `scout harness run` where you tell outcome, it breaks into steps, checks before consequential
- Same isolation: optional backend, only if user has Flash-Next weights locally

**Why it matters:**
- Faster planning = faster `scout inbox` parking for consequential actions (send message, calendar, run command)
- MoE 51B active gives better tool-calling reasoning (you already curate verified tool-calling list via aisuite 14 providers)
- 5.95GB still fits 4090 with room for 2nd model

**Next step:**
- Add to `scout infer` spec: `n-gram speculation: file-mapped, host RAM, opt-in`
- Benchmark: planning latency with vs without n-gram (keep agent + model constant, measure skill effect — see Idea C)

---

## Idea C: Benchmark Pattern Like Gradle — Measure If Instruction Helps

**What:** Gradle ships skills *with repeatable benchmarks* — keep agent + Gradle version constant, skill is variable. Dottie should do same for skills.

**How:**
- Dottie's skills live in `packages/ava-skills` (13 agents/11 packs/6 ultra). Each skill should ship with a `bench/` scenario:
  - Scenario keeps: `agent_version`, `model_version`, `task` constant
  - Variable: `skill_on` vs `skill_off`
  - Metric: `first_green_build_roundtrips`, `planning_latency_ms`, `tool_call_accuracy`
- Example for airLLM skill: same Qwen3.8-27B, same task (fix hoops build), with/without airLLM backend — does 3.3GB mode reduce retries?
- Store in `examples/goldens.jsonl` pattern — you already have goldens

**Why it matters for Launched:**
- You ship verifier ≥8.0, PWA v67 offline13k — benchmarks prove skill actually helps, not just vibes
- Factory mind: same sources → pipelines → features → models → product. Benchmark is your "does this instruction help" gate
- Prevents toy tracker trap (Aug 26) — genuinely utilitarian, simple, distinctive

**Next step:**
- Create `packages/ava-skills/skills/airllm-qwen38/bench.yaml` with 2 scenarios (27B 3.3GB, Flash-Next 5.95GB)
- Add to `playbooks/validation.yaml` — run nightly, same as router retrain 09:00 UTC
- Ship first benchmark result to `docs/LESSONS.md` with what/why/fix/prevents + confidence (your mistake → lesson pair rule)

---

## Monday Launched Relevance

- Launched is Aug 31 11:59 PM CT — 2 days out. airLLM optional backend is *not* a blocker, it's a post-Launched accelerator
- Safe path for Launched: document Idea A/B as "optional, isolated, not required for ship" — keeps zero-deps true, honest 503 intact
- Immediate win: add airLLM detection to `scout infer status` (vram null honest → now reports `airllm: not_installed | available`) — small, safe, shows you're thinking 2-3 moves ahead like Gradle did

## Action Items (for swarm)

1. **Today (pre-Launched):** Add `airllm` to `apps/scout-rtx` optional deps list (not root), add status probe to `scout infer status`, update `docs/DOTTIE_V2_SPEC.md` with "optional local inference tier: airLLM 3.3GB"
2. **Post-Launched Week 1:** Prototype Idea A in `apps/scout-rtx`, measure latency vs memory (block-wise 4bit/8bit), ship bench.yaml
3. **Post-Launched Week 2:** Prototype Idea B if Flash-Next weights available, file-mapped n-gram for planning mode
4. **Guardrail:** Never `pip install airllm` in root workspace — always isolated venv, always opt-in flag, always fail-closed with honest message

---
*Drafted 2026-08-30 12:39 CDT — for Dottie project swarm, from feed unit 367a5dd1*
