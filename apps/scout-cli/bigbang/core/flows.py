# Solo personal project, no connection to employer, built with public/free-tier only
"""Flows — JSON workflow graph core (openswap #27: Zapier / Make / n8n Cloud).

The paid enemy is a hosted automation runner: your trigger, your data and your
credentials all live on someone else's box, and the pricing unit is the "task"
— a counted step. This adapter inverts every part of that: the graph is a JSON
file in your repo, the runner is this module, the steps are free, and NOTHING
leaves the machine (the manifest disables the network axis outright, so "no
payload was shipped anywhere" is architectural rather than a ToS promise).

The shape is Zapier's: a `trigger` fires, `transform` nodes reshape the
payload, `action` nodes cause effects. What is deliberately NOT Zapier's is the
execution model, because an automation runner that can loop forever or call
anything it likes is a footgun with a cron entry:

- BOUNDED STEPS. Every visited node costs one step from a SHARED budget
  ({"used", "cap"} — a sub-flow spends the same budget, so nesting can never
  buy more steps). Hitting the cap is a REFUSAL with the node named, not a
  truncated success.
- NO UNBOUNDED LOOPS. validate() refuses a cyclic graph before the first step,
  and the runner independently caps per-node visits (max_visits, default 1), so
  a graph that dodges validation still terminates. Two independent guards
  because one of them will eventually be bypassed.
- BOUNDED RECURSION. A `flow` node runs a named sub-flow from an injected
  registry; depth is capped (max_depth, default 3) and a self-referencing flow
  is refused at the cap, by name.
- DEFAULT-DENY ACTIONS. An action executes only when its `uses` name is in the
  caller's allowlist AND in this module's ACTIONS catalog AND an effector for
  it was injected. Any of those missing is a recorded refusal that STOPS the
  run (fail closed — continuing past a skipped effect would run downstream
  nodes on a payload that never got its effect, which is the silent-corruption
  failure mode this design exists to kill). The default allowlist is EMPTY.

Honesty invariants, enforced in code rather than documented:
- Every step records EITHER `output` OR `error`, never both and never neither
  (_step raises if that is violated) — so a step can never read as a success
  with nothing behind it.
- Nothing is invented to fill a field: a transform whose source path is absent
  RAISES (copy/count/template/pick), a comparison against an absent field is
  False rather than a coerced zero, an effector that returns no result is
  recorded as an error, and every refusal carries the reason and the node.
- A trigger that does not fire produces outcome "not-triggered" WITH the
  reason, never a silent no-op.

Real I/O lives in the plugin CLI (bigbang/plugins/flows/cli.py): it reads the
flow JSON, resolves the action allowlist, injects the effectors that actually
touch the filesystem, and gates writes on the manifest. This module opens no
socket and writes no file — the only filesystem thing here is the sqlite run
ledger (`.scout/flows.db`, its own file so a busy automation never contends
with the #2 uptime ledger's write lock), which is what makes Zapier's "task
history" pane a local table.

Extension points:
- New actions: add a catalog entry to ACTIONS (name, effects, required and
  optional params) and inject an effector of the same name. validate() starts
  checking its params immediately; the allowlist keeps it off by default.
- New transform ops / condition ops: TRANSFORM_OPS and PREDICATE_OPS are the
  registries; both are pure and total (unknown op -> ValueError -> a recorded
  step error, never a skip).
- Scheduling: last_run_ts() reads the real last run out of the ledger and feeds
  trigger_check's schedule branch — the cadence decision is made from recorded
  data, never from a guessed timestamp.
- Family gate: to_diagnostics() maps validation problems AND run refusals onto
  the openswap diagnostic schema, so `plan --fail-on` / `run --fail-on` behave
  exactly like a prose lint or an uptime outage gate.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

SEV_ERROR = "error"
SEV_WARNING = "warning"

# ---- the graph vocabulary ----------------------------------------------------

KIND_TRANSFORM = "transform"
KIND_FILTER = "filter"
KIND_BRANCH = "branch"
KIND_ACTION = "action"
KIND_FLOW = "flow"
KINDS = (KIND_TRANSFORM, KIND_FILTER, KIND_BRANCH, KIND_ACTION, KIND_FLOW)

TRIGGER_MANUAL = "manual"
TRIGGER_EVENT = "event"
TRIGGER_SCHEDULE = "schedule"
TRIGGERS = (TRIGGER_MANUAL, TRIGGER_EVENT, TRIGGER_SCHEDULE)

# Bounds. Every one of these is a hard cap, not a hint, and every one is
# overridable per call so a bigger graph is a config decision, never a code edit.
DEFAULT_MAX_STEPS = 50
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_VISITS = 1

OUTCOME_OK = "ok"
OUTCOME_FILTERED = "filtered"
OUTCOME_NOT_TRIGGERED = "not-triggered"
OUTCOME_REFUSED = "refused"
OUTCOME_FAILED = "failed"
OUTCOMES = (
    OUTCOME_OK,
    OUTCOME_FILTERED,
    OUTCOME_NOT_TRIGGERED,
    OUTCOME_REFUSED,
    OUTCOME_FAILED,
)

# refusal codes — the runner never skips silently, it refuses with one of these
R_INVALID_FLOW = "invalid-flow"
R_STEP_CAP = "step-cap"
R_VISIT_CAP = "visit-cap"
R_DEPTH_CAP = "depth-cap"
R_UNKNOWN_NODE = "unknown-node"
R_UNKNOWN_ACTION = "unknown-action"
R_NOT_ALLOWLISTED = "action-not-allowlisted"
R_NO_EFFECTOR = "effector-missing"
R_SUBFLOW_MISSING = "subflow-missing"
REFUSAL_CODES = (
    R_INVALID_FLOW,
    R_STEP_CAP,
    R_VISIT_CAP,
    R_DEPTH_CAP,
    R_UNKNOWN_NODE,
    R_UNKNOWN_ACTION,
    R_NOT_ALLOWLISTED,
    R_NO_EFFECTOR,
    R_SUBFLOW_MISSING,
)

# The action catalog. `effects` is the honest blast-radius label that `actions`
# publishes; `params`/`optional` are what validate() checks so a typo'd
# parameter is an error at plan time instead of a no-op at 3am. Every action
# here still needs to be in the caller's allowlist to run.
ACTIONS: dict[str, dict[str, Any]] = {
    "emit": {
        "effects": "none",
        "params": (),
        "optional": ("fields",),
        "description": (
            "return part of the payload as the step result (and, with `into`, "
            "back into the payload) — no side effect at all, the JSON envelope "
            "is the deliverable"
        ),
    },
    "write_file": {
        "effects": "filesystem",
        "params": ("file", "from"),
        "optional": (),
        "description": (
            "write the value at payload path `from` to `file`, confined to the "
            "caller's output directory (utf-8 bytes, no CRLF translation)"
        ),
    },
    "append_jsonl": {
        "effects": "filesystem",
        "params": ("file",),
        "optional": ("fields",),
        "description": (
            "append one deterministic JSON line (whole payload, or just "
            "`fields`) to `file` inside the caller's output directory"
        ),
    },
}

_MISSING = object()


# ---- field paths ------------------------------------------------------------


def split_path(path: Any) -> list[str]:
    """'a.b.0' -> ['a','b','0']. Raises on anything that is not a usable path."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"a field path must be a non-empty string, got {path!r}")
    parts = [p for p in path.strip().split(".") if p != ""]
    if not parts:
        raise ValueError(f"unusable field path {path!r}")
    return parts


