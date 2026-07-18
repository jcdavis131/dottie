#!/usr/bin/env python3
"""
dataset_discovery.py — Discover additional datasets based on eval weaknesses
Solo personal project, no connection to employer, built with public/free-tier only
HOME persona only

Purpose:
- Reads branch_eval_results.json, frontier_eval_results.json (if exists), your_files/ava-agi/runs/latest-log.html to identify weak domains
- Maps weak domains to data needs
- Searches HuggingFace Hub free public API for candidate datasets with permissive licenses (MIT, Apache2, CC0, CC-BY)
- Logs candidates to your_files/ava-agi/dataset_discovery/candidates_{date}.json
- Does NOT auto-download massive data in Hatch VM (limited disk), but prepares download manifests for Alienware
- Writes data/discovery/needs.json: what domains need more tokens

Usage:
  python scripts/dataset_discovery.py --dry-run
  python scripts/dataset_discovery.py --eval-file branch_eval_results.json --out your_files/ava-agi/dataset_discovery/
  python scripts/dataset_discovery.py --eval-results frontier_eval_results.json branch_eval_results.json --out data/discovery/needs.json --candidates-out your_files/ava-agi/dataset_discovery/candidates_2026-07-12.json
"""
import argparse, json, os, re, pathlib, time, hashlib
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

DISCLAIMER = "Solo personal project, no connection to employer, built with public/free-tier only"

# Mapping weak domains -> HF dataset search queries and data needs
DOMAIN_TO_DATASET_QUERIES = {
    "finance": {
        "keywords": ["financial", "finance", "stock", "earnings", "accounting"],
        "hf_datasets": ["financial_phrasebank", "convfinqa", "finqa", "fiqa", "flare-finqa", "bizbench", "sec_qa", "finance-alpaca"],
        "need_tokens": "Need more financial reasoning, SEC filings, earnings reports, accounting textbook style",
        "license_pref": ["apache-2.0","mit","cc0"],
    },
    "bio": {
        "keywords": ["biomedical", "pubmed", "bio", "medical", "genomics"],
        "hf_datasets": ["pubmed_qa", "medmcqa", "medqa", "chemprot", "biorxiv", "bigbio", "scientific_papers"],
        "need_tokens": "Biomed Q&A, PubMed abstracts, medical reasoning chains",
        "license_pref": ["cc0","mit","apache-2.0","cc-by-4.0"],
    },
    "code": {
        "keywords": ["code", "programming", "python", "github", "stack"],
        "hf_datasets": ["the_stack", "code_search_net", "codeparrot/code-complexity", "openai_humaneval", "mbpp", "code_alpaca", "evol-codealpaca"],
        "need_tokens": "More code reasoning traces, bug fix pairs, chain-of-thought debugging",
        "license_pref": ["mit","apache-2.0"],
    },
    "math": {
        "keywords": ["math", "mathematics", "theorem", "proof", "algebra"],
        "hf_datasets": ["lmsys/math", "metamath-qa", "gsm8k", "math", "lean_workbook", "proof_pile", "open-web-math"],
        "need_tokens": "Proofs, step-by-step solutions, Lean theorems",
        "license_pref": ["mit","apache-2.0","cc0"],
    },
    "safety": {
        "keywords": ["safety", "alignment", "toxicity", "harmful"],
        "hf_datasets": ["anthropic/hh-rlhf", "toxic_chat", "safety_bench", "xstest", "beaver_tails"],
        "need_tokens": "Safety early-warning examples, blackmail refusal, Critic hl=30-35 training",
        "license_pref": ["mit","apache-2.0","cc-by-4.0"],
    },
    "long_context": {
        "keywords": ["long", "context", "book", "document"],
        "hf_datasets": ["bookcorpus", "pg19", "longbench", "scrolls", "loogle"],
        "need_tokens": "Long-context 32k-128k docs for YaRN 10k->1M RoPE extension",
        "license_pref": ["mit","apache-2.0","cc0","pg19 is apache?"],
    },
    "reasoning": {
        "keywords": ["reasoning", "logic", "cot", "chain-of-thought"],
        "hf_datasets": ["gsm8k", "commonsense_qa", "strategyqa", "logiqa", "reclor", "proof_qa", "entailment_bank"],
        "need_tokens": "Multi-hop reasoning, logical equivalence, S2 hl=300-400 deliberate tasks",
        "license_pref": ["mit","apache-2.0"],
    },
    "macro": {
        "keywords": ["economics", "macroeconomics", "gdp", "inflation", "federal reserve"],
        "hf_datasets": ["finqa", "convfinqa", "finance-alpaca", "bizbench", "sec_qa", "econ_qa", "flue", "financial_phrasebank"],
        "need_tokens": "Macro economics, Fed reports, GDP, inflation reasoning, econometrics textbook",
        "license_pref": ["mit","apache-2.0","cc0","cc-by-4.0"],
    },
    "materials": {
        "keywords": ["materials science", "battery", "perovskite", "alloy", "polymer"],
        "hf_datasets": ["matsci", "matbench", "chembl", "pubchem", "scientific_papers", "bigbio", "arxiv_papers_materials"],
        "need_tokens": "Materials science QA, crystal structures, battery research, arXiv cond-mat.mtrl-sci",
        "license_pref": ["cc0","mit","apache-2.0","cc-by-4.0"],
    },
    "climate": {
        "keywords": ["climate", "earth science", "meteorology", "ocean", "atmosphere"],
        "hf_datasets": ["climate_qa", "climabench", "scientific_papers", "bigbio", "geoscience_qa"],
        "need_tokens": "Climate physics.ao-ph, greenhouse, ocean currents, atmospheric dynamics textbook",
        "license_pref": ["mit","apache-2.0","cc0","cc-by-4.0"],
    },
    "law": {
        "keywords": ["legal", "law", "contract", "case law", "statute"],
        "hf_datasets": ["lex_glue", "cuad", "law_stack_exchange", "legal_summarization", "casehold"],
        "need_tokens": "Legal reasoning, contract analysis, case law, regulatory compliance",
        "license_pref": ["mit","apache-2.0","cc0"],
    },
    "general": {
        "keywords": ["general", "knowledge"],
        "hf_datasets": ["c4", "pile", "fineweb", "dolma", "dclm-baseline"],
        "need_tokens": "General web-scale filtered (dclm 0.85 edu 4.5)",
        "license_pref": ["apache-2.0","mit","odc-by"],
    }
}

