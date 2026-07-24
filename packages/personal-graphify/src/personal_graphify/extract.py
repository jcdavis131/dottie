"""
extract.py — AST + semantic extraction (Ollama-first, local fallback)
SOTA: tree-sitter where available for JS/TS/Python, AST for Python fallback,
rationale WHY/NOTE extraction, personal ecosystem patterns with file→concept mapping

Solo personal project, no connection to employer, built with public/free-tier only
"""
import ast
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
import hashlib

EXTRACTED = "EXTRACTED"
INFERRED = "INFERRED"
AMBIGUOUS = "AMBIGUOUS"

def hash_id(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]

# Try tree-sitter import (optional, free-tier)
try:
    from tree_sitter import Language, Parser
    import tree_sitter_python
    import tree_sitter_javascript
    import tree_sitter_typescript
    TS_AVAILABLE = True
    PY_LANGUAGE = Language(tree_sitter_python.language())
    JS_LANGUAGE = Language(tree_sitter_javascript.language())
    TS_LANGUAGE = Language(tree_sitter_typescript.language_typescript())
except Exception:
    TS_AVAILABLE = False
    PY_LANGUAGE = None
    JS_LANGUAGE = None

# --- Python extraction with AST + optional tree-sitter boost ---

def extract_python(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    nodes, edges = [], []
    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return nodes, edges
    file_node_id = f"file:{file_path}"
    nodes.append({
        "id": file_node_id,
        "label": file_path.name,
        "type": "file",
        "file": str(file_path),
        "language": "python",
        "full_path": str(file_path)
    })

    # Use AST for reliability, tree-sitter for extra if needed later
    try:
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, ValueError):
        tree = None

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                nid = f"class:{node.name}:{file_path}"
                nodes.append({"id": nid, "label": node.name, "type": "class", "file": str(file_path), "line": getattr(node, 'lineno', 0), "doc": ast.get_docstring(node) or ""})
                edges.append({"source": file_node_id, "target": nid, "type": "defines", "confidence": EXTRACTED})
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        edges.append({"source": nid, "target": f"class:{base.id}", "type": "inherits", "confidence": INFERRED})
                    elif isinstance(base, ast.Attribute):
                        edges.append({"source": nid, "target": f"class:{base.attr}", "type": "inherits", "confidence": AMBIGUOUS})
            elif isinstance(node, ast.FunctionDef):
                # check if method vs function
                nid = f"func:{node.name}:{file_path}:{getattr(node,'lineno',0)}"
                args_count = len(node.args.args)
                ntype = "function"
                doc = ast.get_docstring(node) or ""
                nodes.append({"id": nid, "label": node.name, "type": ntype, "file": str(file_path), "line": getattr(node,'lineno',0), "args": args_count, "doc": doc[:200]})
                edges.append({"source": file_node_id, "target": nid, "type": "defines", "confidence": EXTRACTED})
                # calls inside
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Name):
                            target = f"func:{sub.func.id}"
                            edges.append({"source": nid, "target": target, "type": "calls", "confidence": INFERRED})
                        elif isinstance(sub.func, ast.Attribute):
                            attr = sub.func.attr
                            # filter trivial builtins
                            if attr not in ("append","add","get","set","items","keys","join","split"):
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
                    nodes.append({"id": sym_id, "label": alias.name, "type": "symbol", "module": mod, "file": str(file_path)})
                    edges.append({"source": file_node_id, "target": sym_id, "type": "imports", "confidence": EXTRACTED})

    # Rationale extraction: # NOTE, # WHY, # HACK, # TODO, # FIXME, # BUG
    rationale_re = re.compile(r"#\s*(NOTE|WHY|HACK|TODO|FIXME|BUG|OPTIMIZE|PERF):?\s*(.+)", re.I)
    # also // for python? not needed
    for i, line in enumerate(source.splitlines(), 1):
        m = rationale_re.search(line)
        if m:
            kind = m.group(1).upper()
            text = m.group(2).strip()[:240]
            if len(text) < 3:
                continue
            nid = f"rationale:{hash_id(text+str(file_path)+str(i))}"
            nodes.append({"id": nid, "label": f"{kind}: {text}", "type": "rationale", "file": str(file_path), "line": i, "kind": kind, "text": text})
            edges.append({"source": file_node_id, "target": nid, "type": "explains", "confidence": EXTRACTED})
            # also link to nearest function above if exists
            # find last func node before this line
            func_candidates = [n for n in nodes if n["type"]=="function" and n.get("line",0) < i and n.get("file")==str(file_path)]
            if func_candidates:
                closest = max(func_candidates, key=lambda x: x.get("line",0))
                edges.append({"source": closest["id"], "target": nid, "type": "has_rationale", "confidence": INFERRED})

    return nodes, edges

