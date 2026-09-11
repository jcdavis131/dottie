"""Acceptance matrix (spec §38) and definition of done (§39) as checkable data.

§38 lists RT-01…RT-17 and ML-01…ML-17 with the evidence each needs; the tests in
this package are named after those IDs so coverage is grep-able. §39 lists thirty
"done" items. Both are reported HONESTLY: a test proves the mechanics of an item,
never the operator's part of it. An item whose evidence is a registered runner,
real users, fresh baselines or a drill against real stores stays ``operator_pending``
until the operator supplies that evidence explicitly; ``spec done`` therefore exits
2 until every item is proven, and nothing in this module can make it exit 0 alone.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import now_iso

RT_ITEMS: dict[str, str] = {
    "RT-01": "All surfaces create the same GoalEnvelope semantics",
    "RT-02": "Duplicate intake cannot create duplicate goals",
    "RT-03": "Routing is deterministic under identical inputs/config",
    "RT-04": "Plans are valid acyclic graphs",
    "RT-05": "Effects require exact approval",
    "RT-06": "Capabilities are enforced at execution",
    "RT-07": "Runs resume without duplicate effects",
    "RT-08": "Recovery ladder is bounded",
    "RT-09": "Completion means postcondition verified",
    "RT-10": "Timeline carries mandatory seven fields",
    "RT-11": "Memory writes are evidence-backed",
    "RT-12": "Pair capture is off by default",
    "RT-13": "Capture redacts before persistence",
    "RT-14": "Deletion propagates through lineage",
    "RT-15": "Provider blocks stop all further task calls",
    "RT-16": "Slack reports are deduped and concise",
    "RT-17": "API absence is honest",
}
ML_ITEMS: dict[str, str] = {
    "ML-01": "All dataset inputs have license/consent",
    "ML-02": "QA failures hard-block release",
    "ML-03": "Record accounting reconciles",
    "ML-04": "Train/dev/test are isolated",
    "ML-05": "Packing is lossless where required",
    "ML-06": "Reward resists acceptance hacking",
    "ML-07": "Training is reproducible",
    "ML-08": "Forge runner is real and healthy",
    "ML-09": "Challenger beats incumbent held out",
    "ML-10": "No critical regression",
    "ML-11": "Mocks/synthetic data cannot promote",
    "ML-12": "Metrics are fresh",
    "ML-13": "Canary is attributable",
    "ML-14": "Promotion requires explicit approval",
    "ML-15": "Served artifact matches approved hash",
    "ML-16": "Rollback is tested",
    "ML-17": "One closed loop completes end to end",
}
#: §38: these cannot be waived by a status label, anecdotal usefulness, or urgency
NON_WAIVABLE = ("ML-09", "ML-10", "ML-11", "ML-12", "ML-14", "ML-15", "ML-16")
#: IDs whose acceptance evidence is physical (runner, users, production) — a test proves mechanics only
OPERATOR_EVIDENCE_IDS = {"ML-08": "registered runner + one harmless job", "ML-12": "production metric sources", "ML-15": "direct post-deploy verification of the served artifact", "ML-17": "one real opted-in session through the whole chain"}

#: §39 thirty items: (id, statement, kind, evidence pointer)
DONE_CHECKLIST: tuple[tuple[str, str, str, str], ...] = (
    ("D01", "A user can enter a goal in each supported surface", "mechanics", "RT-01; surfaces.py, cli.py, scout loop goal"),
    ("D02", "Progress and blockers are understandable", "mechanics", "RT-16; errors.BlockedError; civilization report format"),
    ("D03", "Outcomes are verified, not merely generated", "mechanics", "RT-09"),
    ("D04", "Approvals are exact and one-time", "mechanics", "RT-05"),
    ("D05", "Failures resume safely", "mechanics", "RT-07, RT-08"),
    ("D06", "One tool plane enforces capabilities", "mechanics", "RT-06; tools.py"),
    ("D07", "Skills are versioned and benchmarked", "mechanics", "skills.py; mock benchmark evidence refused"),
    ("D08", "Checkpoints and timelines are durable", "mechanics", "RT-10, RT-07; timeline.py fsync"),
    ("D09", "Memory retains provenance and corrections", "mechanics", "RT-11"),
    ("D10", "Incident and rollback runbooks are tested", "operator", "incidents.py + `incident drill` against real stores; ML-16 drill on the served artifact"),
    ("D11", "Capture is opt-in and redacted before write", "mechanics", "RT-12, RT-13"),
    ("D12", "Consent and deletion propagate", "mechanics", "RT-14; privacy hold|delete; canary_deletion_test"),
    ("D13", "QA hard-blocks every release", "mechanics", "ML-02"),
    ("D14", "Deduplication and decontamination pass", "mechanics", "ML-04"),
    ("D15", "Manifests reconcile all records", "mechanics", "ML-03"),
    ("D16", "Training is reproducible on registered hardware", "operator", "ML-07 check + ML-08 registered runner rerun"),
    ("D17", "Reward is task-first and anti-hacking", "mechanics", "ML-06"),
    ("D18", "Held-out primary metric improves", "operator", "ML-09 on a frozen, non-synthetic EvalBundle"),
    ("D19", "Safety and regression floors hold", "operator", "ML-10 on the protected suites against a real challenger"),
    ("D20", "Mocks never count as capability evidence", "mechanics", "ML-11; anti_mock gate; bench excludes synthetic"),
    ("D21", "Canary is limited and attributable", "mechanics", "ML-13; canary.py"),
    ("D22", "Explicit approval is recorded", "mechanics", "ML-14; approvals.py"),
    ("D23", "Served artifact matches approved hash", "operator", "ML-15 against production"),
    ("D24", "Monitoring is fresh and actionable", "operator", "ML-12; observability.py SLOs on production sources"),
    ("D25", "Rollback restores known-good state", "operator", "ML-16 timed drill"),
    ("D26", "Machines handle repeated checks quietly", "mechanics", "civilization.py T0 pollers, deduped wakeups"),
    ("D27", "Specialists are bounded and non-recursive", "mechanics", "rlm.py depth/child budgets; civilization.py"),
    ("D28", "Token and compute costs are measured", "mechanics", "timeline tokens_est/token_method; civilization ledger"),
    ("D29", "Backups restore in drills", "operator", "`incident drill` with every item proven on real backups"),
    ("D30", "Owners and escalation paths are current", "operator", "HANDOFF.md + DAG owners re-verified against git log"),
)

_TOKEN = re.compile(r"(rt|ml)(\d{2})", re.I)
_RANGE = re.compile(r"(rt|ml)(\d{2})_to_(rt|ml)(\d{2})", re.I)
_DEF = re.compile(r"^\s*def (test_\w+)", re.M)


def ids_in_test_name(name: str) -> set[str]:
    """``test_ml09_to_ml13_x`` → ML-09..ML-13; ``test_rt01_a_rt02_b`` → RT-01, RT-02."""
    out: set[str] = set()
    rest = name
    for m in _RANGE.finditer(name):
        a, b = int(m.group(2)), int(m.group(4))
        if m.group(1).lower() != m.group(3).lower() or b < a:
            raise InvalidInputError(f"malformed acceptance range in {name!r}", field="test")
        out.update(f"{m.group(1).upper()}-{i:02d}" for i in range(a, b + 1))
        rest = rest.replace(m.group(0), " ")
    for m in _TOKEN.finditer(rest):
        out.add(f"{m.group(1).upper()}-{int(m.group(2)):02d}")
    return out


def scan_tests(tests_dir: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {i: [] for i in (*RT_ITEMS, *ML_ITEMS)}
    for path in sorted(Path(tests_dir).glob("test_*.py")):
        for name in _DEF.findall(path.read_text(encoding="utf-8")):
            for i in ids_in_test_name(name):
                if i in found:
                    found[i].append(f"{path.name}::{name}")
    return found


def coverage(tests_dir: Path) -> dict[str, Any]:
    if not Path(tests_dir).is_dir():
        raise InvalidInputError("tests directory not found", field="tests")
    found = scan_tests(tests_dir)
    missing = [i for i, t in found.items() if not t]
    return {
        "items": {i: {"requirement": (RT_ITEMS | ML_ITEMS)[i], "tests": t, "mechanics_only": i in OPERATOR_EVIDENCE_IDS, "operator_evidence": OPERATOR_EVIDENCE_IDS.get(i)} for i, t in found.items()},
        "covered": len(found) - len(missing),
        "total": len(found),
        "missing": missing,
        "non_waivable": list(NON_WAIVABLE),
        "verdict": "every acceptance ID has a named test (mechanics); operator evidence still required where marked" if not missing else "incomplete",
        "at": now_iso(),
    }


def definition_of_done(tests_dir: Path, operator_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every §39 item with its status. ``operator_evidence`` maps D-ids to a truthy
    record ({"proven": true, "ref": ...}); a bare ``true`` is not enough — a proof names its evidence."""
    cov = coverage(tests_dir)
    ev = operator_evidence or {}
    items = []
    for did, statement, kind, pointer in DONE_CHECKLIST:
        rt_ml = sorted(ids_in_test_name(pointer.replace("-", "").lower()))
        mechanics = all(cov["items"][i]["tests"] for i in rt_ml) if rt_ml else True
        rec = ev.get(did)
        proven_by_operator = isinstance(rec, dict) and bool(rec.get("proven")) and bool(str(rec.get("ref", "")).strip())
        if kind == "mechanics":
            status = "mechanics_proven" if mechanics else "mechanics_missing"
        else:
            status = "operator_proven" if proven_by_operator else "operator_pending"
        items.append({"id": did, "statement": statement, "kind": kind, "evidence": pointer, "acceptance_ids": rt_ml, "status": status, "operator_ref": rec.get("ref") if proven_by_operator else None})
    pending = [i["id"] for i in items if i["status"] in ("operator_pending", "mechanics_missing")]
    return {"items": items, "complete": not pending, "pending": pending, "counts": {"mechanics_proven": sum(i["status"] == "mechanics_proven" for i in items), "operator_proven": sum(i["status"] == "operator_proven" for i in items), "operator_pending": sum(i["status"] == "operator_pending" for i in items), "mechanics_missing": sum(i["status"] == "mechanics_missing" for i in items)}, "rule": "done is proof that the bounded system can improve safely; mechanics tests never stand in for operator evidence", "at": now_iso()}