def _as_index(part: str) -> int | None:
    try:
        return int(part)
    except ValueError:
        return None


def get_path(data: Any, path: Any, default: Any = None) -> Any:
    """Read a dotted path out of nested dicts/lists; `default` when absent.

    List elements are addressed by integer segment (negative indexes allowed).
    A path that walks into a scalar is absent, not an error — the caller decides
    whether absence is fatal (transforms say yes, conditions say False).
    """
    cur = data
    for part in split_path(path):
        if isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        elif isinstance(cur, (list, tuple)):
            idx = _as_index(part)
            if idx is None or not -len(cur) <= idx < len(cur):
                return default
            cur = cur[idx]
        else:
            return default
    return cur


def has_path(data: Any, path: Any) -> bool:
    """True when the path resolves — distinguishes 'absent' from 'present, None'."""
    return get_path(data, path, _MISSING) is not _MISSING


def require_field(data: Any, path: Any) -> Any:
    """get_path, but an absent path RAISES — nothing is ever invented."""
    value = get_path(data, path, _MISSING)
    if value is _MISSING:
        raise ValueError(f"payload has no field {path!r}")
    return value


def set_path(data: dict[str, Any], path: Any, value: Any) -> dict[str, Any]:
    """Return a COPY of `data` with `path` set; intermediate dicts are created.

    Writes address dict keys only (a list element is read-only here) — the
    alternative is silently growing lists to fit an index, which invents data.
    """
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object to write into")
    parts = split_path(path)
    out = copy.deepcopy(data)
    cur = out
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = copy.deepcopy(value)
    return out


def remove_path(data: dict[str, Any], path: Any) -> tuple[dict[str, Any], bool]:
    """(copy without `path`, whether anything was actually removed)."""
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object to remove from")
    parts = split_path(path)
    out = copy.deepcopy(data)
    cur: Any = out
    for part in parts[:-1]:
        cur = cur.get(part) if isinstance(cur, dict) else None
        if not isinstance(cur, dict):
            return out, False
    if isinstance(cur, dict) and parts[-1] in cur:
        del cur[parts[-1]]
        return out, True
    return out, False


def pick_fields(data: dict[str, Any], fields: Sequence[Any]) -> dict[str, Any]:
    """{last path segment: value} for each field. Absent or colliding -> raise.

    Both refusals matter: a missing column must not quietly vanish from a
    digest, and two fields whose last segment collides ('a.id' and 'b.id')
    would otherwise silently drop one of the two.
    """
    if not isinstance(fields, (list, tuple)) or not fields:
        raise ValueError("`fields` must be a non-empty list of field paths")
    out: dict[str, Any] = {}
    for field in fields:
        key = split_path(field)[-1]
        if key in out:
            raise ValueError(f"field {field!r} collides with an earlier pick on {key!r}")
        out[key] = copy.deepcopy(require_field(data, field))
    return out


def select_fields(
    data: dict[str, Any], fields: Sequence[Any] | None = None
) -> dict[str, Any]:
    """pick_fields, or a deep copy of the whole payload when fields is None."""
    if fields is None:
        return copy.deepcopy(data)
    return pick_fields(data, fields)


def as_text(value: Any) -> str:
    """Deterministic text for a payload value (sorted keys for containers)."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


# ---- templates --------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{([^{}]*)\}")


def render_template(text: Any, data: dict[str, Any]) -> str:
    """Substitute {dotted.path} from `data`; a missing path RAISES.

    No escape syntax and no nesting: a template is a one-line label, and a
    silently empty substitution is how an automation emails "  alerts" at 3am.
    """
    if not isinstance(text, str):
        raise ValueError(f"template must be a string, got {type(text).__name__}")

    def _sub(match: re.Match[str]) -> str:
        ref = match.group(1).strip()
        if not ref:
            raise ValueError(f"empty {{}} reference in template {text!r}")
        return as_text(require_field(data, ref))

    return _TEMPLATE_RE.sub(_sub, text)


# ---- conditions -------------------------------------------------------------

PREDICATE_OPS = (
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "contains",
    "in",
    "exists",
    "missing",
    "truthy",
)
_ORDERED_OPS = ("lt", "le", "gt", "ge")


def _as_number(value: Any) -> float | None:
    """A magnitude, or None. A bool is NOT a magnitude (True is not 1 here)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _contains(container: Any, needle: Any) -> bool:
    if isinstance(container, str):
        return isinstance(needle, str) and needle in container
    if isinstance(container, (list, tuple, dict, set)):
        try:
            return needle in container
        except TypeError:
            return False
    return False


