"""
runner.py — runs harness, supports mock and real modes, torch optional
YAML-versioned tasks (harness/tasks/*.yaml) + Eleuther-style log_samples
Solo personal project, no connection to employer, built with public/free-tier only
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import argparse, json, time, os, sys, pathlib

from .registry import EVAL_REGISTRY, list_evals
# ensure evals loaded
import harness.evals  # noqa

def _try_load_yaml_tasks(tasks_dir: str = "harness/tasks") -> Dict[str, Dict[str,Any]]:
    """Load versioned YAML task definitions if pyyaml available."""
    tasks: Dict[str, Dict[str,Any]] = {}
    # resolve path relative to this file
    here = pathlib.Path(__file__).parent
    cand_dirs = [
        here / "tasks",
        pathlib.Path.cwd() / "harness" / "tasks",
        pathlib.Path.cwd() / tasks_dir,
        here.parent / "tasks",
    ]
    task_dir = None
    for d in cand_dirs:
        if d.exists():
            task_dir = d
            break
    if not task_dir:
        return tasks
    try:
        import yaml
    except ImportError:
        return tasks
    for yf in task_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
            name = data.get("name") or yf.stem
            # version field required for reproducibility
            if "version" not in data:
                data["version"] = "1.0"
            tasks[name] = data
        except Exception:
            continue
    return tasks


def resolve_eval_names(eval_names: List[str] | str) -> List[str]:
    """Resolve eval names and group names to registered evals.

    Unknown names are a HARD ERROR listing valid choices — a typo must never
    silently fall back to running everything. Group names (e.g. 'jspace')
    expand via list_evals(group=...), so `--eval jspace` runs the jspace group
    as the README documents.
    """
    if isinstance(eval_names, str):
        if eval_names == "all":
            return list_evals()
        eval_names = [s.strip() for s in eval_names.split(",") if s.strip()]
    groups = sorted({v["group"] for v in EVAL_REGISTRY.values()})
    resolved: List[str] = []
    for n in eval_names:
        if n == "all":
            expansion = list_evals()
        elif n in EVAL_REGISTRY:
            expansion = [n]
        elif n in groups:
            expansion = list_evals(group=n)
        else:
            raise ValueError(
                f"unknown eval {n!r}. Valid evals: {', '.join(list_evals())}. "
                f"Valid groups: {', '.join(groups)}."
            )
        for e in expansion:
            if e not in resolved:
                resolved.append(e)
    if not resolved:
        raise ValueError(f"no evals selected. Valid evals: {', '.join(list_evals())}")
    return resolved


def _extract_log_samples(res: Dict[str, Any], limit: int) -> List[Any]:
    """Per-sample records for --log-samples.

    Only REAL per-sample data provided by the eval itself is passed through
    (measured['samples'] or measured['details'] lists). When an eval provides
    no per-sample data the result is [] — the harness never synthesizes sample
    rows (the old hash-derived entries were fabricated provenance)."""
    measured = res.get("measured")
    if isinstance(measured, dict):
        for key in ("samples", "details"):
            v = measured.get(key)
            if isinstance(v, list):
                return v[:limit]
    return []


def run_harness(
    eval_names: List[str] | str = "all",
    mode: str = "mock",
    backend: str = "auto",
    ckpt: str | None = None,
    preset: str = "nano",
    device: str = "cpu",
    verbose: bool = False,
    log_samples: int = 0,
    task_version: str = "1.0",
    tokenizer: str | None = None,
    **kwargs,
) -> Dict[str,Any]:
    from .common import load_model, factory_available, factory_root

    # backend: auto|mock only. 'mock' forces mock inference regardless of mode;
    # 'auto' follows mode (mock→mock, real→torch). No phantom hf/vllm backends.
    if backend not in ("auto", "mock"):
        raise ValueError(f"unknown backend {backend!r}; choices are auto|mock")
    if backend == "mock":
        mode = "mock"
    effective_backend = "mock" if mode == "mock" else "torch"

    eval_names = resolve_eval_names(eval_names)

    # load YAML versioned tasks
    yaml_tasks = _try_load_yaml_tasks()
    # merge version info
    versions: Dict[str,str] = {}
    for n in eval_names:
        if n in yaml_tasks:
            versions[n] = str(yaml_tasks[n].get("version", task_version))
        else:
            versions[n] = task_version

    # load model — in real mode any load failure becomes a structured
    # honest-failure report below (never a silent mock).
    model = tok = None
    load_error: Optional[str] = None
    if mode == "real":
        if ckpt is None:
            load_error = "no --ckpt provided"
        else:
            try:
                model, tok = load_model(ckpt, preset=preset, device=device, tokenizer_path=tokenizer)
            except Exception as e:
                load_error = str(e)
    else:
        model, tok = load_model(None, preset=preset, device=device)

    from .common import MockModel as _MockModel, MockTokenizer as _MockTokenizer
    # A "real" report backed by a mock model OR a mock tokenizer is fabricated
    # (HARNESS_SPEC anti-mock rule). Also covers the real-model-but-missing-tokenizer
    # case, where the model would run over hash-derived garbage token IDs.
    real_load_failed = mode == "real" and (
        load_error is not None
        or isinstance(model, _MockModel) or isinstance(tok, _MockTokenizer)
    )

    results: Dict[str,Any] = {
        "meta": {
            "mode": mode,
            "backend": effective_backend,
            "ckpt": ckpt or "mock/random-init",
            "preset": preset,
            "device": device,
            "eval_names": eval_names,
            "versions": versions,
            "task_version": task_version,
            "log_samples": log_samples,
            "yaml_tasks_loaded": len(yaml_tasks),
            "factory_root": factory_root(),
            "factory_available": factory_available(),
        },
        "evals": {}
    }
    start = time.time()
    if real_load_failed:
        # Return a STRUCTURED honest-failure report (not a raise): every downstream
        # caller — the report writer, ava-skills eval-harness-runner, the factory
        # training gate — receives a normal report shape with pass=False + an error
        # per eval, instead of an exception a broad `except` could swallow and then
        # fabricate around. This is the loud failure, expressed as data.
        why = (f"--mode real requested but no real model/tokenizer loaded "
               f"(ckpt={ckpt!r}"
               + (f", cause: {load_error}" if load_error else "")
               + "). Provide a valid --ckpt (and --tokenizer), or use --mode mock.")
        results["meta"]["error"] = why
        results["meta"]["real_load_failed"] = True
        for name in eval_names:
            results["evals"][name] = {"test": name, "measured": None, "pass": False,
                                      "bar": EVAL_REGISTRY[name].get("description", ""),
                                      "error": f"real mode not run: {why}"}
        results["meta"]["wall_s"] = time.time() - start
        results["meta"]["passed"] = 0
        results["meta"]["total"] = len(results["evals"])
        return results
    for name in eval_names:
        entry = EVAL_REGISTRY[name]
        fn = entry["fn"]
        if verbose:
            print(f"[runner] running {name} ({entry['description']}) version={versions.get(name)}")
        try:
            extra = dict(kwargs)
            extra.update({
                "preset": preset,
                "version": versions.get(name, task_version),
                "yaml_task": yaml_tasks.get(name),
            })
            res = fn(model, tok, device, **extra)
            if log_samples > 0:
                res["log_samples"] = _extract_log_samples(res, log_samples)
            results["evals"][name] = res
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-800:]
            results["evals"][name] = {"test": name, "error": str(e), "traceback": tb, "pass": False, "version": versions.get(name)}
    results["meta"]["wall_s"] = time.time()-start
    results["meta"]["passed"] = sum(1 for r in results["evals"].values() if r.get("pass"))
    results["meta"]["total"] = len(results["evals"])
    return results

def write_reports(results: Dict[str,Any], out_dir: str = "reports"):
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "branch_eval_results_real.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    # markdown
    md_path = os.path.join(out_dir, "REPORT_REAL.md")
    lines = []
    lines.append("# Ava Open Harness — Real Eval Report")
    lines.append("")
    lines.append(f"Mode: {results['meta'].get('mode')} | Backend: {results['meta'].get('backend')} | CKPT: {results['meta'].get('ckpt')} | Passed {results['meta'].get('passed')}/{results['meta'].get('total')} | {results['meta'].get('wall_s',0):.3f}s | Versions: {results['meta'].get('task_version')}")
    lines.append("")
    lines.append(f"YAML tasks loaded: {results['meta'].get('yaml_tasks_loaded')} | Factory available: {results['meta'].get('factory_available')} ({results['meta'].get('factory_root')})")
    lines.append("")
    lines.append("| Test | Version | Bar | Measured | PASS/FAIL | Scale | Samples |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, r in results["evals"].items():
        bar = r.get("bar","")
        version = r.get("version", results["meta"].get("versions", {}).get(name, ""))
        measured = r.get("measured",{})
        if isinstance(measured, dict):
            summary = str({k: (v if not isinstance(v,float) else round(v,3)) for k,v in list(measured.items())[:4]})[:120]
        else:
            summary = str(measured)[:120]
        verdict = "PASS" if r.get("pass") else "FAIL"
        if "error" in r:
            verdict = f"ERROR {r['error'][:40]}"
            summary = r["error"][:80]
        scale = r.get("scale", "-")
        if r.get("capability_claim") == "none":
            scale = f"{scale} (capability_claim=none)"
        samples_n = len(r.get("log_samples", [])) if isinstance(r.get("log_samples"), list) else 0
        lines.append(f"| {name} | {version} | {bar} | {summary} | {verdict} | {scale} | {samples_n} |")
    lines.append("")
    lines.append("## Versioned Tasks")
    lines.append("Tasks are versioned YAML in `harness/tasks/*.yaml` with `name`, `version`, `description`, `bar`, `group`. Log samples stored per eval when --log-samples >0 (only real per-sample data from the eval itself; [] otherwise).")
    lines.append("")
    lines.append("## Backend")
    lines.append("- `auto`: mock inference when mode=mock, torch CPU/GPU inference when mode=real")
    lines.append("- `mock`: force deterministic MockTokenizer/MockModel (no torch needed)")
    lines.append("")
    lines.append("## Scale honesty")
    lines.append("Real measurements from the cpu_pilot smoke checkpoint carry `scale: smoke` and `capability_claim: none` — they prove the pipeline is real end-to-end and imply NO model capability.")
    lines.append("")
    lines.append("## Frozen-capability comparison (base vs chat)")
    lines.append("When both base and chat ckpts supplied, Δ% column shows regression if chat >5% worse (system1+system2 frozen).")
    with open(md_path,"w") as f:
        f.write("\n".join(lines))
    print(f"[runner] wrote {json_path} and {md_path}")
    return json_path, md_path

def main():
    ap = argparse.ArgumentParser(description="Ava Open Harness — mock and real eval runner with YAML versioned tasks")
    ap.add_argument("--eval", default="all", help="comma list of eval or group names, or all")
    ap.add_argument("--mode", default="mock", choices=["mock","real"], help="mock = no torch, real = load ckpt (fails loudly if it can't)")
    ap.add_argument("--backend", default="auto", choices=["auto","mock"], help="auto follows --mode; mock forces mock inference")
    ap.add_argument("--ckpt", default=None, help="checkpoint path for real mode, e.g. $AVA_FACTORY_ROOT/runs/cpu_pilot/base/base_final.pt")
    ap.add_argument("--tokenizer", default=None, help="tokenizer JSON path for real mode (default: factory runs/cpu_pilot/tokenizer/ava_nano_bpe.json)")
    ap.add_argument("--preset", default="nano")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--probe-n", type=int, default=200)
    ap.add_argument("--skip", default="", help="comma list to skip")
    ap.add_argument("--out-dir", default="reports")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--wiki-path", default=None)
    ap.add_argument("--log-samples", type=int, default=0, help="pass through up to N real per-sample records per eval (Eleuther compat)")
    ap.add_argument("--task-version", default="1.0", help="global task version fallback, per-task YAML overrides")
    args = ap.parse_args()

    skip = set([s.strip() for s in args.skip.split(",") if s.strip()])
    try:
        eval_names = [n for n in resolve_eval_names(args.eval) if n not in skip]
        res = run_harness(eval_names=eval_names, mode=args.mode, backend=args.backend,
                          ckpt=args.ckpt, tokenizer=args.tokenizer, preset=args.preset,
                          device=args.device, verbose=args.verbose, probe_n=args.probe_n,
                          wiki_path=args.wiki_path, log_samples=args.log_samples,
                          task_version=args.task_version)
    except ValueError as e:
        print(f"[runner] error: {e}", file=sys.stderr)
        return 2
    write_reports(res, out_dir=args.out_dir)
    # exit 0 even if bars fail, per spec
    print(json.dumps(res["meta"], indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
