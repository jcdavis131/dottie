# Offloading Guide — Cloud Hatch ↔ Alienware RTX

This custom fork lets you offload heavy tasks from Hatch cloud (BigBang CLI, Ava, Passive Lab) to your Alienware RTX 4080/4090 Windows box.

## Architecture

```
[Hatch Cloud VM]                          [Alienware Local]
----------------                          ------------------
bigbang-cli v0.5                          C:\Users\jcdav\workspace\autoresearch-rtx-custom
- bb write scan/humanize (CPU)            - uv + torch 2.9.1 cu128 + SDPA
- bb lab ideas/mrr (CPU)                  - RTX 4080 16GB / 4090 24GB
- bb brain goals/memory sync              - Ollama qwen3:32b + deepseek-r1:32b
- bb ava route 0.93/0.91/0.90              - program-ava / turnover / write tracks
- scout rtx queue add ...  ───queue.json──→   - scripts\sync-to-hatch.ps1 watches queue
                                          - Claude / Codex agent edits train.py
                                          - uv run train.py 5-min loop
                                          - results.tsv + bb-offload/results.jsonl
- scout rtx results   ←────results.jsonl──── - ./scripts/sync-to-hatch.ps1
- scout rtx dashboard (web artifact)
```

## Offload scenarios

### 1. Offload Ava research (best use of RTX)

You have Ava v6.4 Docker stack that trains 1B model. This custom runs fast 5-min TinyStories proxy experiments that map to Ava ideas.

From Hatch cloud:
```bash
# Create offload task
scout --json brain sync --out /tmp/brain-sync.json
# Copy brain-sync.json manually to Alienware bb-offload/sync.json (or via WSL mount)

# In Alienware PowerShell:
cd C:\Users\jcdav\workspace\autoresearch-rtx-custom
./scripts/run-autonomous.ps1 -Program programs\program-ava.md -Tag ava-jul15
# Then start Claude:
# "Hi have a look at program.md and let's kick off a new experiment! let's do the setup first."
# Claude will autonomously loop: edit train.py, commit, run, log, keep/discard

# Back in Hatch, after few hours:
scout rtx results
# → shows best val_bpb, maps to Ava Router/veto etc
```

Promote win: take best commit diff, copy idea into `~/workspace/ava-agi-factory-v6-4/model_1b.py`

### 2. Offload Turnover Shield model search

Find minimal ONNX model <2MB for churn prediction.

```powershell
./scripts/run-autonomous.ps1 -Program programs\program-turnover.md -Tag turnover-jul15
```

Agent will Pareto search depth 4-6, params 0.22M etc. Results in `bb-offload/results/turnover.jsonl` → promote to `bb lab shield`.

### 3. Offload Write detector evolution

```powershell
./scripts/run-autonomous.ps1 -Program programs\program-write.md -Tag write-jul15
```

Agent evolves detector weights (participial 0.5 etc). Best weights → update `bigbang-cli/bigbang/plugins/write/cli.py`.

### 4. Queue from Hatch (automated)

We created `bb-offload/queue.json` schema:

```json
{
  "tasks": [
    {"id":"2026-07-15T16:19:23Z","task":"optimize Ava router entropy threshold","program":"program-ava.md","status":"pending"},
    {"id":"2026-07-15T16:20:00Z","task":"find minimal Turnover Shield model <1.8MB","program":"program-turnover.md","status":"pending"}
  ]
}
```

Your local sync script can poll this queue and auto-start agents.

Future: scout rtx plugin will do this automatically via file watcher + local API.

## Setup steps detailed

**In Alienware:**

1. Install prerequisites (PowerShell Admin):
```powershell
winget install --id Astral.UV -e
winget install --id Ollama.Ollama -e
# CUDA driver already present via nvidia-smi
```

2. Clone custom:
```powershell
cd C:\Users\jcdav\workspace
git clone <this-repo> autoresearch-rtx-custom
cd autoresearch-rtx-custom
./scripts/setup-win.ps1 -Program programs\program-base.md
```

3. Verify VRAM profile:
Look at log from `uv run train.py` — should say `gpu_profile` ada-16gb or ada-24gb-plus, amp_dtype bfloat16, TF32 enabled, SDPA.

4. Start agent:
Install Claude Code or Cursor, open folder, prompt: "Hi have a look at program.md and let's kick off a new experiment! let's do the setup first."

**In Hatch cloud (this browser):**

Already has `scout rtx` plugin after next step.

## BigBang plugin install

In `~/workspace/bigbang-cli/bigbang/plugins/rtx/` (we will create next), you get:

- `scout rtx status` — shows local RTX status if sync file present
- `scout rtx queue add "task"` — adds to bb-offload/queue.json (you manually copy to Alienware or via future Tailscale)
- `scout rtx queue list`
- `scout rtx results` — reads bb-offload/results/results.jsonl
- `scout rtx dashboard` — opens web artifact monitoring experiments
- `scout rtx sync` — pulls results into `~/workspace/projects/...`

## Data flow for $1k MRR goal

- `bb lab shield` → shows Turnover Shield MVP
- Offload: `scout rtx queue add "optimize churn model <2MB"` → Alienware runs program-turnover.md → finds 0.22M params model → result syncs → you update Shield MVP → `bb lab mrr --paid 1 --mrr 79`

## Security / disclaimers

- All code runs local on your Alienware, not in cloud. Cloud only sees results.tsv logs.
- No work IP (PAJAMA / Ursa Major) in this fork — home only.
- Footer: Solo personal project, no connection to employer, built with public/free-tier only.
- Torch cu128 official wheels, no unofficial Triton for Windows.

## Next steps after first overnight run

1. Review `results.tsv` — best val_bpb commits are `keep`
2. `git log --oneline --graph` shows experiment lineage
3. Promote win to appropriate repo:
   - Ava win → `~/workspace/ava-agi-factory-v6-4/`
   - Turnover win → `~/workspace/projects/first-1k-mo-passive/`
   - Write win → `~/workspace/bigbang-cli/bigbang/plugins/write/`
4. `bb brain daily "RTX results: ..."`
5. `bb lab mrr --trials X --note "RTX overnight"`
