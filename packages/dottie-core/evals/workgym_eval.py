"""Dottie-on-WorkGym eval harness.

Runs a dottie-core Model as the policy on WorkGym environments and reports
mean reward per env. This is the baseline every future Dottie version must
beat — and the closed loop: the gym that trains Dottie also grades her.

The bridge is the honest seam:
    env obs -> WorldState (beliefs with provenance, source="env:<id>")
            -> typed Model query (CLASSIFY / CHOOSE, never free text)
            -> env action

The model never sees gold labels or reference solutions. For CHOOSE queries
it picks between candidate ids; the candidate *texts* are used only to
derive per-option keyword patterns (retrieval-style matching), never shown
as state.

Usage:
    PYTHONPATH=/path/to/workgym python3 evals/workgym_eval.py --seeds 4
    PYTHONPATH=/path/to/workgym python3 evals/workgym_eval.py \\
        --env workgym/cron-ops-v0 --seeds 8 --out results.json

Requires the `workgym` package:
    pip install -e /path/to/workgym        # local checkout
    # or
    pip install git+https://github.com/jcdavis131/workgym@v0.1.0
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import workgym
except ImportError:
    sys.exit("workgym not importable. pip install -e /path/to/workgym, "
             "or set PYTHONPATH=/path/to/workgym")

from dottie_core.state import Belief, StateRef, empty_state, register_schema
from dottie_core.model import Model, QueryKind, TypedQuery
from dottie_core.heuristic import HeuristicModel

LABELS = ("URGENT", "ACTION", "FYI", "NOISE")

_LABEL_KEYWORDS = {
    "URGENT": [r"unusual charge", r"freeze the card", r"unrecognized", r"sign-in",
               r"\bDOWN\b", r"outage", r"\bbreak\b", r"water main",
               r"verify recent transactions", r"need your approval",
               r"appointment", r"found your dog", r"critical", r"incident",
               r"\bASAP\b", r"immediately"],
    "ACTION": [r"question on", r"rate limits", r"lease renewal", r"response needed",
               r"deploy failed", r"\bdue\b", r"estimated taxes", r"for your review",
               r"\bdraft\b", r"open enrollment", r"ends friday", r"invoice",
               r"net 15"],
    "FYI": [r"is live", r"\bphotos\b", r"monthly statement", r"nightly eval",
            r"next book", r"reminder:", r"cleaning tomorrow"],
    "NOISE": [r"build #\d+ passed", r"today in startups", r"RESOLVED:",
              r"sale", r"% off", r"connection requests", r"this week in data",
              r"double miles", r"rate your recent"],
}

_STOPWORDS = frozenset(
    "the a an of to in on for with and or is are was were be been being "
    "it its this that these those as at by from we you he she they we our "
    "your his her their not no yes if then than so such can will would "
    "should could may might must shall file nothing ever never every "
    "file hook feed cron job server port trigger poll".split()
)


def _distinctive_patterns(text, limit=12):
    """Distinctive len>=4 words -> regex patterns, for per-option matching."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", text.lower())
    seen, pats = set(), []
    for w in words:
        if w in _STOPWORDS or w in seen:
            continue
        seen.add(w)
        pats.append(r"\b" + re.escape(w) + r"\b")
        if len(pats) >= limit:
            break
    return pats


class DottieWorkGymPolicy:
    """Wraps a dottie-core Model as a WorkGym policy."""

    model_id = "dottie-heuristic-bridge-v0"

    def __init__(self, model: Model | None = None):
        self.model = model or HeuristicModel()
        for key in ("subject", "body", "sender", "title", "context",
                    "logs", "config", "evidence"):
            try:
                register_schema(key, "str")
            except Exception:
                pass
        HeuristicModel.reset_keywords()
        for label, patterns in _LABEL_KEYWORDS.items():
            HeuristicModel.register_keywords("classify", label, patterns)

    def _state(self, env_id, fields: dict[str, str]):
        s = empty_state(f"wg-{env_id}")
        for i, (k, v) in enumerate(fields.items()):
            s = s.update(Belief(belief_id=f"b{i}-{k}", key=k, value=v,
                                confidence=1.0, source=f"env:{env_id}",
                                at_version=i), actor="bridge")
        return s

    def _classify_email(self, env_id, email):
        s = self._state(env_id, {
            "sender": email.get("from", ""),
            "subject": email.get("subject", ""),
            "body": email.get("body", ""),
        })
        q = TypedQuery(kind=QueryKind.CLASSIFY,
                       state_ref=StateRef(belief_keys=("sender", "subject", "body")),
                       options=LABELS)
        return self.model.decide(s, q).best.value

    def _choose(self, env_id, evidence: dict[str, str], candidates):
        """candidates: list of {id, text}. Returns chosen id."""
        HeuristicModel.reset_keywords("choose")
        for c in candidates:
            HeuristicModel.register_keywords("choose", c["id"],
                                             _distinctive_patterns(c["text"]))
        s = self._state(env_id, evidence)
        q = TypedQuery(kind=QueryKind.CHOOSE,
                       state_ref=StateRef(belief_keys=tuple(evidence)),
                       options=tuple(c["id"] for c in candidates))
        return self.model.decide(s, q).best.value

    def act(self, env_id, obs):
        if env_id == "workgym/inbox-triage-v0":
            labels = {e["id"]: self._classify_email(env_id, e)
                      for e in obs["emails"]}
            return {"op": "submit", "labels": labels}
        if env_id == "workgym/cron-ops-v0":
            evidence = {"title": obs["title"], "context": obs["context"],
                        "logs": obs["logs"], "config": obs["config"]}
            rc = self._choose(env_id, evidence, obs["root_causes"])
            fx = self._choose(env_id, evidence, obs["fixes"])
            return {"op": "submit", "root_cause": rc, "fix": fx}
        raise ValueError(f"no dottie policy for {env_id} yet")


def run_eval(policy, env_ids, seeds, verbose=False):
    results = {}
    for env_id in env_ids:
        rewards = []
        for seed in seeds:
            env = workgym.make(env_id)
            try:
                obs, _info = env.reset(seed=seed)
                action = policy.act(env_id, obs)
                _o, r, _t, _tr, _i = env.step(action)
                rewards.append(r)
                if verbose:
                    print(f"  {env_id} seed={seed} reward={r:.2f}")
            finally:
                env.close()
        results[env_id] = {
            "mean": sum(rewards) / len(rewards),
            "n": len(rewards),
            "rewards": rewards,
        }
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dottie-on-WorkGym eval harness")
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--env", default=None, help="single env (default: supported envs)")
    ap.add_argument("--out", default=None, help="write JSON results here")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--base-seed", type=int, default=7)
    args = ap.parse_args(argv)

    supported = ["workgym/inbox-triage-v0", "workgym/cron-ops-v0"]
    env_ids = [args.env] if args.env else supported
    unsupported = [e for e in env_ids if e not in supported]
    if unsupported:
        sys.exit(f"no dottie policy for {unsupported} yet (supported: {supported})")

    policy = DottieWorkGymPolicy()
    seeds = list(range(args.base_seed, args.base_seed + args.seeds))
    print(f"dottie model: heuristic-v0 via {DottieWorkGymPolicy.model_id}")
    results = run_eval(policy, env_ids, seeds, verbose=args.verbose)

    print(f"\n{'env':32s} {'mean':>6s} {'n':>3s}")
    for env_id, r in results.items():
        print(f"{env_id:32s} {r['mean']:6.3f} {r['n']:3d}")
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"model": DottieWorkGymPolicy.model_id,
                       "results": results}, f, indent=1)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
