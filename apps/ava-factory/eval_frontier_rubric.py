"""Solo personal project, no connection to employer, built with public/free-tier only
Frontier Rubric Eval — inspired by Samaya FrontierFinance Criteria Eval
Implements Task/Rubric schemas + mock/local/ollama judges (local models only;
the paid Meta Muse and GLM-5.2 API judges were removed 2026-09-27, no paid APIs)
"""

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DISCLAIMER = (
    "Solo personal project, no connection to employer, built with public/free-tier only"
)

CATEGORIES = [
    "Financial Accuracy",
    "Process Transparency & Auditability",
    "Risk & Ethical Disclosure",
    "Coverage Comprehensiveness",
    "Attribution Correctness",
    "Numerical Accuracy",
    "Logical Coherence",
    "Citation Grounding",
    "Instruction Following",
    "Edge Case Handling",
    "Client-Ready Polish",
]


@dataclass
class Rubric:
    id: str
    category: str
    criterion: str
    weight: float
    eval_instructions: str
    ground_truth_ref: str
    citation_span: str = ""
    required: bool = False


@dataclass
class FrontierTask:
    id: str
    domain: str
    subdomain: str
    question: str
    context_docs: list[dict[str, Any]]
    expected_workflow: list[str]
    rubrics: list[Rubric]
    human_baseline_hours: float
    ground_truth: str


def _judge_prompt(rubric: "Rubric", output: str, ground_truth: str) -> str:
    """Judge prompt for the LLM judge (local Ollama)."""
    return (
        f"Rubric Category: {rubric.category}\n"
        f"Criterion: {rubric.criterion}\n"
        f"Ground truth ref: {rubric.ground_truth_ref}\n"
        f"Required: {rubric.required}\n"
        f"Model Output: {output[:1000]}\n"
        f"Ground Truth: {ground_truth[:500]}\n"
        f'Task: Score 0-1 if output satisfies criterion. Return JSON {{"score":0.0-1.0, "reason":"..."}}'
    )


def _parse_score(content: str) -> float | None:
    """Extract a 0-1 score float from a judge response, or None."""
    if not content:
        return None
    m = re.search(r"\"score\"\s*:\s*([0-9]*\.?[0-9]+)", content)
    if not m:
        m2 = re.findall(r"\b(0\.\d+|1\.0|0|1)\b", content)
        if not m2:
            return None
        try:
            return round(max(0.0, min(1.0, float(m2[0]))), 3)
        except Exception:
            return None
    try:
        return round(max(0.0, min(1.0, float(m.group(1)))), 3)
    except Exception:
        return None


class CriteriaJudge:
    """Base mock judge — keyword overlap + length heuristic, free-tier no API.
    `label` reports which judge ACTUALLY produced scores ("mock" here); API
    judges keep label="mock" until a real endpoint call is possible."""

    label = "mock"

    def score(self, rubric: Rubric, output: str, ground_truth: str) -> float:
        output_l = output.lower()
        # Heuristic: check ground_truth_ref keywords present
        refs = re.findall(r"[A-Za-z0-9]{3,}", rubric.ground_truth_ref.lower())
        crit_kw = re.findall(r"[A-Za-z0-9]{3,}", rubric.criterion.lower())[:8]
        keywords = list(set(refs[:6] + crit_kw[:4]))
        if not keywords:
            return 0.5
        hits = sum(1 for k in keywords if k in output_l)
        cov = hits / len(keywords) if keywords else 0
        # numerical check: if rubric about accuracy, require number in output
        needs_num = any(
            w in rubric.category.lower() for w in ["accuracy", "numerical", "financial"]
        )
        num_bonus = 0.15 if (needs_num and re.search(r"\d", output)) else 0
        # citation bonus
        has_cite = (
            0.1
            if (
                "arxiv" in output_l
                or "p." in output_l
                or "sec" in output_l
                or "10-q" in output_l
            )
            else 0
        )
        length_pen = -0.2 if len(output.split()) < 15 else 0
        s = max(0.0, min(1.0, cov * 0.7 + num_bonus + has_cite + length_pen + 0.2))
        # required rubric strict
        if rubric.required and cov < 0.3:
            s *= 0.5
        return round(s, 3)


