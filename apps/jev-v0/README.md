# jev-v0 — System One spike (small + LoRA + pointer heads)

Host overlay formalized from Cam's nugatron checkout. This app is a **typed
decision spike**, not a foundation-model train and not a TypeSafe clone.

**This is NOT `train_1b`.** It does not touch `apps/ava-factory` presets,
`AvaModel1B`, DeepSpeed, J-Space workspaces, or the smoke→nano→mini→base1b
ladder.

**This is NOT TypeSafe parity.** It does not call `api.typesafe.ai`, does not
serve `/v1/systemone`, does not install `typesafe-sdk`, and does not claim
Jev's undisclosed `confidence` formula or any reliability curve. The frozen
contract is `jev-decision-schema-1.0.0` (Choice / Score / Noul). Choice and
Score answers carry `shape_concentration` (max probability) — a named, local
statistic, not `confidence`. A dottie-loop consumer must wrap any scalar
through `backend_signal.BackendProbability` (`backend_confidence`). See
`docs/JEV_COLIBRI_INSIGHTS_SPEC.md`.

## Architecture pivot

The 1B-from-scratch path is the wrong first System One bet on this box.
The spike is:

- a **small** frozen causal LM (default `Qwen/Qwen2.5-0.5B`)
- **LoRA** on attention + MLP projections (r=16, alpha=32)
- **pointer heads** — query at `<decide>`, keys at each `</opt>`
- one closed distribution per question, no free-text decode

That is the same family as the public Jev-architecture reconstructions
(pointer readout over option-boundary tokens), implemented here as a
self-hosted overlay with a Dottie-shaped schema freeze.

## Layout

| Path | Role |
|---|---|
| `schema/decision_schema.json` | Frozen `jev-decision-schema-1.0.0` |
| `fixtures/synthetic_decisions.jsonl` | 8 synthetic operational tickets. No virus/malware content |
| `decision_io.py` | Stdlib load + validate (shared by train and serve) |
| `train_pointer_lora.py` | `--dry-run` (default, torch-free) / `--go` (optional HF+peft) |
| `serve_decide.py` | Typed `POST /decide` on `127.0.0.1:8770` |
| `requirements-jev-v0.txt` | `--go` extras only; not needed for dry-run or serve |

Excluded from the root uv workspace. Checkpoints under `runs/` stay gitignored.

## Dry-run (this PR's verification)

From `apps/jev-v0`:

```bash
python train_pointer_lora.py --dry-run
```

Exits 0, prints JSON with `dry_run: true`, `training: false`,
`torch_imported: false`, and the architecture plan. Validates every fixture
against the frozen schema. Refuses virus/malware wording.

Stdlib tests (no pytest, no torch):

```bash
python3 -m unittest discover -s apps/jev-v0/tests -v
```

Do **not** run `--go` from CI or from this PR. `--go` lazy-imports
torch / transformers / peft and would download a base model.

## Serve (typed `/decide`)

```bash
python serve_decide.py
# GET  http://127.0.0.1:8770/health
# POST http://127.0.0.1:8770/decide
```

Without a pointer checkpoint the server answers `mode=untrained` (uniform
over the offered set). That lets the typed contract be exercised without
GPU weights. It is not a calibrated decision.

Example:

```bash
python - <<'PY'
import json, urllib.request
body = {
  "schema": "jev-decision-schema-1.0.0",
  "state": {"ticket": "TD-1001", "message": "Charged twice on invoice 4412."},
  "questions": {
    "team": {
      "type": "choice",
      "instructions": "Which team should handle this ticket?",
      "criteria": {
        "billing": "Charges, invoices, refunds",
        "technical": "Bugs, outages, integrations",
        "other": "None of these"
      }
    },
    "urgent": {"type": "noul", "instructions": "Does the sender ask for help today?"}
  }
}
req = urllib.request.Request(
    "http://127.0.0.1:8770/decide",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(req, timeout=5).read().decode())
PY
```

## `--go` (host GPU only, not started here)

```bash
pip install -r requirements-jev-v0.txt   # plus the host CUDA torch wheel
python train_pointer_lora.py --go --steps 20 --out runs/jev-v0-pointer
```

`--go` is a spike trainer: LoRA + pointer head, cross-entropy over the
closed option set, synthetic fixtures only. It does not promote, does not
write into `apps/ava-factory`, and does not claim TypeSafe accuracy.

## Schema freeze

`schema/decision_schema.json` `$id` is `jev-decision-schema-1.0.0`. The
loader refuses any other `$id`. Limits refuse rather than truncate
(1–32 questions, Choice 2–255 options, Score 2–10 levels). Content
matching virus/malware wording is refused.