# --- Tree-sitter JS/TS extraction SOTA ---

def _ts_extract_symbols(code: bytes, language) -> List[Tuple[str,str,int]]:
    """Returns list of (kind, name, line)"""
    if not TS_AVAILABLE:
        return []
    parser = Parser(language)
    tree = parser.parse(code)
    # simple walk
    results = []
    def walk(node, depth=0):
        if depth>12:
            return
        t = node.type
        # function
        if t in ("function_declaration","function","method_definition","lexical_declaration"):
            # One name per declaration: a node carries EITHER a direct identifier child
            # (function foo() {}) OR a variable_declarator (const foo = () => {}),
            # never both — so these branches are mutually exclusive by construction.
            for child in node.children:
                if child.type == "identifier":
                    name = code[child.start_byte:child.end_byte].decode(errors="ignore")
                    results.append(("function", name, node.start_point[0]+1))
                elif child.type == "variable_declarator":
                    for sub in child.children:
                        if sub.type == "identifier":
                            name = code[sub.start_byte:sub.end_byte].decode(errors="ignore")
                            results.append(("function", name, node.start_point[0]+1))
        if t == "class_declaration":
            for child in node.children:
                if child.type == "type_identifier" or child.type == "identifier":
                    name = code[child.start_byte:child.end_byte].decode(errors="ignore")
                    results.append(("class", name, node.start_point[0]+1))
        # imports
        if t == "import_statement":
            txt = code[node.start_byte:node.end_byte].decode(errors="ignore")[:200]
            # crude mod extract
            m = re.search(r"from\s+['\"]([^'\"]+)['\"]", txt)
            if m:
                results.append(("import", m.group(1), node.start_point[0]+1))
            m2 = re.search(r"import\(['\"]([^'\"]+)['\"]\)", txt)
            if m2:
                results.append(("import", m2.group(1), node.start_point[0]+1))
        for child in node.children:
            walk(child, depth+1)
    walk(tree.root_node)
    return results

