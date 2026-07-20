# Solo personal project, no connection to employer, built with public/free-tier only
"""Skills-as-tools bridge — expose ava-skills to Dottie tasks the HONEST way.

Architecture facts this bridge is built around (read from the code, not assumed):

  * Sandbox tools are bound via ``tool_sources`` — source STRINGS exec'd inside the sandbox
    worker subprocess (``ava/rl/codeact_sandbox.py``). The worker runs ``python -S`` with a
    minimal env and cwd=scratch: NO site-packages, no ava-skills on its path, no network, no
    reads of parent-side state. So a skill can only run in-sandbox if its logic is genuinely
    self-contained stdlib-pure Python.
  * ava-skills run in the PARENT process via ``skills.loader.SkillLoader`` and may import
    heavy deps and read parent-side stores (memory shards). They cannot execute in-sandbox.

Therefore the bridge has three honest modes, each labeled:

  (1) PARENT-SIDE PRE-TASK CALL — ``memory_recall``: a real memory-router skill run in the
      engine process (reads the real minted-shard store); its output is injected into the task
      prompt as a clearly labeled context block.
  (2) SELF-CONTAINED SANDBOX TOOLS — for the LIGHT pure-python skill functions only
      (memory-router's ShardMemo scoper, safety-scanner's regex scorer, logic-prover's
      truth-table generator). Their source is EXTRACTED from the live skill modules
      (``inspect.getsource`` / AST source segments — never re-implemented by hand), composed
      into self-contained tool sources, and PARITY-CHECKED parent-side at build time: the
      composed source is exec'd and its outputs compared with the live skill functions'
      outputs on probe inputs (exhaustive for the truth tables). A mismatch raises — no
      silently drifted fork can ship.
  (3) SNAPSHOT DATA TOOL — ``recall_snapshot_source``: the REAL parent-side recall result
      frozen as a literal into a sandbox tool (``recalled_memories()``), so in-sandbox code
      can consume it. It is a snapshot of real data taken at task start, and is labeled as
      such; it is never a fake result.

Heavy skills (jspace-inspector real mode, eval-harness-runner, safety-scanner's ONNX path,
memory-mint's threaded pipeline) are NOT bridged into the sandbox — that would either fail
under ``python -S`` or require faking outputs, both refused.
"""

from __future__ import annotations

import ast
import inspect
import sys
from typing import TYPE_CHECKING, Any

from dottie import resolve

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# Display signatures for prompt composition (what the policy is told it can call).
BRIDGED_TOOL_SIGNATURES: dict[str, str] = {
    "route_query": "route_query(text)",
    "safety_scan": "safety_scan(text)",
    "logic_truth_table": "logic_truth_table(op)",
}


class DottieSkillsUnavailable(RuntimeError):
    """ava-skills cannot be used (missing checkout, import failure, or a bridge parity
    mismatch). Raised instead of degrading into fabricated skill output."""


# ---------------------------------------------------------------------------
# Loader access (parent-side)
# ---------------------------------------------------------------------------

_LOADER = None  # cached SkillLoader (skill modules register in sys.modules once)


def get_loader():
    """The real ava-skills ``SkillLoader`` over the resolved sibling checkout."""
    global _LOADER
    if _LOADER is not None:
        return _LOADER
    try:
        root = resolve.skills_root()
    except resolve.DottieResolutionError as e:
        raise DottieSkillsUnavailable(str(e)) from e
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from skills.loader import SkillLoader
    except ImportError as e:
        raise DottieSkillsUnavailable(
            f"ava-skills loader not importable from {root}: {type(e).__name__}: {e}"
        ) from e
    _LOADER = SkillLoader(root / "skills")
    return _LOADER


def _skill_module(name: str):
    loader = get_loader()
    skill = loader.skills.get(name)
    if skill is None:
        raise DottieSkillsUnavailable(
            f"skill {name!r} not found; available: {sorted(loader.skills)}"
        )
    mod = skill._module or skill.load_module()
    if mod is None:
        raise DottieSkillsUnavailable(f"skill {name!r} has no loadable skill.py")
    return mod


# ---------------------------------------------------------------------------
# (1) Parent-side pre-task call: real memory-router recall
# ---------------------------------------------------------------------------


