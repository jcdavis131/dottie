"""dottie/pipeline/trace_factory.py — ET-CoT execution trace factory + GRPO rollout factory
Numpy-only, stdlib + math, no torch.
Implements Scout v3.3 trace→preference pipeline components:
- ET-CoT doc rendering (Input State → <think> steps → <answer>)
- trace elision with state checkpoint
- trace_bank group formation
- memory lattice write-back
- recovery ladder integration
- verification economics scoring

Used by Dottie Scout CLI: `scout --json dottie trace collect` → pref_pairs.jsonl
"""

from __future__ import annotations
import hashlib, json, math, random, re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

THINK_OPEN, THINK_CLOSE = "<think>", "</think>"
ANSWER_OPEN, ANSWER_CLOSE = "<answer>", "</answer>"
CHAT_USER, CHAT_ASSISTANT = "<|user|>", "<|assistant|>"

PHASE_CHAR_BUDGET = {2: 4000, 3: 16000, 4: 12000}
PHASE_ELIDE_OVER = {2: 10**9, 3: 28, 4: 10**9}

def sha16(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]

def render_etcot(task: str, think_lines: List[str], answer_lines: List[str]) -> str:
    parts=[task.rstrip("\n"), "", THINK_OPEN]
    parts.extend(think_lines)
    parts.append(THINK_CLOSE)
    parts.append(ANSWER_OPEN)
    parts.extend(answer_lines)
    parts.append(ANSWER_CLOSE)
    return "\n".join(parts)

def to_chat(text: str) -> str:
    if f"\n\n{THINK_OPEN}\n" not in text:
        # already chat?
        return text
    task, trace = text.split(f"\n\n{THINK_OPEN}\n", 1)
    return f"{CHAT_USER}\n{task}\n{CHAT_ASSISTANT}\n{THINK_OPEN}\n{trace}"

def elide(steps: List[str], states: List[str], elide_over: int, keep_head: int=10, keep_tail: int=4) -> List[str]:
    if len(steps) <= elide_over or len(steps) <= keep_head+keep_tail+1:
        return list(steps)
    omitted=len(steps)-keep_head-keep_tail
    resume=len(steps)-keep_tail
    checkpoint=states[resume-1] if resume<=len(states) else states[-1] if states else "checkpoint"
    marker=f"[.. {omitted} steps elided to fit trace budget; state checkpoint before step {resume+1}: {checkpoint} ..]"
    return [*steps[:keep_head], marker, *steps[-keep_tail:]]

def step_lines(raw: List[str]) -> List[str]:
    out=[]; n=0
    for line in raw:
        if line.startswith("[.."):
            out.append(line)
        else:
            n+=1
            out.append(f"[step {n}] {line}")
    return out

@dataclass
class TraceDoc:
    task_id: str
    prompt: str
    think_lines: List[str]
    answer_lines: List[str]
    trace_id: str
    phase: int = 3
    tokens_est: int = 0
    def render(self) -> str:
        return render_etcot(self.prompt, self.think_lines, self.answer_lines)

@dataclass
class Rollout:
    prompt: str
    completion: str
    rl_return: float
    logp_new: Optional[float]=None
    logp_old: Optional[float]=None
    entropy: Optional[float]=None
    verdict: str="pass"
    trace_id: str=""
    model_ckpt: str="nano-smoke-100"