class LocalHFJudge(CriteriaJudge):
    """Stub for local HF transformers pipeline — falls back to mock if not installed"""

    def __init__(self):
        self.available = False
        try:
            import transformers  # noqa

            self.available = True
        except Exception:
            self.available = False

    def score(self, rubric: Rubric, output: str, ground_truth: str) -> float:
        # No real local HF judge is implemented yet — return the PLAIN mock
        # score labeled "mock". (The old +0.05 "calibration" bonus was an
        # invented value and has been deleted.)
        return super().score(rubric, output, ground_truth)


def build_sample_tasks() -> list[FrontierTask]:
    """1 finance + 1 per new domain, arXiv abstract as ground truth mock"""

    def mk_rubrics(task_id, gt_refs):
        rubs = []
        for i, cat in enumerate(CATEGORIES[:6]):  # use 6 per sample to keep 42 total
            rubs.append(
                Rubric(
                    id=f"R-{task_id}-{i + 1:02d}",
                    category=cat,
                    criterion=f"[{cat}] Must mention key evidence: {gt_refs[i % len(gt_refs)]}",
                    weight=round(1 / 6, 4),
                    eval_instructions=f"Judge: check output contains evidence for {cat} within 10%, citation required, else 0.5 max",
                    ground_truth_ref=gt_refs[i % len(gt_refs)],
                    citation_span=f"doc0 lines {i * 10}-{(i + 1) * 10}",
                    required=(i < 2),
                )
            )
        return rubs

    tasks = []

    # Finance
    tasks.append(
        FrontierTask(
            id="FF-2026-SD-001",
            domain="finance",
            subdomain="Screening & Discovery",
            question="Screen US small-cap biotech cash runway >2y, Ph2 catalyst <90d, insider buying 30d. Produce table with runway calc (cash+ST)/burn_last_Q citing 10-Q page.",
            context_docs=[
                {
                    "type": "sec_filing",
                    "ticker": "MRK",
                    "form": "10-Q",
                    "page": "12",
                    "snippet": "cash $142M ST $18M burn $22M/q runway 7.27q",
                },
                {
                    "type": "arxiv",
                    "id": "2406.12345",
                    "category": "q-bio.BM",
                    "abstract": "AlphaFold3-guided KRAS G12C covalent inhibitor design shows 2.1Å binding pocket...",
                    "citation_span": "Sec3.2",
                },
            ],
            expected_workflow=[
                "planner: identify criteria",
                "executor: query SEC+market",
                "memory: track tickers",
                "reasoning: valuation+risk",
                "attribution: cite spans",
            ],
            rubrics=mk_rubrics(
                "FF-2026-SD-001",
                [
                    "cash $160M",
                    "burn $22M/q",
                    "7.27q runway",
                    "Ph2 catalyst 60d",
                    "insider buying Form4",
                    "arXiv:2406.12345",
                ],
            ),
            human_baseline_hours=18.2,
            ground_truth="MRK runway 7.27q, catalyst 60d per arXiv:2406.12345 Sec3.2, insider buying Form4 Jan15",
        )
    )

    # Bio
    tasks.append(
        FrontierTask(
            id="BIO-001",
            domain="bio",
            subdomain="Drug Discovery",
            question="Propose 3 KRAS G12C scaffolds from AlphaFold3 paper arXiv:2406.12345 binding pocket residues, off-target + Phase1 checklist.",
            context_docs=[
                {
                    "type": "arxiv",
                    "id": "2406.12345",
                    "category": "q-bio.BM",
                    "abstract": "AlphaFold3-guided KRAS G12C 2.1Å pocket Cys12 covalent warhead, off-target EGFR...",
                    "citation_span": "Sec2",
                }
            ],
            expected_workflow=[
                "planner",
                "executor: arXiv+UniProt",
                "memory",
                "reasoning",
                "attribution",
            ],
            rubrics=mk_rubrics(
                "BIO-001",
                [
                    "Cys12 covalent",
                    "2.1Å pocket",
                    "EGFR off-target",
                    "AlphaFold3",
                    "Phase1 dose escalation",
                ],
            ),
            human_baseline_hours=16.0,
            ground_truth="Scaffold binds Cys12 2.1Å, off-target EGFR, Phase1 checklist per arXiv:2406.12345",
        )
    )

    # Climate
    tasks.append(
        FrontierTask(
            id="CLI-001",
            domain="climate",
            subdomain="Tipping Points",
            question="Under SSP2-4.5 probability AMOC collapse before 2100 cross arXiv:2407.01234 + IPCC AR6 Ch4, produce table with CI.",
            context_docs=[
                {
                    "type": "arxiv",
                    "id": "2407.01234",
                    "category": "physics.ao-ph",
                    "abstract": "AMOC collapse 12% by 2100 SSP2-4.5, 95% CI 5-23%, IPCC AR6 Ch4...",
                    "citation_span": "Fig2",
                }
            ],
            expected_workflow=[
                "planner",
                "executor",
                "memory",
                "reasoning",
                "attribution",
            ],
            rubrics=mk_rubrics(
                "CLI-001",
                ["12% collapse", "CI 5-23%", "SSP2-4.5", "IPCC AR6 Ch4", "Fig2"],
            ),
            human_baseline_hours=14.5,
            ground_truth="12% prob CI 5-23% SSP2-4.5 per arXiv:2407.01234 Fig2 + IPCC AR6 Ch4",
        )
    )

    # Materials
    tasks.append(
        FrontierTask(
            id="MAT-001",
            domain="materials",
            subdomain="Solid-State Electrolyte",
            question="Find >5 mS/cm + >4.5V stable electrolyte from arXiv:2408.00123 perovskite + Materials Project query.",
            context_docs=[
                {
                    "type": "arxiv",
                    "id": "2408.00123",
                    "category": "cond-mat.mtrl-sci",
                    "abstract": "High-entropy perovskite Li0.33La0.56TiO3 6.2 mS/cm 4.7V stability...",
                    "citation_span": "Table1",
                }
            ],
            expected_workflow=[
                "planner",
                "executor",
                "memory",
                "reasoning",
                "attribution",
            ],
            rubrics=mk_rubrics(
                "MAT-001",
                [
                    "6.2 mS/cm",
                    "4.7V stability",
                    "perovskite",
                    "Li0.33La0.56TiO3",
                    "Table1 arXiv:2408.00123",
                ],
            ),
            human_baseline_hours=15.0,
            ground_truth="Li0.33La0.56TiO3 6.2 mS/cm 4.7V per arXiv:2408.00123 Table1",
        )
    )

    # Code research
    tasks.append(
        FrontierTask(
            id="CODE-001",
            domain="code",
            subdomain="Repo-Level QA",
            question="RepoAgent memory leak detection across 3 files per arXiv:2405.03456 — provide fix + test.",
            context_docs=[
                {
                    "type": "arxiv",
                    "id": "2405.03456",
                    "category": "cs.SE",
                    "abstract": "RepoAgent long-horizon codebase QA leak pattern: unclosed file handles in loop...",
                    "citation_span": "Sec4.1",
                }
            ],
            expected_workflow=[
                "planner",
                "executor: arXiv+repo",
                "memory",
                "reasoning",
                "attribution",
            ],
            rubrics=mk_rubrics(
                "CODE-001",
                ["unclosed handles", "loop leak", "RepoAgent", "Sec4.1", "test fix"],
            ),
            human_baseline_hours=12.0,
            ground_truth="Leak unclosed handles in loop per arXiv:2405.03456 Sec4.1, fix with context manager",
        )
    )

    # Law
    tasks.append(
        FrontierTask(
            id="LAW-001",
            domain="law",
            subdomain="Contract Review",
            question="Flag indemnity + change-of-control clause risk in mock SaaS agreement, cite arXiv:2404.02222 ambiguity detection criteria.",
            context_docs=[
                {
                    "type": "arxiv",
                    "id": "2404.02222",
                    "category": "cs.CL",
                    "abstract": "Contract ambiguity detection: indemnity unlimited liability risk, change-of-control 30d notice...",
                    "citation_span": "Sec3",
                }
            ],
            expected_workflow=[
                "planner",
                "executor",
                "memory",
                "reasoning",
                "attribution",
            ],
            rubrics=mk_rubrics(
                "LAW-001",
                [
                    "indemnity unlimited",
                    "change-of-control 30d",
                    "arXiv:2404.02222 Sec3",
                    "risk flag",
                ],
            ),
            human_baseline_hours=13.0,
            ground_truth="Flag indemnity unlimited + CoC 30d notice per arXiv:2404.02222 Sec3",
        )
    )

    # Macro
    tasks.append(
        FrontierTask(
            id="MAC-001",
            domain="macro",
            subdomain="Tariff Impact",
            question="What is impact of 15% tariff on US GDP using arXiv:2404.05678 causal world model + FRED import data?",
            context_docs=[
                {
                    "type": "arxiv",
                    "id": "2404.05678",
                    "category": "econ.GN",
                    "abstract": "15% tariff pass-through -0.35% GDP 95% CI -0.6 to -0.1, FRED import elasticity 0.82...",
                    "citation_span": "Table3",
                }
            ],
            expected_workflow=[
                "planner",
                "executor: arXiv+FRED",
                "memory",
                "reasoning",
                "attribution",
            ],
            rubrics=mk_rubrics(
                "MAC-001",
                [
                    "-0.35% GDP",
                    "CI -0.6 to -0.1",
                    "15% tariff",
                    "elasticity 0.82",
                    "Table3",
                ],
            ),
            human_baseline_hours=14.0,
            ground_truth="GDP -0.35% CI -0.6 to -0.1 per arXiv:2404.05678 Table3, elasticity 0.82",
        )
    )

    return tasks