def evaluate(pred: Any, data: dict[str, Any]) -> bool:
    """Evaluate one condition {path, op, value}. No eval, no expressions.

    An absent field is False for every comparison (and True for `missing`),
    never a crash and never coerced to 0/"" — the two shapes that make an
    automation fire on data it never saw. An unknown op raises so it surfaces
    as a step error instead of a default-False skip.
    """
    if not isinstance(pred, dict):
        raise ValueError("a condition must be an object {path, op, value}")
    op = pred.get("op")
    if op not in PREDICATE_OPS:
        raise ValueError(
            f"unknown condition op {op!r} (choose from {'|'.join(PREDICATE_OPS)})"
        )
    if "path" not in pred:
        raise ValueError(f"condition {op!r} needs a `path`")
    left = get_path(data, pred["path"], _MISSING)
    if op == "exists":
        return left is not _MISSING
    if op == "missing":
        return left is _MISSING
    if left is _MISSING:
        return False
    if op == "truthy":
        return bool(left)
    want = pred.get("value")
    if op == "eq":
        return bool(left == want)
    if op == "ne":
        return bool(left != want)
    if op == "contains":
        return _contains(left, want)
    if op == "in":
        return _contains(want, left)
    lo, ro = _as_number(left), _as_number(want)
    if lo is None or ro is None:
        raise ValueError(f"op {op!r} needs two numbers, got {left!r} and {want!r}")
    if op == "lt":
        return lo < ro
    if op == "le":
        return lo <= ro
    if op == "gt":
        return lo > ro
    return lo >= ro


# ---- transforms -------------------------------------------------------------

OP_SET = "set"
OP_COPY = "copy"
OP_REMOVE = "remove"
OP_TEMPLATE = "template"
OP_PICK = "pick"
OP_COUNT = "count"
OP_DEFAULT = "default"
TRANSFORM_OPS = (OP_SET, OP_COPY, OP_REMOVE, OP_TEMPLATE, OP_PICK, OP_COUNT, OP_DEFAULT)


def _op_count(data: dict[str, Any], spec: dict[str, Any]) -> tuple[Any, int]:
    """Length of the sized value at `from`; a scalar has no length -> raise."""
    src = require_field(data, spec.get("from"))
    if isinstance(src, (list, tuple, dict, str)):
        return src, len(src)
    raise ValueError(f"count needs a list/dict/string at {spec.get('from')!r}")


# required keys per op — checked STRUCTURALLY at validate time (no payload
# needed), which is what lets `plan` catch a typo'd op before it runs at 3am.
_OP_REQUIRES: dict[str, tuple[str, ...]] = {
    OP_SET: ("path",),
    OP_COPY: ("path", "from"),
    OP_REMOVE: ("path",),
    OP_TEMPLATE: ("path", "text"),
    OP_PICK: ("fields",),
    OP_COUNT: ("path", "from"),
    OP_DEFAULT: ("path",),
}


def check_op_shape(spec: Any) -> str | None:
    """Structural complaint about one transform op, or None when the shape is fine.

    Shape only — whether the payload actually HAS the source field is a runtime
    fact, so it is not guessed at here (that would either reject valid flows or
    pretend to have checked something it cannot see).
    """
    if not isinstance(spec, dict):
        return f"op must be an object, got {type(spec).__name__}"
    name = spec.get("op")
    if name not in TRANSFORM_OPS:
        return f"unknown transform op {name!r} (choose from {'|'.join(TRANSFORM_OPS)})"
    for key in _OP_REQUIRES[name]:
        if key not in spec:
            return f"op {name!r} needs `{key}`"
    for key in ("path", "from"):
        if key in spec and (key != "path" or name != OP_PICK):
            try:
                split_path(spec[key])
            except ValueError as exc:
                return f"op {name!r}: bad `{key}` — {exc}"
    if name == OP_PICK and spec.get("path") is not None:
        try:
            split_path(spec["path"])
        except ValueError as exc:
            return f"op {name!r}: bad `path` — {exc}"
    if name == OP_TEMPLATE and not isinstance(spec.get("text"), str):
        return f"op {name!r}: `text` must be a string"
    if name == OP_PICK and (
        not isinstance(spec.get("fields"), (list, tuple)) or not spec["fields"]
    ):
        return f"op {name!r}: `fields` must be a non-empty list"
    return None


