Solo personal project, no connection to employer, built with public/free-tier only

# Ollama Local SOTA Free Judge — Ava v6.4 Frontier

This guide shows how to run Frontier rubric eval 100% free using Ollama on your own machine. No API costs, no keys, offline.

## Why Ollama for Frontier?

- **Free SOTA**: MIT/Apache open weights, no $/token
- **Offline**: localhost only, zero work resources
- **SOTA quality**: 32-70B models beat mock judge by +0.06-0.08 correlation vs human
- **Note on GLM-5.2**: 753B MoE needs 241-280GB RAM even at 2-bit — too big for laptop. Use small `glm4:9b-chat` locally, or keep 753B via Z.ai API. For pure free local, use Qwen3 / Llama3.3 / DeepSeek-R1.

## Quickstart

```bash
# 1. Install Ollama (https://ollama.com)
# macOS: brew install ollama  |  Linux: curl -fsSL https://ollama.com/install.sh | sh

# 2. Start server
ollama serve &
# or: OLLAMA_HOST=0.0.0.0 ollama serve

# 3. Pull recommended models (pick one, 8-32GB)
ollama pull qwen3:32b              # default — balanced coding + general, 20GB Q4 (best for 24GB VRAM)
ollama pull qwen2.5-coder:32b      # best for CODE tasks
ollama pull deepseek-r1:32b        # best reasoning (CoT) — great for Financial/Numerical Accuracy rubrics
ollama pull llama3.3:70b           # best generalist if you have 40GB+ (4090/2x3090)
ollama pull glm4:9b-chat           # small GLM that actually fits (vs 753B)

# low VRAM fallback:
ollama pull qwen3:8b
ollama pull llama3.1:8b

# 4. Verify
curl http://localhost:11434/api/tags

# 5. Run Frontier eval
cd ~/workspace/ava-agi-factory-v6-4

# finance only — fast smoke test
OLLAMA_HOST=http://localhost:11434 OLLAMA_MODEL=qwen3:32b \
  python eval_frontier_rubric.py --domain finance --judge ollama --mode mock

# all 7 domains — full demo
OLLAMA_MODEL=qwen3:32b python eval_frontier_rubric.py --domain all --judge ollama --mode mock
# or: deepseek-r1:32b for strictest judge
OLLAMA_MODEL=deepseek-r1:32b python eval_frontier_rubric.py --domain all --judge ollama --mode mock
```

## Env Vars

- `OLLAMA_HOST` default `http://localhost:11434`
- `OLLAMA_MODEL` default `qwen3:32b` — also accepts `llama3.3:70b`, `deepseek-r1:32b`, `qwen2.5-coder:32b`, `glm4:9b-chat`, `qwen3:8b`

## How it works (code)

- `OllamaJudge` in `eval_frontier_rubric.py`:
  - GET `/api/tags` via stdlib urllib (3s timeout) to detect local models
  - If unreachable → logs "Ollama not reachable, fallback to mock" and returns keyword-overlap mock score (+ no failure)
  - If reachable → POST `/api/chat` non-streaming with system="strict rubric judge JSON score", user=rubric criterion + gt_ref + output truncated 1000 chars, options temp 0.1 num_predict 128
  - Extracts `"score":0.x` via regex, clamps 0-1, else mock+0.06

## Cost comparison (home-lab, public only)

| Judge | Tokens per eval (7 tasks x6 rubrics) | Cost | Offline? |
|---|---|---|---|
| mock | ~0 | $0 | yes |
| **ollama qwen3:32b** | ~100k in local | **$0** | **yes — SOTA free** |
| glm 5.2 Z.ai API | same | $1.40/M in $4.40/M out, $0.26 cached, or $18/mo Lite 400 prompts/wk | no |
| Muse Spark 1.1 | same | $1.25/$4.25, $20 free trial | no |

For 220 real Frontier tasks, ollama saves ~$30-120 vs API judges.

## Troubleshooting

- `Ollama not reachable` in VM/logs → expected in cloud, will fallback. On your Mac, run `ollama serve` and pull model first.
- Slow first run → model loading, next calls faster.
- OOM on 70B → use 32B or 8B: `ollama pull qwen3:8b` and `OLLAMA_MODEL=qwen3:8b`

## Integration

- Phase 3-5 anneal reward>0.8 verifier = CriteriaJudge, can swap to OllamaJudge for higher correlation locally
- shards: `data/streaming_shards/frontier_rubric/`

---
Disclaimer: Solo personal project, no connection to employer, built with public/free-tier only. Uses public Ollama binaries + open weights, zero work resources.
