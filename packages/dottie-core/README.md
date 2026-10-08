# dottie-core

Clean-room agent harness: **agent = model + harness**.

- The **model** is a pure decision function: state in, scored answer out. No I/O.
- The **harness** owns lifecycle, policy, cost, HITL, verification, recording —
  all deterministic code, never prompts.

Zero dependencies. MIT licensed.

```bash
python3 examples/classify.py
```
