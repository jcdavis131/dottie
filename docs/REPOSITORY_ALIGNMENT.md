# Repository alignment — 2026-09-11

`jcdavis131/dottie` is the canonical repository. Start new work from its current
`main`; use an isolated feature branch when an older local checkout has unfinished
changes. Fetching remote history does not make a divergent checkout current.

The Docker runtime fix is integrated with `main` through `c18943f`. It includes
all six workspace members and Git, with a repeatable real-container smoke test
documented in [image verification](../deploy/IMAGE_VERIFICATION.md).

## Work preserved for separate integration

| Lane | GitHub tracking | Disposition |
| --- | --- | --- |
| Pair capture, reward, benchmarks, closed loop | PR #28 | Open integration work; not part of the image fix |
| Slack ingress and inbox drain | PR #26; earlier PR #25 | Overlapping proposals; review the later implementation before consolidation |
| MLOps mission lifecycle | PR #24 | Separate feature with its own verification requirements |
| Autonomous web agent | `cursor/autonomous-web-agent` local branch | Unmerged work; do not copy it over current main |
| Distilled traces / older RLM research | `local/dottie-distill-traces` local branch | Divergent history, including patch-equivalent RLM fixes already on main |
| Old Bluehen console edits | Uncommitted in the research checkout | Preserved; no publication or promotion implied |

The local VM scaffold originally written under Vector Hoops is not the Dottie
platform. Future fleet work should use Dottie's existing Scout, jarvisd, and
`dottie_loop.forge` contracts. A declarative policy JSON file alone does not
enforce tool isolation or authorization.

## Local training preference

Use local Docker Desktop and the owner's NVIDIA GPU for underlying-model
training and model-backed evaluation when needed. On 2026-09-11 the runtime
successfully detected an RTX 4080 Laptop GPU with 12,282 MiB through Docker
`--gpus all`. This verifies device access, not a completed PyTorch training run.

Keep training dependencies in the existing factory/trainer image, separate from
the light daemon image. Follow the existing training queue, dataset provenance,
checkpoint, and evaluation gates. Choose batch size and model size for available
VRAM; record actual measurements. GPU access is not authorization to substitute
synthetic results for product benchmarks or to promote an unevaluated model.
