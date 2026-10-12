# dottie-core

Clean-room agent harness: **agent = model + harness**.

- The **model** is a pure decision function: state in, scored answer out. No I/O.
- The **harness** owns lifecycle, policy, cost, HITL, verification, recording —
  all deterministic code, never prompts.

Zero dependencies. MIT licensed.

```bash
python3 examples/classify.py
python3 examples/custom_model.py   # plugin demo: custom Model via registry
```

## Tests

```bash
python3 -m unittest discover -s tests -v   # 27 tests, stdlib only
```

## Evals: Dottie on WorkGym

`evals/workgym_eval.py` runs a dottie-core Model as the policy on
[WorkGym](https://github.com/jcdavis131/workgym) environments — the gym that
trains Dottie also grades her. Baseline (2026-10-12, n=20/env):

| env | mean |
|---|---|
| `workgym/inbox-triage-v0` | 1.000 (hand-tuned keyword baseline) |
| `workgym/cron-ops-v0` | 0.900 |

See [evals/BASELINE.md](evals/BASELINE.md) for the honest read and the
challenger rules.

## Plugins

Swap the model, add a harness stage, or replace the policy engine — without
touching the core. Plugins are discovered via stdlib entry points:

```toml
[project.entry-points."dottie.models"]
my-model = "my_package.module:MyModel"
```

Kinds: `dottie.models`, `dottie.middleware`, `dottie.policies`.
See [plugins/README.md](plugins/README.md) for the author guide.
