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

## Plugins

Swap the model, add a harness stage, or replace the policy engine — without
touching the core. Plugins are discovered via stdlib entry points:

```toml
[project.entry-points."dottie.models"]
my-model = "my_package.module:MyModel"
```

Kinds: `dottie.models`, `dottie.middleware`, `dottie.policies`.
See [plugins/README.md](plugins/README.md) for the author guide.