def evaluate_task(
    task: FrontierTask, model_output: str, judge: CriteriaJudge
) -> dict[str, Any]:
    per = []
    weighted = 0.0
    for r in task.rubrics:
        s = judge.score(r, model_output, task.ground_truth)
        per.append(
            {"rubric_id": r.id, "category": r.category, "score": s, "weight": r.weight}
        )
        weighted += s * r.weight
    overall = max(0.0, min(1.0, weighted))
    return {
        "task_id": task.id,
        "domain": task.domain,
        "overall": round(overall, 3),
        "per_rubric": per,
        "output_len": len(model_output),
    }


class OllamaJudge(CriteriaJudge):
    """
    Solo personal project, no connection to employer, built with public/free-tier only
    Ollama local judge — 100% offline, zero cost. The only LLM judge: the paid
    API judges (Meta Muse Spark, Z.ai GLM-5.2) were removed 2026-09-27.
    - Reads OLLAMA_HOST default http://localhost:11434, OLLAMA_MODEL default qwen3:8b
      (the one model pulled on the home box; 12 GB VRAM / 16 GB RAM).
    - Other local options via OLLAMA_MODEL, if pulled (all open weights):
      * qwen3:32b / qwen2.5-coder:32b — stronger rubric judge, needs ~24GB VRAM at Q4
      * llama3.3:70b — generalist, ~40GB Q4
      * deepseek-r1:32b or deepseek-r1:14b — reasoning judge (chain-of-thought)
      * glm4:9b-chat / llama3.1:8b — small alternatives
    - Why local: open weights, local inference, no API fees, fully offline.
    - Implements graceful fallback: if Ollama not reachable, logs and returns mock.
    """

    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
        self.available = False
        self.label = "mock"
        self.tags = []
        # Try urllib first (stdlib), then requests if present
        try:
            import urllib.error
            import urllib.request

            req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # data format {"models":[{"name":"qwen3:8b"...}]}
                models = data.get("models", [])
                self.tags = [m.get("name", "") for m in models]
                self.available = True
                if self.model not in self.tags and self.tags:
                    # pick first available if preferred not found
                    print(
                        f"[OllamaJudge] Preferred {self.model} not found locally, available: {self.tags[:5]}, using {self.model} anyway (will pull on first use)"
                    )
                print(
                    f"[{DISCLAIMER}] OllamaJudge: reachable at {self.host}, model={self.model}, local models={len(self.tags)}"
                )
        except Exception as e_urllib:
            # try requests fallback
            try:
                import requests

                r = requests.get(f"{self.host}/api/tags", timeout=3)
                if r.ok:
                    data = r.json()
                    models = data.get("models", [])
                    self.tags = [m.get("name", "") for m in models]
                    self.available = True
                    print(
                        f"[{DISCLAIMER}] OllamaJudge (requests): reachable at {self.host}, model={self.model}, local={len(self.tags)}"
                    )
                else:
                    print(
                        f"[{DISCLAIMER}] OllamaJudge: tags endpoint {self.host}/api/tags status {r.status_code}, fallback to mock"
                    )
            except Exception as e_req:
                print(
                    f"[{DISCLAIMER}] OllamaJudge: not reachable at {self.host} ({e_urllib} / {e_req}), fallback to mock (free-tier). Run 'ollama serve && ollama pull {self.model}' to enable free SOTA local judge."
                )

    def _call_ollama(self, prompt: str) -> str | None:
        """POST /api/chat non-streaming, returns content string or None"""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a strict rubric judge. Output ONLY a JSON with score 0-1. Be precise.",
                },
                {
                    "role": "user",
                    "content": prompt[:3000],
                },  # truncate to keep local fast
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 128},
        }
        # Try urllib
        try:
            import urllib.request

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.host}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                # body {"message":{"content":"..."}}
                content = (
                    body.get("message", {}).get("content") or body.get("response") or ""
                )
                return content
        except Exception:
            try:
                import requests

                r = requests.post(f"{self.host}/api/chat", json=payload, timeout=10)
                if r.ok:
                    j = r.json()
                    return (
                        j.get("message", {}).get("content") or j.get("response") or ""
                    )
            except Exception:
                pass
        return None

    def score(self, rubric: Rubric, output: str, ground_truth: str) -> float:
        if not self.available:
            # Ollama unreachable: PLAIN mock score, labeled "mock" — the old
            # +0.06 fallback bonus was an invented value and has been deleted.
            self.label = "mock"
            return super().score(rubric, output, ground_truth)
        content = self._call_ollama(_judge_prompt(rubric, output, ground_truth))
        v = _parse_score(content)
        if v is not None:
            self.label = "ollama"
            return v
        if content:
            print(
                f"[OllamaJudge] Parsed content but no score, plain mock fallback. Raw: {content[:120]}"
            )
        else:
            print(f"[OllamaJudge] Call failed for {rubric.id}, plain mock fallback")
        self.label = "mock"
        return super().score(rubric, output, ground_truth)


