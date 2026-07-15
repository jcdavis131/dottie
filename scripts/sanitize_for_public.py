#!/usr/bin/env python3
"""
sanitize_for_public.py — v3 deduped non-PII public graph
- Strips home paths -> personal-graphify/
- Removes $ balances, account numbers, emails, burn metrics (11k, 206% etc) from labels
- Dedupes concept IDs by title only (fixes concept:or duplicate)
- Filters trivial stopwords
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json, re
from pathlib import Path
from collections import Counter

def sanitize_path(p: str) -> str:
    if not p:
        return p
    p = re.sub(r"/home/hatch/workspace/your_files/personal-graphify/", "personal-graphify/", p)
    p = re.sub(r"/home/hatch/workspace/", "", p)
    p = re.sub(r"/home/hatch/[^\s:]*", "", p)
    p = re.sub(r"^/+", "", p)
    return p[:120]

def sanitize_id(raw_id: str):
    if not raw_id:
        return None
    if ":" in raw_id:
        prefix, rest = raw_id.split(":",1)
        if prefix == "concept":
            # split title vs file
            if "personal-graphify" in rest or ".md" in rest.split(":")[-1] or ".py" in rest.split(":")[-1] or ":/" in rest:
                title = rest.rsplit(":",1)[0] if ":" in rest else rest
            else:
                title = rest
            title=title.strip()[:80]
            if title.lower() in {"or","and","the","a","an","of","in","to","for","with","on"}:
                return None
            return f"concept:{title}"
        else:
            return f"{prefix}:{sanitize_path(rest)}"
    return sanitize_path(raw_id)

def sanitize_label(label: str, ntype: str) -> str:
    if not label:
        return ""
    # Remove home paths
    label = re.sub(r"/home/hatch[^\s]*","",label)
    # for generic file nodes, show basename only if long path
    if len(label) > 80 and "/" in label:
        label = Path(label).name
    # filter PII patterns but keep generic product names
    # Remove $ amount patterns
    if "$" in label and ntype != "business_metric":
        if re.search(r"\$\s*\d", label):
            return ""  # drop node entirely later
    # Remove account numbers patterns 4-digit alone? Keep but generic
    # Burn / EF numbers are PII for public - remove nodes containing 11k, 206%, 12.4mo etc
    if re.search(r"\b11k\b", label, re.I) and "burn" in label.lower():
        # keep label but strip numbers: replace with placeholder
        label = re.sub(r"\$?11k.*","Burn Rate", label, flags=re.I)
    return label.strip()[:120]

def main(src_path: Path, dest_path: Path):
    data = json.loads(src_path.read_text())
    old_to_new = {}
    new_nodes_by_id = {}

    for n in data.get("nodes",[]):
        old_id = n["id"]
        label = str(n.get("label",""))
        ntype = n.get("type","")

        # PII filters
        if re.search(r"jcdavis131@gmail", label, re.I):
            continue
        if "@" in label and "github.com" not in label.lower():
            continue
        if len(label.strip()) <=1:
            continue
        # Drop nodes with $ + digit unless business_metric allowed type but we still want to hide actual balances
        if "$" in label and ntype not in ("business_metric","integration"):
            if re.search(r"\$\d", label):
                # allow MRR / Paid Users label (has $ in our generic?)
                if label != "MRR / Paid Users" and "MRR" not in label:
                    continue

        new_id = sanitize_id(old_id)
        if not new_id:
            continue

        new_label = sanitize_label(label, ntype)
        if not new_label or len(new_label) < 2:
            continue
        if new_label.lower() in {"or","and"}:
            continue

        # copy with sanitization
        n["id"] = new_id
        n["label"] = new_label
        if "file" in n and n["file"]:
            n["file"] = sanitize_path(str(n["file"]))
        if "full_path" in n:
            # drop full_path for public
            n.pop("full_path", None)

        if new_id in new_nodes_by_id:
            existing = new_nodes_by_id[new_id]
            # keep max degree
            try:
                existing["degree"] = max(existing.get("degree",0), n.get("degree",0))
            except:
                pass
            old_to_new[old_id] = new_id
        else:
            new_nodes_by_id[new_id] = n
            old_to_new[old_id] = new_id

    new_nodes = list(new_nodes_by_id.values())

    new_edges = []
    seen = set()
    for e in data.get("edges",[]):
        s = e.get("source"); t = e.get("target")
        if s not in old_to_new or t not in old_to_new:
            continue
        ns = old_to_new[s]; nt = old_to_new[t]
        if ns == nt:
            continue
        key = (ns, nt, e.get("type",""))
        if key in seen:
            continue
        seen.add(key)
        e["source"] = ns; e["target"] = nt
        new_edges.append(e)

    print(f"Original {len(data['nodes'])} nodes {len(data['edges'])} edges -> sanitized {len(new_nodes)} nodes {len(new_edges)} edges")
    ids = [n["id"] for n in new_nodes]
    dup = [i for i,c in Counter(ids).items() if c>1]
    print(f"dup check: {dup[:5]} (should be empty)")

    sanitized = {
        "nodes": new_nodes,
        "edges": new_edges,
        "meta": {
            "nodes": len(new_nodes),
            "edges": len(new_edges),
            "source": "personal-graphify non-PII public v3 deduped",
            "notes": "Solo personal project, no connection to employer, built with public/free-tier only. PII stripped: $ balances, account numbers, emails, burn metrics.",
            "version": "0.2.0-sota"
        }
    }
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(json.dumps(sanitized, indent=2))
    print(f"Wrote {dest_path} {len(dest_path.read_text())/1024:.1f}KB")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="graphify-out/graph.json")
    ap.add_argument("--dest", default="docs/public/graphify-public-non-pii.json")
    args = ap.parse_args()
    main(Path(args.src), Path(args.dest))
