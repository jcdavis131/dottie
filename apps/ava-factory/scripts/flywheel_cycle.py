"""P2 flywheel bridge — one deterministic cycle the nightly Routine runs end-to-end.

Orchestrates the EXISTING pipeline scripts (nothing here mines or trains):

    collect  copy new run dirs from the runner store
             (~/workspace/bundles/ultra/runs) into the repo store
             (bundles/ultra/runs); dirs already present are skipped; a missing
             runner store is a recorded no-op, not a failure.
    mine     subprocess scripts/build_orchestration_corpus.py build
             (--journal-dir passed through when given). A non-zero exit —
             including the corrections validator raising ValueError — aborts
             the cycle with the stderr tail recorded in the summary.
    train    subprocess scripts/orchestrator_hillclimb.py (--epochs passed
             through when > 0; 0 keeps the grid default). Skipped entirely
             with --skip-train (mine + gate-report only, for cheap refreshes).
    gate     parse reports/orchestrator/eval_report.json. FAIL-CLOSED: only a
             literal ``gate_passed: true`` selects the promoted path; false,
             missing, garbage, or any other value resolves to not-promoted.
    sync     reuse apps/dottie-harness-api/lib/copy_artifacts.py. Promoted:
             full vendor (weights + eval summary + corpus meta). Not promoted:
             meta jsons only — the champion weights in lib/weights are NEVER
             touched — so dashboard progress stays visible without shipping an
             ungated model.
    dashboard  subprocess apps/dottie-harness-api/scripts/build_dashboard.py.
    summary  always write reports/flywheel/cycle-summary.json.

``deploy_required`` in the summary is true after a promotion, or when a
meta-only sync changed the dashboard inputs (sha256 before/after of the synced
files). The deploy itself (Vercel, who-e project) is a PRIVILEGED operator /
session step and is deliberately NOT performed by this script — it only
reports that a deploy would change the live surface.

Usage:

    uv run python apps/ava-factory/scripts/flywheel_cycle.py \
        [--journal-dir DIR] [--epochs N] [--skip-train] [--dry-run]

Exit 0 iff every attempted step succeeded — a NOT-promoted gate verdict is
success (the gate doing its job is not an error). Exit 1 on any step failure.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

_REPO = Path(__file__).resolve().parents[3]

# Statuses that do NOT fail the cycle. Membership-checked (never dispatched on
# with a bare if/elif chain) so an unknown status fails CLOSED.
_OK_STATUSES = frozenset({"ok", "skipped"})

_SUMMARY_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _sha256(path: Path) -> str | None:
    """Hex digest of a file, or None when it does not exist."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tail(text: str, max_lines: int = 30, max_chars: int = 4000) -> str:
    lines = (text or "").strip().splitlines()
    return "\n".join(lines[-max_lines:])[-max_chars:]


def _paths() -> dict[str, Path]:
    """All filesystem surfaces the cycle touches, derived at call time.

    Reads the module-level ``_REPO`` so tests can point the whole cycle at a
    fixture tree; the runner store is HOME-relative per the harness manifest
    (~/workspace/bundles/ultra/runs — canonical, never CWD).
    """
    repo = _REPO
    ava = repo / "apps" / "ava-factory"
    pkg = repo / "apps" / "dottie-harness-api"
    return {
        "runner_store": Path.home() / "workspace" / "bundles" / "ultra" / "runs",
        "repo_store": repo / "bundles" / "ultra" / "runs",
        "mine_script": ava / "scripts" / "build_orchestration_corpus.py",
        "train_script": ava / "scripts" / "orchestrator_hillclimb.py",
        "corpus_dir": ava / "data" / "orchestration",
        "corpus_jsonl": ava / "data" / "orchestration" / "corpus.jsonl",
        "corpus_meta": ava / "data" / "orchestration" / "corpus_meta.json",
        "reports_dir": ava / "reports" / "orchestrator",
        "eval_report": ava / "reports" / "orchestrator" / "eval_report.json",
        "train_weights": ava / "reports" / "orchestrator" / "champion_weights.json",
        "copy_artifacts": pkg / "lib" / "copy_artifacts.py",
        "lib_meta": pkg / "lib" / "meta",
        "lib_weights": pkg / "lib" / "weights" / "champion_weights.json",
        "dashboard_script": pkg / "scripts" / "build_dashboard.py",
        "summary": ava / "reports" / "flywheel" / "cycle-summary.json",
    }