JS_FUNC_RE = re.compile(r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*\(.*?\)\s*=>|class\s+(\w+)|export\s+(?:default\s+)?(?:function\s+(\w+)|class\s+(\w+)))")
JS_IMPORT_RE = re.compile(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|import\(['\"]([^'\"]+)['\"]\)|require\(['\"]([^'\"]+)['\"]\)")

def extract_js_generic(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    nodes, edges = [], []
    try:
        src = file_path.read_text(encoding="utf-8", errors="ignore")
        src_bytes = src.encode()
    except OSError:
        return nodes, edges
    file_node_id = f"file:{file_path}"
    nodes.append({"id": file_node_id, "label": file_path.name, "type": "file", "file": str(file_path), "language": file_path.suffix.strip("."), "full_path": str(file_path)})

    symbols = []
    if TS_AVAILABLE and file_path.suffix in (".js",".mjs",".cjs",".jsx"):
        symbols = _ts_extract_symbols(src_bytes, JS_LANGUAGE)
    elif TS_AVAILABLE and file_path.suffix in (".ts",".mts",".tsx"):
        symbols = _ts_extract_symbols(src_bytes, TS_LANGUAGE)
    else:
        # fallback regex
        for m in JS_FUNC_RE.finditer(src):
            name = m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5)
            if not name or len(name)<2:
                continue
            kind = "class" if m.group(3) or m.group(5) else "function"
            symbols.append((kind, name, 0))
        for m in JS_IMPORT_RE.finditer(src):
            mod = m.group(1) or m.group(2) or m.group(3)
            if mod:
                symbols.append(("import", mod, 0))

    seen_sym_ids = set()
    for kind, name, line in symbols:
        if kind in ("function","class"):
            nid = f"{kind}:{name}:{file_path}"
            if nid in seen_sym_ids:
                continue
            seen_sym_ids.add(nid)
            nodes.append({"id": nid, "label": name, "type": kind, "file": str(file_path), "line": line})
            edges.append({"source": file_node_id, "target": nid, "type": "defines", "confidence": EXTRACTED})
        elif kind == "import":
            mod_id = f"module:{name}"
            if mod_id not in seen_sym_ids:
                seen_sym_ids.add(mod_id)
                nodes.append({"id": mod_id, "label": name, "type": "module"})
            edges.append({"source": file_node_id, "target": mod_id, "type": "imports", "confidence": EXTRACTED})

    # Rationale for JS/TS: // NOTE, // WHY, /* NOTE */
    rationale_re = re.compile(r"(?:\/\/|#|\/\*+)\s*(NOTE|WHY|HACK|TODO|FIXME|OPTIMIZE):?\s*(.+)", re.I)
    for i, line in enumerate(src.splitlines(), 1):
        m = rationale_re.search(line)
        if m:
            kind = m.group(1).upper()
            text = m.group(2).strip()[:240].strip(" */")
            if len(text)<3:
                continue
            nid = f"rationale:{hash_id(text+str(file_path)+str(i))}"
            nodes.append({"id": nid, "label": f"{kind}: {text}", "type": "rationale", "file": str(file_path), "line": i, "kind": kind})
            edges.append({"source": file_node_id, "target": nid, "type": "explains", "confidence": EXTRACTED})

    return nodes, edges

# --- Docs extraction SOTA ---

MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)|\[\[([^\]]+)\]\]")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
MD_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