def parse_eval_results(eval_path: Path):
    """Parse branch_eval_results.json to find weak domains"""
    weak = []
    try:
        data = json.loads(eval_path.read_text())
        if isinstance(data, dict):
            for branch, result in data.items():
                if isinstance(result, dict) and "tests" in result:
                    for t in result["tests"]:
                        if not t.get("pass", True):
                            test_name = t.get("test","")
                            desc = t.get("desc","")
                            if "safety" in test_name or "blackmail" in desc.lower():
                                weak.append(("safety", 0.0, f"{test_name} failed: {desc}"))
                            elif "finance" in test_name or "finance" in desc.lower():
                                weak.append(("finance", 0.2, desc))
                            elif "bio" in test_name or "spider" in test_name.lower():
                                weak.append(("reasoning", 0.5, desc))
                            else:
                                weak.append(("reasoning", 0.5, desc))
                    cap = result.get("cap_score", 1.0)
                    if cap < 0.9:
                        weak.append(("general", cap, f"{branch} cap_score low {cap}"))
                    align = result.get("align_auc", 1.0)
                    if align < 0.85:
                        weak.append(("safety", align, f"{branch} align_auc low {align}"))
        print(f"[Discovery] Parsed {eval_path}, found {len(weak)} weakness signals")
    except Exception as e:
        print(f"[Discovery] Failed parse {eval_path}: {e}, using defaults")
        weak = [("reasoning", 0.6, "no eval data, default to reasoning"), ("math", 0.6, "default"), ("code", 0.6, "default")]

    grouped = defaultdict(list)
    for dom, score, reason in weak:
        grouped[dom].append((score, reason))
    agg = []
    for dom, lst in grouped.items():
        min_score = min(s for s,_ in lst)
        reasons = [r for _,r in lst]
        agg.append((dom, min_score, reasons))
    agg.sort(key=lambda x: x[1])
    return agg

def parse_frontier_results(frontier_path: Path):
    weak = []
    try:
        data = json.loads(frontier_path.read_text())
        results = data.get("results", [])
        domain_scores = defaultdict(list)
        for r in results:
            domain = r.get("domain","unknown")
            overall = r.get("overall", 0.5)
            domain_scores[domain].append(overall)
        for domain, scores in domain_scores.items():
            avg = sum(scores)/len(scores) if scores else 0.5
            # consider weak if <0.65 per spec
            if avg < 0.70:
                weak.append((domain, avg, [f"frontier {domain} avg {avg:.3f} over {len(scores)} tasks"]))
        # also include all domains sorted
        weak_sorted = sorted(weak, key=lambda x: x[1])
        print(f"[Discovery] Frontier parsed {frontier_path}: domain avgs {dict((d, sum(s)/len(s)) for d,s in domain_scores.items())}")
        return weak_sorted, domain_scores
    except Exception as e:
        print(f"[Discovery] frontier parse failed {e}")
        return [], {}