# ---------------------------------------------------------------------------
# step: collect
# ---------------------------------------------------------------------------


def collect_runs(src: Path, dst: Path) -> dict:
    """Copy run dirs from the runner store into the repo store.

    Dirs already present in ``dst`` are skipped (runs are append-only; the
    repo copy is authoritative once landed). A missing ``src`` is a recorded
    no-op — the runner store legitimately does not exist on every host.

    Each copy lands via a ``<name>.tmp-collect`` staging dir renamed into
    place, so an interrupted cycle can never leave a half-copied run dir
    under the final name — which the skip-existing check would then freeze
    forever and the miner would read as a complete run. Stale staging dirs
    from a crashed cycle are removed up front and re-copied whole.
    """
    if not src.is_dir():
        return {
            "status": "ok",
            "copied": 0,
            "skipped": 0,
            "note": f"runner store absent ({src}) — nothing to collect",
        }
    dst.mkdir(parents=True, exist_ok=True)
    for stale in dst.glob("*.tmp-collect"):
        shutil.rmtree(stale)
    copied = 0
    skipped = 0
    for run_dir in sorted(p for p in src.iterdir() if p.is_dir()):
        target = dst / run_dir.name
        if target.exists():
            skipped += 1
            continue
        staging = dst / (run_dir.name + ".tmp-collect")
        shutil.copytree(run_dir, staging)
        staging.rename(target)
        copied += 1
    return {
        "status": "ok",
        "copied": copied,
        "skipped": skipped,
        "source": str(src),
        "dest": str(dst),
    }


# ---------------------------------------------------------------------------
# steps: mine / train / dashboard (subprocess the existing scripts)
# ---------------------------------------------------------------------------


def _mine_cmd(args: argparse.Namespace, paths: dict[str, Path]) -> list[str]:
    cmd = [
        sys.executable,
        str(paths["mine_script"]),
        "build",
        "--out",
        str(paths["corpus_dir"]),
        "--ultra-dir",
        str(paths["repo_store"]),
    ]
    if args.journal_dir is not None:
        cmd += ["--journal-dir", str(args.journal_dir)]
    return cmd


def _train_cmd(args: argparse.Namespace, paths: dict[str, Path]) -> list[str]:
    cmd = [
        sys.executable,
        str(paths["train_script"]),
        "--corpus",
        str(paths["corpus_jsonl"]),
        "--out",
        str(paths["reports_dir"]),
    ]
    if args.epochs > 0:
        cmd += ["--epochs", str(args.epochs)]
    return cmd


def _dashboard_cmd(paths: dict[str, Path]) -> list[str]:
    return [sys.executable, str(paths["dashboard_script"])]