def get_judge(name: str) -> CriteriaJudge:
    n = name.lower().strip()
    if n == "local":
        return LocalHFJudge()
    if n in (
        "ollama",
        "ollama-local",
        "local-ollama",
        "qwen3",
        "deepseek-r1",
        "llama3.3",
    ):
        return OllamaJudge()
    return CriteriaJudge()


def mock_model_output(task: FrontierTask) -> str:
    # Generates output containing some gt keywords to get partial score — for demo free-tier
    refs = " ".join([r.ground_truth_ref for r in task.rubrics[:3]])
    return f"Analysis for {task.id} domain {task.domain}: {task.question} | Evidence: {refs} | cites arXiv {task.context_docs[0].get('id', 'unknown')} {task.context_docs[0].get('citation_span', '')} p.12 with calculation 7.27q / -0.35% GDP / 6.2 mS/cm. Risk disclosed, attribution correct, table included. Client-ready memo with process transparency."


def main():
    ap = argparse.ArgumentParser(description=f"{DISCLAIMER} — Frontier rubric eval")
    ap.add_argument(
        "--domain",
        default="all",
        help="finance,bio,climate,materials,code,law,macro,all or comma list",
    )
    ap.add_argument(
        "--judge",
        default="mock",
        choices=[
            "mock",
            "local",
            "ollama",
            "ollama-local",
        ],
        help="judge type: mock (free, keyword overlap), local (HF), ollama (free local judge, OLLAMA_MODEL default qwen3:8b). Local models only: no paid API judges.",
    )
    ap.add_argument("--mode", default="mock", choices=["mock", "real"], help="mode")
    args = ap.parse_args()

    tasks = build_sample_tasks()
    wanted = args.domain.lower().split(",") if args.domain else ["all"]
    if "all" not in wanted:
        tasks = [t for t in tasks if t.domain in wanted]

    judge = get_judge(args.judge)
    print(
        f"[{DISCLAIMER}] Judge requested={args.judge} available={getattr(judge, 'available', True)} url={getattr(judge, 'url', 'n/a')} | Tasks={len(tasks)}"
    )

    results = []
    for t in tasks:
        out = mock_model_output(t)
        ev = evaluate_task(t, out, judge)
        ev["judge"] = getattr(judge, "label", "mock")  # what ACTUALLY scored this task
        results.append(ev)
        print(
            f"  {t.id} {t.domain:8s} overall={ev['overall']} judge={ev['judge']} rubrics={len(ev['per_rubric'])}"
        )

    # save JSON — "judge" is the label of what actually produced the scores
    # ("mock" whenever keys/endpoints were absent), not merely what was requested.
    effective = getattr(judge, "label", "mock")
    out_json = Path("frontier_eval_results.json")
    with open(out_json, "w") as f:
        json.dump(
            {
                "disclaimer": DISCLAIMER,
                "model_output_source": "mock_model_output() demo text — NOT a real model generation",
                "judge": effective,
                "judge_requested": args.judge,
                "mode": args.mode,
                "results": results,
            },
            f,
            indent=2,
        )

    # save MD report
    md = Path("FRONTIER_EVAL_REPORT.md")
    with open(md, "w") as f:
        f.write(f"{DISCLAIMER}\n\n# Frontier Eval Report — Ava v6.4\n\n")
        f.write(
            f"Judge (effective): {effective} (requested {args.judge}) Mode: {args.mode} | Total tasks: {len(results)}\n\n"
        )
        f.write(
            "Metrics: weighted clipped 0-1 per Samaya FrontierFinance Criteria Eval (11 cats), mock uses keyword overlap\n\n"
        )
        f.write("| Task | Domain | Overall | Cats |\n|---|---|---|---|\n")
        for r in results:
            f.write(
                f"| {r['task_id']} | {r['domain']} | {r['overall']} | {len(r['per_rubric'])} |\n"
            )
        f.write("\n## Per-task details\n")
        for r in results:
            f.write(f"\n### {r['task_id']} ({r['domain']}) overall {r['overall']}\n")
            for pr in r["per_rubric"]:
                f.write(
                    f"- {pr['rubric_id']} {pr['category']}: {pr['score']} w={pr['weight']}\n"
                )
        f.write(
            "\n## Integration\n- Phase 3-5 anneal reward>0.8 verifier = CriteriaJudge\n- shards: data/streaming_shards/frontier_rubric/\n- Local models only: no paid API judges (Meta Muse / GLM-5.2 removed 2026-09-27).\n- OllamaJudge: reads OLLAMA_HOST default http://localhost:11434, OLLAMA_MODEL default qwen3:8b (larger local alternatives if pulled: qwen3:32b, qwen2.5-coder:32b, deepseek-r1:32b, llama3.3:70b). 100% offline via Ollama, open weights. Detects /api/tags, calls /api/chat non-streaming, extracts JSON score, falls back to the PLAIN mock score labeled judge=mock if unreachable (no additive bonus). Zero cost, local only.\n"
        )

    print(f"Saved {out_json} + {md}")


if __name__ == "__main__":
    main()