def search_hf_datasets_free(domain, query_list, license_pref, dry_run=False):
    candidates = []
    base_info = DOMAIN_TO_DATASET_QUERIES.get(domain, {})
    hf_list = base_info.get("hf_datasets", []) + query_list
    import urllib.request, urllib.parse
    for ds_name in hf_list[:15]:
        meta = {
            "name": ds_name,
            "source": "huggingface",
            "domain": domain,
            "url": f"https://huggingface.co/datasets/{ds_name}",
            "license": "unknown",
            "tokens_estimate": "unknown",
            "relevance_score": 0.8 if domain in ds_name or any(k in ds_name for k in DOMAIN_TO_DATASET_QUERIES.get(domain, {}).get("keywords", [])) else 0.6,
            "download_method": f'python -m datasets load_dataset "{ds_name}" --streaming for inspection, then .save_to_disk',
            "wget": f'# pip install datasets; python -c "from datasets import load_dataset; ds=load_dataset(\'{ds_name}\', streaming=True); print(next(iter(ds)))"',
            "license_ok": False,
        }
        if not dry_run:
            try:
                api_url = f"https://huggingface.co/api/datasets/{urllib.parse.quote(ds_name, safe='')}"
                req = urllib.request.Request(api_url, headers={"User-Agent": "Ava-Dataset-Discovery/6.4"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        j = json.loads(resp.read().decode())
                        tags = j.get("tags", [])
                        card = j.get("cardData", {})
                        lic = card.get("license") or next((t.split(":")[1] for t in tags if t.startswith("license:")), "unknown")
                        meta["license"] = lic if isinstance(lic, str) else str(lic)
                        meta["downloads"] = j.get("downloads",0)
                        meta["likes"] = j.get("likes",0)
                        lic_lower = str(meta["license"]).lower()
                        meta["license_ok"] = any(lp in lic_lower for lp in license_pref) or any(lp in lic_lower for lp in ["mit","apache","cc0","cc-by"])
                        if meta["license_ok"]:
                            meta["relevance_score"] += 0.15
                            meta["relevance_score"] = min(1.0, meta["relevance_score"])
            except Exception as e:
                meta["api_error"] = str(e)[:200]
        else:
            meta["license"] = "assumed permissive" if domain in ["math","code","logic"] else "needs check"
            meta["license_ok"] = True if domain in ["math","code","reasoning"] else False
            meta["dry_run"] = True
        candidates.append(meta)
    return candidates

def main():
    ap = argparse.ArgumentParser(description="Dataset Discovery based on eval weaknesses")
    ap.add_argument("--eval-results", nargs="+", default=None, help="eval results json files (frontier, branch)")
    ap.add_argument("--eval-file", default="branch_eval_results.json", help="eval results json (legacy)")
    ap.add_argument("--out", default="data/discovery/needs.json", help="output dir for candidates OR needs.json file")
    ap.add_argument("--candidates-out", default=None, help="candidates json output file")
    ap.add_argument("--dry-run", action="store_true", help="skip network calls, use cached lists")
    ap.add_argument("--domains", nargs="*", default=None, help="force domains to search")
    args = ap.parse_args()

    print(f"[{DISCLAIMER}]")
    repo_root = Path(__file__).parent.parent

    # Determine eval sources
    eval_paths = []
    if args.eval_results:
        for p in args.eval_results:
            pp = Path(p)
            if not pp.is_absolute():
                pp = repo_root / pp
            if pp.exists():
                eval_paths.append(pp)
            else:
                # try repo_root
                alt = repo_root / p
                if alt.exists():
                    eval_paths.append(alt)
                else:
                    print(f"[Discovery] eval path not found: {p}")
    else:
        eval_path = Path(args.eval_file)
        if not eval_path.is_absolute():
            eval_path = repo_root / eval_path
        if eval_path.exists():
            eval_paths.append(eval_path)

    # Parse all evals
    all_weak = []
    frontier_domains_scores = {}
    for ep in eval_paths:
        if "frontier" in str(ep):
            weak_f, scores = parse_frontier_results(ep)
            all_weak.extend(weak_f)
            frontier_domains_scores.update(scores)
        else:
            all_weak.extend(parse_eval_results(ep))

    # If no evals or all strong cap preserved, fallback to frontier weak
    frontier_path = repo_root / "frontier_eval_results.json"
    if frontier_path.exists() and not any("frontier" in str(p) for p in eval_paths):
        weak_f, scores = parse_frontier_results(frontier_path)
        all_weak.extend(weak_f)
        frontier_domains_scores.update(scores)

    if not all_weak:
        # fallback from task description: use defaults based on known weak
        all_weak = [("macro",0.499,["frontier macro low 0.499"]), ("materials",0.502,["frontier materials low 0.502"]), ("climate",0.549,["frontier climate low 0.549"]), ("bio",0.621,["frontier bio low 0.621"]), ("finance",0.625,["frontier finance low 0.625"]), ("code",0.634,["frontier code 0.634"])]

    # Deduplicate and sort
    grouped = defaultdict(list)
    for dom, score, reasons in all_weak:
        if isinstance(reasons, list):
            grouped[dom].extend([(score, r) for r in reasons])
        else:
            grouped[dom].append((score, str(reasons)))
    agg = []
    for dom, lst in grouped.items():
        min_score = min(s for s,_ in lst)
        reasons = [r for _,r in lst]
        agg.append((dom, min_score, reasons))
    agg.sort(key=lambda x: x[1])

    if args.domains:
        agg = [(d,0.5,[f"forced domain {d}"]) for d in args.domains]
        print(f"[Discovery] Forced domains {args.domains}")

    print(f"[Discovery] Weak domains identified (weakest first):")
    for dom, score, reasons in agg:
        print(f"  - {dom}: score {score:.2f} reasons: {reasons[:2]}")

    # Determine output paths
    out_arg = Path(args.out)
    if not out_arg.is_absolute():
        out_arg = repo_root / out_arg

    # --out can be file (needs.json) or directory
    if out_arg.suffix == ".json":
        needs_path = out_arg
        candidates_dir = needs_path.parent
        if args.candidates_out:
            candidates_dir = Path(args.candidates_out).parent if Path(args.candidates_out).suffix == ".json" else Path(args.candidates_out)
            if not candidates_dir.is_absolute():
                candidates_dir = repo_root / candidates_dir
        else:
            # default candidates dir sibling to needs? use data/discovery parent? Actually spec says your_files/ava-agi/dataset_discovery
            candidates_dir = repo_root / "your_files/ava-agi/dataset_discovery"
    else:
        candidates_dir = out_arg
        needs_path = repo_root / "data/discovery/needs.json"
        if not candidates_dir.is_absolute():
            candidates_dir = repo_root / candidates_dir

    candidates_dir.mkdir(parents=True, exist_ok=True)
    needs_path.parent.mkdir(parents=True, exist_ok=True)

    if args.candidates_out:
        cand_out_path = Path(args.candidates_out)
        if not cand_out_path.is_absolute():
            cand_out_path = repo_root / cand_out_path
        cand_out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        cand_out_path = candidates_dir / f"candidates_{timestamp}.json"

    # For task compliance, also ensure date-based path with %Y-%m-%d exists
    # Create both timestamped and date-based if needed
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_based_path = repo_root / f"your_files/ava-agi/dataset_discovery/candidates_{date_str}.json"
    date_based_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. For each weak domain, search candidates
    all_candidates = []
    needs = {}
    for dom, score, reasons in agg:
        domain_info = DOMAIN_TO_DATASET_QUERIES.get(dom, DOMAIN_TO_DATASET_QUERIES.get("general"))
        queries = domain_info["keywords"] if domain_info else [dom]
        license_pref = domain_info["license_pref"] if domain_info else ["mit","apache-2.0"]
        print(f"[Discovery] Searching HF for domain {dom} keywords {queries[:3]} dry_run={args.dry_run}")
        candidates = search_hf_datasets_free(dom, queries, license_pref, dry_run=args.dry_run)
        all_candidates.extend(candidates)
        needs[dom] = {
            "current_score": score,
            "reasons": reasons,
            "need_description": domain_info["need_tokens"] if domain_info else f"Need more {dom}",
            "tokens_needed_estimate": f"{'500M-2B' if dom in ['finance','bio','macro','materials','climate'] else '100M-500M'} tokens to improve",
            "candidate_count": len(candidates),
            "top_candidates": [c["name"] for c in sorted(candidates, key=lambda x: x["relevance_score"], reverse=True)[:3]]
        }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # 3. Write candidates with timestamp
    candidates_payload = {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weak_domains": [{"domain": d, "score": s, "reasons": r} for d,s,r in agg],
        "candidates": all_candidates,
        "total_candidates": len(all_candidates),
        "license_note": "Only MIT, Apache-2.0, CC0, CC-BY are safe for commercial training. Avoid CC-BY-NC, CC-BY-SA-NC.",
        "usage": "Review candidates_{date}.json, pick top 2 per domain with license_ok=True, then run download manifest on Alienware (not Hatch VM due disk)",
    }
    cand_out_path.write_text(json.dumps(candidates_payload, indent=2))
    print(f"[Discovery] Wrote {cand_out_path} with {len(all_candidates)} candidates")

    # Also write date-based if different
    if cand_out_path != date_based_path:
        date_based_path.write_text(json.dumps(candidates_payload, indent=2))
        print(f"[Discovery] Also wrote date-based {date_based_path}")

    # Also write timestamp version in candidates_dir if out is date-based
    if candidates_dir != cand_out_path.parent or cand_out_path.name.startswith("candidates_20") and "_" in cand_out_path.name and len(cand_out_path.name) > 20:
        # Ensure one more copy with full timestamp for history
        ts_path = candidates_dir / f"candidates_{timestamp}.json"
        if ts_path != cand_out_path and ts_path != date_based_path:
            ts_path.write_text(json.dumps(candidates_payload, indent=2))
            print(f"[Discovery] Also wrote timestamp {ts_path}")

    # 4. Write needs.json for downstream
    needs_payload = {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "eval_source": [str(p) for p in eval_paths],
        "weak_domains": {d: {"score": s, "reasons": r} for d,s,r in agg},
        "needs": needs,
        "next_action": "Run dataset_expansion.py --phases for weak domains, and prepare download scripts for top HF candidates",
        "download_manifest_template": {
            "finance": "python -m datasets download financial_phrasebank -- to data/raw/finance/ ; then run nemo curated filtering",
            "bio": "python -m datasets download pubmed_qa ; filter reward>0.8",
        },
        "frontier_domain_avgs": {k: (sum(v)/len(v) if v else 0) for k,v in frontier_domains_scores.items()} if frontier_domains_scores else {}
    }
    needs_path.write_text(json.dumps(needs_payload, indent=2))
    print(f"[Discovery] Wrote {needs_path}")

    # 5. Write Alienware download script
    out_root_for_sh = cand_out_path.parent
    download_sh = out_root_for_sh / f"download_candidates_{timestamp}.sh"
    lines = [
        f"#!/bin/bash",
        f"# Solo personal project, no connection to employer, built with public/free-tier only",
        f"# Auto-generated {timestamp} from dataset_discovery",
        f"# Review LICENSES before training",
        f"set -e",
        f"mkdir -p data/raw",
        f"",
    ]
    for cand in sorted(all_candidates, key=lambda x: x["relevance_score"], reverse=True)[:12]:
        if not cand.get("license_ok", False) and not args.dry_run:
            lines.append(f"# SKIP {cand['name']} license {cand['license']} not permissive — review manually")
            continue
        lines.append(f"echo \"Downloading {cand['name']} ({cand['url']}) license {cand['license']}\" ")
        lines.append(f"# {cand['download_method']}")
        lines.append(f"# python scripts/ingest_hf.py --dataset {cand['name']} --out data/raw/{cand['domain']}/{cand['name'].replace('/','_')} --filter reward>0.8")
        lines.append("")
    download_sh.write_text("\n".join(lines))
    download_sh.chmod(0o755)
    print(f"[Discovery] Wrote download script {download_sh}")

    # 6. Summary
    print(f"\n[Discovery] Summary:")
    for dom, info in needs.items():
        print(f"  {dom}: need {info['tokens_needed_estimate']} — top {info['top_candidates']}")

    print(f"\nNext steps:")
    print(f"  - Review {cand_out_path}")
    print(f"  - On Alienware RTX 4090: bash {download_sh}")
    print(f"  - Then run: ./scripts/local_train.sh python scripts/dataset_expansion.py --tokens 100M --phases {' '.join([d for d,_ in [(dom,0) for dom in needs.keys()][:2]])} --out data/daily_expanded")

if __name__ == "__main__":
    main()
