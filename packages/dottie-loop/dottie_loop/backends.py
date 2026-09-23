"""Router backends: the answers :func:`dottie_loop.router.route_goal` reads.

The router is one policy (:mod:`dottie_loop.router`). A backend only answers
"which tier does this goal need?"; it never decides. Three backends exist:

* :class:`HeuristicBackend`: MoMA-lite, the keyword classifier ported from
  ``bundles/router/router.ultra.js``. This module is its ONLY implementation;
  scout's ``bigbang.plugins.harness.cli`` keeps its old ``_score_intent`` /
  ``_complexity`` / ``_classify_moma`` / ``_routed_agents`` names as thin
  wrappers over the functions below. It is always available and is the
  authority today.
* :class:`LearnedMLPBackend`: the orchestrator MLP (ava-factory
  ``champion_weights.json``, schema_version 1). Advisory unless its artifact
  says ``gate_passed: true`` AND a human stamped it (:mod:`dottie_loop.router_artifacts`).
* :class:`SystemOneBackend`: an HTTP client for a dottie-os ``POST /decide``
  endpoint (System One, frozen ``jev-decision-schema-1.0.0``). Off unless
  ``DOTTIE_OS_URL`` is set. Stdlib ``urllib``, short timeout, never raises. An
  ``untrained`` sidecar answers uniformly, so its answer is recorded as "no
  signal". Answers carry System One's ``shape_concentration``, never a
  ``confidence``.

Every ``answer()`` returns a plain dict and never raises: a backend failure is
recorded as ``available: false`` with a reason, and routing continues on the
heuristic.

Stdlib only. numpy is imported lazily by the MLP backend and only when it is
enabled; without numpy that backend reports itself unavailable.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, ClassVar

#: The five MoMA-lite tiers, cheapest first. ``dottie_loop.router.LEGACY_TIER``
#: maps each onto the spec's T0..T4.
MOMA_TIERS: dict[str, dict[str, str]] = {
    "deterministic": {"cap": "cheap", "desc": "heartbeat/monitor, pure-function, no LLM"},
    "llm": {"cap": "medium", "desc": "chat, awareness, simple decomposition"},
    "deep_research": {"cap": "heavy 9K", "desc": "5-7 sources A/B/C triangulation, contradiction matrix, freshness Aug 2026"},
    "action_operator": {"cap": "medium-verify", "desc": "gmail/calendar chain, idempotent, rollback, side_effect_class"},
    "agentic_epic": {"cap": "checkpointed 13-swarm", "desc": "opaque goals, DAG version++, bounded recovery, OODA inner"},
}
TIER_ORDER = tuple(MOMA_TIERS)

INTENT_KEYWORDS: dict[str, dict[str, Any]] = {
    "agentic_loop": {"words": ["launch", "ship", "build", "end-to-end", "loop", "factory", "close the loop"], "patterns": [r"\b12 things at once\b", r"\bopaque goal\b", r"\bkeep track\b"], "weight": 1},
    "deep_research": {"words": ["compare", "vs", "stripe", "lemon squeezy", "research", "sota", "paper", "benchmark", "triangulation", "sources"], "patterns": [r"\baug\s*2026\b", r"\b5-7 sources\b"], "weight": 1},
    "complex_action": {"words": ["gmail", "calendar", "drive", "notion", "linear", "pay", "invoice", "book", "schedule"], "patterns": [r"\btool\s*chain\b"], "weight": 1},
    "deterministic": {"words": ["heartbeat", "monitor", "cron", "tick"], "patterns": [], "weight": 1},
}

# Engineering-flavoured tokens. Must match apps/ava-factory/orchestrator_infer.py
# CODE_TERMS exactly (a frozen cross-lane featurize contract).
CODE_TERMS = frozenset({
    "code", "build", "test", "deploy", "api", "bug", "fix", "refactor",
    "cli", "pipeline", "json", "python", "script", "repo", "harness",
})
_CHAIN_RE = re.compile(r"(->|then|after|next|→)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


# --- MoMA-lite (the one implementation) ------------------------------------------


def score_intent(text: str, intent: str) -> float:
    """Keyword score of ``text`` for one intent: +1 per word, +2.5 per pattern."""
    cfg = INTENT_KEYWORDS.get(intent, {})
    t = text.lower()
    score: float = 0
    for w in cfg.get("words", []):
        if w.lower() in t:
            score += 1
    for pat in cfg.get("patterns", []):
        if re.search(pat, t, re.I):
            score += 2.5
    return score


def chain_signals(text: str) -> int:
    """Count of sequencing markers (``->``, then, after, next, →) plus a long-``and`` bonus."""
    lower = text.lower()
    words = len(text.split())
    return len(_CHAIN_RE.findall(lower)) + (1 if " and " in lower and words > 10 else 0)


def complexity(text: str) -> str:
    """simple | medium | epic, from word count and chain signals."""
    words = len(text.split())
    if words > 60 or chain_signals(text) >= 3:
        return "epic"
    if words > 18:
        return "medium"
    return "simple"


def classify_moma(text: str, intent: str, cplx: str) -> str:
    """MoMA-lite tier. First match wins, in this order."""
    t = text.lower()
    if any(k in t for k in ["heartbeat", "monitor", "tick", "cron health"]):
        return "deterministic"
    if intent == "deep_research" or any(k in t for k in ["stripe", "lemon", "triangulation", "paper", "sota", "sources"]):
        return "deep_research"
    if intent == "complex_action" or any(k in t for k in ["gmail", "calendar trick", "chain call"]):
        return "action_operator"
    if intent == "agentic_loop" or cplx == "epic":
        return "agentic_epic"
    return "llm"


def routed_agents(intent: str, cplx: str) -> list[str]:
    """Agent roster for an intent/complexity pair (unknown values take the minimal roster)."""
    if intent not in ("deep_research", "complex_action", "agentic_loop"):
        intent = "chat"
    if cplx not in ("simple", "medium", "epic"):
        cplx = "simple"
    if intent == "deep_research":
        return ["deep-researcher", "synthesist", "forensic-auditor"] if cplx != "epic" else ["deep-researcher", "synthesist", "researcher", "forensic-auditor", "critic"]
    if intent == "complex_action":
        return ["action-operator", "operator", "critic"]
    if intent == "agentic_loop":
        if cplx == "epic":
            return ["scout-prime-coordinator", "strategist", "planner", "deep-researcher", "synthesist", "builder", "operator", "action-operator", "executor", "critic", "forensic-auditor", "researcher", "communicator"]
        return ["scout-prime-coordinator", "strategist", "planner", "builder", "executor", "critic", "operator", "action-operator", "synthesist"][:5]
    if cplx == "epic":
        return ["scout-prime-coordinator", "strategist", "planner", "deep-researcher", "synthesist", "builder", "executor", "critic"]
    if cplx == "medium":
        return ["scout-prime-coordinator", "strategist", "builder"]
    return ["operator", "scout-prime-coordinator"]


def moma_route(goal: str) -> dict[str, Any]:
    """The full MoMA-lite answer for a goal.

    ``confidence`` here is the pre-existing keyword-score ratio (max score / 4,
    capped at 0.96; 0.4 when nothing matched). It is NOT a probability and the
    router never thresholds it; the key name is kept because scout, jarvisd and
    their consumers already read it.
    """
    scores = {k: score_intent(goal, k) for k in INTENT_KEYWORDS}
    best = max(scores.values())
    intent = max(scores, key=lambda k: scores[k]) if best > 0 else "llm"
    cplx = complexity(goal)
    tier = classify_moma(goal, intent, cplx)
    confidence = round(min(0.96, best / 4.0), 2) if best > 0 else 0.4
    return {
        "intent": intent,
        "intent_scores": scores,
        "complexity": cplx,
        "moma_tier": tier,
        "moma_cap": MOMA_TIERS[tier]["cap"],
        "confidence": confidence,
        "routed_agents": routed_agents(intent, cplx),
    }


def goal_features(goal: str) -> dict[str, Any]:
    """Task-relevant features of a goal, safe to log: a hash, never the text itself."""
    toks = _TOKEN_RE.findall(goal.lower())
    return {
        "goal_sha256": hashlib.sha256(goal.encode("utf-8")).hexdigest(),
        "n_words": len(goal.split()),
        "n_chars": len(goal),
        "n_chain_signals": chain_signals(goal),
        "has_code_terms": any(t in CODE_TERMS for t in toks),
        "complexity": complexity(goal),
        "intent_scores": {k: score_intent(goal, k) for k in INTENT_KEYWORDS},
        "mcp_prefix": goal.startswith("mcp:"),
    }


# --- backends ---------------------------------------------------------------------


class HeuristicBackend:
    """MoMA-lite. Always available; authoritative by default."""

    name = "heuristic"

    def answer(self, goal: str) -> dict[str, Any]:
        out = moma_route(goal)
        return {
            "backend": self.name,
            "enabled": True,
            "available": True,
            "tier": out["moma_tier"],
            "detail": out,
            "gate_passed": None,
            "stamped": None,
            "reason": "keyword classifier; the default authority",
        }


def _repo_root() -> Path:
    # packages/dottie-loop/dottie_loop/backends.py -> repo root
    return Path(__file__).resolve().parents[3]


def default_weights_path() -> Path:
    env = os.environ.get("SCOUT_ORCH_MODEL")
    return Path(env) if env else _repo_root() / "apps" / "ava-factory" / "reports" / "orchestrator" / "champion_weights.json"


def default_infer_path() -> Path:
    env = os.environ.get("SCOUT_ORCH_INFER")
    return Path(env) if env else _repo_root() / "apps" / "ava-factory" / "orchestrator_infer.py"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class LearnedMLPBackend:
    """The orchestrator MLP (schema_version 1 weights), advisory unless gated and stamped.

    Inference is the frozen featurize + forward contract. It is served by the
    shared module ``apps/ava-factory/orchestrator_infer.py`` when importable
    (``infer_impl="shared_module"``); otherwise by :mod:`dottie_loop.mlp_infer`,
    the in-package copy of the same contract (``infer_impl="internal"``).
    """

    name = "learned_mlp"
    _cache: ClassVar[dict[tuple[str, float, str], tuple[Any, str, Any, str]]] = {}

    def __init__(self, weights_path: Path | None = None, infer_path: Path | None = None) -> None:
        self.weights_path = Path(weights_path) if weights_path else default_weights_path()
        self.infer_path = Path(infer_path) if infer_path else default_infer_path()

    def _unavailable(self, reason: str) -> dict[str, Any]:
        return {"backend": self.name, "enabled": True, "available": False, "tier": None,
                "gate_passed": False, "stamped": False, "reason": reason}

    def _shared_module(self) -> Any:
        try:
            if not self.infer_path.exists():
                return None
            spec = importlib.util.spec_from_file_location("orch_infer", str(self.infer_path))
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if callable(getattr(mod, "load_weights", None)) and callable(getattr(mod, "predict", None)):
                return mod
        except Exception:
            return None
        return None

    def answer(self, goal: str) -> dict[str, Any]:
        try:
            try:
                import numpy  # noqa: F401  availability probe only
            except ImportError:
                return self._unavailable("numpy unavailable")
            path = self.weights_path
            if not path.exists():
                return self._unavailable(f"weights not found at {path}")
            key = (str(path), path.stat().st_mtime, str(self.infer_path))
            cached = self._cache.get(key)
            if cached is None:
                mod = self._shared_module()
                try:
                    if mod is not None:
                        impl, model = "shared_module", mod.load_weights(path)
                    else:
                        from dottie_loop import mlp_infer

                        impl, model = "internal", mlp_infer.load_weights(path)
                except Exception as exc:
                    return self._unavailable(f"weights invalid: {exc}")
                type(self)._cache.clear()  # one champion per process
                cached = (model, impl, mod, file_sha256(path))
                type(self)._cache[key] = cached
            model, impl, mod, sha = cached
            if impl == "shared_module":
                out = mod.predict(model, goal)
            else:
                from dottie_loop import mlp_infer

                out = mlp_infer.predict(model, goal)
            try:
                vocab = list(model["config"]["tier_vocab"])
            except Exception:
                vocab = list(TIER_ORDER)
            raw = out.get("tier_probs")
            probs = {t: float(p) for t, p in zip(vocab, list(raw), strict=False)} if raw is not None else {}
            return {
                "backend": self.name,
                "enabled": True,
                "available": True,
                "tier": out.get("tier"),
                "tier_probs": probs,
                "risk": float(out.get("risk", 0.0)),
                "cost": float(out.get("cost", 0.0)),
                "model_version": str(out.get("model_version", "")),
                "gate_passed": bool(out.get("gate_passed", False)),
                "artifact_sha256": sha,
                "artifact": str(path),
                "infer_impl": impl,
                "stamped": False,
                "reason": "orchestrator MLP answer",
            }
        except Exception as exc:  # a backend never raises
            return self._unavailable(f"learned route error: {type(exc).__name__}: {exc}")


# --- System One over /decide --------------------------------------------------------

SYSTEM_ONE_SCHEMA = "jev-decision-schema-1.0.0"
ACTION_CRITERIA = {
    "execute": "safe to run now",
    "escalate": "needs human confirm",
    "halt": "must not run",
    "other": "not a tool decision",
}
SEVERITY_LEVELS = ["negligible", "critical"]


def system_one_questions() -> dict[str, Any]:
    """The four typed questions the router asks System One. The pack uses the same set."""
    return {
        "tier": {
            "type": "choice",
            "instructions": "Which execution tier does this goal need? Prefer the cheapest tier that can succeed.",
            "criteria": {t: MOMA_TIERS[t]["desc"] for t in TIER_ORDER},
        },
        "action": {
            "type": "choice",
            "instructions": "What should the harness do with this goal?",
            "criteria": dict(ACTION_CRITERIA),
        },
        "safe": {"type": "noul", "instructions": "P(safe to execute without a human)"},
        "severity": {"type": "score", "instructions": "Risk severity if it goes wrong, 0-1", "criteria": list(SEVERITY_LEVELS)},
    }


def trace_text_enabled() -> bool:
    """Goal text leaves this process (trace file, /decide state) only on explicit opt-in."""
    return os.environ.get("DOTTIE_TRACE_TEXT", "").strip().lower() in ("1", "true", "yes")


def system_one_state(features: dict[str, Any], goal: str | None = None) -> dict[str, Any]:
    """The ``state`` System One sees. Same builder for serving and for the training pack."""
    state: dict[str, Any] = {
        "goal_features": {k: features[k] for k in ("n_words", "n_chars", "n_chain_signals", "has_code_terms", "complexity", "intent_scores", "mcp_prefix") if k in features},
    }
    if goal:
        state["goal_text"] = goal
    return state


class SystemOneBackend:
    """HTTP client for dottie-os ``POST /decide``. Never raises; short timeout."""

    name = "system_one"

    def __init__(self, url: str | None = None, timeout: float | None = None) -> None:
        self.url = (url if url is not None else os.environ.get("DOTTIE_OS_URL", "")).strip().rstrip("/")
        try:
            self.timeout = float(timeout if timeout is not None else os.environ.get("DOTTIE_OS_TIMEOUT", "1.5"))
        except ValueError:
            self.timeout = 1.5

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def request_body(self, goal: str) -> dict[str, Any]:
        feats = goal_features(goal)
        return {
            "schema": SYSTEM_ONE_SCHEMA,
            "state": system_one_state(feats, goal if trace_text_enabled() else None),
            "questions": system_one_questions(),
        }

    def _call(self, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        url = self.url + path
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"DOTTIE_OS_URL must be http(s): {self.url!r}")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",  # noqa: S310  scheme checked above
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310  scheme checked above
            return json.loads(resp.read().decode("utf-8"))

    def answer(self, goal: str) -> dict[str, Any]:
        base = {"backend": self.name, "enabled": self.enabled, "url": self.url or None}
        if not self.enabled:
            return {**base, "available": False, "tier": None, "signal": False, "gate_passed": False,
                    "stamped": False, "reason": "DOTTIE_OS_URL unset (System One off by default)"}
        try:
            health: dict[str, Any] = {}
            try:
                health = self._call("/health", None)
            except Exception:
                health = {}
            body = self._call("/decide", self.request_body(goal))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return {**base, "available": False, "tier": None, "signal": False, "gate_passed": False,
                    "stamped": False, "reason": f"dottie-os unreachable: {type(exc).__name__}: {exc}"}
        except Exception as exc:
            return {**base, "available": False, "tier": None, "signal": False, "gate_passed": False,
                    "stamped": False, "reason": f"dottie-os answer unreadable: {type(exc).__name__}: {exc}"}
        return {**base, **map_decide_answer(body, health)}


def _concentration(ans: dict[str, Any]) -> float | None:
    val = ans.get("shape_concentration")
    if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val)):
        return float(val)
    return None


def map_decide_answer(body: dict[str, Any], health: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map a ``/decide`` response onto a router answer. ``untrained`` = no signal."""
    health = health or {}
    mode = str(body.get("mode") or "")
    answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
    if body.get("schema") != SYSTEM_ONE_SCHEMA or not answers:
        return {"available": False, "tier": None, "signal": False, "gate_passed": False, "stamped": False,
                "mode": mode or None, "reason": "response is not a jev-decision-schema-1.0.0 answer"}
    tier_ans = answers.get("tier") if isinstance(answers.get("tier"), dict) else {}
    action_ans = answers.get("action") if isinstance(answers.get("action"), dict) else {}
    safe_ans = answers.get("safe") if isinstance(answers.get("safe"), dict) else {}
    sev_ans = answers.get("severity") if isinstance(answers.get("severity"), dict) else {}
    tier = tier_ans.get("choice") if tier_ans.get("choice") in MOMA_TIERS else None
    out: dict[str, Any] = {
        "available": True,
        "mode": mode,
        "model": body.get("model"),
        "shape_concentration": {k: _concentration(a) for k, a in (("tier", tier_ans), ("action", action_ans), ("severity", sev_ans))},
        "action": action_ans.get("choice"),
        "safe": safe_ans.get("noul"),
        "severity": sev_ans.get("score"),
        "artifact_sha256": health.get("checkpoint_sha256"),
        "gate_passed": bool(health.get("gate_passed", False)),
        "stamped": False,
    }
    if mode == "untrained":
        # uniform answers: keep the served shape_concentration as evidence, drop the arg-maxes
        return {**out, "tier": None, "action": None, "safe": None, "severity": None, "signal": False,
                "reason": "dottie-os mode=untrained: a uniform answer carries no signal"}
    if tier is None:
        return {**out, "tier": None, "signal": False, "reason": "no tier choice in the answer"}
    return {**out, "tier": tier, "signal": True, "reason": f"System One answer (mode={mode})"}
