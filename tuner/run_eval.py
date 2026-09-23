"""CLI driver: run a prompt-optimization eval against a real or stub backend.

Harness self-test (no model needed — verifies the machinery only):
    python3 -m tuner.run_eval --eval approval_gate --backend stub

Real model via CLI (e.g. ollama):
    python3 -m tuner.run_eval --eval approval_gate --backend cmd \\
        --cmd "ollama run qwen3:0.6b" --cv 5

Real model via OpenAI-compatible HTTP (e.g. `ollama serve`):
    python3 -m tuner.run_eval --eval approval_gate --backend http \\
        --base-url http://localhost:11434/v1 --model qwen3:0.6b --cv 5

Writes: tuner/.runs/<run-id>/results.json + timeline.jsonl (gitignored).
"""

import argparse
import json
import os
import shlex
import sys

from tuner.backends import CommandGenerator, HTTPGenerator, StubGenerator
from tuner.evals import approval_gate
from tuner.prompt_tuner import PromptTuner, utcnow

EVALS = {"approval_gate": approval_gate}

RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runs")


def _stub_for_eval(X, y, templates):
    """Deterministic stand-in so `--backend stub` exercises the tuner end to end.

    TEST ONLY. The stub answers correctly only when the prompt carries the
    full safety-policy wording, so the search has a real winner to find.
    It knows the labels by construction — never a model evaluation.
    """
    truth = dict(zip(X, y))

    def reply(prompt):
        # recover the job text: it is the tail of the prompt after the template head
        text = next((t for t in X if t in prompt), None)
        label = truth.get(text, "unknown")
        if "Safety policy:" in prompt:
            return label
        return "approval" if label == "auto" else "auto"

    return StubGenerator(reply)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dottie prompt tuner")
    ap.add_argument("--eval", default="approval_gate", choices=sorted(EVALS))
    ap.add_argument("--backend", default="stub", choices=("stub", "cmd", "http"))
    ap.add_argument("--cmd", default="", help="CLI model command, e.g. 'ollama run qwen3:0.6b'")
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--model", default="qwen3:0.6b")
    ap.add_argument("--cv", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    mod = EVALS[args.eval]
    X, y, templates, labels = mod.load()

    if args.backend == "stub":
        generate_fn = _stub_for_eval(X, y, templates)
        note = "STUB SELF-TEST — exercises the tuner only, not a model evaluation"
    elif args.backend == "cmd":
        if not args.cmd:
            ap.error("--cmd is required with --backend cmd")
        generate_fn = CommandGenerator(shlex.split(args.cmd))
        note = "real model via CLI: %s" % args.cmd
    else:
        generate_fn = HTTPGenerator(args.base_url, args.model)
        note = "real model via HTTP: %s (%s)" % (args.base_url, args.model)

    run_id = "run-" + utcnow().replace(":", "").replace("+", "z")
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)

    tuner = PromptTuner(
        generate_fn,
        {"prompt_template": templates},
        cv=args.cv,
        seed=args.seed,
        labels=labels,
        timeline_path=os.path.join(run_dir, "timeline.jsonl"),
        run_id=run_id,
    )
    tuner.fit(X, y)

    results = {
        "eval": args.eval,
        "backend": args.backend,
        "note": note,
        "n_examples": len(X),
        "cv": args.cv,
        "seed": args.seed,
        "best_params": tuner.best_params_,
        "best_score": tuner.best_score_,
        "cv_results": tuner.cv_results_,
        "run_id": run_id,
    }
    with open(os.path.join(run_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("Optimization Complete! (%s)\n" % note)
    print("Best Prompt Template: '%s'" % tuner.best_params_["prompt_template"])
    print("Best Cross-Validated Accuracy: %.1f%%" % (tuner.best_score_ * 100))
    print("\nAll candidates:")
    for r in tuner.cv_results_:
        folds = ", ".join("%.0f%%" % (s * 100) for s in r["fold_scores"])
        print("  %.1f%%  [%s]  %.60s..." % (r["mean_accuracy"] * 100, folds, r["prompt_template"]))
    print("\nResults + timeline: %s" % run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
