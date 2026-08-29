# Glimmer Scout-CLI Local Agent — Lane 2

**Branch:** `scout/glimmer-scout-cli`  
**Goal:** dynamic-tracking-always-on-orchestrator  
**Date:** 2026-08-29

## What shipped

Made scout-cli call local Glimmer (Meta Muse Glimmer 30B) instead of cloud:

### 1. Glimmer provider `bigbang/core/glimmer.py` (350 LOC)
- **Model discovery:** `GLIMMER_MODELS = ["muse-glimmer:30b", "muse-glimmer", ...]` priority-first in `PREFERRED_MODELS`
- **Ollama endpoint config:** `GLIMMER_BASE` > `OLLAMA_BASE` > `localhost:11434` / `host.docker.internal:11434`
  - `get_glimmer_endpoint()` honours env, fast DNS check, 30s cache
  - Honest 503 when offline
- **Text+Image multimodal:** `build_messages(prompt, images=[...])` encodes images to base64, Ollama `images[]` field
  - `_encode_image_to_b64(path)` 10MB limit, graceful None
  - Verified with real PNG tmpfile
- **Reasoning effort low/med/high/xhigh via system prompt** (Meta spec):
  - `REASONING_LEVELS` dict -> system prompt fragments
  - `build_system_prompt(level, extra)` composes `GLIMMER_BASE_SYSTEM` + level
  - Ollama options: low temp0.2 512 tok, med 0.4 1024, high 0.6 2048, xhigh 0.7 4096 ctx131k
- **Function calling:** `glimmer_chat_with_tools()` Ollama `/api/chat` tools array, DEFAULT_TOOLS (read_file/write_file/exec)
- **Coding tasks:** `test_glimmer_coding_task()` fib(n) prompt, `test_glimmer_tool_calling()`
- **Chat wrapper:** `glimmer_chat()` returns `{ok, content, model, base, elapsed, tokens, reasoning, has_images}` never raises

### 2. Updated `bigbang/core/llm.py`
- Added Glimmer models to front of `PREFERRED_MODELS` (priority)
- Added `GLIMMER_MODELS` alias export

### 3. Plugin `bigbang/plugins/glimmer/cli.py` + `manifest.yaml`
- `scout glimmer status` — endpoint, best model, glimmer models list, env, pull hint
- `scout glimmer chat "prompt" --reasoning medium --image file.png` — text+image
- `scout glimmer code "task"` — coding verification
- `scout glimmer tools` — function calling test
- `scout glimmer reason low|medium|high|xhigh` — show system prompt
- `scout glimmer pull --model muse-glimmer:30b` — ollama pull wrapper

### 4. Tests `tests/test_glimmer.py` (15 tests)
- Preferred models ordering
- Reasoning levels completeness
- System prompt composition
- Text-only and history messages
- Image encode missing/real
- Endpoint env var honoring
- Offline handling (honest 503)
- Available offline false
- Best model fallback and glimmer picking
- Plugin CLI exists
- GLIMMER_MODELS export

Verified manually (no pytest in env, ran via python -c):
- Import ok, multimodal encoding ok, all 4 reasoning prompts len 652-757, tools ok, offline handling ok

## How to use

```bash
# Pull model (one-time, needs ollama running)
ollama pull muse-glimmer:30b
# or
scout glimmer pull

# Check status
scout glimmer status

# Chat local (no cloud)
scout glimmer chat "explain this codebase" --reasoning medium

# With image
scout glimmer chat "describe this screenshot" --image ./shot.png --reasoning high

# Coding
scout glimmer code "write fib(n) iterative zero-deps" --reasoning high

# Tools
scout glimmer tools

# Reason level preview
scout glimmer reason xhigh

# In code
from bigbang.core.glimmer import glimmer_chat
res = glimmer_chat("hello", reasoning="low")
if res["ok"]:
    print(res["content"])
```

Env:
- `GLIMMER_BASE=http://localhost:11434` (or `OLLAMA_BASE`)
- `OLLAMA_URL` / `OLLAMA_HOST` also honoured

## Integration with always-on orchestrator

- Replaces cloud calls in churn aligner / heartbeat with local Glimmer
- 24GB VRAM single GPU, offline capable, no token bills
- Text+image for screenshot analysis (dashboard verification)
- xhigh reasoning for critical path analysis

## Next steps

- Wire `scout agent run` to use Glimmer provider by default when available
- Add to `scout herd` worker routing (cheapest tier)
- Measure tok/s vs cloud, add to MLOps observability
