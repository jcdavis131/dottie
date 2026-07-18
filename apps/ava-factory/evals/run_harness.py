"""CLI orchestrator for the real evaluation harness."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from evals.common import EVAL_SEED, load_model
from evals.jspace_tests import run_all_jspace_tests
from evals.needle import run_needle
from evals.perplexity import compute_ppl
from evals.probes import score_probes

_REPO = Path(__file__).resolve().parent.parent
REPORT_JSON = _REPO / "reports" / "branch_eval_results_real.json"
REPORT_MD = _REPO / "reports" / "REPORT_REAL.md"


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=_REPO, text=True).strip()
    except Exception:
        return "unknown"


def _verdict(row: dict) -> str:
    if "error" in row:
        return "ERROR"
    if row.get("pass") is True:
        return "PASS"
    if row.get("pass") is False:
        return "FAIL"
    return "MEASURED"


def _md_table(rows: list[tuple[str, str, str, str]]) -> str:
    lines = ["| Test | Bar | Measured | Verdict |", "|---|---|---|---|"]
    for test, bar, measured, verdict in rows:
        lines.append(f"| {test} | {bar} | {measured} | {verdict} |")
    return "\n".join(lines)


def run_harness(
    preset: str = "nano",
    base_ckpt: str = "none",
    chat_ckpt: str = "none",
    device: str = "cpu",
    probe_n: int = 200,
    skip_needle: bool = False,
) -> dict:
    t0 = time.time()
    import torch

    results: dict = {"meta": {}, "base": {}, "chat": {}}

    for branch, ckpt, chat in (("base", base_ckpt, False), ("chat", chat_ckpt, True)):
        torch.manual_seed(EVAL_SEED)
        model, tok, label = load_model(ckpt, preset, device, branch_chat=chat)
        branch_out: dict = {"ckpt": label}

        try:
            branch_out["perplexity"] = compute_ppl(model, preset, device=device)
        except Exception as e:
            branch_out["perplexity"] = {"error": str(e)}

        try:
            branch_out["probes"] = score_probes(model, tok, n_per_set=probe_n, device=device)
        except Exception as e:
            branch_out["probes"] = {"error": str(e)}

        try:
            branch_out["jspace"] = run_all_jspace_tests(model, tok, preset, device)
        except Exception as e:
            branch_out["jspace"] = {"error": str(e)}

        if branch == "base" and not skip_needle:
            try:
                branch_out["needle"] = run_needle(model, tok, device=device)
            except Exception as e:
                branch_out["needle"] = {"error": str(e)}

        results[branch] = branch_out

    results["meta"] = {
        "preset": preset,
        "base_ckpt": base_ckpt,
        "chat_ckpt": chat_ckpt,
        "device": device,
        "probe_n": probe_n,
        "git_sha": _git_sha(),
        "torch": torch.__version__,
        "wall_s": round(time.time() - t0, 2),
    }
    return results


def write_reports(results: dict) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")

    rows = []
    for branch in ("base", "chat"):
        jspace = results.get(branch, {}).get("jspace", [])
        if isinstance(jspace, list):
            for t in jspace:
                measured = json.dumps(t.get("measured", t.get("error", "")), default=str)[:80]
                rows.append((f"{branch}/{t.get('test', '?')}", t.get("bar", "-"), measured, _verdict(t)))

    # frozen-capability comparison
    comp_rows = ["\n## Frozen-capability comparison (base vs chat)\n"]
    comp_rows.append("| Metric | Base | Chat | Δ% | Note |")
    comp_rows.append("|---|---:|---:|---:|---|")
    base_p = results.get("base", {}).get("probes", {})
    chat_p = results.get("chat", {}).get("probes", {})
    if isinstance(base_p, dict) and isinstance(chat_p, dict):
        for key in ("arithmetic", "facts"):
            b = base_p.get(key, {}).get("accuracy")
            c = chat_p.get(key, {}).get("accuracy")
            if b is not None and c is not None and b > 0:
                delta = (c - b) / b * 100
                note = "REGRESSION" if delta < -5 else ""
                comp_rows.append(f"| probe {key} | {b:.3f} | {c:.3f} | {delta:+.1f}% | {note} |")

    md = [
        "# Ava Real Eval Report",
        "",
        f"Preset: {results['meta'].get('preset')} | Wall: {results['meta'].get('wall_s')}s | Device: {results['meta'].get('device')}",
        "",
        "## J-Space canonical tests",
        _md_table(rows) if rows else "(no jspace results)",
        "\n".join(comp_rows),
    ]
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Real eval harness")
    ap.add_argument("--preset", default="nano")
    ap.add_argument("--base-ckpt", default="none")
    ap.add_argument("--chat-ckpt", default="none")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--probe-n", type=int, default=200)
    ap.add_argument("--skip-needle", action="store_true")
    args = ap.parse_args()

    results = run_harness(
        preset=args.preset,
        base_ckpt=args.base_ckpt,
        chat_ckpt=args.chat_ckpt,
        device=args.device,
        probe_n=args.probe_n,
        skip_needle=args.skip_needle,
    )
    write_reports(results)
    print(f"wrote {REPORT_JSON} and {REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
