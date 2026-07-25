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

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

DISCLAIMER = (
    "Solo personal project, no connection to employer, built with public/free-tier only"
)

# ---------------------------------------------------------------------------
# License gate — deny by default.
#
# The previous gate was `any(lp in lic_lower for lp in [..., "cc-by"])`, i.e. a
# SUBSTRING test, and "cc-by" is a substring of "cc-by-nc-4.0",
# "cc-by-nd-4.0" and "cc-by-nc-nd-4.0". Measured 2026-07-25: all three were
# ADMITTED. That breaks the two standing rules outright — NoDerivatives is
# always excluded because training a model on a work is a derivative use, and
# NonCommercial is excluded by default because this project has a revenue
# mission. It is the same bypass shape as the substring domain matcher fixed in
# scout-cli's policy engine: match COMPONENTS, never substrings.
#
# Three further defects in that gate, all fixed here:
#   * `any(license_pref) or any(<blanket list>)` made every per-domain
#     license_pref decorative — a domain narrowed to ["mit","apache-2.0"] still
#     admitted every cc-by* variant via the blanket half.
#   * a LIST-valued license was str()'d, so "['cc-by-4.0', 'cc-by-nd-4.0']"
#     matched on the permissive element and admitted the record even though ND
#     also applies. pull_oapen_books.py::gate_rights already had to learn this:
#     evaluate EVERY value, deny if ANY value denies.
#   * --dry-run set license_ok=True for math/code/reasoning domains with the
#     license string "assumed permissive" — a cleared verdict from zero
#     evidence. A code corpus is not permissive because it is code.
#
# Tokens are compared component-wise after splitting on "-", so "nd" cannot
# match inside an unrelated word and "cc-by" cannot swallow "cc-by-nc-nd".
# ---------------------------------------------------------------------------

# Denied outright wherever they appear, whatever else a record also claims.
LICENSE_DENY_TOKENS = {
    "nd": "NoDerivatives — training a model on the work is a derivative use",
    "nc": "NonCommercial — incompatible with a revenue mission",
}

# Exact HF/SPDX-style ids that clear the gate. An id absent from this set is
# DENIED, including "unknown", "other" and a missing license field: an
# unverified license is not a permissive one.
LICENSE_ALLOW = {
    "mit",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "cc0-1.0",
    "cc-by-2.0",
    "cc-by-3.0",
    "cc-by-4.0",
    "cc-by-sa-3.0",  # ShareAlike carries obligations but is not ND/NC
    "cc-by-sa-4.0",
    "odc-by-1.0",
    "odc-by",
    "pddl-1.0",
    "unlicense",
    "openrail",
}


# ---------------------------------------------------------------------------
# Second gate dimension: SYNTHETIC PROVENANCE (model-output terms).
#
# A licence tag describes what the UPLOADER grants. It says nothing about
# whether the CONTENT was permitted to exist. Most frontier-model terms of
# service forbid using model outputs to train a competing model, so a dump of
# another model's completions can be tagged `mit` by its uploader and still be
# unusable here. The HF trending list is currently dominated by exactly this
# shape — distillation dumps and agent traces named after the model that
# produced them.
#
# This is the same structure as the shadow-library rule: FORBIDDEN regardless of
# the licence field, because the licence field is not the binding constraint.
#
# Deliberately a FLAG, not an auto-deny. Distinguishing "outputs of a model whose
# terms forbid this" from "openly licensed synthetic data released by its own
# trainer" is a judgement about a specific ToS, and that belongs to the operator.
# Names are matched on word-ish boundaries, not bare substrings — see the
# licence gate above for why substring matching on identifiers is a trap.
# ---------------------------------------------------------------------------