def extract_markdown(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    nodes, edges = [], []
    try:
        src = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return nodes, edges
    file_id = f"doc:{file_path}"
    nodes.append({"id": file_id, "label": file_path.name, "type": "doc", "file": str(file_path), "full_path": str(file_path)})

    # frontmatter via python-frontmatter if available
    try:
        import frontmatter
        post = frontmatter.loads(src)
        fm = post.metadata
        for k,v in fm.items():
            if isinstance(v,str) and len(v)>0:
                nid = f"concept:{k}={v}:{file_path}"
                nodes.append({"id": nid, "label": f"{k}: {v}", "type": "metadata", "file": str(file_path)})
                edges.append({"source": file_id, "target": nid, "type": "has_metadata", "confidence": EXTRACTED})
    except Exception:  # optional frontmatter dep may be absent, or parse may fail
        pass

    # headings as concepts + hierarchy
    prev_headings = []  # stack of (level, id)
    for m in MD_HEADING_RE.finditer(src):
        level = len(m.group(1))
        title = m.group(2).strip()[:120]
        if len(title) < 2 or title.lower() in ("or","and"):
            continue
        nid = f"concept:{title}:{file_path}"
        nodes.append({"id": nid, "label": title, "type": "concept", "file": str(file_path), "level": level})
        edges.append({"source": file_id, "target": nid, "type": "contains", "confidence": EXTRACTED})
        # hierarchy
        while prev_headings and prev_headings[-1][0] >= level:
            prev_headings.pop()
        if prev_headings:
            parent_id = prev_headings[-1][1]
            edges.append({"source": parent_id, "target": nid, "type": "contains", "confidence": INFERRED})
        prev_headings.append((level, nid))

    # links as references
    for m in MD_LINK_RE.finditer(src):
        link_text = m.group(1) or m.group(3) or ""
        link_url = m.group(2) or m.group(3) or ""
        if not link_url or len(link_url)<2:
            continue
        # skip trivial anchors
        if link_url.startswith("#"):
            continue
        target_id = f"ref:{link_url}"
        nodes.append({"id": target_id, "label": link_url[:120], "type": "reference", "file": str(file_path), "link_text": link_text[:80]})
        edges.append({"source": file_id, "target": target_id, "type": "references", "confidence": EXTRACTED, "meta": {"text": link_text}})

    return nodes, edges

# --- Personal ecosystem extractors SOTA ---

PERSONAL_PATTERNS = {
    # integrations
    "stripe": ("integration:stripe", "Stripe", "integration", "Billing for Turnover Shield $79-149/mo"),
    "plaid": ("integration:plaid", "Plaid", "integration", "Bank linking for Davis Family Brain burn $11k EF $66k"),
    "betterment": ("integration:betterment", "Betterment", "integration", "Family joint cash + investing buckets"),
    "supabase": ("integration:supabase", "Supabase", "integration", "DB for Turnover Shield free-tier"),
    "cloudflare": ("integration:cloudflare", "Cloudflare Workers", "integration", "Workers + R2 free hosting"),
    "workers": ("integration:cloudflare", "Cloudflare Workers", "integration", "Workers + R2 free hosting"),
    "r2": ("integration:cloudflare", "Cloudflare Workers", "integration", "R2 storage"),
    "chase": ("integration:chase", "Chase", "integration", "Chase Southwest + routing"),
    "schwab": ("integration:schwab", "Schwab", "integration", "Schwab brokerage holdings (META/VOO)"),
    "usaa": ("integration:usaa", "USAA", "integration", "USAA cash hub Classic + savings"),
    # goal linking SOTA — First $1k/mo passive
    "first $1k": ("concept:first-1k-mrr", "First $1k/mo passive goal", "business_metric", "$1k MRR sustained, 7-13 customers @ $79-149/mo"),
    "1k/mo passive": ("concept:first-1k-mrr", "First $1k/mo passive goal", "business_metric", "$1k MRR sustained"),
    "revenue tracker": ("concept:revenue-tracker", "Turnover Shield Revenue Tracker", "business_metric", "MRR tracker via crons weekly Friday trials/paid/MRR/churn%"),
    "mrr tracker": ("concept:revenue-tracker", "Turnover Shield Revenue Tracker", "business_metric", "Weekly MRR check Friday 9am"),
    "passive income": ("concept:passive-income", "Passive Income Web App", "product", "Self-sustaining web app for passive income — Turnover Shield Pick"),
    "trade crew": ("concept:trade-crew", "Trade Crew (Plumbing/Electrical/HVAC)", "business_metric", "Boring B2B vertical for Turnover Shield"),
    "goal_76da7701": ("concept:first-1k-mrr", "First $1k/mo passive goal", "business_metric", "Goal ID goal_76da7701a682 — pricing $79-149/mo"),
    # products
    "turnover shield": ("concept:turnover-shield", "Turnover Shield", "product", "Boring B2B SaaS $79-149/mo churn prediction for trade crews, aiming $1k MRR = 7-13 customers"),
    "turnover": ("concept:turnover-shield", "Turnover Shield", "product", "Churn prediction for trade crews"),
    "retention playbook": ("concept:retention-playbook", "Retention Playbook", "product_feature", "Actionable steps to keep tech when churn risk high"),
    "churn prediction": ("concept:churn-prediction", "Churn Prediction", "ml_feature", "Predict which plumber/electrician tech will leave"),
    "family brain": ("concept:family-brain", "Davis Family Brain", "product", "V9 Household OS client-only localStorage + Plaid $11k burn tracking"),
    "davis family brain": ("concept:family-brain", "Davis Family Brain", "product", "Household OS"),
    # business metrics
    "mrr": ("concept:mrr", "MRR / Paid Users", "business_metric", "Target $1k MRR, pricing $79-149, ROI saving 1 tech = $5k hiring cost"),
    "arr": ("concept:arr", "ARR", "business_metric", "Annual recurring"),
    "burn rate": ("concept:burn-rate", "Burn Rate $11k/mo", "business_metric", "$11k joint burn, 21mo runway, EF 206% $136k"),
    # ml concepts
    "mtNN": ("concept:mtnn", "MTNN v5_concat_b2_h160_t32_d48_mlp128", "ml_concept", "Multi-Task Neural Net 120 feats 17 families cat([x·m,m]) masking 544+12→128→48 L2"),
    "mtnn": ("concept:mtnn", "MTNN v5_concat_b2_h160_t32_d48_mlp128", "ml_concept", "MTNN architecture 12,966 seasons vector-hoops"),
    "mtNN v4": ("concept:mtnn", "MTNN v5_concat_b2_h160_t32_d48_mlp128", "ml_concept", "MTNN"),
    "ava": ("concept:ava", "Ava AGI Factory v6.4", "ml_concept", "Real-mode Jacobian 4 J-Spaces S1 Fast hl8 S2 Slow hl300 Critic hl30 Planner hl150 Router/veto local Docker CUDA"),
    "j-space": ("concept:jspace", "Ava J-Space Multi (S1 hl8 S2 hl300 Critic hl30 Planner hl150)", "ml_concept", "4 workspaces multi-space Jacobian"),
    "jspace": ("concept:jspace", "Ava J-Space Multi", "ml_concept", "Multi-space"),
    "s1 fast": ("concept:s1-fast", "Ava S1 Fast hl8", "ml_concept", "Fast system hl8 32"),
    "s2 slow": ("concept:s2-slow", "Ava S2 Slow hl300", "ml_concept", "Slow system hl300 64"),
    "critic": ("concept:critic", "Ava Critic hl30", "ml_concept", "Critic hl30 16"),
    "planner": ("concept:planner", "Ava Planner hl150", "ml_concept", "Planner hl150 32"),
    "vector hoops": ("concept:vector-hoops", "Vector Hoops 12,966 seasons", "product", "Daily NBA chimera 12,966 player-seasons PCA 3 8 archetypes MTNN CQS 85.87"),
    "vector pitch": ("concept:vector-pitch", "Vector Pitch 633 WC tournaments", "product", "World Cup chimera 633 player-tournaments StatsBomb per-90"),
    "vector gridiron": ("concept:vector-gridiron", "Vector Gridiron Fantasy", "product", "Fantasy cockpit MAE 4.268 R²0.39"),
    "dumbmodel": ("concept:dumbmodel", "dumbmodel.com ecosystem", "product", "hoops/pitch/gridiron + jcamd.com hub Vercel static"),
    "dinov3": ("concept:tennis-dinov3", "Tennis DINOv3 ExecuTorch", "product", "Serve coach DINOv3 + ConvNeXt-Tiny distilled XNNPACK"),
    "tennis": ("concept:tennis-dinov3", "Tennis DINOv3", "product", "Digital line judge baseline"),
    "graphify": ("concept:graphify", "Personal Graphify", "tool", "Ollama-first local graphify fork with task/impact/onboard"),
    "ollama": ("concept:ollama", "Ollama qwen3:32b local", "tool", "Local LLM judge for frontier rubric 11-cat"),
    "workforce embedding": ("concept:workforce-embedding", "Workforce Embedding 120d + 4 heads", "ml_feature", "120 days of turnover signals + 4 tower heads from Passive Lab research"),
    "120d + 4 heads": ("concept:workforce-embedding", "Workforce Embedding 120d + 4 heads", "ml_feature", "Trade crew embedding"),
    # Scout control plane (ex-BigBang) — agent-native HOME-only
    "scout cli": ("concept:scout", "Scout CLI", "tool", "Personal control plane (ex-BigBang): Ava brain + authentic writing + lab MRR + RTX offload"),
    "scout-cli": ("concept:scout", "Scout CLI", "tool", "Personal control plane agent-native security-first"),
    "scout": ("concept:scout", "Scout CLI", "tool", "HOME-only personal control plane wiring Ava + lab + RTX"),
    "bigbang": ("concept:scout", "Scout CLI (ex-BigBang)", "tool", "Renamed personal control plane"),
    "rtx offload": ("concept:rtx-offload", "RTX Offload", "tool", "Local GPU offload path used by Scout/Ava"),
    "jcamd.com": ("concept:jcamd", "jcamd.com hub", "product", "Workforce intelligence consulting + Lab + public Personal Graphify"),
}

#: Extensions whose files get a `doc:` node (extract_markdown); everything else gets a
#: `file:` node. Single source of truth shared with extract_file's dispatch below so the two
#: never drift — a mismatch dangled every ecosystem/goal/pattern edge off a phantom `file:`
#: node for markdown docs, so e.g. a .md/.rst note in 01_Finance was never linked to
#: ecosystem:finance (edges hard-coded `file:` or special-cased only `.md`).
_DOC_NODE_EXTS = (".md", ".mdx", ".mdc", ".txt", ".rst", ".qmd")


def extract_personal_patterns(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    nodes, edges = [], []
    fp_str = str(file_path)
    # This file's canonical node id, matching what extract_file created for it (doc: for a
    # markdown-family file, file: otherwise). Used for EVERY edge below.
    file_id = f"doc:{file_path}" if file_path.suffix.lower() in _DOC_NODE_EXTS else f"file:{file_path}"
    # ecosystem domain mapping
    parts = file_path.parts
    if "01_Finance" in parts:
        nid = "ecosystem:finance"
        if not any(n["id"]==nid for n in nodes):
            nodes.append({"id": nid, "label": "01_Finance - Davis Family Brain & FIRE $50", "type": "ecosystem_domain", "desc": "Family finance $2.25M vested + $11k burn FIRE 50"})
        edges.append({"source": file_id, "target": nid, "type": "belongs_to", "confidence": INFERRED})
    if "02_Passive_Lab" in parts:
        nid = "ecosystem:passive_lab"
        if not any(n["id"]==nid for n in nodes):
            nodes.append({"id": nid, "label": "02_Passive_Lab - Turnover Shield + 10 boring B2B", "type": "ecosystem_domain", "desc": "Top 10 boring SaaS $79-149/mo, aiming first $1k/mo"})
        edges.append({"source": file_id, "target": nid, "type": "belongs_to", "confidence": INFERRED})
    if "04_Tennis_DINOv3" in parts or "tennis" in fp_str.lower():
        nid = "ecosystem:tennis"
        nodes.append({"id": nid, "label": "04_Tennis_DINOv3 ExecuTorch", "type": "ecosystem_domain"})
        edges.append({"source": file_id, "target": nid, "type": "belongs_to", "confidence": INFERRED})
    # SOTA goal linking: first-1k-mo-passive and self-sustaining app projects
    fp_lower = fp_str.lower()
    if "first-1k-mo-passive" in fp_lower or "first_1k" in fp_lower or "goal_76da7701" in fp_lower:
        nid = "ecosystem:goal-first-1k"
        if not any(n["id"]==nid for n in nodes):
            nodes.append({"id": nid, "label": "Goal: First $1k/mo passive — Turnover Shield", "type": "ecosystem_domain", "desc": "Outcome $1k MRR sustained, 7-13 customers @ $79-149/mo, pricing vs competitors, weekly tracking trials/paid/MRR/churn"})
        edges.append({"source": file_id, "target": nid, "type": "belongs_to", "confidence": INFERRED})
        # also link file directly to core product nodes
        edges.append({"source": file_id, "target": "concept:turnover-shield", "type": "tracks", "confidence": INFERRED})
        edges.append({"source": file_id, "target": "concept:first-1k-mrr", "type": "tracks", "confidence": INFERRED})
        edges.append({"source": file_id, "target": "concept:revenue-tracker", "type": "implements", "confidence": INFERRED})
    if "build-a-self-sustaining-web-app-for-passive-income" in fp_lower or "passive-income" in fp_lower:
        nid2 = "ecosystem:goal-passive-app"
        if not any(n["id"]==nid2 for n in nodes):
            nodes.append({"id": nid2, "label": "Goal: Build self-sustaining web app for passive income", "type": "ecosystem_domain", "desc": "Start small grow long-term, deep market research niche, no ongoing input"})
        edges.append({"source": file_id, "target": nid2, "type": "belongs_to", "confidence": INFERRED})

    # text pattern matching - lower + keep case for mtNN
    try:
        src = file_path.read_text(encoding="utf-8", errors="ignore")
        low = src.lower()

        for key, vals in PERSONAL_PATTERNS.items():
            # vals may be 3 or 4 tuple
            if len(vals) == 3:
                nid, label, typ = vals
                desc = ""
            else:
                nid, label, typ, desc = vals
            if key.lower() in low or key in src:  # exact case for mtNN
                node_data = {"id": nid, "label": label, "type": typ}
                if desc:
                    node_data["desc"] = desc
                # dedup
                if not any(n["id"]==nid for n in nodes):
                    nodes.append(node_data)
                edges.append({"source": file_id, "target": nid, "type": "uses", "confidence": INFERRED, "meta": {"pattern": key}})

        # special multi-pattern flows: if both Stripe + MRR present → edge Stripe --enables--> MRR
        if "stripe" in low and "mrr" in low:
            edges.append({"source": "integration:stripe", "target": "concept:mrr", "type": "enables", "confidence": INFERRED})
        if "plaid" in low and ("burn" in low or "family brain" in low):
            edges.append({"source": "integration:plaid", "target": "concept:family-brain", "type": "feeds", "confidence": INFERRED})
        if "turnover" in low and "churn" in low:
            edges.append({"source": "concept:turnover-shield", "target": "concept:churn-prediction", "type": "contains", "confidence": INFERRED})
        if "churn" in low and "retention" in low:
            edges.append({"source": "concept:churn-prediction", "target": "concept:retention-playbook", "type": "triggers", "confidence": INFERRED})
        if "first $1k" in low or "first 1k" in low or "1k/mo" in low or "revenue tracker" in low or "goal_76da7701" in low:
            edges.append({"source": "concept:turnover-shield", "target": "concept:first-1k-mrr", "type": "enables", "confidence": INFERRED})
            edges.append({"source": "concept:mrr", "target": "concept:first-1k-mrr", "type": "feeds", "confidence": INFERRED})
            edges.append({"source": "concept:revenue-tracker", "target": "concept:first-1k-mrr", "type": "tracks", "confidence": INFERRED})
            edges.append({"source": "concept:passive-income", "target": "concept:turnover-shield", "type": "contains", "confidence": INFERRED})
        if "48→64" in src or "48->64" in src or "hl=" in low or "mtNN" in src:
            nodes.append({"id": "concept:mtnn-head", "label": "MTNN head 48→64→k tower arch", "type": "ml_concept", "desc": "48→64→k from Vector Hoops truthful MTNN"})
            edges.append({"source": file_id, "target": "concept:mtnn-head", "type": "uses", "confidence": INFERRED})
        # Scout ↔ Ava / lab / graphify bridges
        if ("scout" in low or "bigbang" in low) and "ava" in low:
            edges.append({"source": "concept:scout", "target": "concept:ava", "type": "orchestrates", "confidence": INFERRED})
        if ("scout" in low or "bigbang" in low) and ("mrr" in low or "turnover" in low):
            edges.append({"source": "concept:scout", "target": "concept:turnover-shield", "type": "tracks", "confidence": INFERRED})
            edges.append({"source": "concept:scout", "target": "concept:mrr", "type": "tracks", "confidence": INFERRED})
        if ("scout" in low or "bigbang" in low) and "graphify" in low:
            edges.append({"source": "concept:scout", "target": "concept:graphify", "type": "uses", "confidence": INFERRED})
        if "ava" in low and ("j-space" in low or "jspace" in low or "planner" in low) and "critic" in low:
            edges.append({"source": "concept:planner", "target": "concept:critic", "type": "interacts_with", "confidence": INFERRED})
            edges.append({"source": "concept:ava", "target": "concept:jspace", "type": "contains", "confidence": INFERRED})

    except Exception as e:
        # silent
        pass

    return nodes, edges

def extract_file(file_path: Path) -> Tuple[List[Dict], List[Dict]]:
    suffix = file_path.suffix.lower()
    nodes, edges = [], []
    if suffix == ".py":
        n, e = extract_python(file_path)
        nodes.extend(n); edges.extend(e)
    elif suffix in (".js",".ts",".jsx",".tsx",".mjs",".mts",".cts",".vue",".svelte"):
        n, e = extract_js_generic(file_path)
        nodes.extend(n); edges.extend(e)
    elif suffix in _DOC_NODE_EXTS:
        n, e = extract_markdown(file_path)
        nodes.extend(n); edges.extend(e)
    else:
        # generic file node for other code types
        file_node_id = f"file:{file_path}"
        nodes.append({"id": file_node_id, "label": file_path.name, "type": "file", "file": str(file_path), "full_path": str(file_path)})

    # personal patterns always (even for code) — SOTA for Davis family
    n2, e2 = extract_personal_patterns(file_path)
    nodes.extend(n2); edges.extend(e2)

    # dedup nodes by id keeping richest
    seen = {}
    dedup_nodes = []
    for n in nodes:
        nid = n["id"]
        if nid not in seen:
            seen[nid]=n
            dedup_nodes.append(n)
        else:
            # merge: keep longer label/desc
            existing = seen[nid]
            if len(n.get("label","")) > len(existing.get("label","")):
                existing["label"] = n["label"]
            if n.get("desc") and not existing.get("desc"):
                existing["desc"] = n["desc"]

    return dedup_nodes, edges

def _merge_pool(pool) -> Tuple[List[Dict], List[Dict]]:
    """Merge per-file (nodes, edges) pairs: dedup nodes by id, edges by (source, target, type)."""
    all_nodes: List[Dict] = []
    all_edges: List[Dict] = []
    id_seen = set()
    for nodes, edges in pool:
        for n in nodes:
            if n["id"] not in id_seen:
                id_seen.add(n["id"])
                all_nodes.append(n)
        all_edges.extend(edges)
    edge_seen = set()
    dedup_edges = []
    for e in all_edges:
        key = (e["source"], e["target"], e["type"])
        if key not in edge_seen:
            edge_seen.add(key)
            dedup_edges.append(e)
    return all_nodes, dedup_edges


def extract_all(files: List[Path]) -> Tuple[List[Dict], List[Dict]]:
    return _merge_pool(extract_file(fp) for fp in files)


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_with_cache(files: List[Path], cache_path: Path, update: bool = False) -> Tuple[List[Dict], List[Dict], Dict]:
    """Incremental extraction backed by a content-hash cache.

    cache_path (graphify-out/cache/extract.json) maps path → {mtime, md5, nodes, edges}.
    On update=True, unchanged files (same mtime, or same md5 when only mtime moved) reuse
    their cached extraction; changed/new files are re-extracted. The graph is ALWAYS
    rebuilt from the full merged pool, so the output never mixes stale topology.
    Returns (nodes, edges, stats) with real reused/re-extracted counters.
    """
    import json as _json

    cache: Dict[str, Dict] = {}
    if update and cache_path.exists():
        try:
            cache = _json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    new_cache: Dict[str, Dict] = {}
    pool: List[Tuple[List[Dict], List[Dict]]] = []
    reused = 0
    re_extracted = 0
    for fp in files:
        key = str(fp)
        try:
            mtime = fp.stat().st_mtime
        except OSError:
            continue
        entry = cache.get(key)
        md5 = None
        if entry is not None:
            if entry.get("mtime") == mtime:
                pool.append((entry.get("nodes", []), entry.get("edges", [])))
                new_cache[key] = entry
                reused += 1
                continue
            md5 = file_md5(fp)
            if entry.get("md5") == md5:
                # touched but content-identical — refresh mtime, reuse extraction
                entry = {**entry, "mtime": mtime}
                pool.append((entry.get("nodes", []), entry.get("edges", [])))
                new_cache[key] = entry
                reused += 1
                continue
        nodes, edges = extract_file(fp)
        if md5 is None:
            try:
                md5 = file_md5(fp)
            except OSError:
                md5 = ""
        new_cache[key] = {"mtime": mtime, "md5": md5, "nodes": nodes, "edges": edges}
        pool.append((nodes, edges))
        re_extracted += 1

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(_json.dumps(new_cache), encoding="utf-8")
    except OSError:
        pass  # cache is an optimization, never a build failure

    all_nodes, all_edges = _merge_pool(pool)
    stats = {"files": len(files), "reused": reused, "re_extracted": re_extracted}
    return all_nodes, all_edges, stats
