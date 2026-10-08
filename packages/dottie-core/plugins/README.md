# Dottie Plugins — Author Guide

The core is minimal by design. Everything swappable — the decision function,
a harness stage, the policy engine — is a plugin. This guide shows you how
to write each kind, with working code, not abstract advice.

## The three plugin kinds

| Kind | Entry-point group | What it is |
|------|-------------------|------------|
| Model | `dottie.models` | The decision function: state in, scored answer out |
| Middleware | `dottie.middleware` | A harness stage: `Callable[[RunContext], RunContext]` |
| Policy | `dottie.policies` | A policy factory: `Callable[[], Policy]` |

## Hello world: a Model plugin

A Model is a pure function. No I/O, no side effects, deterministic given
(state, query). Implement the `Model` protocol:

```python
# my_package/optimist.py
from dottie_core import Model, QueryKind, ScoredAnswer, ScoredValue, TypedQuery, WorldState

class OptimistModel:
    """Always confident. (Don't ship this. It's a demo.)"""

    model_id = "optimist-v0"
    calibration = "uncalibrated"

    def decide(self, state: WorldState, query: TypedQuery) -> ScoredAnswer:
        if query.kind == QueryKind.CHOOSE and query.options:
            # Pick the first option with maximum confidence.
            return ScoredAnswer(
                best=ScoredValue(value=query.options[0], confidence=0.99),
                alternatives=tuple(
                    ScoredValue(value=o, confidence=0.01)
                    for o in query.options[1:]
                ),
                model_id=self.model_id,
                calibration=self.calibration,
            )
        # For anything else, abstain honestly.
        return ScoredAnswer(
            best=ScoredValue(value=None, confidence=0.0),
            alternatives=(),
            model_id=self.model_id,
            calibration=self.calibration,
        )
```

Register it in your `pyproject.toml`:

```toml
[project.entry-points."dottie.models"]
optimist-v0 = "my_package.optimist:OptimistModel"
```

Use it — no core changes needed:

```python
from dottie_core import Goal, Harness, default_policy, plugins

model_cls = plugins.load("model", "optimist-v0")
harness = Harness(model=model_cls(), policy=default_policy())
result = harness.run(Goal(intent="do the thing", state_seed={}))
```

See `../examples/custom_model.py` for a complete runnable Model plugin
(a structural classifier — different decision procedure, same protocol).

## A Middleware plugin

Middleware is a stage in the chain: `observe -> policy_gate -> route ->
execute -> verify -> record`. A custom stage has the same signature:

```python
# my_package/audit.py
from dottie_core.harness import RunContext

def audit_trail(ctx: RunContext) -> RunContext:
    """Append a timestamped marker to state before execution.

    Middleware sees the full RunContext (goal, state, policy, model, cost)
    and returns it, possibly modified. Keep it pure: no I/O here either —
    write markers into state, let the record stage persist them.
    """
    from dottie_core import Belief
    marker = Belief(
        belief_id=f"audit-{ctx.state.version}",
        key="audit_marker",
        value={"stage": "pre-execute", "tier": ctx.tier},
        confidence=1.0,
        source="middleware:audit",
        at_version=ctx.state.version,
    )
    ctx.state = ctx.state.update(marker, actor="audit-middleware")
    return ctx
```

```toml
[project.entry-points."dottie.middleware"]
audit-trail = "my_package.audit:audit_trail"
```

Wire it into a custom chain:

```python
from dottie_core import Harness, default_policy, plugins
from dottie_core.harness import DEFAULT_CHAIN, execute

audit = plugins.load("middleware", "audit-trail")
# Insert before execute, keep everything else.
chain = tuple(
    audit if stage is execute else stage
    for stage in DEFAULT_CHAIN
)
# Hmm — that replaces execute. To INSERT, splice instead:
idx = DEFAULT_CHAIN.index(execute)
chain = DEFAULT_CHAIN[:idx] + (audit,) + DEFAULT_CHAIN[idx:]

harness = Harness(model=model, policy=default_policy(), chain=chain)
```

## A Policy plugin

A Policy is a set of default-deny rules. Provide a factory:

```python
# my_package/strict.py
from dottie_core import Policy
from dottie_core.policy import PolicyRule

def strict_policy() -> Policy:
    """Deny everything except read-only tool calls."""
    return Policy(rules=(
        PolicyRule(
            rule_id="allow-read-only",
            action_kinds=("tool_call",),
            side_effect_classes=("read_only",),
            effect="allow",
            reason="read-only tools are safe",
        ),
        # No match = deny (default-deny). No catch-all allow rule.
    ))
```

```toml
[project.entry-points."dottie.policies"]
strict = "my_package.strict:strict_policy"
```

```python
policy_factory = plugins.load("policy", "strict")
harness = Harness(model=model, policy=policy_factory())
```

## Discovery without installing

For scripts and tests, skip the install step:

```python
from dottie_core import plugins

plugins.register("model", "my-model", MyModel)  # object, not string
plugins.register("model", "other", "my_package.mod:OtherModel")  # lazy import

print(plugins.discover("model"))  # {'my-model': ..., 'other': ...}
model_cls = plugins.load("model", "my-model")
```

`register()` shadows entry points of the same name — that's how tests
swap in fakes without touching installed packages.

## Rules for plugin authors

1. **Models are pure.** No I/O, no network, no file reads in `decide()`.
   If your model needs data, it comes in through the state.
2. **Confidence is honest.** Uncalibrated models get capped by the harness.
   Don't inflate scores to game routing — the harness will escalate anyway.
3. **Middleware is transparent.** Each stage must return a valid RunContext.
   Don't swallow `ctx.halted` — a halted context stays halted.
4. **Policy is default-deny.** Your Policy should deny by default and allow
   explicitly. If your rules allow everything, you've built a footgun.
5. **No core imports at module top-level** that aren't in `dottie_core`.
   Plugins depend on the core, never the reverse.
