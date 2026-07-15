"""
extract.py — AST + semantic extraction (Ollama-first, local fallback)
Solo personal project, no connection to employer, built with public/free-tier only
Uses tree-sitter where available, falls back to Python ast + regex for free-tier minimal deps.
"""
import ast
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
import hashlib

# Node shape
# {id, label, type, file, line, community, meta}
# Edge shape
# {source, target, type, confidence: EXTRACTED|INFERRED|AMBIGUOUS, meta}

EXTRACTED = "EXTRACTED"
INFERRED = "INFERRED"
AMBIGUOUS = "AMBIGUOUS"

def hash_id(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]

# --- Python AST extraction ---

def extract_python(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    nodes, edges = [], []
    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
    except:
        return nodes, edges
    try:
        tree = ast.parse(source, filename=str(file_path))
    except:
        return nodes, edges

    file_node_id = f"file:{file_path}"
    nodes.append({
        "id": file_node_id,
        "label": str(file_path),
        "type": "file",
        "file": str(file_path),
        "language": "python"
    })

    # classes, funcs, imports
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            nid = f"class:{node.name}:{file_path}"
            nodes.append({"id": nid, "label": node.name, "type": "class", "file": str(file_path), "line": getattr(node, 'lineno', 0)})
            edges.append({"source": file_node_id, "target": nid, "type": "defines", "confidence": EXTRACTED})
            # bases -> inherits
            for base in node.bases:
                if isinstance(base, ast.Name):
                    edges.append({"source": nid, "target": f"class:{base.id}", "type": "inherits", "confidence": INFERRED})
        elif isinstance(node, ast.FunctionDef):
            nid = f"func:{node.name}:{file_path}:{getattr(node,'lineno',0)}"
            ntype = "function"
            # check if inside class via parent? simplified: if file contains class earlier, but we skip
            nodes.append({"id": nid, "label": node.name, "type": ntype, "file": str(file_path), "line": getattr(node,'lineno',0)})
            edges.append({"source": file_node_id, "target": nid, "type": "defines", "confidence": EXTRACTED})
            # calls inside
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    if isinstance(sub.func, ast.Name):
                        target = f"func:{sub.func.id}"
                        edges.append({"source": nid, "target": target, "type": "calls", "confidence": INFERRED})
                    elif isinstance(sub.func, ast.Attribute):
                        attr = sub.func.attr
                        target = f"func:{attr}"
                        edges.append({"source": nid, "target": target, "type": "calls", "confidence": AMBIGUOUS})

        elif isinstance(node, ast.Import):
            for alias in node.names:
                imp_id = f"module:{alias.name}"
                if not any(n["id"]==imp_id for n in nodes):
                    nodes.append({"id": imp_id, "label": alias.name, "type": "module", "file": str(file_path)})
                edges.append({"source": file_node_id, "target": imp_id, "type": "imports", "confidence": EXTRACTED})
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            mod_id = f"module:{mod}"
            if mod and not any(n["id"]==mod_id for n in nodes):
                nodes.append({"id": mod_id, "label": mod, "type": "module"})
            if mod:
                edges.append({"source": file_node_id, "target": mod_id, "type": "imports", "confidence": EXTRACTED})
            for alias in node.names:
                sym_id = f"symbol:{alias.name}:{mod}"
                nodes.append({"id": sym_id, "label": alias.name, "type": "symbol", "module": mod})
                edges.append({"source": file_node_id, "target": sym_id, "type": "imports", "confidence": EXTRACTED})

    # NOTE/WIY comments as rationale nodes
    rationale_re = re.compile(r"#\s*(NOTE|WHY|HACK|TODO):?\s*(.+)", re.I)
    for i, line in enumerate(source.splitlines(), 1):
        m = rationale_re.search(line)
        if m:
            kind = m.group(1).upper()
            text = m.group(2).strip()[:200]
            nid = f"rationale:{hash_id(text+str(file_path)+str(i))}"
            nodes.append({"id": nid, "label": f"{kind}: {text}", "type": "rationale", "file": str(file_path), "line": i, "kind": kind})
            edges.append({"source": file_node_id, "target": nid, "type": "explains", "confidence": EXTRACTED})

    return nodes, edges

# --- Generic JS/TS regex fallback ---

JS_FUNC_RE = re.compile(r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*\(.*?\)\s*=>|class\s+(\w+))")
JS_IMPORT_RE = re.compile(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\)")
JS_CALL_RE = re.compile(r"(\w+)\s*\(")

def extract_js_generic(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    nodes, edges = [], []
    try:
        src = file_path.read_text(encoding="utf-8", errors="ignore")
    except:
        return nodes, edges
    file_node_id = f"file:{file_path}"
    nodes.append({"id": file_node_id, "label": str(file_path), "type": "file", "file": str(file_path), "language": file_path.suffix})
    for m in JS_FUNC_RE.finditer(src):
        name = m.group(1) or m.group(2) or m.group(3)
        if not name:
            continue
        nid = f"symbol:{name}:{file_path}"
        nodes.append({"id": nid, "label": name, "type": "class" if m.group(3) else "function", "file": str(file_path)})
        edges.append({"source": file_node_id, "target": nid, "type": "defines", "confidence": EXTRACTED})
    for m in JS_IMPORT_RE.finditer(src):
        mod = m.group(1) or m.group(2)
        if not mod:
            continue
        mod_id = f"module:{mod}"
        nodes.append({"id": mod_id, "label": mod, "type": "module"})
        edges.append({"source": file_node_id, "target": mod_id, "type": "imports", "confidence": EXTRACTED})
    return nodes, edges

# --- Docs extraction ---

MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\[\[([^\]]+)\]\]")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)

def extract_markdown(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    nodes, edges = [], []
    try:
        src = file_path.read_text(encoding="utf-8", errors="ignore")
    except:
        return nodes, edges
    file_id = f"doc:{file_path}"
    nodes.append({"id": file_id, "label": file_path.name, "type": "doc", "file": str(file_path)})

    # headings as concepts
    for m in MD_HEADING_RE.finditer(src):
        title = m.group(2).strip()[:100]
        nid = f"concept:{title}:{file_path}"
        nodes.append({"id": nid, "label": title, "type": "concept", "file": str(file_path)})
        edges.append({"source": file_id, "target": nid, "type": "contains", "confidence": EXTRACTED})

    # links as references
    for m in MD_LINK_RE.finditer(src):
        link_text = m.group(1) or m.group(3) or ""
        link_url = m.group(2) or m.group(3) or ""
        if not link_url:
            continue
        target_id = f"ref:{link_url}"
        nodes.append({"id": target_id, "label": link_url, "type": "reference"})
        edges.append({"source": file_id, "target": target_id, "type": "references", "confidence": EXTRACTED, "meta": {"text": link_text}})

    # special: PROJECT.md custom patterns for personal ecosystem
    if file_path.name == "PROJECT.md":
        # extract goals
        goal_re = re.compile(r"-\s*(.+)", re.M)
        for line in src.splitlines():
            if len(line.strip())>0 and len(nodes)<50:
                if "MRR" in line or "Turnover" in line or "MTNN" in line or "Ava" in line or "Family" in line:
                    nid = f"concept:{hash_id(line)}"
                    nodes.append({"id": nid, "label": line.strip()[:120], "type": "concept", "file": str(file_path)})
                    edges.append({"source": file_id, "target": nid, "type": "contains", "confidence": INFERRED})

    return nodes, edges

# --- Personal ecosystem extractors ---

PERSONAL_PATTERNS = {
    "stripe": ("integration:stripe", "Stripe", "integration"),
    "plaid": ("integration:plaid", "Plaid", "integration"),
    "betterment": ("integration:betterment", "Betterment", "integration"),
    "supabase": ("integration:supabase", "Supabase", "integration"),
    "cloudflare": ("integration:cloudflare", "Cloudflare Workers", "integration"),
    "workers": ("integration:cloudflare", "Cloudflare Workers", "integration"),
    "turnover shield": ("concept:turnover-shield", "Turnover Shield", "product"),
    "turnover": ("concept:turnover-shield", "Turnover Shield", "product"),
    "family brain": ("concept:family-brain", "Davis Family Brain", "product"),
    "mrr": ("concept:mrr", "MRR / Paid Users", "business_metric"),
    "mtNN": ("concept:mtnn", "MTNN v5_concat_b2_h160_t32_d48_mlp128", "ml_concept"),
    "mtnn": ("concept:mtnn", "MTNN v5_concat_b2_h160_t32_d48_mlp128", "ml_concept"),
    "ava": ("concept:ava", "Ava AGI Factory v6.4", "ml_concept"),
    "j-space": ("concept:jspace", "Ava J-Space Multi (S1 hl8 S2 hl300 Critic hl30 Planner hl150)", "ml_concept"),
    "jspace": ("concept:jspace", "Ava J-Space Multi (S1 hl8 S2 hl300 Critic hl30 Planner hl150)", "ml_concept"),
    "s1 fast": ("concept:s1-fast", "Ava S1 Fast hl8", "ml_concept"),
    "s2 slow": ("concept:s2-slow", "Ava S2 Slow hl300", "ml_concept"),
    "critic": ("concept:critic", "Ava Critic hl30", "ml_concept"),
    "planner": ("concept:planner", "Ava Planner hl150", "ml_concept"),
    "vector hoops": ("concept:vector-hoops", "Vector Hoops 12,966 seasons", "product"),
    "dumbmodel": ("concept:dumbmodel", "dumbmodel.com ecosystem", "product"),
    "dinov3": ("concept:tennis-dinov3", "Tennis DINOv3 ExecuTorch", "product"),
    "graphify": ("concept:graphify", "Personal Graphify", "tool"),
}

def extract_personal_patterns(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    nodes, edges = [], []
    # Look for 01_Finance, 02_Passive_Lab patterns in path
    parts = file_path.parts
    if "01_Finance" in parts or "02_Passive_Lab" in parts or "04_Tennis_DINOv3" in parts:
        cat = "finance" if "01_Finance" in parts else "passive_lab" if "02_Passive_Lab" in parts else "tennis"
        nid = f"ecosystem:{cat}"
        nodes.append({"id": nid, "label": cat, "type": "ecosystem_domain"})
        file_id = f"file:{file_path}"
        edges.append({"source": file_id, "target": nid, "type": "belongs_to", "confidence": INFERRED})
    try:
        src = file_path.read_text(encoding="utf-8", errors="ignore")
        low = src.lower()
        file_id = f"file:{file_path}"
        for key, (nid, label, typ) in PERSONAL_PATTERNS.items():
            if key.lower() in low:
                nodes.append({"id": nid, "label": label, "type": typ})
                edges.append({"source": file_id, "target": nid, "type": "uses", "confidence": INFERRED})
        # special detect 48→64→k, hl=8 etc even case-sensitive
        if "48→64" in src or "48->64" in src or "hl=" in low:
            nodes.append({"id": "concept:mtnn-head", "label": "MTNN head 48→64→k", "type": "ml_concept"})
            edges.append({"source": file_id, "target": "concept:mtnn-head", "type": "uses", "confidence": INFERRED})
    except:
        pass
    return nodes, edges

def extract_file(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    suffix = file_path.suffix.lower()
    nodes, edges = [], []
    if suffix == ".py":
        n, e = extract_python(file_path)
        nodes.extend(n); edges.extend(e)
    elif suffix in (".js",".ts",".jsx",".tsx",".mjs",".mts",".cts"):
        n, e = extract_js_generic(file_path)
        nodes.extend(n); edges.extend(e)
    elif suffix in (".md",".mdx",".mdc",".txt",".rst"):
        n, e = extract_markdown(file_path)
        nodes.extend(n); edges.extend(e)
    # personal patterns always
    n2, e2 = extract_personal_patterns(file_path)
    nodes.extend(n2); edges.extend(e2)

    # dedup nodes by id
    seen = {}
    dedup_nodes = []
    for n in nodes:
        if n["id"] not in seen:
            seen[n["id"]]=True
            dedup_nodes.append(n)
    return dedup_nodes, edges

def extract_all(files: List[Path]) -> Tuple[List[Dict], List[Dict]]:
    all_nodes: List[Dict] = []
    all_edges: List[Dict] = []
    id_seen = {}
    for fp in files:
        nodes, edges = extract_file(fp)
        for n in nodes:
            if n["id"] not in id_seen:
                id_seen[n["id"]]=True
                all_nodes.append(n)
        all_edges.extend(edges)
    # dedup edges by source/target/type
    edge_seen = {}
    dedup_edges = []
    for e in all_edges:
        key = (e["source"], e["target"], e["type"])
        if key not in edge_seen:
            edge_seen[key]=True
            dedup_edges.append(e)
    return all_nodes, dedup_edges
