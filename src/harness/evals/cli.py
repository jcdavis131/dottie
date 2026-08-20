"""CLI YAML runner like `harness-evals run my-eval.eval.yaml` — zero-deps."""
import pathlib, json, yaml, asyncio
from .core.golden import Golden
from .metrics.deterministic import ExactMatchMetric
from .baseline import JsonBaselineStore

def load_dataset(path: str):
    p=pathlib.Path(path)
    golds=[]
    if p.suffix==".jsonl":
        for line in p.read_text().splitlines():
            if not line.strip(): continue
            j=json.loads(line)
            golds.append(Golden(input=j.get("input",""), expected=j.get("expected",""), id=j.get("id","")))
    else:
        arr=json.loads(p.read_text())
        for j in arr: golds.append(Golden(input=j.get("input",""), expected=j.get("expected","")))
    return golds

def run_config(yaml_path: str, fail_under=0.0, baseline=False):
    cfg=yaml.safe_load(pathlib.Path(yaml_path).read_text())
    dataset=cfg.get("dataset","goldens.jsonl")
    metrics_cfgs=cfg.get("metrics", ["exact_match"])
    golds=load_dataset(dataset)
    # very minimal metric resolver
    metrics=[]
    for m in metrics_cfgs:
        if isinstance(m,str) and m=="exact_match": metrics.append(ExactMatchMetric())
        elif isinstance(m,dict) and m.get("kind")=="exact_match": metrics.append(ExactMatchMetric())
    # fake agent = echo expected
    from .core.golden import EvalCase
    from .core.metric import evaluate_cases
    cases=[EvalCase(input=g.input, output=g.expected or "", expected=g.expected) for g in golds]
    all_scores=evaluate_cases(cases, metrics)
    mean=sum(s[0].value for s in all_scores)/len(all_scores) if all_scores else 0
    if fail_under and mean < fail_under:
        print(f"FAIL under {fail_under}: {mean:.2f}")
        return 1
    print(f"mean:{mean:.2f} cases:{len(cases)} metrics:{len(metrics)}")
    return 0
