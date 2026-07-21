#!/usr/bin/env python3
"""
lighten_public_graph.py — shrink public graph for jcamd.com/graphify/

Keeps ecosystem seeds + 1-hop signal (files/docs/hot symbols), drops
inferred_ref builtins, call-graph spam, and low-value markdown concepts.

Solo personal project, no connection to employer, built with public/free-tier only.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

SEED_TYPES = {
    "product",
    "tool",
    "ml_concept",
    "ml_feature",
    "business_metric",
    "ecosystem_domain",
    "integration",
    "product_feature",
}

# Match against label/id only (NOT file paths — "ava" appears in every Ava repo path).
SEED_LABEL_RES = [
    re.compile(p, re.I)
    for p in (
        r"\bscout\b",
        r"\bava\b",
        r"turnover\s*shield",
        r"\bturnover\b",
        r"vector\s+(hoops|pitch|gridiron|tennis)",
        r"\bstripe\b",
        r"\bmrr\b",
        r"\bgraphify\b",
        r"family\s*brain",
        r"davis\s+family",
        r"\bmtnn\b",
        r"\bjcamd\b",
        r"\bdumbmodel\b",
        r"retention\s*playbook",
        r"churn\s*prediction",
        r"\bplaid\b",
        r"\bollama\b",
        r"\bj[- ]?space\b",
        r"\bjspace\b",
        r"ava\s+(planner|critic|s1|s2)",
        r"\brtx\s*offload\b",
        r"passive\s*(lab|income)",
        r"\bdinov3?\b",
        r"workforce\s*embedding",
        r"first\s*\$?1k",
        r"personal\s*graphify",
    )
]

# Prefer keeping these relational edges even if ends are sparse
PRIORITY_EDGE_TYPES = {
    "orchestrates",
    "tracks",
    "enables",
    "feeds",
    "interacts_with",
    "triggers",
    "contains",
    "belongs_to",
    "uses",
    "implements",
    "explains",
    "has_rationale",
    "references",
}

BUILTIN_RE = re.compile(
    r"^(func:)?(len|str|int|float|bool|list|dict|set|tuple|print|range|open|path|"
    r"exists|getattr|setattr|isinstance|enumerate|zip|map|filter|sorted|sum|min|max|"
    r"any|all|type|id|repr|hex|bytes|object|super|property|staticmethod|classmethod|"
    r"abspath|joinpath|mkdir|resolve|relative_to|read_text|write_text|loads|dumps)$",
    re.I,
)

JUNK_PATH_RE = re.compile(
    r"(egg-info|node_modules|__pycache__|package-lock|OPEN_SOURCE_TOOLCHAIN)",
    re.I,
)


def _strip_paths(text: str) -> str:
    """Remove Windows/Unix path fragments so 'ava-agi-factory' in file ids cannot seed."""
    if not text:
        return ""
    text = text.replace("\\", "/")
    text = re.sub(r"(?i)[A-Z]:/[^:\s]+", " ", text)
    text = re.sub(
        r"(?i)/(?:users|home|ava-agi[^/\s]*|scout-cli|personal-graphify|vector-[^/\s]*)/[^:\s]*",
        " ",
        text,
    )
    # dottie monorepo layout: apps/* + packages/* fragments (relative ids have no leading /)
    text = re.sub(
        r"(?i)\b(?:apps/(?:scout-cli|scout-rtx|ava-factory)|"
        r"packages/(?:personal-graphify|ava-skills|ava-open-harness))/[^:\s]*",
        " ",
        text,
    )
    return text


def _label_blob(n: dict) -> str:
    """Human labels only — never raw file paths inside node ids."""
    parts = [str(n.get("label", "")), str(n.get("desc", ""))]
    nid = str(n.get("id", ""))
    # Allow stable concept/integration ids; strip path-bearing function/file/doc ids
    if nid.startswith(("concept:", "integration:", "ecosystem:", "tool:")):
        parts.append(_strip_paths(nid))
    return " ".join(parts)


def _path_blob(n: dict) -> str:
    return f"{n.get('file', '')}".lower().replace("\\", "/")


def is_seed(n: dict) -> bool:
    if n.get("type") in SEED_TYPES:
        return True
    # Keyword seeds are label/desc driven (plus clean concept ids) — not every Ava file
    typ = n.get("type", "")
    if typ in ("function", "class", "module", "symbol", "inferred_ref", "file"):
        # Files can seed only via label (basename already) matching strong patterns
        blob = str(n.get("label", ""))
        strong = (re.compile(r"multi_jspace|graphify|turnover|scout", re.I),)
        return any(rx.search(blob) for rx in strong)
    blob = _label_blob(n)
    return any(rx.search(blob) for rx in SEED_LABEL_RES)


def is_junk(n: dict) -> bool:
    nid = str(n.get("id", ""))
    label = str(n.get("label", ""))
    typ = n.get("type", "")
    if typ == "inferred_ref" and BUILTIN_RE.match(label.replace("func:", "")):
        return True
    if BUILTIN_RE.match(
        nid.replace("func:", "").split(":")[0] if nid.startswith("func:") else ""
    ):
        # func:len / func:str style
        short = nid.split(":")[1] if nid.startswith("func:") and ":" in nid else label
        if BUILTIN_RE.match(short) or BUILTIN_RE.match(f"func:{short}"):
            return True
    if nid.startswith("func:") and BUILTIN_RE.match(
        nid.split(":")[1] if ":" in nid else ""
    ):
        return True
    if JUNK_PATH_RE.search(_path_blob(n)) or JUNK_PATH_RE.search(_label_blob(n)):
        return True
    # Tiny heading spam
    if typ == "concept" and len(label) < 4:
        return True
    # Drop generic Python/stdlib module noise even if high degree
    if typ in ("module", "symbol") and label.lower() in {
        "json",
        "os",
        "re",
        "sys",
        "path",
        "typing",
        "pathlib",
        "annotations",
        "collections",
        "dataclasses",
        "functools",
        "itertools",
        "asyncio",
    }:
        return True
    return False


def neighbor_worth_keeping(n: dict, seed_ids: set[str], adj_priority: set[str]) -> bool:
    if is_junk(n):
        return False
    typ = n.get("type", "")
    deg = int(n.get("degree") or 0)
    nid = n["id"]
    if typ in ("file", "doc"):
        return True
    if typ in SEED_TYPES:
        return True
    # symbols/functions/classes only if linked via priority edge or hot
    if typ in ("function", "class", "module", "symbol"):
        # Only hot symbols that touch priority ecosystem edges
        if nid in adj_priority and deg >= 8:
            return True
        return False
    if typ == "concept":
        if is_seed(n):
            return True
        # 1-hop markdown headings only if priority-linked and reasonably hot
        return deg >= 4 and nid in adj_priority
    if typ in ("metadata", "reference", "rationale"):
        return nid in adj_priority
    if typ == "inferred_ref":
        return False
    return False


def lighten(data: dict, max_nodes: int = 480, max_hops: int = 1) -> dict:
    nodes = {n["id"]: n for n in data.get("nodes", []) if n.get("id")}
    edges = data.get("edges", [])

    seeds = {nid for nid, n in nodes.items() if is_seed(n) and not is_junk(n)}
    if not seeds:
        raise SystemExit("No seed nodes found — refusing to lighten empty ecosystem")

    # adjacency
    adj: dict[str, set[str]] = defaultdict(set)
    priority_touch: set[str] = set()
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in nodes and t in nodes:
            adj[s].add(t)
            adj[t].add(s)
            if e.get("type") in PRIORITY_EDGE_TYPES:
                priority_touch.add(s)
                priority_touch.add(t)

    keep = set(seeds)
    frontier = set(seeds)
    for _ in range(max_hops):
        nxt = set()
        for nid in frontier:
            for nb in adj.get(nid, ()):
                if nb in keep or nb not in nodes:
                    continue
                if neighbor_worth_keeping(nodes[nb], seeds, priority_touch):
                    keep.add(nb)
                    nxt.add(nb)
        frontier = nxt

    # Fill with hottest remaining files/docs (not junk) up to cap
    if len(keep) < max_nodes:
        candidates = []
        for nid, n in nodes.items():
            if nid in keep or is_junk(n):
                continue
            typ = n.get("type", "")
            if typ not in ("file", "doc"):
                continue
            # prefer hot project files
            score = int(n.get("degree") or 0)
            path = _path_blob(n)
            # bare names match both standalone (scout-cli/) and dottie (apps/scout-cli/) layouts
            if any(
                k in path
                for k in (
                    "scout-cli",
                    "scout-rtx",
                    "personal-graphify",
                    "vector-",
                    "turnover",
                    "ava-factory",
                    "ava-skills",
                    "ava-open-harness",
                )
            ):
                score += 40
            # multi_jspace / graphify core files
            if any(k in path for k in ("multi_jspace", "graphify", "/ava/", "bigbang")):
                score += 30
            candidates.append((score, nid))
        candidates.sort(reverse=True)
        for score, nid in candidates:
            if len(keep) >= max_nodes:
                break
            keep.add(nid)

    # If still over cap (too many 1-hop), rank: seeds first, then by degree
    if len(keep) > max_nodes:
        ranked = sorted(
            keep,
            key=lambda nid: (
                0 if nid in seeds else 1,
                0 if nodes[nid].get("type") in SEED_TYPES else 1,
                0 if nodes[nid].get("type") in ("file", "doc") else 1,
                -int(nodes[nid].get("degree") or 0),
            ),
        )
        keep = set(ranked[:max_nodes])
        # never drop seeds that fit — if seeds > max, raise max
        if not seeds.issubset(keep):
            keep |= seeds
            # trim non-seeds again
            extras = sorted(
                (keep - seeds),
                key=lambda nid: -int(nodes[nid].get("degree") or 0),
            )
            budget = max(0, max_nodes - len(seeds))
            keep = set(seeds) | set(extras[:budget])

    # Compact node payloads
    out_nodes = []
    for nid in keep:
        n = nodes[nid]
        slim = {
            "id": nid,
            "label": n.get("label", nid),
            "type": n.get("type", "concept"),
            "degree": int(n.get("degree") or 0),
        }
        if n.get("community") is not None:
            slim["community"] = n["community"]
        if n.get("file"):
            slim["file"] = n["file"]
        if n.get("desc") and n.get("type") in SEED_TYPES:
            slim["desc"] = str(n["desc"])[:160]
        out_nodes.append(slim)

    out_edges = []
    seen = set()
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s not in keep or t not in keep:
            continue
        et = e.get("type", "references")
        # Drop call-graph spam unless both ends are seeds or priority type
        if et == "calls" and not (s in seeds or t in seeds):
            continue
        if et == "imports" and not (
            s in seeds or t in seeds or nodes[s].get("type") in ("file", "doc")
        ):
            continue
        key = (s, t, et)
        if key in seen:
            continue
        seen.add(key)
        out_edges.append(
            {
                "source": s,
                "target": t,
                "type": et,
                "confidence": e.get("confidence", "INFERRED"),
            }
        )

    # Ensure priority edges among seeds survive even if filtered oddly
    for e in edges:
        if e.get("type") not in PRIORITY_EDGE_TYPES:
            continue
        s, t = e.get("source"), e.get("target")
        if s in keep and t in keep:
            key = (s, t, e.get("type"))
            if key not in seen:
                seen.add(key)
                out_edges.append(
                    {
                        "source": s,
                        "target": t,
                        "type": e.get("type"),
                        "confidence": e.get("confidence", "INFERRED"),
                    }
                )

    out_nodes.sort(key=lambda n: (-n.get("degree", 0), n.get("label", "")))
    return {
        "nodes": out_nodes,
        "edges": out_edges,
        "meta": {
            "nodes": len(out_nodes),
            "edges": len(out_edges),
            "source": "personal-graphify public light v1",
            "notes": (
                "Solo personal project, no connection to employer, built with public/free-tier only. "
                "Light public graph: ecosystem seeds + 1-hop signal; call-graph/builtin noise dropped."
            ),
            "version": "0.3.1-light-ava-scout",
            "seeds": len(seeds),
            "max_nodes": max_nodes,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="docs/public/graphify-public-non-pii.json")
    ap.add_argument("--dest", default="docs/public/graphify-public-non-pii.json")
    ap.add_argument("--max-nodes", type=int, default=250)
    ap.add_argument("--minify", action="store_true", help="Compact JSON (no indent)")
    args = ap.parse_args()

    src = Path(args.src)
    data = json.loads(src.read_text(encoding="utf-8"))
    before_n, before_e = len(data.get("nodes", [])), len(data.get("edges", []))
    light = lighten(data, max_nodes=args.max_nodes)
    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if args.minify:
        text = json.dumps(light, separators=(",", ":"), ensure_ascii=False)
    else:
        text = json.dumps(light, indent=2, ensure_ascii=False)
    dest.write_text(text, encoding="utf-8")
    kb = len(text) / 1024
    print(
        f"Lightened {before_n}n/{before_e}e → {light['meta']['nodes']}n/{light['meta']['edges']}e "
        f"({kb:.1f} KB) seeds={light['meta']['seeds']} → {dest}"
    )


if __name__ == "__main__":
    main()
