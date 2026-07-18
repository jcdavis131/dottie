# BigBang RTX Plugin — Usage

This is the `bb rtx` plugin you requested, now part of BigBang CLI v0.5.5.

## Install

BigBang CLI v0.5.5 already includes `rtx` plugin (no extra install). Just:

```bash
cd ~/workspace/bigbang-cli
pip install -e . --break-system-packages -q
bb --help | grep rtx
```

## Quick offload flow

### 1. On Hatch Cloud (here) — queue tasks:

```bash
bb --json rtx status
bb --json rtx programs
bb --json rtx queue add --task "Optimize Ava router entropy threshold 0.7" --program programs/program-ava.md
bb --json rtx queue add --task "Find minimal Turnover Shield model <1.8MB ONNX" --program programs/program-turnover.md
bb --json rtx queue list
```

This writes to `~/workspace/autoresearch-rtx-custom/bb-offload/queue.json`

### 2. On Alienware Local — run autonomous research:

Copy the custom folder to Alienware:

```powershell
# On Windows Alienware:
cd C:\Users\jcdav\workspace
# Copy from Hatch workspace via Git or USB
git clone https://github.com/YOURNAME/autoresearch-rtx-custom.git
cd autoresearch-rtx-custom

# One-time setup:
.\scripts\setup-win.ps1 -Program programs\program-ava.md -Tag ava-jul15

# Check queue from cloud:
cat bb-offload\queue.json

# Start autonomous loop for Ava:
.\scripts\run-autonomous.ps1 -Program programs\program-ava.md -Tag ava-jul15

# In another terminal, start Claude Code:
# Prompt: "Hi have a look at program.md and let's kick off a new experiment! let's do the setup first."
# Claude will loop: edit train.py, git commit, uv run train.py 5-min, log results.tsv, keep/discard

# Or for fully autonomous (no extra agent, just baseline repeats):
uv run train.py --smoke-test
```

### 3. Monitor:

```powershell
# In Alienware:
.\scripts\sync-to-hatch.ps1 -Watch -IntervalSec 30
# Shows results.tsv tail + best val_bpb

# Back in Hatch cloud:
bb --json rtx results --best
bb --json rtx sync
```

### 4. Promote wins:

```bash
# After overnight run, best val_bpb shows:
bb rtx results --best

# Promote to Ava:
# Copy train.py diff idea to ~/workspace/ava-agi-factory-v6-4/model_1b.py
bb brain daily "RTX overnight: best val_bpb 0.9932 from program-ava, router entropy gating idea"

# Promote to Turnover Shield:
# Copy minimal model idea to Turnover Shield MVP
bb lab mrr --trials 3 --note "RTX found 0.22M params model <1.8MB"
```

## Ava + Agent routing

Now `bb ava route` and `bb agent run` understand offload:

```bash
bb --json ava route "offload this to my RTX box" # → rtx 0.95
bb --json ava route "optimize Ava on local GPU"
bb --json agent run "offload Ava research to RTX with program ava"
# → [bb ava status, bb rtx status, bb rtx queue add ...]
```

## Hardware tuning

Your RTX 4080 16GB → ada-16gb batch 32
Your RTX 4090 24GB → ada-24gb-plus batch 64

See `docs/HARDWARE_PROFILE.md` in custom repo for MFU expectations: 300-500M tokens / 5min.

## Solo disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. No work data.
