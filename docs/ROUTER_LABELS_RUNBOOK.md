# Router labels: host runbook

How to turn real work into router labels on your own machine: start a local
model, probe the benchmark, pack, train the MLP router on CPU, evaluate it,
spot-check it, and (only if it earned it) stamp it. The rules behind each
step are in `docs/ARCHITECTURE.md` ("Data policy" and "The learning loop").

Nothing here promotes anything automatically. The heuristic stays the
authority until a candidate passes the gate AND you stamp it.

## 0. Once: a local model

```bash
ollama serve &                               # or the desktop app
ollama pull qwen2.5:7b-instruct              # the llm tier's default model
export OLLAMA_HOST=http://localhost:11434    # the one Ollama variable
# optional: another local model
export DOTTIE_LLM_MODEL=qwen2.5:14b-instruct
```

Optional backends, tried only after Ollama and only when both variables are
set (there is no default hosted model): `ANTHROPIC_API_KEY` +
`DOTTIE_ANTHROPIC_MODEL`, or `OPENAI_API_KEY` + `DOTTIE_OPENAI_MODEL`
(+ `OPENAI_BASE_URL`). Hosted calls cost money: set
`DOTTIE_LLM_PRICE_PER_MTOK_IN` / `_OUT` to have `cost_usd` recorded, otherwise
it is recorded as unpriced. `SEMANTIC_SCHOLAR_API_KEY` adds Semantic Scholar
to deep research (the keyless API rate-limits); `JARVIS_URL` adds your jarvisd
memories.

Check what the executors can reach:

```bash
curl -s "$OLLAMA_HOST/api/tags" | head -c 200
```

## 1. Probe the benchmark (benchmark-verified labels)

```bash
cd apps/scout-cli
uv run scout --json router probe --limit 20          # a quick look first
uv run scout --json router probe                     # all 221 goals
```

Each goal runs cheapest tier first (deterministic -> llm -> deep_research),
one tier up at a time, until its automatic verifier passes. Side-effecting
tiers are never probed. If a tier's backend is unreachable the probe stops for
that goal and records `unavailable` (no label): fix the backend and re-run.
`--past-unavailable` keeps going and records upper-bound labels, which the
pack refuses unless you pass `--allow-upper-bound`; use it only to exercise
the pipeline.

Traces land in `~/.dottie/traces/` (`DOTTIE_TRACE_DIR` overrides). Goal text is
stored only with `DOTTIE_TRACE_TEXT=1`; the pack joins the public benchmark
text from the committed goal set either way.

## 2. Collect production traces

Use Dottie for real work: `scout harness run "<goal>"` (or through jarvisd).
With the backends above up, nodes run their real executors and the outcome is
`executor: real`; a node whose backend is down falls back to its stub and the
run is `stub` (never a label). `DOTTIE_EXECUTORS=real` makes an unavailable
backend fail the node instead. The gate needs at least 50 production rows.

## 3. Pack, train, evaluate

```bash
uv run scout --json router pack --out ~/dottie-packs/router-001
uv run scout --json router train --mlp --pack ~/dottie-packs/router-001 --out ~/dottie-ckpt/router-mlp.json
uv run scout --json router eval --pack ~/dottie-packs/router-001 --checkpoint ~/dottie-ckpt/router-mlp.json
```

Read `MANIFEST.json` (rows by provenance, rejects with reasons) and the eval's
`refusals`. Expect refusals until there are 50+ production rows and the
candidate beats the heuristic on the production holdout without regressing on
the benchmark holdout.

The System One pointer-LoRA trains on the GPU host instead:
`scout router train --pack ... --go --out <ckpt dir>`.

## 4. Spot-check, then stamp (only if the gate passed)

```bash
uv run scout --json router spotcheck ~/dottie-ckpt/router-mlp.json --pack ~/dottie-packs/router-001 --n 20
# read ~/dottie-ckpt/router-mlp.json.spotcheck.json; for each label decide ok or bad, then:
uv run scout --json router spotcheck ~/dottie-ckpt/router-mlp.json --mark <id>=ok --mark <id>=bad ... --by <you>
uv run scout --json router promote ~/dottie-ckpt/router-mlp.json --i-have-reviewed --by <you>
```

`promote` refuses without a fully marked spot-check (more than 10% bad also
refuses), without `gate_passed: true`, or when the bytes changed since eval.
To route with the stamped MLP: `SCOUT_ORCH_MODEL=~/dottie-ckpt/router-mlp.json`
and `scout route --learned` (or `hints.learned` on `/api/decide`).
