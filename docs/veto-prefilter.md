# Veto pre-filter for `/decide`

The live HELPER on nugatron `:8770` is the off-tree factory-trainer Docker
image, not `apps/jev-v0` (a parked fixture). The halt-class matcher lives in a
dependency-free module any serve can import:

`packages/dottie-core/dottie_core/serving/veto.py`

`veto(command) -> VetoResult | None`. Wrap the **/decide handler** (the
function that receives the request payload), not `model.decide`. A hit skips
the model and returns a jev-schema body (`answers.<qid>.choice` / `.score` /
`.noul`) plus `veto_rule`. The matcher is **fail-closed**: any exception,
deadline, parse failure, oversize field, or unknown construct returns halt
(`veto_error` / `veto_oversize`) and never execute. Failures are logged as
`veto_error: Type: msg` on stderr. The wrapper only ever adds a halt. There
is no env kill-switch.

Halt classes: pipe a download into a shell interpreter, fork bomb, serve
control-plane URL (`/reload` and other admin paths on `:8770`/`:8765`/`:8769`,
loopback, `nugatron`, tailnet — after percent-decode and `.`/`..` path
normalize), `rm -rf` (any path, flag reorderings), `mkfs*` and other block-device
wipes (`dd of=/dev/sd*`, `wipefs`, `shred`).

The in-tree dottie-core serve (`packages/dottie-core/dottie_core/serving/server.py`)
runs the veto on the raw `/decide` body before the model. The jev-v0 fixture
keeps its existing wrap. The in-tree serves do not implement `/reload`; unknown
paths are 404.

## Factory-trainer (off-tree) integration

Put `packages/dottie-core` on `PYTHONPATH`, **or** copy `veto.py` next to the
serve and change the import to `from veto import wrap_decide`. Wrap the handler
that reads the request, not `model.decide`:

```python
from dottie_core.serving.veto import wrap_decide

decide = wrap_decide(handle_decide)
# POST /decide — parse errors, timeouts and unknown constructs halt
return decide(payload)
```

`handle_decide` is the function that already returns a jev decision body
(`schema`, `model`, `mode`, `answers`). A veto returns the same `answers`
shape plus `veto_rule`.

## Open question (Cam)

`rm -rf ./build`, `node_modules`, `dist`, and `/tmp/...` currently halt
(`rm_rf` on any path). That is by design until Cam picks a narrower policy
(for example only `/`, `~`, `$HOME`, `*`, or paths outside the working
directory). Do not change this in the matcher without that call.

## Critic variant set

```bash
PYTHONPATH=packages/dottie-core python -m dottie_core.serving.veto --selftest
```

Runs every positive and every negative case, plus wrap_decide skip / fallthrough
/ halt-only checks. Exit 0 is green.