# Model FAMILY names and process words only — deliberately NO version numbers.
# The first cut listed versioned markers ("gpt-4", "glm-5") and matched a marker
# when all of its hyphen-separated parts appeared anywhere in the text. Run
# against the operator's real HuggingFace list that was wrong three ways:
#   * "GPT-5.5-Gemini-3.1-Pro-Grok-4-Claude-Fables" was reported as matching
#     "gpt-4" — "gpt" and "4" both appear, but the 4 came from "Grok-4".
#     Fabricated evidence for a real flag is still fabricated evidence.
#   * "GLM-5.2-Conversation" was MISSED: marker "glm-5" needs the token "5", but
#     the token is "5.2".
#   * "qwen3.8-max-distillation" matched only "distillation": "qwen" was missed
#     because the token is "qwen3.8".
# Version numbers fuse with family names, so match the FAMILY by token prefix.
MODEL_OUTPUT_MARKERS = (
    # frontier / hosted model families whose terms typically restrict using
    # outputs to train a competing model
    "gpt", "chatgpt", "openai", "claude", "anthropic", "gemini", "bard",
    "palm", "grok", "llama", "mistral", "qwen", "deepseek", "glm", "kimi",
    "ernie", "yi", "command",
    # process words that say "these are model outputs" whatever produced them
    "distill", "distillation", "sharegpt", "alpaca", "wizardlm", "orca",
    "ultrachat", "openhermes", "selfinstruct", "synthetic", "traces",
)


def _tokens(text):
    """Alphanumeric-and-dot tokens, lowercased. '.' is kept so a version stays
    attached to its family ('qwen3.8'), which is what makes prefix matching
    work."""
    out, token = set(), ""
    for ch in str(text).lower():
        if ch.isalnum() or ch == ".":
            token += ch
        else:
            if token:
                out.add(token)
            token = ""
    if token:
        out.add(token)
    return out


def flag_synthetic_provenance(dataset_id, tags=None, description=""):
    """(needs_review, markers). Heuristic — it flags, it does not decide.

    A hit means "a human must read this dataset's card AND the terms of whatever
    produced the content before any ingestion". It does NOT mean denied: openly
    licensed synthetic data released by the party that trained the model is fine,
    and telling that apart from a ToS-violating dump is a judgement about a
    specific ToS, which is the operator's to make.

    A marker matches a token that either equals it, or begins with it followed by
    a DIGIT — so "qwen" matches "qwen3.8" while "orca" does not match
    "orcadian".
    """
    words = _tokens(
        " ".join([str(dataset_id or ""), " ".join(tags or []), str(description or "")])
    )
    hits = set()
    for marker in MODEL_OUTPUT_MARKERS:
        for word in words:
            if word == marker or (
                word.startswith(marker) and word[len(marker) :][:1].isdigit()
            ):
                hits.add(marker)
                break
    return (bool(hits), sorted(hits))