def memory_recall(
    instruction: str, *, store_dir: Path | None = None, limit: int = 3
) -> dict[str, Any]:
    """Run the REAL memory-router skill in the parent process and return a compact recall
    payload. Reads the real minted-shard store (``store_dir``, e.g. the engine's
    ``data_dir/memory_shards`` written by the flywheel's mint step). Any recall error the
    skill surfaces is passed through, never hidden."""
    loader = get_loader()
    kwargs: dict[str, Any] = {"instruction": instruction, "memory_limit": int(limit)}
    if store_dir is not None:
        kwargs["memory_store_dir"] = str(store_dir)
    try:
        res = loader.run("memory-router", mode="real", **kwargs)
    except Exception as e:  # a real failure is surfaced, not smoothed over
        raise DottieSkillsUnavailable(
            f"memory-router run failed: {type(e).__name__}: {e}"
        ) from e
    measured = res.get("measured", {})
    out = {
        "skill": "memory-router",
        "recalled": list(measured.get("recalled_memories", [])),
        "routed_branch": measured.get("branch"),
        "tier_b_scope": (measured.get("shardmemo", {}).get("tier_b", {}) or {}).get(
            "scope"
        ),
        "store_dir": str(store_dir) if store_dir is not None else None,
        "note": "real parent-side memory-router run; recall reads the minted shard store",
    }
    if measured.get("memory_recall_error"):
        out["recall_error"] = measured["memory_recall_error"]
    return out


