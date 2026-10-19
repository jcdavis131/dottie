# Veto pre-filter for `/decide`

The live HELPER on nugatron `:8770` is the off-tree factory-trainer Docker
image, not `apps/jev-v0` (a parked fixture). The halt-class matcher lives in a
dependency-free module any serve can import:

`packages/dottie-core/dottie_core/serving/veto.py`

`veto(command) -> VetoResult | None`. `wrap_decide(decide_fn)` runs it first:
a hit skips the model and returns Choice=`halt` with `veto_rule`; a parse
exception is logged (`veto_error: Type: msg` on stderr) and the model still
answers. The wrapper only ever adds a halt. There is no env kill-switch.

Halt classes: pipe a download into a shell interpreter, fork bomb, serve
control-plane URL (`/reload` and other admin paths on `:8770`/`:8765`/`:8769`,
loopback, `nugatron`, tailnet), `rm -rf` (any path, flag reorderings), `mkfs*`.

The in-tree dottie-core serve (`packages/dottie-core/dottie_core/serving/server.py`)
and the jev-v0 fixture both wrap `/decide` this way. The in-tree serves do not
implement `/reload`; unknown paths are 404.

## Factory-trainer (off-tree) integration

Five lines. Copy `dottie_core/serving/veto.py` next to the serve, or put
`packages/dottie-core` on `PYTHONPATH`.

```python
from dottie_core.serving.veto import wrap_decide

decide = wrap_decide(model.decide)
# POST /decide — parse errors fall through to the model
return decide(payload)
```

## Critic variant set

```bash
PYTHONPATH=packages/dottie-core python -m dottie_core.serving.veto --selftest
```

Runs every positive and every negative case, plus wrap_decide skip / fallthrough
/ halt-only checks. Exit 0 is green.
