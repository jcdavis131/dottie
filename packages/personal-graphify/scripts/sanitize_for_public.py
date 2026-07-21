#!/usr/bin/env python3
"""
sanitize_for_public.py — v4 non-PII public graph
- Strips Unix + Windows home paths → project aliases
- Removes emails, account digits, burn balances from labels/desc
- Dedupes concept IDs by title only (fixes concept:or duplicate)
- Filters trivial stopwords + egg-info junk
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import os
import re
from pathlib import Path
from collections import Counter

# Dottie monorepo checkout root (set when exports are built inside a dottie checkout).
# Prefer DOTTIE_ROOT when present; the layout-fragment regexes below still redact
# dottie paths when it is unset, and standalone-layout paths keep working unchanged.
_DOTTIE_ROOT = os.environ.get("DOTTIE_ROOT", "").replace("\\", "/").rstrip("/")

ACCT_RE = re.compile(r"\b(0472|5594|8889)\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
WIN_USER_RE = re.compile(r"(?i)[A-Z]:[/\\]Users[/\\][^/\\]+[/\\]")
HOME_HATCH_RE = re.compile(r"/home/hatch/[^\s\"']*")
DOLLAR_AMT_RE = re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?(?:k|K|m|M)?")
BURN_RE = re.compile(r"\b11k\b|\b206%\b|\b12\.4\s*mo\b", re.I)

STOP_CONCEPTS = {"or", "and", "the", "a", "an", "of", "in", "to", "for", "with", "on"}


def sanitize_path(p: str) -> str:
    if not p:
        return p
    p = p.replace("\\", "/")
    if _DOTTIE_ROOT:
        p = p.replace(_DOTTIE_ROOT + "/", "")
    p = re.sub(r"/home/hatch/workspace/your_files/personal-graphify/", "personal-graphify/", p)
    p = re.sub(r"/home/hatch/workspace/", "", p)
    p = HOME_HATCH_RE.sub("", p)
    replacements = [
        (r"(?i)[A-Z]:/Users/[^/]+/personal-graphify/", "personal-graphify/"),
        (r"(?i)[A-Z]:/Users/[^/]+/scout-cli/", "scout-cli/"),
        (r"(?i)[A-Z]:/Users/[^/]+/scout-rtx/", "scout-rtx/"),
        (r"(?i)[A-Z]:/Users/[^/]+/ava-agi-factory-v6-4/", "ava-agi-factory/"),
        (r"(?i)[A-Z]:/Users/[^/]+/ava-agi/", "ava-agi/"),
        (r"(?i)[A-Z]:/Users/[^/]+/vector-hoops/", "vector-hoops/"),
        (r"(?i)[A-Z]:/Users/[^/]+/vector-pitch/", "vector-pitch/"),
        (r"(?i)[A-Z]:/Users/[^/]+/vector-gridiron/", "vector-gridiron/"),
        (r"(?i)[A-Z]:/Users/[^/]+/vector-tennis/", "vector-tennis/"),
        (r"(?i)[A-Z]:/Users/[^/]+/jcamd-site/", "jcamd-site/"),
        # dottie monorepo layout: apps/* + packages/* fragments → project aliases,
        # regardless of the checkout prefix (home dir, DOTTIE_ROOT, drive letter)
        (r"(?i)^(?:.*/)?apps/scout-cli/", "scout-cli/"),
        (r"(?i)^(?:.*/)?apps/scout-rtx/", "scout-rtx/"),
        (r"(?i)^(?:.*/)?apps/ava-factory/", "ava-factory/"),
        (r"(?i)^(?:.*/)?packages/personal-graphify/", "personal-graphify/"),
        (r"(?i)^(?:.*/)?packages/ava-skills/", "ava-skills/"),
        (r"(?i)^(?:.*/)?packages/ava-open-harness/", "ava-open-harness/"),
        (r"(?i)[A-Z]:/Users/[^/]+/", ""),
    ]
    for pat, repl in replacements:
        p = re.sub(pat, repl, p)
    p = re.sub(r"^/+", "", p)
    return p[:120]


def scrub_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\\", "/")
    text = HOME_HATCH_RE.sub("", text)
    text = WIN_USER_RE.sub("", text)
    text = EMAIL_RE.sub("[email]", text)
    text = ACCT_RE.sub("[acct]", text)
    text = BURN_RE.sub("[redacted]", text)
    # Keep generic MRR pricing language; strip other dollar amounts in prose
    if "MRR" not in text and "79" not in text and "149" not in text and "1k" not in text.lower():
        text = DOLLAR_AMT_RE.sub("[amt]", text)
    return text.strip()


def sanitize_id(raw_id: str):
    if not raw_id:
        return None
    raw_id = scrub_text(str(raw_id))
    if ":" in raw_id:
        prefix, rest = raw_id.split(":", 1)
        if prefix == "concept":
            # Drop path suffixes: concept:title:C:/... or concept:title:/path
            if ":" in rest:
                # Prefer left-most title before a drive/path fragment
                parts = rest.split(":")
                title = parts[0]
                for part in parts[1:]:
                    # The extension list must match the doc types the pipeline indexes
                    # (detect.py DOC_EXTS: md/mdx/mdc/txt/rst/qmd/yaml/yml — `.md` already
                    # covers mdx/mdc as a substring). Omitting rst/qmd/yaml leaked the
                    # internal repo path (e.g. dottie/notes/guide.rst) into the "public"
                    # concept id AND broke title-only dedup against the same heading in a
                    # .md file. A per-extension list is used, not a generic `\.\w+$`, so a
                    # legitimate title segment like "Node.js" is not mistaken for a path.
                    if re.search(r"(?i)^[A-Z]/|^/|personal-graphify|ava-agi|scout-|"
                                 r"\.md|\.py|\.txt|\.rst|\.qmd|\.ya?ml", part):
                        break
                    title = f"{title}:{part}"
            else:
                title = rest
            # Also strip trailing path if embedded with /
            title = re.split(r"(?=[A-Z]:/|/Users/|/home/)", title)[0]
            title = scrub_text(title).strip()[:80]
            if not title or title.lower() in STOP_CONCEPTS:
                return None
            return f"concept:{title}"
        return f"{prefix}:{sanitize_path(rest)}"
    return sanitize_path(raw_id)


def sanitize_label(label: str, ntype: str) -> str:
    if not label:
        return ""
    label = scrub_text(label)
    # file:C:/... → basename
    if label.startswith("file:") or (len(label) > 60 and ("/" in label or "\\" in label)):
        label = Path(label.replace("\\", "/").split(":")[-1]).name or label
    if "$" in label and ntype != "business_metric":
        if re.search(r"\$\s*\d", label) and "MRR" not in label and "1k" not in label.lower():
            return ""
    if re.search(r"\b11k\b", label, re.I) and "burn" in label.lower():
        label = re.sub(r"\$?11k.*", "Burn Rate", label, flags=re.I)
    return label.strip()[:120]


def is_junk_node(old_id: str, label: str) -> bool:
    blob = f"{old_id} {label}".lower()
    junk = ("egg-info", "node_modules", "__pycache__", ".pyc", "package-lock")
    return any(j in blob for j in junk)


def main(src_path: Path, dest_path: Path):
    data = json.loads(src_path.read_text(encoding="utf-8"))
    old_to_new = {}
    new_nodes_by_id = {}

    for n in data.get("nodes", []):
        old_id = n["id"]
        label = str(n.get("label", ""))
        ntype = n.get("type", "")

        if is_junk_node(str(old_id), label):
            continue
        if re.search(r"jcdavis131@gmail", label, re.I):
            continue
        if "@" in label and "github.com" not in label.lower() and "[email]" not in label:
            continue
        if len(label.strip()) <= 1:
            continue
        if "$" in label and ntype not in ("business_metric", "integration"):
            if re.search(r"\$\d", label) and "MRR" not in label and "1k" not in label.lower():
                continue
        # Drop nodes whose private desc is mostly account/burn PII and label is just bank name
        desc = str(n.get("desc", ""))
        if ACCT_RE.search(desc) or ACCT_RE.search(label):
            # scrub rather than drop named integrations
            desc = scrub_text(desc)
            label = scrub_text(label)

        new_id = sanitize_id(old_id)
        if not new_id or WIN_USER_RE.search(new_id) or "Users/" in new_id:
            continue

        new_label = sanitize_label(label, ntype)
        if not new_label or len(new_label) < 2:
            continue
        if new_label.lower() in STOP_CONCEPTS:
            continue

        clean = {
            "id": new_id,
            "label": new_label,
            "type": ntype,
            "degree": n.get("degree", 0),
        }
        if n.get("community") is not None:
            clean["community"] = n.get("community")
        if n.get("file"):
            clean["file"] = sanitize_path(str(n["file"]))
        if desc:
            scrubbed_desc = scrub_text(desc)
            # Drop desc that still looks like account/burn detail
            if scrubbed_desc and not ACCT_RE.search(scrubbed_desc) and "burn $" not in scrubbed_desc.lower():
                # Soften remaining dollar product pricing only
                clean["desc"] = scrubbed_desc[:200]

        if new_id in new_nodes_by_id:
            existing = new_nodes_by_id[new_id]
            existing["degree"] = max(existing.get("degree", 0), clean.get("degree", 0))
            if clean.get("desc") and not existing.get("desc"):
                existing["desc"] = clean["desc"]
            if len(clean.get("label", "")) > len(existing.get("label", "")):
                existing["label"] = clean["label"]
            old_to_new[old_id] = new_id
        else:
            new_nodes_by_id[new_id] = clean
            old_to_new[old_id] = new_id

    new_nodes = list(new_nodes_by_id.values())

    new_edges = []
    seen = set()
    for e in data.get("edges", []):
        s = e.get("source")
        t = e.get("target")
        if s not in old_to_new or t not in old_to_new:
            continue
        ns = old_to_new[s]
        nt = old_to_new[t]
        if ns == nt:
            continue
        key = (ns, nt, e.get("type", ""))
        if key in seen:
            continue
        seen.add(key)
        new_edges.append({
            "source": ns,
            "target": nt,
            "type": e.get("type", "references"),
            "confidence": e.get("confidence", "INFERRED"),
        })

    print(
        f"Original {len(data['nodes'])} nodes {len(data['edges'])} edges "
        f"-> sanitized {len(new_nodes)} nodes {len(new_edges)} edges"
    )
    ids = [n["id"] for n in new_nodes]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    print(f"dup check: {dup[:5]} (should be empty)")

    # Hard fail if username / acct digits remain
    blob = json.dumps({"nodes": new_nodes, "edges": new_edges})
    leaks = []
    if re.search(r"(?i)Users[/\\\\]jcdav|C:[/\\\\]Users", blob):
        leaks.append("Users_path")
    if ACCT_RE.search(blob):
        leaks.append("acct")
    if re.search(r"jcdavis131@gmail", blob, re.I):
        leaks.append("email")
    if leaks:
        raise SystemExit(f"PII gate failed: {leaks}")

    sanitized = {
        "nodes": new_nodes,
        "edges": new_edges,
        "meta": {
            "nodes": len(new_nodes),
            "edges": len(new_edges),
            "source": "personal-graphify non-PII public v4",
            "notes": (
                "Solo personal project, no connection to employer, built with public/free-tier only. "
                "PII stripped: paths, emails, account numbers, burn metrics."
            ),
            "version": "0.3.0-sota-ava-scout",
        },
    }
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")
    print(f"Wrote {dest_path} {len(dest_path.read_text(encoding='utf-8'))/1024:.1f}KB")


if __name__ == "__main__":
    import argparse
    import subprocess
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="graphify-out/graph.json")
    ap.add_argument("--dest", default="docs/public/graphify-public-non-pii.json")
    ap.add_argument(
        "--light",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After sanitize, lighten to ecosystem seeds (default on for public dest)",
    )
    ap.add_argument("--max-nodes", type=int, default=250, help="Cap for --light")
    args = ap.parse_args()
    dest = Path(args.dest)
    if args.light:
        # Write full sanitized intermediate beside dest, then lighten into dest
        full = dest.with_name(dest.stem + "-full" + dest.suffix)
        main(Path(args.src), full)
        lighten = Path(__file__).with_name("lighten_public_graph.py")
        cmd = [
            sys.executable,
            str(lighten),
            "--src",
            str(full),
            "--dest",
            str(dest),
            "--max-nodes",
            str(args.max_nodes),
            "--minify",
        ]
        raise SystemExit(subprocess.call(cmd))
    main(Path(args.src), dest)