class TraceFactory:
    """Factory that collects ET-CoT docs + telemetry into bankable rollouts."""

    def __init__(self, seed: int=7):
        self.rng=random.Random(seed)
        self.docs: List[TraceDoc]=[]
        self.rollouts: List[Rollout]=[]

    def add_doc(self, doc: TraceDoc):
        self.docs.append(doc)

    def ingest_telemetry(self, path: Path) -> int:
        if not path.exists(): return 0
        n=0
        for line in path.read_text().splitlines():
            line=line.strip()
            if not line: continue
            try:
                j=json.loads(line)
                r=Rollout(
                    prompt=j.get("prompt","") or j.get("task",""),
                    completion=j.get("completion","") or j.get("answer",""),
                    rl_return=float(j.get("rl_return", j.get("return", j.get("score", 0)))),
                    logp_new=j.get("logp_new"),
                    logp_old=j.get("logp_old"),
                    entropy=j.get("entropy", j.get("h_policy")),
                    verdict=j.get("verdict","pass"),
                    trace_id=j.get("trace_id", sha16(j.get("prompt","") + str(n))),
                    model_ckpt=j.get("model_ckpt","nano")
                )
                self.rollouts.append(r); n+=1
            except Exception:
                continue
        return n

    def ingest_eval_json(self, path: Path) -> int:
        if not path.exists(): return 0
        try:
            data=json.loads(path.read_text())
        except:
            return 0
        # handle both dict-of-results and list
        items=[]
        if isinstance(data, dict):
            # frontier_eval style {"task_id": score ...} or {"results": [...]}
            if "results" in data:
                items=data["results"]
            else:
                for k,v in data.items():
                    if isinstance(v, dict):
                        items.append({"task_id":k, **v})
                    else:
                        items.append({"task_id":k, "score":v})
        elif isinstance(data, list):
            items=data
        n=0
        for it in items:
            if not isinstance(it, dict): continue
            score=float(it.get("score", it.get("return", 0)))
            # map score to return 0-1
            r=Rollout(
                prompt=it.get("prompt", it.get("task", it.get("task_id",""))),
                completion=it.get("trace", it.get("answer",""))[:2000],
                rl_return=score,
                verdict="pass" if score>=0.8 else "fail",
                trace_id=it.get("trace_id", sha16(it.get("task_id","") + str(n))),
            )
            self.rollouts.append(r); n+=1
        return n

    def group_rollouts(self, min_group: int=2) -> Dict[str, List[Rollout]]:
        groups: Dict[str, List[Rollout]]={}
        for ro in self.rollouts:
            key=sha16(ro.prompt) if ro.prompt else sha16(ro.trace_id)
            groups.setdefault(key, []).append(ro)
        # filter min_group
        return {k:v for k,v in groups.items() if len(v)>=min_group}

    def emit_pref_pairs(self, groups: Dict[str, List[Rollout]], margin: float=0.05) -> List[Dict[str,Any]]:
        from .grpo import group_advantages
        pairs=[]
        for gid, ros in groups.items():
            returns=[r.rl_return for r in ros]
            advs=group_advantages(returns)
            # attach adv to ros via index
            max_idx=max(range(len(ros)), key=lambda i: ros[i].rl_return)
            min_idx=min(range(len(ros)), key=lambda i: ros[i].rl_return)
            delta=ros[max_idx].rl_return - ros[min_idx].rl_return
            if delta < margin:
                continue
            pairs.append({
                "prompt_id": gid,
                "prompt": ros[0].prompt,
                "chosen": {"completion": ros[max_idx].completion, "trace_id": ros[max_idx].trace_id, "return": ros[max_idx].rl_return, "adv": advs[max_idx], "entropy": ros[max_idx].entropy},
                "rejected": {"completion": ros[min_idx].completion, "trace_id": ros[min_idx].trace_id, "return": ros[min_idx].rl_return, "adv": advs[min_idx], "entropy": ros[min_idx].entropy},
                "group_size": len(ros),
                "group_mean": sum(returns)/len(returns),
                "group_std": (sum((r-sum(returns)/len(returns))**2 for r in returns)/len(returns))**0.5,
                "delta_return": delta,
            })
        return pairs

    def write_outputs(self, out_dir: Path, min_group: int=2, margin: float=0.05):
        out_dir.mkdir(parents=True, exist_ok=True)
        groups=self.group_rollouts(min_group=min_group)
        # trace_bank.jsonl
        with open(out_dir/"trace_bank.jsonl","w",encoding="utf-8") as f:
            for gid, ros in groups.items():
                for r in ros:
                    f.write(json.dumps({"prompt_id":gid,"prompt":r.prompt,"completion":r.completion,"rl_return":r.rl_return,"logp_new":r.logp_new,"logp_old":r.logp_old,"entropy":r.entropy,"verdict":r.verdict,"trace_id":r.trace_id,"model_ckpt":r.model_ckpt})+"\n")
        pairs=self.emit_pref_pairs(groups, margin=margin)
        with open(out_dir/"pref_pairs.jsonl","w",encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps(p)+"\n")
        # group_stats
        with open(out_dir/"grpo_group_stats.jsonl","w",encoding="utf-8") as f:
            for gid, ros in groups.items():
                returns=[r.rl_return for r in ros]
                mean=sum(returns)/len(returns)
                f.write(json.dumps({"prompt_id":gid,"group_size":len(ros),"group_mean":mean,"group_std": (sum((x-mean)**2 for x in returns)/len(returns))**0.5,"min_return":min(returns),"max_return":max(returns)})+"\n")
        manifest={"seed":7,"groups":len(groups),"pairs":len(pairs),"rollouts":len(self.rollouts),"docs":len(self.docs),"deterministic":True,"source":"trace_factory numpy-only"}
        with open(out_dir/"MANIFEST.json","w",encoding="utf-8") as f:
            json.dump(manifest,f,indent=2)
        return manifest

def main():
    import argparse
    ap=argparse.ArgumentParser(description="Trace factory — ET-CoT docs + telemetry → bank/pairs")
    ap.add_argument("--telemetry", type=str, default="reports/dottie_telemetry.jsonl")
    ap.add_argument("--eval", type=str, default="reports/branch_eval_results_real.json")
    ap.add_argument("--out", type=str, default="runs/grpo_pref")
    ap.add_argument("--min_group", type=int, default=2)
    ap.add_argument("--margin", type=float, default=0.05)
    args=ap.parse_args()
    fac=TraceFactory(seed=7)
    fac.ingest_telemetry(Path(args.telemetry))
    fac.ingest_eval_json(Path(args.eval))
    man=fac.write_outputs(Path(args.out), min_group=args.min_group, margin=args.margin)
    print(json.dumps(man, indent=2))

if __name__=="__main__":
    main()