def apply_transform(
    ops: Any, data: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Apply an `ops` list to a COPY of the payload -> (new payload, notes).

    Notes are the audit line for the step ('set totals.n', 'remove x (absent)')
    so a transform's effect is visible in the run record without dumping the
    whole payload at every step. Any bad spec raises ValueError, which the
    runner records as a step error and a FAILED run — never a skipped op.
    """
    if not isinstance(ops, list) or not ops:
        raise ValueError("a transform needs a non-empty `ops` list")
    out = copy.deepcopy(data)
    notes: list[str] = []
    for i, spec in enumerate(ops, start=1):
        if not isinstance(spec, dict):
            raise ValueError(f"op #{i} must be an object, got {type(spec).__name__}")
        name = spec.get("op")
        if name not in TRANSFORM_OPS:
            raise ValueError(
                f"op #{i}: unknown transform op {name!r} "
                f"(choose from {'|'.join(TRANSFORM_OPS)})"
            )
        path = spec.get("path")
        if name == OP_SET:
            out = set_path(out, path, spec.get("value"))
            notes.append(f"set {path}")
        elif name == OP_COPY:
            out = set_path(out, path, require_field(out, spec.get("from")))
            notes.append(f"copy {spec.get('from')} -> {path}")
        elif name == OP_REMOVE:
            out, removed = remove_path(out, path)
            notes.append(f"remove {path}" + ("" if removed else " (absent)"))
        elif name == OP_TEMPLATE:
            out = set_path(out, path, render_template(spec.get("text"), out))
            notes.append(f"template {path}")
        elif name == OP_PICK:
            picked = pick_fields(out, spec.get("fields"))
            out = set_path(out, path, picked) if path is not None else picked
            notes.append(f"pick {len(picked)} field(s)" + (f" -> {path}" if path else ""))
        elif name == OP_COUNT:
            _src, size = _op_count(out, spec)
            out = set_path(out, path, size)
            notes.append(f"count {spec.get('from')} = {size} -> {path}")
        else:  # OP_DEFAULT
            if has_path(out, path):
                notes.append(f"default {path} (already set)")
            else:
                out = set_path(out, path, spec.get("value"))
                notes.append(f"default {path} applied")
    return out, notes


# ---- graph shape ------------------------------------------------------------


def successors(node: Any) -> list[str]:
    """Outgoing edges of one node: `next`, or a branch's `then`/`else`."""
    if not isinstance(node, dict):
        return []
    if node.get("kind") == KIND_BRANCH:
        return [str(v) for v in (node.get("then"), node.get("else")) if v]
    nxt = node.get("next")
    return [str(nxt)] if nxt else []


def walk_order(flow: Any) -> list[str]:
    """Reachable node ids, breadth-first from `start` — 'what can run'."""
    nodes = (flow or {}).get("nodes") or {}
    start = (flow or {}).get("start")
    if not isinstance(nodes, dict) or start not in nodes:
        return []
    order: list[str] = []
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in successors(nodes.get(current)):
            if nxt in nodes and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return order


def has_cycle(flow: Any) -> list[str]:
    """The first cycle found as a node-id path, or [] when the graph is acyclic."""
    nodes = (flow or {}).get("nodes") or {}
    if not isinstance(nodes, dict):
        return []
    state: dict[str, int] = {}
    for root in nodes:
        if state.get(root):
            continue
        stack: list[tuple[str, list[str]]] = [(root, [root])]
        while stack:
            current, path = stack.pop()
            if state.get(current) == 2:
                continue
            state[current] = 2
            for nxt in successors(nodes.get(current)):
                if nxt not in nodes:
                    continue
                if nxt in path:
                    return [*path, nxt]
                stack.append((nxt, [*path, nxt]))
    return []


def requested_actions(flow: Any) -> list[str]:
    """Sorted unique action names the graph asks for — what to allowlist."""
    nodes = ((flow or {}).get("nodes") or {}) if isinstance(flow, dict) else {}
    names = {
        str(n.get("uses"))
        for n in nodes.values()
        if isinstance(n, dict) and n.get("kind") == KIND_ACTION and n.get("uses")
    }
    return sorted(names)


def subflow_names(flow: Any) -> list[str]:
    """Sorted unique sub-flow names referenced by `flow` nodes."""
    nodes = ((flow or {}).get("nodes") or {}) if isinstance(flow, dict) else {}
    names = {
        str(n.get("uses"))
        for n in nodes.values()
        if isinstance(n, dict) and n.get("kind") == KIND_FLOW and n.get("uses")
    }
    return sorted(names)


def _problem(code: str, severity: str, message: str, node: str = "") -> dict[str, str]:
    return {"code": code, "severity": severity, "node": node, "message": message}


def _validate_action(node_id: str, node: dict[str, Any]) -> list[dict[str, str]]:
    """One action node's `uses` + `with` parameters against the catalog."""
    uses = node.get("uses")
    if uses not in ACTIONS:
        return [
            _problem(
                R_UNKNOWN_ACTION,
                SEV_ERROR,
                f"unknown action {uses!r} (known: {'|'.join(sorted(ACTIONS))})",
                node_id,
            )
        ]
    params = node.get("with") or {}
    if not isinstance(params, dict):
        return [_problem("bad-params", SEV_ERROR, "`with` must be an object", node_id)]
    spec = ACTIONS[uses]
    known = set(spec["params"]) | set(spec["optional"])
    out = [
        _problem(
            "missing-param",
            SEV_ERROR,
            f"action {uses!r} needs `with.{p}`",
            node_id,
        )
        for p in spec["params"]
        if p not in params
    ]
    out += [
        _problem(
            "unknown-param",
            SEV_ERROR,
            f"action {uses!r} has no parameter {p!r} (known: {'|'.join(sorted(known))})",
            node_id,
        )
        for p in sorted(params)
        if p not in known
    ]
    return out


def _validate_node(
    node_id: str, node: Any, nodes: dict[str, Any], registry: dict[str, Any]
) -> list[dict[str, str]]:
    """Per-node checks: kind, edges, and the kind's own required fields."""
    if not isinstance(node, dict):
        return [_problem("bad-node", SEV_ERROR, "a node must be an object", node_id)]
    out: list[dict[str, str]] = []
    kind = node.get("kind")
    if kind not in KINDS:
        return [
            _problem(
                "unknown-kind",
                SEV_ERROR,
                f"unknown node kind {kind!r} (choose from {'|'.join(KINDS)})",
                node_id,
            )
        ]
    for edge in successors(node):
        if edge not in nodes:
            out.append(
                _problem(
                    "dangling-edge", SEV_ERROR, f"edge points at missing node {edge!r}", node_id
                )
            )
    if kind == KIND_TRANSFORM:
        ops = node.get("ops")
        if not isinstance(ops, list) or not ops:
            out.append(
                _problem("bad-transform", SEV_ERROR, "transform needs a non-empty `ops` list", node_id)
            )
        else:
            out += [
                _problem("bad-transform", SEV_ERROR, f"op #{i}: {complaint}", node_id)
                for i, spec in enumerate(ops, start=1)
                if (complaint := check_op_shape(spec)) is not None
            ]
    elif kind in (KIND_FILTER, KIND_BRANCH):
        try:
            evaluate(node.get("when"), {})
        except ValueError as exc:
            out.append(_problem("bad-condition", SEV_ERROR, str(exc), node_id))
        if kind == KIND_BRANCH and not node.get("then"):
            out.append(_problem("bad-branch", SEV_ERROR, "branch needs a `then`", node_id))
    elif kind == KIND_ACTION:
        out += _validate_action(node_id, node)
    elif node.get("uses") not in registry:  # KIND_FLOW
        out.append(
            _problem(
                "subflow-unresolved",
                SEV_WARNING,
                f"sub-flow {node.get('uses')!r} is not in the registry — the run "
                "will refuse at this node unless it is supplied",
                node_id,
            )
        )
    return out


def validate(flow: Any, *, registry: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Every structural problem in one flow, worst-first. [] means runnable.

    Errors are fail-closed: run_flow refuses a flow with any error BEFORE
    executing a single step. Warnings (unreachable nodes, an unresolved
    sub-flow) run but are reported.
    """
    registry = registry or {}
    if not isinstance(flow, dict):
        return [_problem("bad-flow", SEV_ERROR, "a flow must be a JSON object")]
    out: list[dict[str, str]] = []
    if not str(flow.get("name") or "").strip():
        out.append(_problem("no-name", SEV_ERROR, "flow needs a non-empty `name`"))
    trigger = flow.get("trigger")
    if not isinstance(trigger, dict) or trigger.get("type") not in TRIGGERS:
        out.append(
            _problem(
                "bad-trigger",
                SEV_ERROR,
                "flow needs a `trigger` object with type "
                f"{'|'.join(TRIGGERS)} — a workflow with no trigger is not a workflow",
            )
        )
    nodes = flow.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        out.append(_problem("no-nodes", SEV_ERROR, "flow needs a non-empty `nodes` object"))
        return out
    start = flow.get("start")
    if start not in nodes:
        out.append(
            _problem("bad-start", SEV_ERROR, f"`start` {start!r} is not one of the nodes")
        )
    for node_id in sorted(nodes):
        out += _validate_node(str(node_id), nodes[node_id], nodes, registry)
    cycle = has_cycle(flow)
    if cycle:
        out.append(
            _problem(
                "cycle",
                SEV_ERROR,
                "graph has a cycle (" + " -> ".join(cycle) + ") — refused: an "
                "automation runner with an unbounded loop is a footgun with a cron entry",
            )
        )
    reachable = set(walk_order(flow))
    for node_id in sorted(set(nodes) - reachable):
        out.append(
            _problem("unreachable", SEV_WARNING, "node cannot be reached from `start`", str(node_id))
        )
    return sorted(out, key=lambda p: (openswap.severity_rank(p["severity"]), p["node"], p["code"]))


def preflight(flow: Any, allow: Iterable[str]) -> dict[str, Any]:
    """What WOULD run and what would be refused, without running anything.

    The honest answer to "can I schedule this yet": requested actions split
    into allowed / refused (not in the caller's allowlist) / unknown (not in the
    catalog at all). `runnable` is False if any action would be refused.
    """
    allowed = frozenset(allow or ())
    requested = requested_actions(flow)
    known = [a for a in requested if a in ACTIONS]
    return {
        "requested": requested,
        "allowlist": sorted(allowed),
        "allowed": [a for a in known if a in allowed],
        "refused": [a for a in known if a not in allowed],
        "unknown": [a for a in requested if a not in ACTIONS],
        "runnable": all(a in allowed for a in requested) and len(known) == len(requested),
    }


# ---- triggers ---------------------------------------------------------------


def trigger_check(
    flow: Any, payload: dict[str, Any], *, now: float, last_run: float | None = None
) -> tuple[bool, str]:
    """(fired, reason). A trigger that does not fire always says WHY.

    manual   — always fires (the human/cron already decided).
    event    — fires when `match` (a condition) holds against the payload.
    schedule — fires when `now - last_run >= every_seconds`. `last_run` comes
               from the ledger (last_run_ts); None means "never ran", which
               fires. The reason carries the real seconds remaining — no
               invented cadence when the data is absent.
    """
    trigger = ((flow or {}).get("trigger") or {}) if isinstance(flow, dict) else {}
    ttype = trigger.get("type")
    if ttype == TRIGGER_MANUAL:
        return True, "manual trigger"
    if ttype == TRIGGER_EVENT:
        match = trigger.get("match")
        if match is None:
            return True, "event trigger with no match filter"
        try:
            hit = evaluate(match, payload)
        except ValueError as exc:
            return False, f"event trigger match is unusable: {exc}"
        return (
            (True, "event matched the trigger filter")
            if hit
            else (False, "event did not match the trigger filter")
        )
    if ttype == TRIGGER_SCHEDULE:
        every = _as_number(trigger.get("every_seconds"))
        if every is None or every <= 0:
            return False, (
                "schedule trigger needs a positive `every_seconds`, got "
                f"{trigger.get('every_seconds')!r}"
            )
        if last_run is None:
            return True, "schedule trigger: no prior run recorded"
        remaining = round(float(last_run) + every - now, 2)
        if remaining > 0:
            return False, f"schedule trigger not due for {remaining}s (every {every:g}s)"
        return True, f"schedule trigger due ({-remaining}s past every {every:g}s)"
    return False, f"unknown trigger type {ttype!r}"


# ---- the bounded runner -----------------------------------------------------


def _step(
    *,
    seq: int,
    node: str,
    kind: Any,
    outcome: str,
    uses: Any = None,
    output: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    """One step record. EITHER output OR error — enforced, not documented."""
    if (output is None) == (error is None):
        raise ValueError(
            "a step records EITHER an output OR an error — never both, never neither"
        )
    return {
        "seq": int(seq),
        "node": node,
        "kind": kind,
        "uses": uses,
        "outcome": outcome,
        "output": output,
        "error": error,
    }


def _finish(
    run: dict[str, Any],
    budget: dict[str, int],
    outcome: str,
    reason: str | None = None,
    problems: Iterable[dict[str, str]] = (),
) -> dict[str, Any]:
    """Seal a run: outcome, reason, accumulated problems, spent budget."""
    run["outcome"] = outcome
    run["reason"] = reason
    run["problems"] = [*run["problems"], *problems]
    run["refusals"] = [p for p in run["problems"] if p["code"] in REFUSAL_CODES]
    run["steps_used"] = budget["used"]
    run["step_cap"] = budget["cap"]
    return run


def _run_action(
    node_id: str,
    node: dict[str, Any],
    data: dict[str, Any],
    *,
    seq: int,
    allowed: frozenset[str],
    effectors: dict[str, Callable[[dict[str, Any], dict[str, Any]], Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str] | None]:
    """Execute one action node -> (step, payload, refusal-or-None).

    Three default-deny gates in order (catalog, allowlist, injected effector),
    each a REFUSAL naming the action, then the effector call. An effector that
    returns nothing is an error, not an empty success: a reading has either a
    value or an error.
    """
    uses = node.get("uses")

    def _refuse(code: str, message: str) -> tuple[dict, dict, dict]:
        return (
            _step(
                seq=seq,
                node=node_id,
                kind=KIND_ACTION,
                uses=uses,
                outcome=OUTCOME_REFUSED,
                error=message,
            ),
            data,
            _problem(code, SEV_ERROR, message, node_id),
        )

    if uses not in ACTIONS:
        return _refuse(R_UNKNOWN_ACTION, f"action {uses!r} is not in the catalog")
    if uses not in allowed:
        return _refuse(
            R_NOT_ALLOWLISTED,
            f"action {uses!r} is not allowlisted (allowed: "
            f"{', '.join(sorted(allowed)) or 'nothing'}) — pass --allow {uses}",
        )
    effector = effectors.get(str(uses))
    if effector is None:
        return _refuse(
            R_NO_EFFECTOR, f"action {uses!r} is allowlisted but no effector was supplied"
        )
    try:
        result = effector(node.get("with") or {}, data)
    except Exception as exc:  # an effector reports failure by raising
        return (
            _step(
                seq=seq,
                node=node_id,
                kind=KIND_ACTION,
                uses=uses,
                outcome=OUTCOME_FAILED,
                error=f"{type(exc).__name__}: {exc}",
            ),
            data,
            _problem("action-failed", SEV_ERROR, f"{type(exc).__name__}: {exc}", node_id),
        )
    if result is None:
        return (
            _step(
                seq=seq,
                node=node_id,
                kind=KIND_ACTION,
                uses=uses,
                outcome=OUTCOME_FAILED,
                error=f"action {uses!r} returned no result",
            ),
            data,
            _problem("action-failed", SEV_ERROR, f"action {uses!r} returned no result", node_id),
        )
    into = node.get("into")
    if into:
        data = set_path(data, into, result)
    return (
        _step(
            seq=seq,
            node=node_id,
            kind=KIND_ACTION,
            uses=uses,
            outcome=OUTCOME_OK,
            output=result,
        ),
        data,
        None,
    )


def run_flow(
    flow: Any,
    payload: dict[str, Any] | None = None,
    *,
    allow: Iterable[str] = (),
    effectors: dict[str, Callable[[dict[str, Any], dict[str, Any]], Any]] | None = None,
    registry: dict[str, Any] | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_visits: int = DEFAULT_MAX_VISITS,
    now: float | None = None,
    last_run: float | None = None,
    budget: dict[str, int] | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    """Execute one flow under hard bounds. Never loops, never runs an
    un-allowlisted action, never skips silently.

    `effectors` maps action name -> callable(params, payload) that performs the
    real effect and returns a result dict (the CLI injects these; tests inject
    fakes, which is why nothing in this module touches the filesystem). `budget`
    is the SHARED step budget — pass it through to sub-flows so nesting cannot
    buy more steps.
    """
    now = time.time() if now is None else float(now)
    allowed = frozenset(allow or ())
    effectors = effectors or {}
    registry = registry or {}
    if budget is None:
        budget = {"used": 0, "cap": max(0, int(max_steps))}
    graph: dict[str, Any] = flow if isinstance(flow, dict) else {}
    run: dict[str, Any] = {
        "flow": str(graph.get("name") or "(unnamed)"),
        "trigger": (graph.get("trigger") or {}).get("type"),
        "ts": now,
        "depth": depth,
        "allowlist": sorted(allowed),
        "steps": [],
        "problems": [],
        "actions_run": [],
        "data": copy.deepcopy(payload) if isinstance(payload, dict) else {},
        "outcome": OUTCOME_OK,
        "reason": None,
        "steps_used": budget["used"],
        "step_cap": budget["cap"],
    }
    problems = validate(flow, registry=registry)
    errors = [p for p in problems if p["severity"] == SEV_ERROR]
    if errors:
        return _finish(
            run,
            budget,
            OUTCOME_REFUSED,
            f"flow is invalid ({len(errors)} error(s)) — refused before any step ran",
            [_problem(R_INVALID_FLOW, SEV_ERROR, "flow failed validation"), *errors],
        )
    fired, reason = trigger_check(flow, run["data"], now=now, last_run=last_run)
    if not fired:
        return _finish(run, budget, OUTCOME_NOT_TRIGGERED, reason)

    nodes = graph["nodes"]
    node_id = graph["start"]
    visits: dict[str, int] = {}
    while node_id:
        if budget["used"] >= budget["cap"]:
            msg = (
                f"step cap {budget['cap']} reached at node {node_id!r} — "
                f"{len(run['steps'])} step(s) ran in this flow"
            )
            return _finish(run, budget, OUTCOME_REFUSED, msg, [_problem(R_STEP_CAP, SEV_ERROR, msg, node_id)])
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            msg = f"node {node_id!r} does not exist"
            return _finish(run, budget, OUTCOME_REFUSED, msg, [_problem(R_UNKNOWN_NODE, SEV_ERROR, msg, node_id)])
        visits[node_id] = visits.get(node_id, 0) + 1
        if visits[node_id] > max_visits:
            msg = f"node {node_id!r} would run a {visits[node_id]}th time (visit cap {max_visits})"
            return _finish(run, budget, OUTCOME_REFUSED, msg, [_problem(R_VISIT_CAP, SEV_ERROR, msg, node_id)])
        budget["used"] += 1
        seq = budget["used"]
        kind = node.get("kind")
        next_id = node.get("next")

        if kind == KIND_TRANSFORM:
            try:
                run["data"], notes = apply_transform(node.get("ops"), run["data"])
            except ValueError as exc:
                run["steps"].append(
                    _step(seq=seq, node=node_id, kind=kind, outcome=OUTCOME_FAILED, error=str(exc))
                )
                return _finish(
                    run, budget, OUTCOME_FAILED, str(exc),
                    [_problem("transform-failed", SEV_ERROR, str(exc), node_id)],
                )
            run["steps"].append(
                _step(seq=seq, node=node_id, kind=kind, outcome=OUTCOME_OK, output={"applied": notes})
            )
        elif kind in (KIND_FILTER, KIND_BRANCH):
            try:
                passed = evaluate(node.get("when"), run["data"])
            except ValueError as exc:
                run["steps"].append(
                    _step(seq=seq, node=node_id, kind=kind, outcome=OUTCOME_FAILED, error=str(exc))
                )
                return _finish(
                    run, budget, OUTCOME_FAILED, str(exc),
                    [_problem("condition-failed", SEV_ERROR, str(exc), node_id)],
                )
            if kind == KIND_BRANCH:
                next_id = node.get("then") if passed else node.get("else")
            run["steps"].append(
                _step(
                    seq=seq, node=node_id, kind=kind,
                    outcome=OUTCOME_OK if (passed or kind == KIND_BRANCH) else OUTCOME_FILTERED,
                    output={"passed": passed, "next": next_id},
                )
            )
            if kind == KIND_FILTER and not passed:
                return _finish(
                    run, budget, OUTCOME_FILTERED, f"filter {node_id!r} did not pass"
                )
        elif kind == KIND_ACTION:
            step, run["data"], refusal = _run_action(
                str(node_id), node, run["data"], seq=seq, allowed=allowed, effectors=effectors
            )
            run["steps"].append(step)
            if refusal is not None:
                return _finish(run, budget, step["outcome"], step["error"], [refusal])
            run["actions_run"].append(node.get("uses"))
        else:  # KIND_FLOW — bounded recursion
            name = str(node.get("uses"))
            if depth + 1 > max_depth:
                msg = f"sub-flow {name!r} refused: depth cap {max_depth} reached"
                run["steps"].append(
                    _step(seq=seq, node=node_id, kind=kind, uses=name, outcome=OUTCOME_REFUSED, error=msg)
                )
                return _finish(run, budget, OUTCOME_REFUSED, msg, [_problem(R_DEPTH_CAP, SEV_ERROR, msg, node_id)])
            sub = registry.get(name)
            if not isinstance(sub, dict):
                msg = f"sub-flow {name!r} is not in the registry"
                run["steps"].append(
                    _step(seq=seq, node=node_id, kind=kind, uses=name, outcome=OUTCOME_REFUSED, error=msg)
                )
                return _finish(run, budget, OUTCOME_REFUSED, msg, [_problem(R_SUBFLOW_MISSING, SEV_ERROR, msg, node_id)])
            sub_run = run_flow(
                sub, run["data"], allow=allowed, effectors=effectors, registry=registry,
                max_depth=max_depth, max_visits=max_visits, now=now, budget=budget, depth=depth + 1,
            )
            run["data"] = sub_run["data"]
            run["actions_run"] += sub_run["actions_run"]
            run["problems"] += [{**p, "node": f"{node_id}/{p['node']}"} for p in sub_run["problems"]]
            run["steps"].append(
                _step(
                    seq=seq, node=node_id, kind=kind, uses=name, outcome=sub_run["outcome"],
                    output={
                        "flow": sub_run["flow"], "outcome": sub_run["outcome"],
                        "reason": sub_run["reason"], "steps": len(sub_run["steps"]),
                        "depth": sub_run["depth"],
                    },
                )
            )
            if sub_run["outcome"] != OUTCOME_OK:
                return _finish(
                    run, budget, sub_run["outcome"],
                    f"sub-flow {name!r} ended {sub_run['outcome']}: {sub_run['reason']}",
                )
        node_id = next_id
    return _finish(run, budget, OUTCOME_OK, f"{len(run['steps'])} step(s) completed")


# ---- output containment (pure) ----------------------------------------------


def resolve_output_path(out_dir: str | Path, rel: Any) -> Path:
    """Confine an action's target file inside `out_dir`. Escapes RAISE.

    Refused: absolute paths, drive/UNC-qualified paths, and any '..' segment —
    checked as text (so a POSIX box refuses 'C:/x' too) and then confirmed
    structurally with resolve()+relative_to. pathlib only, no os.path.
    """
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError("action `file` must be a non-empty relative path")
    raw = rel.strip().replace("\\", "/")
    if raw.startswith("/") or ":" in raw:
        raise ValueError(f"refusing absolute or drive-qualified path {rel!r}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise ValueError(f"refusing path escape {rel!r}")
    base = Path(out_dir)
    target = base.joinpath(*parts)
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"{rel!r} escapes the output directory {base}") from exc
    return target


# ---- family diagnostics -----------------------------------------------------


def to_diagnostics(source: str, problems: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """Validation problems AND run refusals -> the family diagnostic schema.

    One diagnostic per problem, `flows:<code>` as the rule, the node id carried
    in the message (a graph has no line numbers, so line/col stay 0 rather than
    pretending). This is what makes `--fail-on` behave like every other adapter.
    """
    diags = [
        openswap.diagnostic(
            path=source,
            line=0,
            col=0,
            rule=f"flows:{p.get('code', '?')}",
            severity=p.get("severity", SEV_WARNING),
            message=(f"[{p['node']}] " if p.get("node") else "") + str(p.get("message", "")),
        )
        for p in problems
    ]
    return openswap.sort_diagnostics(diags)


# ---- run ledger (own sqlite file) -------------------------------------------

DB_REL = Path(".scout") / "flows.db"
OUT_REL = Path(".scout") / "flows-out"
SCHEMA_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow TEXT NOT NULL,
    source TEXT,
    trigger TEXT,
    ts REAL NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    steps_used INTEGER NOT NULL,
    step_cap INTEGER NOT NULL,
    depth INTEGER NOT NULL,
    allowlist TEXT NOT NULL,
    actions_run TEXT,
    problems TEXT,
    payload_out TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_flow_ts ON runs(flow, ts);
CREATE TABLE IF NOT EXISTS steps(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    node TEXT NOT NULL,
    kind TEXT,
    uses TEXT,
    outcome TEXT NOT NULL,
    output TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id, seq);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the flow run ledger — its OWN sqlite file.

    Never the #2 uptime ledger: an automation pass can fire many times an hour
    and must not contend with monitoring probes for the same write lock.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def record_run(
    conn: sqlite3.Connection, run: dict[str, Any], *, source: str | None = None
) -> int:
    """Append one run + its steps to the ledger; returns the run id.

    The step rows keep the either/or invariant: exactly one of output/error is
    non-NULL per row, so a history query can never show a step that both
    succeeded and failed (or did neither).
    """
    cur = conn.execute(
        "INSERT INTO runs(flow, source, trigger, ts, outcome, reason, steps_used,"
        " step_cap, depth, allowlist, actions_run, problems, payload_out)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.get("flow"),
            source,
            run.get("trigger"),
            float(run.get("ts") or 0.0),
            run.get("outcome"),
            run.get("reason"),
            int(run.get("steps_used") or 0),
            int(run.get("step_cap") or 0),
            int(run.get("depth") or 0),
            json.dumps(run.get("allowlist") or []),
            json.dumps(run.get("actions_run") or []),
            json.dumps(run.get("problems") or []) if run.get("problems") else None,
            json.dumps(run.get("data"), sort_keys=True, default=str),
        ),
    )
    run_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO steps(run_id, seq, node, kind, uses, outcome, output, error)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                int(s["seq"]),
                s["node"],
                s.get("kind"),
                s.get("uses"),
                s["outcome"],
                None if s.get("output") is None else json.dumps(s["output"], sort_keys=True, default=str),
                s.get("error"),
            )
            for s in run.get("steps") or []
        ],
    )
    conn.commit()
    return run_id


def list_runs(
    conn: sqlite3.Connection,
    *,
    flow: str | None = None,
    outcome: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Newest-first run history — the local replacement for Zapier's task pane."""
    rows = conn.execute(
        "SELECT * FROM runs WHERE (? IS NULL OR flow = ?)"
        " AND (? IS NULL OR outcome = ?) ORDER BY ts DESC, id DESC LIMIT ?",
        (flow, flow, outcome, outcome, int(limit)),
    )
    return [dict(r) for r in rows]


def run_detail(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    """One run with its ordered steps, or None when the id is unknown."""
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (int(run_id),)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["steps"] = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM steps WHERE run_id = ? ORDER BY seq ASC, id ASC", (int(run_id),)
        )
    ]
    return out


def last_run_ts(conn: sqlite3.Connection, flow: str) -> float | None:
    """Timestamp of the newest recorded run of `flow`, or None if it never ran.

    This is what a schedule trigger reads. None means "no evidence it ever
    ran", which fires the trigger — the alternative (defaulting to now) would
    invent a cadence out of nothing.
    """
    row = conn.execute(
        "SELECT MAX(ts) AS ts FROM runs WHERE flow = ?", (flow,)
    ).fetchone()
    if row is None or row["ts"] is None:
        return None
    return float(row["ts"])


def outcome_counts(conn: sqlite3.Connection, *, flow: str | None = None) -> dict[str, int]:
    """Runs per outcome — the 'is my automation actually working' roll-up."""
    rows = conn.execute(
        "SELECT outcome, COUNT(*) AS n FROM runs WHERE (? IS NULL OR flow = ?)"
        " GROUP BY outcome ORDER BY outcome ASC",
        (flow, flow),
    )
    return {r["outcome"]: int(r["n"]) for r in rows}


# ---- a real, runnable example -----------------------------------------------

# Shipped as data (not a file on disk) so `scout flows actions` can print a
# graph that actually runs and `plan --example` needs no fixture. It is the
# canonical shape: event trigger with a match filter -> transform -> filter ->
# allowlisted action.
EXAMPLE_FLOW: dict[str, Any] = {
    "name": "cert-error-digest",
    "description": (
        "when a cert/uptime event arrives at error severity, count the affected "
        "hosts and append one digest line — the Zapier 'if X then log Y' shape"
    ),
    "trigger": {
        "type": "event",
        "match": {"path": "severity", "op": "eq", "value": "error"},
    },
    "start": "summarize",
    "nodes": {
        "summarize": {
            "kind": "transform",
            "ops": [
                {"op": "count", "from": "hosts", "path": "host_count"},
                {"op": "template", "path": "line", "text": "{host_count} host(s) at {severity}: {hosts}"},
            ],
            "next": "any",
        },
        "any": {
            "kind": "filter",
            "when": {"path": "host_count", "op": "gt", "value": 0},
            "next": "record",
        },
        "record": {
            "kind": "action",
            "uses": "append_jsonl",
            "with": {"file": "cert-digest.jsonl", "fields": ["line", "host_count"]},
            "into": "written",
        },
    },
}
