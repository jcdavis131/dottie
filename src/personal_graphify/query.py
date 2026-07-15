"""
query.py — query/path/explain/impact/task/onboard against graph.json
SOTA for agents: hybrid lexical + structural ranking, impact graph, task compiler
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import networkx as nx
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import re
from collections import Counter, defaultdict

def load_graph_json(path: Path) -> nx.MultiDiGraph:
    data = json.loads(path.read_text(encoding="utf-8"))
    G = nx.MultiDiGraph()
    for n in data.get("nodes", []):
        nid = n.get("id")
        if not nid:
            continue
        G.add_node(nid, **n)
    for e in data.get("edges", []):
        src = e.get("source"); tgt = e.get("target")
        if not src or not tgt:
            continue
        # skip if nodes missing (old graph)
        if src not in G or tgt not in G:
            # still add missing as placeholder? skip for now
            if src not in G:
                G.add_node(src, label=src, type="unknown")
            if tgt not in G:
                G.add_node(tgt, label=tgt, type="unknown")
        attrs = {k:v for k,v in e.items() if k not in ("source","target")}
        G.add_edge(src, tgt, **attrs)
    return G

# Stopwords that pollute concept extraction (single char / or etc)
STOP_LABELS = {"or","and","the","a","an","of","in","to","for","with","on","is","are","be","or:"}

def _tokenize(s: str) -> List[str]:
    return [t.lower() for t in re.split(r"[^a-z0-9→_]+", s.lower()) if len(t)>=2 and t not in STOP_LABELS]

def search_nodes(G: nx.MultiDiGraph, query: str, limit: int = 30, boost_file_type: str = None) -> List[Dict]:
    qlower = query.lower()
    terms = _tokenize(query)
    if not terms:
        terms = [qlower]
    qset = set(terms)

    results = []
    for nid, data in G.nodes(data=True):
        label = str(data.get("label",""))
        typ = str(data.get("type",""))
        file_ = str(data.get("file",""))
        nid_l = nid.lower()
        blob = f"{label} {typ} {file_} {nid_l}".lower()
        # lexical score
        score = 0
        # exact phrase boost
        if qlower in blob:
            score += 20
        # term overlap
        matched = 0
        for t in terms:
            if t in blob:
                matched += 1
        if matched == 0:
            # fuzzy: check if any term is substring of label tokens
            continue
        score += matched * 3
        # boost if term in label vs file
        label_l = label.lower()
        if any(t in label_l for t in terms):
            score += 5
        # structural boosts
        deg = G.degree(nid)
        score += min(deg/10.0, 3.0)  # god nodes slight boost
        # type boosts for agents: prefer file, function, class, product over generic ref
        type_boost = {
            "file": 1.5, "function": 2.0, "class": 2.0, "module": 0.5,
            "product": 2.5, "ml_concept": 2.0, "integration": 1.8,
            "business_metric": 1.5, "tool": 1.2, "ecosystem_domain": 1.0
        }
        score += type_boost.get(typ, 0)
        # file type filter boost
        if boost_file_type and boost_file_type.lower() in file_.lower():
            score += 2
        # community diversity later
        results.append((score, deg, nid, data, matched))

    # sort by score, then degree, then matched
    results.sort(key=lambda x: (x[0], x[1], x[4]), reverse=True)
    # deduplicate by label for cleaner top list, but keep id mapping
    seen_labels = set()
    deduped = []
    for score, deg, nid, data, matched in results:
        # allow same label different file to pass if file differs
        key = (data.get("label","").lower(), data.get("file",""))
        if key in seen_labels and len(deduped) > 10:
            # still allow if high score
            if score < 15:
                continue
        seen_labels.add(key)
        deduped.append({"id": nid, **data, "score": round(score,2), "matched_terms": matched, "degree": deg})
        if len(deduped) >= limit*2:
            break

    return deduped[:limit]

def subgraph_for_query(G: nx.MultiDiGraph, query: str, hops: int = 2, limit_nodes: int = 60, include_rationale: bool = True) -> nx.MultiDiGraph:
    matches = search_nodes(G, query, limit=8)
    if not matches:
        return G.subgraph([]).copy()
    # BFS from matches, weighted by confidence
    frontier = [m["id"] for m in matches if m["id"] in G]
    visited = set(frontier)
    # include rationale nodes directly attached to frontier
    if include_rationale:
        for nid in list(frontier):
            for _, nbr, edata in G.out_edges(nid, data=True):
                if G.nodes[nbr].get("type") == "rationale":
                    visited.add(nbr)
            for src, _, edata in G.in_edges(nid, data=True):
                if G.nodes[src].get("type") == "rationale":
                    visited.add(src)

    for _ in range(hops):
        new_frontier = []
        for node in frontier:
            # successors - prefer EXTRACTED edges
            for _, nbr, edata in G.out_edges(node, data=True):
                if nbr not in visited:
                    # filter trivial refs if too many
                    if G.nodes[nbr].get("type") == "reference" and len(visited) > 40:
                        continue
                    visited.add(nbr)
                    new_frontier.append(nbr)
            for src, _, edata in G.in_edges(node, data=True):
                if src not in visited:
                    visited.add(src)
                    new_frontier.append(src)
        frontier = new_frontier
        if len(visited) >= limit_nodes:
            break

    visited_list = list(visited)[:limit_nodes]
    sub = G.subgraph(visited_list).copy()
    return sub

def shortest_path(G: nx.MultiDiGraph, source_q: str, target_q: str, max_hops: int = 6) -> Optional[List[str]]:
    src_candidates = search_nodes(G, source_q, limit=3)
    tgt_candidates = search_nodes(G, target_q, limit=3)
    if not src_candidates or not tgt_candidates:
        return None
    # try combos
    UG = nx.Graph(G)  # undirected for path
    for s in src_candidates[:2]:
        for t in tgt_candidates[:2]:
            src = s["id"]; tgt = t["id"]
            if src not in UG or tgt not in UG:
                continue
            try:
                path = nx.shortest_path(UG, source=src, target=tgt)
                if len(path)-1 <= max_hops:
                    return path
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
    return None

def explain_node(G: nx.MultiDiGraph, query: str, include_code_snippet: bool = False) -> Optional[Dict]:
    matches = search_nodes(G, query, limit=1)
    if not matches:
        return None
    nid = matches[0]["id"]
    data = G.nodes[nid]
    neighbors_out = []
    neighbors_in = []
    for _, neigh, edata in G.out_edges(nid, data=True):
        nd = G.nodes.get(neigh, {"label": neigh})
        neighbors_out.append({
            "id": neigh,
            "label": nd.get("label"),
            "type": nd.get("type"),
            "file": nd.get("file",""),
            "edge_type": edata.get("type"),
            "confidence": edata.get("confidence"),
            "direction": "out"
        })
    for src, _, edata in G.in_edges(nid, data=True):
        nd = G.nodes.get(src, {"label": src})
        neighbors_in.append({
            "id": src,
            "label": nd.get("label"),
            "type": nd.get("type"),
            "file": nd.get("file",""),
            "edge_type": edata.get("type"),
            "confidence": edata.get("confidence"),
            "direction": "in"
        })
    # sort neighbors by confidence EXTRACTED first, then degree
    def conf_rank(c):
        return 0 if c=="EXTRACTED" else 1 if c=="INFERRED" else 2
    neighbors_out.sort(key=lambda x: (conf_rank(x["confidence"]), -G.degree(x["id"]) if x["id"] in G else 0))
    neighbors_in.sort(key=lambda x: (conf_rank(x["confidence"]), -G.degree(x["id"]) if x["id"] in G else 0))

    # try to read code snippet if file exists
    snippet = None
    if include_code_snippet:
        fpath = data.get("file")
        if fpath:
            p = Path(fpath)
            # attempt to resolve relative to cwd
            if not p.exists():
                # try personal-graphify path
                cand = Path("personal-graphify") / p
                if cand.exists():
                    p = cand
            if p.exists() and p.is_file():
                try:
                    lines = p.read_text(errors="ignore").splitlines()
                    line = data.get("line", 0)
                    if line and line>0:
                        start = max(0, line-5)
                        end = min(len(lines), line+15)
                        snippet = "\n".join(lines[start:end])
                except:
                    pass

    return {
        "node": {"id": nid, **data},
        "neighbors_out": neighbors_out[:40],
        "neighbors_in": neighbors_in[:40],
        "degree": G.degree(nid),
        "community": data.get("community", -1),
        "snippet": snippet
    }

def impact_analysis(G: nx.MultiDiGraph, query: str, direction: str = "both", depth: int = 3, limit: int = 80) -> Dict:
    """
    What breaks if you change this node? BFS downstream impact + upstream dependencies.
    direction: downstream = what this affects, upstream = what it depends on, both = both
    """
    matches = search_nodes(G, query, limit=1)
    if not matches:
        return {"error": f"Node '{query}' not found"}
    root_id = matches[0]["id"]
    impacted = {"downstream": [], "upstream": []}
    visited = set([root_id])

    if direction in ("downstream","both"):
        frontier = [root_id]
        for d in range(depth):
            nf = []
            for nid in frontier:
                for _, nbr, edata in G.out_edges(nid, data=True):
                    if nbr not in visited:
                        visited.add(nbr)
                        impacted["downstream"].append({
                            "id": nbr,
                            "label": G.nodes[nbr].get("label"),
                            "type": G.nodes[nbr].get("type"),
                            "file": G.nodes[nbr].get("file",""),
                            "edge_type": edata.get("type"),
                            "confidence": edata.get("confidence"),
                            "depth": d+1
                        })
                        nf.append(nbr)
            frontier = nf

    visited_up = set([root_id])
    if direction in ("upstream","both"):
        frontier = [root_id]
        for d in range(depth):
            nf = []
            for nid in frontier:
                for src, _, edata in G.in_edges(nid, data=True):
                    if src not in visited_up:
                        visited_up.add(src)
                        impacted["upstream"].append({
                            "id": src,
                            "label": G.nodes[src].get("label"),
                            "type": G.nodes[src].get("type"),
                            "file": G.nodes[src].get("file",""),
                            "edge_type": edata.get("type"),
                            "confidence": edata.get("confidence"),
                            "depth": d+1
                        })
                        nf.append(src)
            frontier = nf

    # sort by depth then confidence
    for k in impacted:
        impacted[k] = sorted(impacted[k], key=lambda x: (x["depth"], 0 if x["confidence"]=="EXTRACTED" else 1))[:limit]

    # file-level summary for agent action
    downstream_files = Counter([x["file"] for x in impacted["downstream"] if x["file"]])
    upstream_files = Counter([x["file"] for x in impacted["upstream"] if x["file"]])

    return {
        "root": matches[0],
        "downstream": impacted["downstream"],
        "upstream": impacted["upstream"],
        "downstream_files": [{"file": f, "count": c} for f,c in downstream_files.most_common(15)],
        "upstream_files": [{"file": f, "count": c} for f,c in upstream_files.most_common(15)],
        "summary": f"Changing '{matches[0].get('label')}' affects {len(impacted['downstream'])} downstream nodes in {len(downstream_files)} files, depends on {len(impacted['upstream'])} upstream nodes in {len(upstream_files)} files"
    }

def task_compiler(G: nx.MultiDiGraph, task_description: str) -> Dict:
    """
    Given a natural language task, produce minimal subgraph + file list + action plan.
    SOTA for agents: instead of reading whole repo, get targeted context.
    """
    # extract entities from task
    entities = _tokenize(task_description)
    # boost detection for personal ecosystem
    personal_boosts = {
        "turnover": "Turnover Shield",
        "retention": "Turnover Shield",
        "stripe": "Stripe",
        "mrr": "MRR / Paid Users",
        "plaid": "Plaid",
        "family": "Davis Family Brain",
        "brain": "Davis Family Brain",
        "churn": "Turnover Shield",
        "mtNN": "MTNN",
        "ava": "Ava AGI Factory v6.4",
        "vector": "Vector Hoops",
        "dino": "Tennis DINOv3 ExecuTorch"
    }
    boosted_queries = []
    for token in entities:
        if token in personal_boosts:
            boosted_queries.append(personal_boosts[token])

    # search for each entity
    all_matches = []
    for q in set(entities + boosted_queries):
        if len(q) < 3:
            continue
        matches = search_nodes(G, q, limit=3)
        all_matches.extend(matches)

    # deduplicate and rank
    by_id = {}
    for m in all_matches:
        if m["id"] not in by_id or m["score"] > by_id[m["id"]]["score"]:
            by_id[m["id"]] = m
    ranked = sorted(by_id.values(), key=lambda x: x["score"], reverse=True)[:10]

    if not ranked:
        return {"error": f"No relevant nodes for task '{task_description}'", "suggestion": "Try broader terms: Stripe, Turnover Shield, Family Brain, MTNN, Ava"}

    # build combined subgraph from top matches
    all_ids = set([m["id"] for m in ranked])
    sub_nodes = set()
    for nid in all_ids:
        if nid not in G:
            continue
        sub_nodes.add(nid)
        # add 1-hop neighbors that are code files or product concepts
        for _, nbr, _ in G.out_edges(nid, data=True):
            if G.nodes[nbr].get("type") in ("file","function","class","product","integration","ml_concept"):
                sub_nodes.add(nbr)
        for src, _, _ in G.in_edges(nid, data=True):
            if G.nodes[src].get("type") in ("file","function","class"):
                sub_nodes.add(src)

    sub = G.subgraph(list(sub_nodes)[:80]).copy()

    # file list prioritized
    files_counter = Counter()
    for _, data in sub.nodes(data=True):
        f = data.get("file")
        if f:
            files_counter[f] += 1 + (data.get("degree",0)/10)

    files_ranked = [ {"file": f, "relevance": round(c,1)} for f,c in files_counter.most_common(15)]

    # generate action plan
    # simple heuristic based on task verbs
    task_lower = task_description.lower()
    plan = []
    if any(w in task_lower for w in ["add","create","implement"]):
        plan.append(f"1. Read GRAPH_REPORT.md god nodes + {len(files_ranked)} relevant files first")
        plan.append(f"2. Query specific: pgraphify query \"{task_description[:60]}\"")
        plan.append("3. Edit files in order of relevance (lowest dependency first): check upstream graph")
        plan.append("4. Run pgraphify impact on changed nodes")
        plan.append("5. Test + rebuild graph: pgraphify . --out graphify-out")
    elif any(w in task_lower for w in ["fix","bug","debug"]):
        plan.append(f"1. Explain root cause: pgraphify explain \"{ranked[0].get('label')}\"")
        plan.append(f"2. Impact check: pgraphify impact \"{ranked[0].get('label')}\" --direction both")
        plan.append("3. Edit minimal files")
        plan.append("4. Verify no downstream breakage")
    elif any(w in task_lower for w in ["refactor","move","rename"]):
        plan.append(f"1. Path analysis: pgraphify path \"{ranked[0].get('label')}\" \"{ranked[-1].get('label')}\" if 2 concepts")
        plan.append("2. Impact downstream for all affected files")
        plan.append("3. Refactor in steps, commit graph.json each time")
    else:
        plan.append("1. Query graph for context")
        plan.append("2. Explain top nodes")
        plan.append("3. Check impact")
        plan.append("4. Edit + rebuild graph")

    # token estimate savings
    naive_tokens = G.number_of_nodes()*50
    scoped_tokens = sub.number_of_nodes()*25
    reduction = round(naive_tokens / max(scoped_tokens,1), 1)

    return {
        "task": task_description,
        "top_matches": [{"label": m.get("label"), "type": m.get("type"), "file": m.get("file",""), "score": m.get("score")} for m in ranked[:10]],
        "subgraph": {"nodes": sub.number_of_nodes(), "edges": sub.number_of_edges()},
        "files": files_ranked,
        "plan": plan,
        "token_estimate": {"naive": naive_tokens, "scoped": scoped_tokens, "reduction_x": reduction},
        "copy_paste_context": f"Task: {task_description}\nTop files: {', '.join([f['file'] for f in files_ranked[:5]])}\nGod nodes to check: see graphify-out/GRAPH_REPORT.md\nRelevant query: pgraphify query \"{task_description}\""
    }

def onboard_report(G: nx.MultiDiGraph, top_n_god: int = 10) -> Dict:
    """
    Senior-dev onboarding: god nodes, surprises, hot paths, entry points, suggested questions
    """
    # god nodes by degree
    degs = [(nid, G.degree(nid), G.nodes[nid]) for nid in G.nodes]
    degs.sort(key=lambda x: x[1], reverse=True)
    god = [{"id": nid, "label": d.get("label"), "type": d.get("type"), "file": d.get("file",""), "degree": deg} for nid, deg, d in degs[:top_n_god]]

    # communities
    comm_counts = Counter([G.nodes[n].get("community",-1) for n in G.nodes])
    comm_summary = [{"community": c, "size": s} for c,s in comm_counts.most_common(10)]

    # file hotspots
    file_deg = Counter()
    for _, data in G.nodes(data=True):
        f = data.get("file")
        if f:
            file_deg[f] += data.get("degree", G.degree(data.get("id","")) if "id" in data else 0)
    hot_files = [{"file": f, "score": round(s,1)} for f,s in file_deg.most_common(15)]

    # entry points: files with high out-degree but low in-degree (sources)
    entry_points = []
    for nid, data in G.nodes(data=True):
        if data.get("type") == "file":
            out_d = G.out_degree(nid)
            in_d = G.in_degree(nid)
            if out_d > 5 and out_d > in_d*2:
                entry_points.append({"file": data.get("label"), "out": out_d, "in": in_d})
    entry_points = sorted(entry_points, key=lambda x: x["out"], reverse=True)[:10]

    # suggested questions based on god nodes + product nodes
    suggestions = []
    product_nodes = [d for _, d in G.nodes(data=True) if d.get("type") in ("product","ml_concept","integration")]
    for p in product_nodes[:5]:
        suggestions.append(f"Where is {p.get('label')} implemented?")
    for g in god[:3]:
        suggestions.append(f"What depends on {g.get('label')}?")
    suggestions.extend([
        "How does Stripe webhook connect to MRR dashboard?",
        "Trace Turnover Shield retention playbook",
        "Explain Ava S2 Slow vs Planner broadcast",
        "What is the impact of changing Family Brain Plaid hub?"
    ])

    return {
        "god_nodes": god,
        "communities": comm_summary,
        "hot_files": hot_files,
        "entry_points": entry_points,
        "suggested_questions": suggestions[:12],
        "meta": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "communities": len(comm_counts)}
    }

# -- formatting for CLI --

def format_query_answer(G: nx.MultiDiGraph, query: str) -> str:
    sub = subgraph_for_query(G, query)
    if sub.number_of_nodes()==0:
        return f"No nodes found for query '{query}'. Try broader terms: Stripe, Turnover Shield, MTNN, Ava, Family Brain, Vector Hoops"
    lines = [f"Query: '{query}' — {sub.number_of_nodes()} nodes, {sub.number_of_edges()} edges in scoped subgraph (token-est ~{sub.number_of_nodes()*25} vs naive ~{G.number_of_nodes()*50} = {round(G.number_of_nodes()*50 / max(sub.number_of_nodes()*25,1),1)}x reduction)"]
    lines.append("")
    lines.append("Top matches:")
    # search_nodes already ranked
    for m in search_nodes(G, query, limit=12):
        lines.append(f"- {m.get('label')} ({m.get('type')}) in {m.get('file','')} [comm {m.get('community',0)}] deg {m.get('degree',0)} score {m.get('score')}")

    lines.append("")
    lines.append("Edges (sample):")
    for u,v,d in list(sub.edges(data=True))[:20]:
        src_label = G.nodes[u].get("label",u)[:50]
        tgt_label = G.nodes[v].get("label",v)[:50]
        lines.append(f"  {src_label} --{d.get('type')} [{d.get('confidence')}]--> {tgt_label}")

    # add rationale hints
    rationale_nodes = [nid for nid,d in sub.nodes(data=True) if d.get("type")=="rationale"]
    if rationale_nodes:
        lines.append("")
        lines.append(f"Rationale found: {len(rationale_nodes)} WHY/NOTE nodes — check explain")

    return "\n".join(lines)

def format_path_answer(G: nx.MultiDiGraph, src_q: str, tgt_q: str) -> str:
    path = shortest_path(G, src_q, tgt_q)
    if not path:
        return f"No path found between '{src_q}' and '{tgt_q}' (tried top-3 matches each, max 6 hops)."
    lines = [f"Shortest path {len(path)-1} hops between '{src_q}' and '{tgt_q}':", ""]
    for i in range(len(path)-1):
        u = path[i]; v = path[i+1]
        # find edge data (first)
        edata = {}
        if G.has_edge(u,v):
            edges = list(G.get_edge_data(u,v).values())
            edata = edges[0] if edges else {}
        elif G.has_edge(v,u):
            edges = list(G.get_edge_data(v,u).values())
            edata = edges[0] if edges else {}
            # swap for display
            u,v = v,u
        u_label = G.nodes[u].get("label",u)
        v_label = G.nodes[v].get("label",v)
        lines.append(f"  {i+1}. {u_label} --{edata.get('type','?')} [{edata.get('confidence','?')}]--> {v_label} (file {G.nodes[v].get('file','')})")
    return "\n".join(lines)

def format_impact_answer(impact: Dict) -> str:
    if "error" in impact:
        return impact["error"]
    lines = [f"Impact analysis for '{impact['root'].get('label')}' ({impact['root'].get('type')})", impact["summary"], ""]
    if impact["downstream"]:
        lines.append(f"Downstream ({len(impact['downstream'])} nodes, {len(impact['downstream_files'])} files):")
        for d in impact["downstream"][:15]:
            lines.append(f"  depth {d['depth']}: {d['label']} ({d['type']}) in {d['file']} --{d['edge_type']} [{d['confidence']}]")
        lines.append("")
    if impact["downstream_files"]:
        lines.append("Downstream files (hot):")
        for f in impact["downstream_files"][:10]:
            lines.append(f"  {f['file']} : {f['count']} edges")
        lines.append("")
    if impact["upstream"]:
        lines.append(f"Upstream dependencies ({len(impact['upstream'])} nodes):")
        for u in impact["upstream"][:15]:
            lines.append(f"  depth {u['depth']}: {u['label']} ({u['type']}) in {u['file']}")
    return "\n".join(lines)

def format_task_answer(task_result: Dict) -> str:
    if "error" in task_result:
        return f"{task_result['error']} — {task_result.get('suggestion','')}"
    lines = [f"Task: {task_result['task']}", f"Subgraph: {task_result['subgraph']['nodes']} nodes {task_result['subgraph']['edges']} edges | Token est {task_result['token_estimate']['scoped']} vs naive {task_result['token_estimate']['naive']} = {task_result['token_estimate']['reduction_x']}x", ""]
    lines.append("Top matches:")
    for m in task_result["top_matches"][:8]:
        lines.append(f"  - {m['label']} ({m['type']}) {m['file']} score {m['score']}")
    lines.append("")
    lines.append("Files to read (priority order):")
    for f in task_result["files"][:12]:
        lines.append(f"  {f['file']} relevance {f['relevance']}")
    lines.append("")
    lines.append("Agent plan:")
    for step in task_result["plan"]:
        lines.append(f"  {step}")
    lines.append("")
    lines.append("Copy-paste context for agent:")
    lines.append(task_result["copy_paste_context"])
    return "\n".join(lines)

def format_onboard_answer(onboard: Dict) -> str:
    lines = [f"Onboarding — {onboard['meta']['nodes']} nodes {onboard['meta']['edges']} edges {onboard['meta']['communities']} communities", ""]
    lines.append("God nodes (highest-degree, central):")
    for g in onboard["god_nodes"]:
        lines.append(f"  {g['label']} ({g['type']}) {g['file']} deg {g['degree']}")
    lines.append("")
    lines.append("Hot files:")
    for hf in onboard["hot_files"][:10]:
        lines.append(f"  {hf['file']} score {hf['score']}")
    lines.append("")
    lines.append("Entry points (high out, low in):")
    for ep in onboard["entry_points"][:8]:
        lines.append(f"  {ep['file']} out {ep['out']} in {ep['in']}")
    lines.append("")
    lines.append("Suggested questions to bootstrap:")
    for q in onboard["suggested_questions"]:
        lines.append(f"  - {q}")
    return "\n".join(lines)
