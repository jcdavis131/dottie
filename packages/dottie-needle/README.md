# dottie-needle

Dottie's **native** grammar-constrained function calling — our rewrite of the
Needle concept, built as stdlib-only Python. No vendor binary, no weights, no
telemetry, no new dependencies.

## The idea (one paragraph)

Cactus Needle 3's load-bearing trick is not the 35MB model — it is the
**grammar**: tool JSON schemas are compiled into a byte-level grammar at init,
so during decode a malformed tool call is *unreachable*, not just unlikely.
`dottie_needle` reimplements that trick natively:

- the model's short reasoning trace stays **unconstrained** free text;
- the emitted **call** — `{"tool": "<name>", "arguments": {...}}` — is
  grammar-bound and validated **fail-closed** before it ever reaches
  Dottie's tool plane.

Authorization still lives in `dottie_loop` (approvals/policy). This package
never executes anything and never authorizes anything.

## Tier 1 (this package, stdlib, works with any model)

- `dottie_needle.grammar` — compile tool specs into a strict validator:
  objects, arrays, strings (length/pattern/enum), integers/numbers
  (range/enum), booleans, null, const. Every failure names the position and
  what was expected. No trailing garbage, no duplicate keys, no trailing
  commas.
- `dottie_needle.engine` — the guided loop: top-k tool retrieval over tool
  descriptions (+ trigger regexes, mirroring Needle), prompt rendering with
  the compiled schema, generate → extract call span → validate → deterministic
  repair (up to N attempts with the grammar error fed back) → fail closed.
- `dottie_needle.bench` — golden set built from Dottie's real tool surface;
  measures valid-call rate with mock samplers (no model needed).

## Tier 2 (our own weights — Alienware GPU via Forge)

Train a ~7M-parameter function-calling model on pairs generated from Dottie's
real tool schemas, then run inference through a sampler **we own** — which is
what unlocks true per-step grammar masking ("invalid is unreachable" instead
of "invalid is rejected"). See `training/` (queued via Forge; needs the
Forge runner on Alienware).

## Layout

```
packages/dottie-needle/
  dottie_needle/
    __init__.py     public surface
    grammar.py      schema -> fail-closed validator (the grammar)
    engine.py       retrieval + guided generate/validate/repair loop
    bench.py        golden-set benchmark (mock samplers, no model needed)
  training/         Tier 2: arch spec, data pipeline, torch trainer, Forge job
  tests/            pytest suite (stdlib-only)
```