def _run_cmd(cmd: list[str]) -> dict:
    """Run one pipeline subprocess; non-zero exit fails the step, closed."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    rec: dict = {"cmd": cmd, "returncode": proc.returncode}
    if proc.returncode == 0:
        rec["status"] = "ok"
        rec["stdout_tail"] = _tail(proc.stdout, max_lines=10)
        return rec
    rec["status"] = "failed"
    rec["stdout_tail"] = _tail(proc.stdout, max_lines=10)
    rec["stderr_tail"] = _tail(proc.stderr)
    return rec


# ---------------------------------------------------------------------------
# step: gate (fail-closed parse of the trainer's verdict)
# ---------------------------------------------------------------------------


def resolve_gate(eval_report: Path) -> dict:
    """Parse the promotion verdict from eval_report.json, failing CLOSED.

    ``promoted`` is True ONLY when ``gate.gate_passed`` is the literal JSON
    ``true``. False, a missing file, a missing/odd gate section, unparseable
    JSON, or any non-boolean stand-in (``"true"``, ``1``, …) all resolve to
    not-promoted. The cycle never defaults to promoted on ambiguity.
    """
    out: dict = {
        "eval_report": str(eval_report),
        "gate_passed": None,
        "reason": None,
        "promoted": False,
    }
    try:
        doc = json.loads(eval_report.read_text(encoding="utf-8"))
    except FileNotFoundError:
        out["reason"] = "eval_report.json missing — not promoted (fail closed)"
        return out
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        out["reason"] = (
            f"eval_report.json unreadable ({type(exc).__name__}) — "
            "not promoted (fail closed)"
        )
        return out
    gate = doc.get("gate") if isinstance(doc, dict) else None
    if not isinstance(gate, dict):
        out["reason"] = (
            "gate section missing or not an object — not promoted (fail closed)"
        )
        return out
    out["gate_passed"] = gate.get("gate_passed")
    out["reason"] = gate.get("reason")
    out["promoted"] = gate.get("gate_passed") is True
    return out


# ---------------------------------------------------------------------------
# step: sync (reuse copy_artifacts.py — full vendor vs meta-only)
# ---------------------------------------------------------------------------


def _load_copy_artifacts(path: Path) -> ModuleType:
    """Import the harness package's vendoring script by file path.

    Loaded fresh per call (never cached in sys.modules) so the module's own
    __file__-relative source/dest resolution always matches ``path``.
    """
    spec = importlib.util.spec_from_file_location("_flywheel_copy_artifacts", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load copy_artifacts from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sync_artifacts(promoted: bool, paths: dict[str, Path]) -> dict:
    """Vendor artifacts into apps/dottie-harness-api/lib via copy_artifacts.py.

    Promoted: full vendor (weights verbatim + transformed eval summary +
    corpus meta) via the module's own copy functions, whose bool returns are
    recorded as measured; then verify sha256(lib weights) == sha256(trained
    weights) — copy_artifacts treats a missing source as a no-op, so a mere
    existence check would fail OPEN when a stale champion from a previous
    promotion is still vendored. Not promoted: the two meta jsons only;
    lib/weights is never touched.

    ``deploy_required`` is True on promotion, else true only when a synced
    meta file's sha256 changed (dashboard inputs moved).
    """
    meta_targets = {
        "eval_summary.json": paths["lib_meta"] / "eval_summary.json",
        "corpus_meta.json": paths["lib_meta"] / "corpus_meta.json",
    }
    before = {name: _sha256(p) for name, p in meta_targets.items()}
    mod = _load_copy_artifacts(paths["copy_artifacts"])
    if promoted:
        synced = {
            "weights/champion_weights.json": bool(mod._copy_weights()),
            "meta/eval_summary.json": bool(mod._copy_eval_summary()),
            "meta/corpus_meta.json": bool(mod._copy_corpus_meta()),
        }
        src_sha = _sha256(paths["train_weights"])
        if (
            not synced["weights/champion_weights.json"]
            or src_sha is None
            or _sha256(paths["lib_weights"]) != src_sha
        ):
            return {
                "status": "failed",
                "error": (
                    "promoted but lib/weights/champion_weights.json does not "
                    "match the freshly trained champion (source missing or "
                    "vendor no-op; a stale previous champion may still be "
                    "vendored) — refusing to report a deployable state"
                ),
            }
    else:
        synced = {
            "meta/eval_summary.json": bool(mod._copy_eval_summary()),
            "meta/corpus_meta.json": bool(mod._copy_corpus_meta()),
        }
    after = {name: _sha256(p) for name, p in meta_targets.items()}
    meta_changed = sorted(name for name in before if before[name] != after[name])
    deploy_required = True if promoted else bool(meta_changed)
    return {
        "status": "ok",
        "mode": "full_vendor" if promoted else "meta_only",
        "synced": synced,
        "meta_sha256_before": before,
        "meta_sha256_after": after,
        "meta_changed": meta_changed,
        "deploy_required": deploy_required,
    }


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def _corpus_counts(meta_path: Path) -> dict | None:
    """counts{} from the freshly mined corpus_meta.json, or None if unreadable."""
    try:
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    counts = doc.get("counts") if isinstance(doc, dict) else None
    return counts if isinstance(counts, dict) else None


def _write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# cycle driver
# ---------------------------------------------------------------------------


def run_cycle(args: argparse.Namespace, paths: dict[str, Path]) -> dict:
    """Run the cycle, always writing the machine-readable summary."""
    started_at = _utc_now_iso()
    steps: list[dict] = []
    failed = False
    promoted = False
    deploy_required = False
    mine_fresh = False  # corpus_meta.json was (re)written by THIS cycle's mine
    gate_summary: dict = {
        "gate_passed": None,
        "reason": "gate step not reached (an earlier step failed)",
    }

    def _attempt(name: str, fn) -> dict:
        nonlocal failed
        try:
            rec = dict(fn())
        except Exception as exc:  # fail closed on anything unexpected
            rec = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        rec = {"name": name, **rec}
        steps.append(rec)
        if rec.get("status") not in _OK_STATUSES:
            failed = True
        return rec

    _attempt(
        "collect", lambda: collect_runs(paths["runner_store"], paths["repo_store"])
    )
    if not failed:
        mine_rec = _attempt("mine", lambda: _run_cmd(_mine_cmd(args, paths)))
        mine_fresh = mine_rec.get("status") == "ok"
    if not failed:
        if args.skip_train:
            steps.append(
                {
                    "name": "train",
                    "status": "skipped",
                    "note": "--skip-train: gate reads the existing eval_report.json",
                }
            )
        else:
            _attempt("train", lambda: _run_cmd(_train_cmd(args, paths)))
    if not failed:
        gate_rec = _attempt(
            "gate", lambda: {"status": "ok", **resolve_gate(paths["eval_report"])}
        )
        promoted = gate_rec.get("promoted") is True
        gate_summary = {
            "gate_passed": gate_rec.get("gate_passed"),
            "reason": gate_rec.get("reason"),
        }
    if not failed:
        sync_rec = _attempt("sync", lambda: sync_artifacts(promoted, paths))
        if sync_rec.get("status") == "ok":
            deploy_required = sync_rec.get("deploy_required") is True
    if not failed:
        _attempt("dashboard", lambda: _run_cmd(_dashboard_cmd(paths)))

    summary = {
        "schema_version": _SUMMARY_SCHEMA_VERSION,
        "script": "apps/ava-factory/scripts/flywheel_cycle.py",
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "args": {
            "journal_dir": (
                str(args.journal_dir) if args.journal_dir is not None else None
            ),
            "epochs": args.epochs,
            "skip_train": args.skip_train,
        },
        "steps": steps,
        "gate": gate_summary,
        "promoted": promoted,
        # Only counts the mine step wrote THIS cycle; a stale corpus_meta.json
        # from a previous night must never be reported as this cycle's corpus.
        "corpus_counts": (
            _corpus_counts(paths["corpus_meta"]) if mine_fresh else None
        ),
        "deploy_required": deploy_required,
        "ok": not failed,
    }
    _write_summary(paths["summary"], summary)
    return summary


def _plan_lines(args: argparse.Namespace, paths: dict[str, Path]) -> list[str]:
    lines = [
        (
            f"collect:   copy new run dirs {paths['runner_store']} -> "
            f"{paths['repo_store']} (existing dirs skipped)"
        ),
        "mine:      " + " ".join(_mine_cmd(args, paths)),
    ]
    if args.skip_train:
        lines.append("train:     skipped (--skip-train)")
    else:
        lines.append("train:     " + " ".join(_train_cmd(args, paths)))
    lines += [
        (
            f"gate:      parse {paths['eval_report']} — promoted ONLY on "
            "gate_passed == true (fail closed)"
        ),
        (
            f"sync:      {paths['copy_artifacts']} — full vendor when promoted, "
            "meta-only otherwise (weights untouched)"
        ),
        "dashboard: " + " ".join(_dashboard_cmd(paths)),
        f"summary:   write {paths['summary']}",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "P2 flywheel bridge: collect -> mine -> train -> gate -> sync -> "
            "dashboard, with a machine-readable summary in "
            "reports/flywheel/cycle-summary.json. Fail-closed at every step; "
            "the deploy itself is a privileged session step, not this script's job."
        )
    )
    parser.add_argument(
        "--journal-dir",
        type=Path,
        default=None,
        help="passed through to build_orchestration_corpus.py build (optional; "
        "the workflow journal lives outside the repo)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=0,
        help="passed through to orchestrator_hillclimb.py when > 0; "
        "0 keeps the trainer's grid default (nightly full-budget uses 200)",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="mine + gate-report only (train step skipped; the gate reads the "
        "existing eval_report.json) — for cheap refreshes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and execute nothing (no subprocesses, no writes)",
    )
    args = parser.parse_args(argv)
    paths = _paths()

    if args.dry_run:
        print("[flywheel] DRY RUN — plan only, executing nothing")
        for line in _plan_lines(args, paths):
            print(f"  {line}")
        return 0

    summary = run_cycle(args, paths)
    print(
        "[flywheel] ok={ok} promoted={promoted} deploy_required={deploy} "
        "summary={path}".format(
            ok=summary["ok"],
            promoted=summary["promoted"],
            deploy=summary["deploy_required"],
            path=paths["summary"],
        )
    )
    if summary["ok"]:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