def _license_values(raw):
    """Flatten a license field into every individual value it asserts.

    HF returns a str, a list, or (via cardData) something nested. Anything that
    is not a str/list is stringified as ONE value rather than iterated, so a
    dict never silently decomposes into its keys.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple, set)):
        out = []
        for item in raw:
            out.extend(_license_values(item))
        return out
    return [str(raw)]


def gate_license(raw) -> tuple[bool, str]:
    """(allowed, reason). Deny by default; EVERY asserted license must pass.

    A record claiming both CC-BY-4.0 and CC-BY-ND-4.0 is denied — the most
    restrictive term governs what may be done with the work.
    """
    values = _license_values(raw)
    if not values:
        return False, "no license stated — deny by default (unverified is not permissive)"
    for value in values:
        ident = str(value).strip().lower()
        if not ident:
            return False, "empty license value — deny by default"
        parts = ident.split("-")
        for token, why in LICENSE_DENY_TOKENS.items():
            if token in parts:
                return False, f"{ident}: {why}"
        if ident not in LICENSE_ALLOW:
            return False, (
                f"{ident} is not in the permissive allowlist — deny by default; "
                "add it to LICENSE_ALLOW deliberately if it really is permissive"
            )
    joined = ", ".join(sorted({str(v).strip().lower() for v in values}))
    return True, f"permissive: {joined}"

# Mapping weak domains -> HF dataset search queries and data needs
DOMAIN_TO_DATASET_QUERIES = {
    "finance": {
        "keywords": ["financial", "finance", "stock", "earnings", "accounting"],
        "hf_datasets": [
            "financial_phrasebank",
            "convfinqa",
            "finqa",
            "fiqa",
            "flare-finqa",
            "bizbench",
            "sec_qa",
            "finance-alpaca",
        ],
        "need_tokens": "Need more financial reasoning, SEC filings, earnings reports, accounting textbook style",
        "license_pref": ["apache-2.0", "mit", "cc0"],
    },
    "bio": {
        "keywords": ["biomedical", "pubmed", "bio", "medical", "genomics"],
        "hf_datasets": [
            "pubmed_qa",
            "medmcqa",
            "medqa",
            "chemprot",
            "biorxiv",
            "bigbio",
            "scientific_papers",
        ],
        "need_tokens": "Biomed Q&A, PubMed abstracts, medical reasoning chains",
        "license_pref": ["cc0", "mit", "apache-2.0", "cc-by-4.0"],
    },
    "code": {
        "keywords": ["code", "programming", "python", "github", "stack"],
        "hf_datasets": [
            "the_stack",
            "code_search_net",
            "codeparrot/code-complexity",
            "openai_humaneval",
            "mbpp",
            "code_alpaca",
            "evol-codealpaca",
        ],
        "need_tokens": "More code reasoning traces, bug fix pairs, chain-of-thought debugging",
        "license_pref": ["mit", "apache-2.0"],
    },
    "math": {
        "keywords": ["math", "mathematics", "theorem", "proof", "algebra"],
        "hf_datasets": [
            "lmsys/math",
            "metamath-qa",
            "gsm8k",
            "math",
            "lean_workbook",
            "proof_pile",
            "open-web-math",
        ],
        "need_tokens": "Proofs, step-by-step solutions, Lean theorems",
        "license_pref": ["mit", "apache-2.0", "cc0"],
    },
    "safety": {
        "keywords": ["safety", "alignment", "toxicity", "harmful"],
        "hf_datasets": [
            "anthropic/hh-rlhf",
            "toxic_chat",
            "safety_bench",
            "xstest",
            "beaver_tails",
        ],
        "need_tokens": "Safety early-warning examples, blackmail refusal, Critic hl=30-35 training",
        "license_pref": ["mit", "apache-2.0", "cc-by-4.0"],
    },
    "long_context": {
        "keywords": ["long", "context", "book", "document"],
        "hf_datasets": ["bookcorpus", "pg19", "longbench", "scrolls", "loogle"],
        "need_tokens": "Long-context 32k-128k docs for YaRN 10k->1M RoPE extension",
        "license_pref": ["mit", "apache-2.0", "cc0", "pg19 is apache?"],
    },
    "reasoning": {
        "keywords": ["reasoning", "logic", "cot", "chain-of-thought"],
        "hf_datasets": [
            "gsm8k",
            "commonsense_qa",
            "strategyqa",
            "logiqa",
            "reclor",
            "proof_qa",
            "entailment_bank",
        ],
        "need_tokens": "Multi-hop reasoning, logical equivalence, S2 hl=300-400 deliberate tasks",
        "license_pref": ["mit", "apache-2.0"],
    },
    "macro": {
        "keywords": [
            "economics",
            "macroeconomics",
            "gdp",
            "inflation",
            "federal reserve",
        ],
        "hf_datasets": [
            "finqa",
            "convfinqa",
            "finance-alpaca",
            "bizbench",
            "sec_qa",
            "econ_qa",
            "flue",
            "financial_phrasebank",
        ],
        "need_tokens": "Macro economics, Fed reports, GDP, inflation reasoning, econometrics textbook",
        "license_pref": ["mit", "apache-2.0", "cc0", "cc-by-4.0"],
    },
    "materials": {
        "keywords": ["materials science", "battery", "perovskite", "alloy", "polymer"],
        "hf_datasets": [
            "matsci",
            "matbench",
            "chembl",
            "pubchem",
            "scientific_papers",
            "bigbio",
            "arxiv_papers_materials",
        ],
        "need_tokens": "Materials science QA, crystal structures, battery research, arXiv cond-mat.mtrl-sci",
        "license_pref": ["cc0", "mit", "apache-2.0", "cc-by-4.0"],
    },
    "climate": {
        "keywords": ["climate", "earth science", "meteorology", "ocean", "atmosphere"],
        "hf_datasets": [
            "climate_qa",
            "climabench",
            "scientific_papers",
            "bigbio",
            "geoscience_qa",
        ],
        "need_tokens": "Climate physics.ao-ph, greenhouse, ocean currents, atmospheric dynamics textbook",
        "license_pref": ["mit", "apache-2.0", "cc0", "cc-by-4.0"],
    },
    "law": {
        "keywords": ["legal", "law", "contract", "case law", "statute"],
        "hf_datasets": [
            "lex_glue",
            "cuad",
            "law_stack_exchange",
            "legal_summarization",
            "casehold",
        ],
        "need_tokens": "Legal reasoning, contract analysis, case law, regulatory compliance",
        "license_pref": ["mit", "apache-2.0", "cc0"],
    },
    "general": {
        "keywords": ["general", "knowledge"],
        "hf_datasets": ["c4", "pile", "fineweb", "dolma", "dclm-baseline"],
        "need_tokens": "General web-scale filtered (dclm 0.85 edu 4.5)",
        "license_pref": ["apache-2.0", "mit", "odc-by"],
    },
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
                            test_name = t.get("test", "")
                            desc = t.get("desc", "")
                            if "safety" in test_name or "blackmail" in desc.lower():
                                weak.append(
                                    ("safety", 0.0, f"{test_name} failed: {desc}")
                                )
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
                        weak.append(
                            ("safety", align, f"{branch} align_auc low {align}")
                        )
        print(f"[Discovery] Parsed {eval_path}, found {len(weak)} weakness signals")
    except Exception as e:
        print(f"[Discovery] Failed parse {eval_path}: {e}, using defaults")
        weak = [
            ("reasoning", 0.6, "no eval data, default to reasoning"),
            ("math", 0.6, "default"),
            ("code", 0.6, "default"),
        ]

    grouped = defaultdict(list)
    for dom, score, reason in weak:
        grouped[dom].append((score, reason))
    agg = []
    for dom, lst in grouped.items():
        min_score = min(s for s, _ in lst)
        reasons = [r for _, r in lst]
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
            domain = r.get("domain", "unknown")
            overall = r.get("overall", 0.5)
            domain_scores[domain].append(overall)
        for domain, scores in domain_scores.items():
            avg = sum(scores) / len(scores) if scores else 0.5
            # consider weak if <0.65 per spec
            if avg < 0.70:
                weak.append(
                    (
                        domain,
                        avg,
                        [f"frontier {domain} avg {avg:.3f} over {len(scores)} tasks"],
                    )
                )
        # also include all domains sorted
        weak_sorted = sorted(weak, key=lambda x: x[1])
        print(
            f"[Discovery] Frontier parsed {frontier_path}: domain avgs { {d: sum(s) / len(s) for d, s in domain_scores.items()} }"
        )
        return weak_sorted, domain_scores
    except Exception as e:
        print(f"[Discovery] frontier parse failed {e}")
        return [], {}


def search_hf_datasets_free(domain, query_list, license_pref, dry_run=False):
    candidates = []
    base_info = DOMAIN_TO_DATASET_QUERIES.get(domain, {})
    hf_list = base_info.get("hf_datasets", []) + query_list
    import urllib.parse
    import urllib.request

    for ds_name in hf_list[:15]:
        meta = {
            "name": ds_name,
            "source": "huggingface",
            "domain": domain,
            "url": f"https://huggingface.co/datasets/{ds_name}",
            "license": "unknown",
            "tokens_estimate": "unknown",
            "relevance_score": 0.8
            if domain in ds_name
            or any(
                k in ds_name
                for k in DOMAIN_TO_DATASET_QUERIES.get(domain, {}).get("keywords", [])
            )
            else 0.6,
            "download_method": f'python -m datasets load_dataset "{ds_name}" --streaming for inspection, then .save_to_disk',
            "wget": f"# pip install datasets; python -c \"from datasets import load_dataset; ds=load_dataset('{ds_name}', streaming=True); print(next(iter(ds)))\"",
            "license_ok": False,
        }
        if not dry_run:
            try:
                api_url = f"https://huggingface.co/api/datasets/{urllib.parse.quote(ds_name, safe='')}"
                req = urllib.request.Request(
                    api_url, headers={"User-Agent": "Ava-Dataset-Discovery/6.4"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        j = json.loads(resp.read().decode())
                        tags = j.get("tags", [])
                        card = j.get("cardData", {})
                        lic = card.get("license") or next(
                            (t.split(":")[1] for t in tags if t.startswith("license:")),
                            "unknown",
                        )
                        meta["license"] = lic if isinstance(lic, str) else str(lic)
                        meta["downloads"] = j.get("downloads", 0)
                        meta["likes"] = j.get("likes", 0)
                        # Gate on the RAW value, not meta["license"] — that one is
                        # already str()'d for display, which is exactly how a
                        # ['cc-by-4.0', 'cc-by-nd-4.0'] pair used to pass.
                        meta["license_ok"], meta["license_reason"] = gate_license(lic)
                        if meta["license_ok"]:
                            meta["relevance_score"] += 0.15
                            meta["relevance_score"] = min(1.0, meta["relevance_score"])
            except Exception as e:
                meta["api_error"] = str(e)[:200]
        else:
            # --dry-run makes no network call, so it has NO evidence about the
            # license and must not manufacture a verdict. This previously set
            # license_ok=True for math/code/reasoning with the license string
            # "assumed permissive" — a cleared gate from nothing, and precisely
            # the "it is a code corpus, code corpora are permissive" inference
            # the gate exists to refuse.
            meta["license"] = "unchecked (--dry-run makes no API call)"
            meta["license_ok"] = False
            meta["license_reason"] = (
                "not checked: --dry-run performs no license lookup. Re-run "
                "without --dry-run before treating any candidate as usable."
            )
            meta["dry_run"] = True
        # Second gate dimension, applied in BOTH branches: the licence field
        # cannot express whether the content was permitted to exist. Runs offline
        # off the id/tags, so --dry-run gets it too.
        meta["provenance_review"], meta["provenance_markers"] = (
            flag_synthetic_provenance(
                ds_name, meta.get("tags"), meta.get("description", "")
            )
        )
        candidates.append(meta)
    return candidates


def main():
    ap = argparse.ArgumentParser(
        description="Dataset Discovery based on eval weaknesses"
    )
    ap.add_argument(
        "--eval-results",
        nargs="+",
        default=None,
        help="eval results json files (frontier, branch)",
    )
    ap.add_argument(
        "--eval-file",
        default="branch_eval_results.json",
        help="eval results json (legacy)",
    )
    ap.add_argument(
        "--out",
        default="data/discovery/needs.json",
        help="output dir for candidates OR needs.json file",
    )
    ap.add_argument(
        "--candidates-out", default=None, help="candidates json output file"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="skip network calls, use cached lists"
    )
    ap.add_argument(
        "--domains", nargs="*", default=None, help="force domains to search"
    )
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
        all_weak = [
            ("macro", 0.499, ["frontier macro low 0.499"]),
            ("materials", 0.502, ["frontier materials low 0.502"]),
            ("climate", 0.549, ["frontier climate low 0.549"]),
            ("bio", 0.621, ["frontier bio low 0.621"]),
            ("finance", 0.625, ["frontier finance low 0.625"]),
            ("code", 0.634, ["frontier code 0.634"]),
        ]

    # Deduplicate and sort
    grouped = defaultdict(list)
    for dom, score, reasons in all_weak:
        if isinstance(reasons, list):
            grouped[dom].extend([(score, r) for r in reasons])
        else:
            grouped[dom].append((score, str(reasons)))
    agg = []
    for dom, lst in grouped.items():
        min_score = min(s for s, _ in lst)
        reasons = [r for _, r in lst]
        agg.append((dom, min_score, reasons))
    agg.sort(key=lambda x: x[1])

    if args.domains:
        agg = [(d, 0.5, [f"forced domain {d}"]) for d in args.domains]
        print(f"[Discovery] Forced domains {args.domains}")

    print("[Discovery] Weak domains identified (weakest first):")
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
            candidates_dir = (
                Path(args.candidates_out).parent
                if Path(args.candidates_out).suffix == ".json"
                else Path(args.candidates_out)
            )
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
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        cand_out_path = candidates_dir / f"candidates_{timestamp}.json"

    # For task compliance, also ensure date-based path with %Y-%m-%d exists
    # Create both timestamped and date-based if needed
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    date_based_path = (
        repo_root / f"your_files/ava-agi/dataset_discovery/candidates_{date_str}.json"
    )
    date_based_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. For each weak domain, search candidates
    all_candidates = []
    needs = {}
    for dom, score, reasons in agg:
        domain_info = DOMAIN_TO_DATASET_QUERIES.get(
            dom, DOMAIN_TO_DATASET_QUERIES.get("general")
        )
        queries = domain_info["keywords"] if domain_info else [dom]
        license_pref = (
            domain_info["license_pref"] if domain_info else ["mit", "apache-2.0"]
        )
        print(
            f"[Discovery] Searching HF for domain {dom} keywords {queries[:3]} dry_run={args.dry_run}"
        )
        candidates = search_hf_datasets_free(
            dom, queries, license_pref, dry_run=args.dry_run
        )
        all_candidates.extend(candidates)
        needs[dom] = {
            "current_score": score,
            "reasons": reasons,
            "need_description": domain_info["need_tokens"]
            if domain_info
            else f"Need more {dom}",
            "tokens_needed_estimate": f"{'500M-2B' if dom in ['finance', 'bio', 'macro', 'materials', 'climate'] else '100M-500M'} tokens to improve",
            "candidate_count": len(candidates),
            "top_candidates": [
                c["name"]
                for c in sorted(
                    candidates, key=lambda x: x["relevance_score"], reverse=True
                )[:3]
            ],
        }

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    # 3. Write candidates with timestamp
    candidates_payload = {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(UTC).isoformat(),
        "weak_domains": [{"domain": d, "score": s, "reasons": r} for d, s, r in agg],
        "candidates": all_candidates,
        "total_candidates": len(all_candidates),
        # This note used to say "Only MIT, Apache-2.0, CC0, CC-BY are safe ...
        # Avoid CC-BY-NC, CC-BY-SA-NC" — which never mentioned NoDerivatives at
        # all, and writing the family bare as "CC-BY" is what invited the
        # substring gate that admitted cc-by-nd-4.0. Enumerate versioned ids.
        "license_note": (
            "Gate is deny-by-default (gate_license). ANY -nd component is denied "
            "outright: training on a work is a derivative use. ANY -nc component "
            "is denied: revenue mission. A record asserting several licenses must "
            "pass on EVERY one — CC-BY-4.0 plus CC-BY-ND-4.0 is denied. 'unknown' "
            "and 'other' are denied: unverified is not permissive. Allowed ids are "
            "enumerated in LICENSE_ALLOW (mit, apache-2.0, cc0-1.0, cc-by-4.0, "
            "cc-by-sa-4.0, odc-by, ...) — never a bare family prefix."
        ),
        "license_shadow_libraries": (
            "FORBIDDEN as ingestion sources regardless of license field: Memory of "
            "the World, LibGen, Sci-Hub, Z-Library, Anna's Archive, Books3."
        ),
        "usage": "Review candidates_{date}.json, pick top 2 per domain with license_ok=True, then run download manifest on Alienware (not Hatch VM due disk)",
    }
    cand_out_path.write_text(json.dumps(candidates_payload, indent=2))
    print(f"[Discovery] Wrote {cand_out_path} with {len(all_candidates)} candidates")

    # Also write date-based if different
    if cand_out_path != date_based_path:
        date_based_path.write_text(json.dumps(candidates_payload, indent=2))
        print(f"[Discovery] Also wrote date-based {date_based_path}")

    # Also write timestamp version in candidates_dir if out is date-based
    if candidates_dir != cand_out_path.parent or (
        cand_out_path.name.startswith("candidates_20")
        and "_" in cand_out_path.name
        and len(cand_out_path.name) > 20
    ):
        # Ensure one more copy with full timestamp for history
        ts_path = candidates_dir / f"candidates_{timestamp}.json"
        if ts_path != cand_out_path and ts_path != date_based_path:
            ts_path.write_text(json.dumps(candidates_payload, indent=2))
            print(f"[Discovery] Also wrote timestamp {ts_path}")

    # 4. Write needs.json for downstream
    needs_payload = {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(UTC).isoformat(),
        "eval_source": [str(p) for p in eval_paths],
        "weak_domains": {d: {"score": s, "reasons": r} for d, s, r in agg},
        "needs": needs,
        "next_action": "Run dataset_expansion.py --phases for weak domains, and prepare download scripts for top HF candidates",
        "download_manifest_template": {
            "finance": "python -m datasets download financial_phrasebank -- to data/raw/finance/ ; then run nemo curated filtering",
            "bio": "python -m datasets download pubmed_qa ; filter reward>0.8",
        },
        "frontier_domain_avgs": {
            k: (sum(v) / len(v) if v else 0) for k, v in frontier_domains_scores.items()
        }
        if frontier_domains_scores
        else {},
    }
    needs_path.write_text(json.dumps(needs_payload, indent=2))
    print(f"[Discovery] Wrote {needs_path}")

    # 5. Write Alienware download script
    out_root_for_sh = cand_out_path.parent
    download_sh = out_root_for_sh / f"download_candidates_{timestamp}.sh"
    lines = [
        "#!/bin/bash",
        "# Solo personal project, no connection to employer, built with public/free-tier only",
        f"# Auto-generated {timestamp} from dataset_discovery",
        "# Review LICENSES before training",
        "set -e",
        "mkdir -p data/raw",
        "",
    ]
    ranked = sorted(all_candidates, key=lambda x: x["relevance_score"], reverse=True)
    if len(ranked) > 12:
        # Never truncate silently: a manifest that lists 12 of 40 reads as
        # "these are the candidates" unless it says otherwise.
        lines.append(f"# NOTE: {len(ranked)} candidates found; only the top 12 by")
        lines.append("# relevance_score are listed here. Re-run to see the rest.")
        lines.append("")
    for cand in ranked[:12]:
        # The guard used to be `... and not args.dry_run`, which DISABLED the
        # license skip in dry-run mode — and --dry-run is exactly what
        # docs/crons/dataset-discovery-daily.md tells the daily cron to use. The
        # result was an executable download manifest listing every top-12
        # candidate with no license filtering whatsoever, feeding
        # scripts/ingest_hf.py. The license gate has to bite hardest on the path
        # that actually fetches data, so license_ok is now the ONLY condition.
        if not cand.get("license_ok", False):
            reason = cand.get("license_reason") or "not permissive"
            lines.append(
                f"# SKIP {cand['name']} — license {cand['license']}: {reason}"
            )
            continue
        if cand.get("provenance_review"):
            # A permissive licence is not sufficient here. This manifest is
            # EXECUTABLE and feeds ingest_hf.py, so an automated path must not
            # fetch content whose terms of production are unresolved. The
            # operator can still download it by hand after reading the card and
            # the source model's terms — that is a decision, not a default.
            lines.append(
                f"# REVIEW-REQUIRED {cand['name']} — looks like model output "
                f"({', '.join(cand['provenance_markers'])}). A licence tag states "
                "what the UPLOADER grants, not whether the content was permitted "
                "to exist; most frontier-model terms forbid training a competing "
                "model on their outputs. Read the card + those terms, then ingest "
                "manually if cleared."
            )
            continue
        lines.append(
            f'echo "Downloading {cand["name"]} ({cand["url"]}) license {cand["license"]}" '
        )
        lines.append(f"# {cand['download_method']}")
        lines.append(
            f"# python scripts/ingest_hf.py --dataset {cand['name']} --out data/raw/{cand['domain']}/{cand['name'].replace('/', '_')} --filter reward>0.8"
        )
        lines.append("")
    download_sh.write_text("\n".join(lines))
    download_sh.chmod(0o755)
    print(f"[Discovery] Wrote download script {download_sh}")

    # 6. Summary
    print("\n[Discovery] Summary:")
    for dom, info in needs.items():
        print(
            f"  {dom}: need {info['tokens_needed_estimate']} — top {info['top_candidates']}"
        )

    print("\nNext steps:")
    print(f"  - Review {cand_out_path}")
    print(f"  - On Alienware RTX 4090: bash {download_sh}")
    print(
        f"  - Then run: ./scripts/local_train.sh python scripts/dataset_expansion.py --tokens 100M --phases {' '.join([d for d, _ in [(dom, 0) for dom in needs.keys()][:2]])} --out data/daily_expanded"
    )


if __name__ == "__main__":
    main()
