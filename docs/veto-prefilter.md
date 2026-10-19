# Veto pre-filter for `/decide`

The live HELPER on nugatron `:8770` is the off-tree factory-trainer Docker
image, not `apps/jev-v0` (a parked fixture). The halt-class matcher lives in a
dependency-free module any serve can import:

`packages/dottie-core/dottie_core/serving/veto.py`

`veto(command) -> VetoResult | None`. Wrap the **/decide handler** (the
function that receives the request payload), not `model.decide`. A hit skips
the model. Jev payloads return a frozen `decideResponse` (`schema`, `model`,
`mode` in `{untrained, pointer-lora}`, `answers`) with no extra keys — not a
`veto` mode and not `veto_rule`. Non-jev payloads still carry `veto_rule`.
The matcher is **fail-closed**: any exception, deadline, parse failure,
oversize field, or unknown construct returns halt (`veto_error` /
`veto_oversize`) and never execute. Failures are logged as
`veto_error: Type: msg` on stderr. The wrapper only ever adds a halt. There
is no env kill-switch.

Halt classes: pipe a download into a shell interpreter (`curl`/`wget`/`fetch`
into `sh`/`bash`/`zsh`/`python`, including `sh -c "$(curl …)"` and
`source <(curl …)`), fork bomb, serve control-plane URL (`/reload` and other
admin paths on `:8770`/`:8765`/`:8769`, loopback, `nugatron`, tailnet — after
percent-decode and `.`/`..` path normalize; search tools and non-serve ports
such as `localhost:3000/admin` do not match), `rm -rf` (any path, flag
reorderings, including `./build`), `mkfs*` and block-device wipes
(`dd of=/dev/sd*|xvd|mapper|md`, `tee`/`cp` onto those devices, `wipefs`,
`shred` of a device — not `shred file.txt`), extra download-to-interp pipes
(`node`/`ruby`/`php`, `curl > f; bash f`), and credential reads
(`~/.ssh/id_*`, `~/.aws/credentials`, `.env` / token files via
`cat`/`less`/`cp`/`scp`/`base64`/`python -c open`). Relative `find . -delete`
and `dd if=/dev/sdX of=file` (read) do not halt.

The in-tree dottie-core serve (`packages/dottie-core/dottie_core/serving/server.py`)
runs the veto on the raw `/decide` body before the model. Request bodies over
256 KiB return **413** (`veto_oversize`); a per-field cap inside the matcher
fail-closes as halt. Each snippet is scanned once, with a per-request work
budget. The jev-v0 fixture keeps its existing wrap. The in-tree serves do not
implement `/reload`; unknown paths are 404.

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
shape. `mode` stays on the frozen enum; Cam's alternative is a versioned
`veto` mode plus `veto_rule`.

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
