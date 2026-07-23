"""Post-run probe error analysis — bucket per-probe generations into failure modes.

The live probe suite (evals/probes.py via evals/run_harness.py) reports only
aggregate exact-match counts per set — reports/branch_eval_results_real.json
carries ``{"accuracy", "correct", "total"}`` and nothing per item. 0/200 says
*that* the model missed, not *how*. This tool consumes a per-probe generations
artifact and classifies every miss:

    wrong_tool     — named/called an inventory tool other than the gold one,
                     or reached for any tool when the gold answer is "no tool"
    malformed_call — call syntax that never closes, or a callable that is not
                     in the tool inventory at all (hallucinated tool)
    refusal        — refusal/deflection phrasing instead of an answer
    other          — none of the above (incl. degenerate text loops)

Generations artifact: JSONL, one row per probe item:

    {"set": "tool_selection", "prompt": "...", "answer": "...", "generation": "..."}

That is the dump a post-run decode pass over evals/probe_items/*.jsonl produces
(greedy_decode per item, decoded continuation in "generation"). Producing it
needs the trainer image + a checkpoint; pointed at the aggregate report alone,
this tool prints the aggregates and states exactly what is missing — it never
fabricates per-item data (repo anti-mock discipline).

``--dry-run`` exercises the full path against scripts/fixtures/probe_error_analysis/
(no model, no GPU, no writes). Fixture rows carry an ``expect`` field; dry-run
verifies the classifier against it and fails loudly on drift.

Truth parity: answer normalization is imported from evals.probe_items_gen
(``norm_answer``) — the same primitive the real scorer uses — so "correct" here
can never drift from the probe suite's definition.

Host-side, torch-free. Works from the repo root or inside the trainer image.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from evals.probe_items_gen import norm_answer  # noqa: E402

_FIXTURE_DIR = _REPO / "scripts" / "fixtures" / "probe_error_analysis"

NO_TOOL = "no tool"
FAILURE_MODES = ("wrong_tool", "malformed_call", "refusal", "other")

_REFUSAL_MARKERS = (
    "i cannot",
    "i can't",
    "i won't",
    "i refuse",
    "cannot help",
    "can not help",
    "unable to",
    "will not help",
    "as an ai",
)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# The probe surface-form's menu framing (evals/probe_items/tool_selection.jsonl).
_MENU_RE = re.compile(r"Toolbox:\s*([^.]+)\.")


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{i}: not valid JSON ({exc})") from exc
    return rows


def build_inventory(rows: list[dict]) -> set[str]:
    """Tool inventory derived from the ARTIFACT itself: identifier-shaped gold
    answers of tool-flavored sets ("tool" in the set name), plus every name
    listed in any prompt's Toolbox menu. Non-tool sets' golds (e.g. facts'
    'Paris') stay out. Deliberately not seeded from generations — an unknown
    callable in a generation is the malformed-call signal, not inventory."""
    inv: set[str] = set()
    for row in rows:
        ans = str(row.get("answer", "")).strip()
        if (
            "tool" in str(row.get("set", "")).lower()
            and ans
            and ans != NO_TOOL
            and _IDENT_RE.fullmatch(ans)
        ):
            inv.add(ans.lower())
        m = _MENU_RE.search(str(row.get("prompt", "")))
        if m:
            for name in m.group(1).split(","):
                name = name.strip()
                if _IDENT_RE.fullmatch(name):
                    inv.add(name.lower())
    return inv


def classify(row: dict, inventory: set[str]) -> tuple[str, str]:
    """(label, detail) for one generation row. Label is 'correct' or one of
    FAILURE_MODES. Heuristics are ordered; the first match decides."""
    gold = str(row.get("answer", "")).strip()
    gen = str(row.get("generation", ""))
    ng, na = norm_answer(gen), norm_answer(gold)

    if ng == na or ng.startswith(na + " "):
        return "correct", "exact/prefix match"

    if any(marker in ng for marker in _REFUSAL_MARKERS):
        return "refusal", "refusal phrasing"

    gold_is_tool = gold.lower() in inventory
    mentioned = [w.lower() for w in _IDENT_RE.findall(gen) if w.lower() in inventory]

    if na == NO_TOOL:
        if mentioned or _CALL_RE.search(gen):
            return "wrong_tool", "reached for a tool when none was needed"
        return "other", "missed 'no tool' without naming one"

    call = _CALL_RE.search(gen)
    if call:
        name = call.group(1).lower()
        if ")" not in gen[call.end():]:
            return "malformed_call", f"unclosed call to {name!r}"
        if name not in inventory:
            return "malformed_call", f"hallucinated callable {name!r}"
        if gold_is_tool and name == gold.lower():
            # right tool, wrong surface form — the exact-match probe wanted the bare name
            return "other", "right tool called, exact-match form missed"
        return "wrong_tool", f"called {name!r}, gold {gold!r}"

    if gold_is_tool and mentioned:
        if mentioned[0] == gold.lower():
            return "other", "right tool named, exact-match form missed"
        return "wrong_tool", f"named {mentioned[0]!r}, gold {gold!r}"

    return "other", "no tool named, no call, no refusal"


def analyze(rows: list[dict]) -> dict:
    inventory = build_inventory(rows)
    sets: dict[str, dict] = {}
    out_rows = []
    for row in rows:
        label, detail = classify(row, inventory)
        name = str(row.get("set", "?"))
        bucket = sets.setdefault(
            name,
            {"total": 0, "counts": {"correct": 0, **{m: 0 for m in FAILURE_MODES}}},
        )
        bucket["total"] += 1
        bucket["counts"][label] += 1
        out_rows.append({**row, "class": label, "detail": detail})
    return {"inventory": sorted(inventory), "sets": sets, "rows": out_rows}


def print_report_aggregates(report: dict, log=print) -> None:
    log("aggregate probe results (per-set exact-match, from the harness report):")
    for branch in ("base", "chat"):
        probes = report.get(branch, {}).get("probes", {})
        if not isinstance(probes, dict) or not probes:
            continue
        ckpt = report.get(branch, {}).get("ckpt", "?")
        log(f"  [{branch}] ckpt={ckpt}")
        for name, agg in probes.items():
            if isinstance(agg, dict) and "total" in agg:
                log(
                    f"    {name:<16} {agg.get('correct', '?'):>4}/{agg.get('total', '?'):<4}"
                    f" acc={agg.get('accuracy', float('nan')):.3f}"
                )


def print_analysis(analysis: dict, max_dump: int, log=print) -> None:
    log(f"tool inventory ({len(analysis['inventory'])}): "
        + ", ".join(analysis["inventory"]))
    log("")
    log("per-set failure modes:")
    header = f"  {'set':<16}{'total':>6}{'correct':>9}" + "".join(
        f"{m:>16}" for m in FAILURE_MODES
    )
    log(header)
    for name, bucket in analysis["sets"].items():
        c = bucket["counts"]
        log(
            f"  {name:<16}{bucket['total']:>6}{c['correct']:>9}"
            + "".join(f"{c[m]:>16}" for m in FAILURE_MODES)
        )
    log("")
    log(f"per-probe generations (first {max_dump} per set):")
    shown: dict[str, int] = {}
    for row in analysis["rows"]:
        name = str(row.get("set", "?"))
        if shown.get(name, 0) >= max_dump:
            continue
        shown[name] = shown.get(name, 0) + 1
        gen = str(row.get("generation", "")).replace("\n", "\\n")
        log(f"  [{name}] {row['class']:<15} gold={row.get('answer', '')!r:<20}"
            f" gen={gen[:80]!r}  ({row['detail']})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="probe_error_analysis", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--generations", type=Path, default=None,
                    help="per-probe generations JSONL (set/prompt/answer/generation)")
    ap.add_argument("--report", type=Path, default=None,
                    help="run_harness JSON (branch_eval_results_real.json shape) "
                         "for aggregate context")
    ap.add_argument("--out", type=Path, default=None,
                    help="write the full classified analysis as JSON here")
    ap.add_argument("--max-dump", type=int, default=25,
                    help="per-set cap on dumped generations (default 25)")
    ap.add_argument("--dry-run", action="store_true",
                    help="run against the bundled fixture; verify classifier "
                         "against each row's 'expect'; never write")
    args = ap.parse_args(argv)

    if args.dry_run:
        args.generations = _FIXTURE_DIR / "generations.jsonl"
        args.report = _FIXTURE_DIR / "report.json"
        if args.out:
            print("--dry-run never writes; ignoring --out")
            args.out = None

    if not args.generations and not args.report:
        ap.error("need --generations and/or --report (or --dry-run)")

    if args.report:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        print_report_aggregates(report)
        print("")

    if not args.generations:
        print(
            "no per-probe generations artifact given: the aggregate harness report "
            "does not contain per-item generations, so failure modes are UNMEASURED "
            "here. Produce a generations dump (trainer image + checkpoint) and pass "
            "--generations; --dry-run demonstrates the pipeline on the fixture."
        )
        return 0

    rows = load_jsonl(Path(args.generations))
    analysis = analyze(rows)
    print_analysis(analysis, args.max_dump)

    if args.dry_run:
        drift = [
            (r.get("set"), r.get("answer"), r.get("expect"), r["class"])
            for r in analysis["rows"]
            if r.get("expect") and r["class"] != r["expect"]
        ]
        if drift:
            print("\nFIXTURE DRIFT — classifier disagrees with fixture expectations:")
            for s, a, want, got in drift:
                print(f"  [{s}] gold={a!r}: expected {want}, classified {got}")
            return 1
        n = sum(1 for r in analysis["rows"] if r.get("expect"))
        print(f"\ndry-run OK: classifier matches all {n} fixture expectations")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