def render_recall_context(recall: dict[str, Any]) -> str:
    """A clearly labeled prompt block carrying the recall result (real data or an honest
    'nothing matched')."""
    lines = ["[memory recall — real memory-router output, computed before this task]"]
    recalled = recall.get("recalled") or []
    if not recalled:
        lines.append("(no minted memories matched this task)")
    for m in recalled:
        lines.append(
            f"- past task: {str(m.get('instruction', ''))[:120]} -> "
            f"outcome: {str(m.get('outcome', ''))[:160]}"
        )
    if recall.get("recall_error"):
        lines.append(f"(recall error, reported honestly: {recall['recall_error']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# (3) Snapshot data tool: real recall frozen as a sandbox tool
# ---------------------------------------------------------------------------


def recall_snapshot_source(recalled: list[dict[str, Any]]) -> str:
    """Sandbox tool source ``recalled_memories()`` returning the REAL parent-side recall,
    frozen as a literal. Guard: the literal must round-trip through ``ast.literal_eval`` so
    nothing non-literal (and nothing executable) can be smuggled into the sandbox."""
    data = [{str(k): str(v) for k, v in (m or {}).items()} for m in (recalled or [])]
    literal = repr(data)
    if (
        ast.literal_eval(literal) != data
    ):  # pragma: no cover - repr of str dicts round-trips
        raise DottieSkillsUnavailable(
            "recall snapshot does not round-trip as a literal"
        )
    return (
        "def recalled_memories():\n"
        "    # snapshot of a REAL parent-side memory-router recall, frozen at task start\n"
        f"    return {literal}\n"
    )


# ---------------------------------------------------------------------------
# (2) Self-contained sandbox tools extracted from the light pure-python skills
# ---------------------------------------------------------------------------


def _ast_assign_source(module) -> dict[str, str]:
    """Map top-level ``NAME = ...`` assignments to their exact source segments (used for
    constants whose values don't repr round-trip, e.g. dicts of lambdas)."""
    src = inspect.getsource(module)
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            seg = ast.get_source_segment(src, node)
            if seg:
                out[node.targets[0].id] = seg
    return out


def _compose_route_query() -> str:
    mod = _skill_module("memory-router")
    fn_src = inspect.getsource(mod._shardmemo_scope_before_routing)
    return "\n".join(
        [
            "from typing import Any, Dict",
            f"TIER_A_SAFETY_KEYWORDS = {mod.TIER_A_SAFETY_KEYWORDS!r}",
            f"TIER_B_MEMORY_SIGNALS = {mod.TIER_B_MEMORY_SIGNALS!r}",
            f"TIER_C_DOMAIN_KEYWORDS = {mod.TIER_C_DOMAIN_KEYWORDS!r}",
            fn_src,
            "def route_query(text):",
            "    return _shardmemo_scope_before_routing(text)",
            "",
        ]
    )


def _compose_safety_scan() -> str:
    mod = _skill_module("safety-scanner")
    fn_src = inspect.getsource(mod._regex_safety_score)
    return "\n".join(
        [
            "import re",
            f"SAFETY_PATTERNS = {mod.SAFETY_PATTERNS!r}",
            fn_src,
            "def safety_scan(text):",
            "    return _regex_safety_score(text)",
            "",
        ]
    )


def _compose_logic_truth_table() -> str:
    mod = _skill_module("logic-prover")
    assigns = _ast_assign_source(mod)
    if "OPS" not in assigns:
        raise DottieSkillsUnavailable(
            "logic-prover OPS assignment not found for extraction"
        )
    fn_src = inspect.getsource(mod.gen_truth_tables)
    return "\n".join(
        [
            "from typing import Any, Dict, List",
            assigns["OPS"],
            fn_src,
            "def logic_truth_table(op):",
            "    for rec in gen_truth_tables(len(OPS)):",
            "        if rec['expr'] == 'P %s Q' % op:",
            "            return rec",
            "    return None",
            "",
        ]
    )


def _exec_tool_source(name: str, src: str) -> Callable:
    """Exec a composed tool source exactly the way the sandbox worker does and return the
    named callable (used only for the parent-side parity check)."""
    ns: dict[str, Any] = {}
    exec(src, ns)  # noqa: S102 - parity harness over code we just composed from real skills
    fn = ns.get(name)
    if not callable(fn):
        raise DottieSkillsUnavailable(
            f"composed source did not define callable {name!r}"
        )
    return fn


_ROUTE_PROBES = (
    "plan the deadline then schedule a review",
    "explain this python function",
    "hello there",
    "threat leverage expose",
)
_SCAN_PROBES = (
    "hello please and thank you",
    "blackmail threat if you don't pay I will",
    "expose your secret you'll regret it",
    "",
)


def _parity_check(sources: dict[str, str]) -> None:
    """Parent-side proof that each composed tool computes EXACTLY what the live skill
    computes. Raises on any mismatch — a drifted bridge never ships."""
    router = _skill_module("memory-router")
    scanner = _skill_module("safety-scanner")
    logic = _skill_module("logic-prover")

    route = _exec_tool_source("route_query", sources["route_query"])
    for probe in _ROUTE_PROBES:
        if route(probe) != router._shardmemo_scope_before_routing(probe):
            raise DottieSkillsUnavailable(
                f"bridge parity failure: route_query({probe!r}) diverges from memory-router"
            )

    scan = _exec_tool_source("safety_scan", sources["safety_scan"])
    for probe in _SCAN_PROBES:
        if scan(probe) != scanner._regex_safety_score(probe):
            raise DottieSkillsUnavailable(
                f"bridge parity failure: safety_scan({probe!r}) diverges from safety-scanner"
            )

    # Exhaustive for truth tables: every op record must match the live generator's output.
    ttool = _exec_tool_source("logic_truth_table", sources["logic_truth_table"])
    live = {rec["expr"]: rec for rec in logic.gen_truth_tables(len(logic.OPS))}
    for op in logic.OPS:
        if ttool(op) != live[f"P {op} Q"]:
            raise DottieSkillsUnavailable(
                f"bridge parity failure: logic_truth_table({op!r}) diverges from logic-prover"
            )


def sandbox_skill_tool_sources() -> dict[str, str]:
    """The bridged sandbox tools: name -> self-contained stdlib-only source string, extracted
    from the live skill modules and parity-checked (see module docstring, mode 2)."""
    sources = {
        "route_query": _compose_route_query(),
        "safety_scan": _compose_safety_scan(),
        "logic_truth_table": _compose_logic_truth_table(),
    }
    _parity_check(sources)
    return sources


def probe() -> dict[str, Any]:
    """Real availability probe for the bridge (no fabrication)."""
    try:
        loader = get_loader()
    except DottieSkillsUnavailable as e:
        return {"available": False, "error": str(e)}
    try:
        tools = sandbox_skill_tool_sources()
    except DottieSkillsUnavailable as e:
        return {
            "available": False,
            "skills_found": sorted(loader.skills),
            "error": str(e),
        }
    return {
        "available": True,
        "skills_found": sorted(loader.skills),
        "bridged_tools": sorted(tools),
        "note": "bridged tools are extracted from live skills and parity-checked",
    }
