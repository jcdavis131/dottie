"""
query.py — query/path/explain/impact/task/onboard against graph.json
SOTA for agents: hybrid lexical + degree + optional semantic embeddings (Ollama mxbai-embed-large) + impact graph + task compiler
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import re
from collections import Counter

import networkx as nx

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
        if src not in G:
            G.add_node(src, label=src, type="unknown")
        if tgt not in G:
            G.add_node(tgt, label=tgt, type="unknown")
        attrs = {k:v for k,v in e.items() if k not in ("source","target")}
        G.add_edge(src, tgt, **attrs)
    return G

# Stopwords that pollute concept extraction
STOP_LABELS = {"or","and","the","a","an","of","in","to","for","with","on","is","are","be","or:"}

def _tokenize(s: str) -> List[str]:
    return [t.lower() for t in re.split(r"[^a-z0-9→_]+", s.lower()) if len(t)>=2 and t not in STOP_LABELS]

# -------- Ollama embeddings optional (SOTA semantic rerank) --------
_EMBED_MODEL_DEFAULT = "mxbai-embed-large"

def _try_import_ollama():
    try:
        import ollama  # type: ignore
        return ollama
    except Exception:
        return None

def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a)!=len(b):
        return 0.0
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    if na==0 or nb==0:
        return 0.0
    return dot/(na*nb)

def get_ollama_embeddings(texts: List[str], model: str = _EMBED_MODEL_DEFAULT) -> Optional[List[List[float]]]:
    """Try Ollama local embeddings, return None if unavailable."""
    ollama_mod = _try_import_ollama()
    if not ollama_mod:
        return None
    # filter empty
    texts = [t[:800] for t in texts]  # cap
    try:
        # Newer API: ollama.embed(model, input=texts)
        # Try embed first
        if hasattr(ollama_mod, "embed"):
            resp = ollama_mod.embed(model=model, input=texts)
            # resp is dict with embeddings
            if isinstance(resp, dict) and "embeddings" in resp:
                return resp["embeddings"]
            # some versions return list directly?
            if isinstance(resp, list):
                return resp
        # Fallback: embeddings
        if hasattr(ollama_mod, "embeddings"):
            out = []
            for t in texts:
                try:
                    r = ollama_mod.embeddings(model=model, prompt=t)
                    emb = r.get("embedding") if isinstance(r, dict) else None
                    if emb:
                        out.append(emb)
                except Exception:
                    out.append(None)
            if any(x is None for x in out):
                return None
            return out
    except Exception as e:
        # Could be no server running, model not pulled, etc — silent fallback
        # Debug: print(f"[graphify] ollama embed failed: {e}")
        return None
    return None

def _node_text_for_embed(data: Dict) -> str:
    # Combine label + type + desc + file for embedding
    parts = []
    for k in ("label","type","desc","file"):
        v = data.get(k)
        if v:
            parts.append(str(v)[:200])
    return " ".join(parts)[:500]

# -------- Cost logging (SOTA token savings dashboard) --------

def _cost_path_for_graph(graph_path: Path) -> Path:
    """cost.json lives next to graph.json in same out dir"""
    g = Path(graph_path)
    if g.is_dir():
        return g / "cost.json"
    return g.parent / "cost.json"

def _atomic_write_text(path: Path, text: str) -> None:
    """``Path.write_text`` truncates before writing, so a process killed mid-write
    leaves a torn file. The next ``log_query_cost`` call would then hit the corrupt
    branch below — write to a per-process temp name and replace so a reader never
    observes a partial file (same shape as the vault/telemetry fixes, 3e301cb/f274be8)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

def log_query_cost(graph_path: Path, question: str, naive: int, scoped: int, reduction_x: float, mode: str = "lexical", basis: str = ""):
    try:
        cpath = _cost_path_for_graph(Path(graph_path))
        if not cpath.exists():
            # create base
            data = {"nodes": 0, "edges": 0, "queries": [], "total_saved_tokens": 0, "total_naive": 0, "total_scoped": 0, "mode": "ollama-first local"}
            try:
                # try read existing graph for nodes/edges if available
                if Path(graph_path).exists() and Path(graph_path).is_file():
                    gj = json.loads(Path(graph_path).read_text(encoding="utf-8")[:2000000])
                    data["nodes"] = len(gj.get("nodes",[]))
                    data["edges"] = len(gj.get("edges",[]))
            except Exception:
                pass
        else:
            try:
                data = json.loads(cpath.read_text(encoding="utf-8"))
            except Exception as e:
                # A torn/corrupt cost.json used to be swallowed here and silently
                # replaced with a zeroed dict, which the write below then cemented —
                # every prior query's logged savings lost with no trace (same bug
                # class as telemetry.py's _load_live_status, f274be8). This function
                # must stay non-raising (it must never break a query just to log its
                # cost), so the fix is to stop being SILENT about it: preserve the
                # bytes and say so on stderr, rather than raise.
                try:
                    backup = cpath.with_name(f"{cpath.name}.corrupt-{int(time.time())}")
                    backup.write_bytes(cpath.read_bytes())
                    note = f", previous bytes preserved at {backup}"
                except OSError:
                    note = ""
                print(f"[personal_graphify] {cpath} is unreadable ({e}); resetting the "
                      f"cost log{note}.", file=sys.stderr)
                data = {"nodes":0,"edges":0,"queries":[],"total_saved_tokens":0,"total_naive":0,"total_scoped":0}

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "question": question[:200],
            "naive": naive,
            "scoped": scoped,
            "saved": max(0, naive - scoped),
            "reduction_x": reduction_x,
            "mode": mode,
            "basis": basis or "unknown"
        }
        if "queries" not in data:
            data["queries"] = []
        data["queries"].append(entry)
        # keep last 200 queries
        if len(data["queries"]) > 200:
            data["queries"] = data["queries"][-200:]
        data["total_naive"] = sum(q.get("naive",0) for q in data["queries"])
        data["total_scoped"] = sum(q.get("scoped",0) for q in data["queries"])
        data["total_saved_tokens"] = data["total_naive"] - data["total_scoped"]
        data["last_query"] = entry
        # preserve nodes/edges if missing
        _atomic_write_text(cpath, json.dumps(data, indent=2))
    except Exception:
        # never break query on cost log failure
        pass

def format_cost_dashboard(cost_path: Path) -> str:
    try:
        data = json.loads(Path(cost_path).read_text(encoding="utf-8"))
        qs = data.get("queries", [])
        total_saved = data.get("total_saved_tokens", 0)
        total_naive = data.get("total_naive", 0)
        total_scoped = data.get("total_scoped", 0)
        avg_reduction = (total_naive / max(total_scoped,1)) if total_scoped else 0
        lines = [f"Cost dashboard — {len(qs)} queries logged (cost.json)", f"Total naive tokens: {total_naive} | scoped: {total_scoped} | saved: {total_saved} → {avg_reduction:.1f}x avg reduction", ""]
        lines.append("Recent queries:")
        for q in qs[-15:][::-1]:
            basis_tag = str(q.get("basis", "unknown")).split(":")[0]
            lines.append(f"  - [{q.get('mode','lex')}] [{basis_tag}] {q.get('ts','')[:16]} | {q.get('question','')[:60]} → {q.get('scoped')} vs {q.get('naive')} = {q.get('reduction_x')}x saved {q.get('saved')}")
        # Only monetize savings whose naive basis was actually measured (file bytes on disk).
        # Entries with an estimated or unknown basis are modeled numbers — never priced.
        measured_saved = sum(q.get("saved", 0) for q in qs if str(q.get("basis", "")).startswith("measured"))
        unmeasured = len(qs) - sum(1 for q in qs if str(q.get("basis", "")).startswith("measured"))
        est_dollars = measured_saved * 0.005 / 1000
        lines.append("")
        lines.append(f"Est. API cost avoided (at $5/M): ~${est_dollars:.2f} based on {measured_saved} measured-basis tokens saved")
        if unmeasured:
            lines.append(f"  ({unmeasured} queries had estimated/unknown token basis — excluded from $ figure)")
        lines.append(f"Storage: free local Ollama — mode: {data.get('mode','ollama-first local')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Cost dashboard unavailable: {e}"

# -------- Core search with optional semantic rerank --------

def search_nodes(G: nx.MultiDiGraph, query: str, limit: int = 30, boost_file_type: str = None,
                 semantic: bool = False, embed_model: str = _EMBED_MODEL_DEFAULT,
                 top_lexical_for_rerank: int = 60) -> List[Dict]:
    qlower = query.lower()
    terms = _tokenize(query)
    if not terms:
        terms = [qlower]

    results_lex = []
    for nid, data in G.nodes(data=True):
        label = str(data.get("label",""))
        typ = str(data.get("type",""))
        file_ = str(data.get("file",""))
        desc = str(data.get("desc",""))
        nid_l = nid.lower()
        blob = f"{label} {typ} {desc} {file_} {nid_l}".lower()
        score = 0
        if qlower in blob:
            score += 20
        matched = 0
        for t in terms:
            if t in blob:
                matched += 1
        if matched == 0:
            continue
        score += matched * 3
        label_l = label.lower()
        if any(t in label_l for t in terms):
            score += 5
        deg = G.degree(nid)
        score += min(deg/10.0, 3.0)
        type_boost = {
            "file": 1.5, "function": 2.0, "class": 2.0, "module": 0.5,
            "product": 2.5, "ml_feature": 2.0, "integration": 1.8,
            "business_metric": 1.5, "tool": 1.2, "ecosystem_domain": 1.0,
            "product_feature": 2.8, "concept": 0.8
        }
        score += type_boost.get(typ, 0)
        if boost_file_type and boost_file_type.lower() in file_.lower():
            score += 2
        # boost Turnover Shield / Stripe / Plaid / Scout / Ava core for agent relevance
        if typ in ("product","business_metric","tool","ml_concept") and score>5:
            if "turnover" in blob or "mrr" in blob or "stripe" in blob or "scout" in blob or "ava" in blob:
                score += 1.5
        results_lex.append((score, deg, nid, data, matched))

    results_lex.sort(key=lambda x: (x[0], x[1], x[4]), reverse=True)
    # keep top N for semantic rerank candidate pool
    lexical_pool = results_lex[:top_lexical_for_rerank]

    # If semantic requested, try rerank
    if semantic and lexical_pool:
        try:
            texts = [_node_text_for_embed(d) for _,_,_,d,_ in lexical_pool]
            # Query first
            query_emb_list = get_ollama_embeddings([query], model=embed_model)
            cand_emb_list = get_ollama_embeddings(texts, model=embed_model)
            if query_emb_list and cand_emb_list and len(cand_emb_list)==len(texts):
                q_emb = query_emb_list[0]
                reranked = []
                for (score, deg, nid, data, matched), cand_emb in zip(lexical_pool, cand_emb_list):
                    sim = _cosine(q_emb, cand_emb)  # 0-1
                    # combined: lexical 60% + semantic 40% scaled to same range (~0-25)
                    combined = score * 0.55 + sim * 22  # sim*22 gives up to 22 points
                    reranked.append((combined, score, sim, deg, nid, data, matched))
                reranked.sort(key=lambda x: (x[0], x[3]), reverse=True)
                # convert to final list shape with semantic info
                deduped = []
                seen = set()
                for combined, lex_score, sim, deg, nid, data, matched in reranked:
                    key = (data.get("label","").lower(), data.get("file",""))
                    if key in seen and len(deduped)>10 and combined<14:
                        continue
                    seen.add(key)
                    deduped.append({
                        "id": nid, **data,
                        "score": round(combined,2),
                        "lexical_score": round(lex_score,2),
                        "semantic_score": round(sim,3),
                        "matched_terms": matched,
                        "degree": deg
                    })
                    if len(deduped) >= limit*2:
                        break
                return deduped[:limit]
            # if embeddings failed, fall through to lexical
        except Exception:
            pass  # silent fallback

    # Lexical-only path (dedupe)
    seen_labels = set()
    deduped = []
    for score, deg, nid, data, matched in lexical_pool:
        key = (data.get("label","").lower(), data.get("file",""))
        if key in seen_labels and len(deduped) > 10:
            if score < 15:
                continue
        seen_labels.add(key)
        deduped.append({"id": nid, **data, "score": round(score,2), "matched_terms": matched, "degree": deg})
        if len(deduped) >= limit*2:
            break
    return deduped[:limit]

def subgraph_for_query(G: nx.MultiDiGraph, query: str, hops: int = 2, limit_nodes: int = 60,
                       include_rationale: bool = True, semantic: bool = False,
                       embed_model: str = _EMBED_MODEL_DEFAULT) -> nx.MultiDiGraph:
    matches = search_nodes(G, query, limit=8, semantic=semantic, embed_model=embed_model)
    if not matches:
        return G.subgraph([]).copy()
    frontier = [m["id"] for m in matches if m["id"] in G]
    visited = set(frontier)
    if include_rationale:
        for nid in list(frontier):
            for _, nbr, _ in G.out_edges(nid, data=True):
                if G.nodes[nbr].get("type") == "rationale":
                    visited.add(nbr)
            for src, _, _ in G.in_edges(nid, data=True):
                if G.nodes[src].get("type") == "rationale":
                    visited.add(src)
    for _ in range(hops):
        new_frontier = []
        for node in frontier:
            for _, nbr, _ in G.out_edges(node, data=True):
                if nbr not in visited:
                    if G.nodes[nbr].get("type") == "reference" and len(visited) > 40:
                        continue
                    visited.add(nbr)
                    new_frontier.append(nbr)
            for src, _, _ in G.in_edges(node, data=True):
                if src not in visited:
                    visited.add(src)
                    new_frontier.append(src)
        frontier = new_frontier
        if len(visited) >= limit_nodes:
            break
    visited_list = list(visited)[:limit_nodes]
    sub = G.subgraph(visited_list).copy()
    return sub

def shortest_path(G: nx.MultiDiGraph, source_q: str, target_q: str, max_hops: int = 6, semantic: bool = False) -> Optional[List[str]]:
    src_candidates = search_nodes(G, source_q, limit=3, semantic=semantic)
    tgt_candidates = search_nodes(G, target_q, limit=3, semantic=semantic)
    if not src_candidates or not tgt_candidates:
        return None
    UG = nx.Graph(G)
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

def explain_node(G: nx.MultiDiGraph, query: str, include_code_snippet: bool = False, semantic: bool = False, graph_path: Optional[Path] = None) -> Optional[Dict]:
    matches = search_nodes(G, query, limit=1, semantic=semantic)
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
    def conf_rank(c):
        return 0 if c=="EXTRACTED" else 1 if c=="INFERRED" else 2
    neighbors_out.sort(key=lambda x: (conf_rank(x["confidence"]), -G.degree(x["id"]) if x["id"] in G else 0))
    neighbors_in.sort(key=lambda x: (conf_rank(x["confidence"]), -G.degree(x["id"]) if x["id"] in G else 0))

    snippet = None
    if include_code_snippet:
        fpath = data.get("file")
        if fpath:
            p = Path(fpath)
            if not p.exists() and graph_path is not None and not p.is_absolute():
                # Resolve relative to the graph file's location: graph.json lives in
                # <repo>/graphify-out/, so try both the out dir and the repo root.
                base = Path(graph_path).resolve()
                base = base.parent if base.is_file() or base.suffix else base
                for cand in (base / p, base.parent / p):
                    if cand.exists():
                        p = cand
                        break
            if p.exists() and p.is_file():
                try:
                    # encoding= matters MORE here, not less, because errors="ignore" would
                    # otherwise silently DROP every byte the locale codepage cannot decode --
                    # returning a mangled snippet instead of failing loudly.
                    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
                    line = data.get("line", 0)
                    if line and line>0:
                        start = max(0, line-5)
                        end = min(len(lines), line+15)
                        snippet = "\n".join(lines[start:end])
                except OSError:
                    pass

    return {
        "node": {"id": nid, **data},
        "neighbors_out": neighbors_out[:40],
        "neighbors_in": neighbors_in[:40],
        "degree": G.degree(nid),
        "community": data.get("community", -1),
        "snippet": snippet
    }

def impact_analysis(G: nx.MultiDiGraph, query: str, direction: str = "both", depth: int = 3, limit: int = 80, semantic: bool = False) -> Dict:
    matches = search_nodes(G, query, limit=1, semantic=semantic)
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

    for k in impacted:
        impacted[k] = sorted(impacted[k], key=lambda x: (x["depth"], 0 if x["confidence"]=="EXTRACTED" else 1))[:limit]

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

def task_compiler(G: nx.MultiDiGraph, task_description: str, semantic: bool = False) -> Dict:
    entities = _tokenize(task_description)
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
        "scout": "Scout CLI",
        "bigbang": "Scout CLI",
        "vector": "Vector Hoops",
        "dino": "Tennis DINOv3 ExecuTorch"
    }
    boosted_queries = []
    for token in entities:
        if token in personal_boosts:
            boosted_queries.append(personal_boosts[token])

    all_matches = []
    for q in set(entities + boosted_queries):
        if len(q) < 3:
            continue
        matches = search_nodes(G, q, limit=3, semantic=semantic)
        all_matches.extend(matches)

    # also try full task query as fallback for semantic
    if semantic:
        all_matches.extend(search_nodes(G, task_description, limit=5, semantic=True))

    by_id = {}
    for m in all_matches:
        if m["id"] not in by_id or m["score"] > by_id[m["id"]]["score"]:
            by_id[m["id"]] = m
    ranked = sorted(by_id.values(), key=lambda x: x["score"], reverse=True)[:12]

    if not ranked:
        return {"error": f"No relevant nodes for task '{task_description}'", "suggestion": "Try broader terms: Stripe, Turnover Shield, Family Brain, MTNN, Ava, Scout"}

    all_ids = set([m["id"] for m in ranked])
    sub_nodes = set()
    for nid in all_ids:
        if nid not in G:
            continue
        sub_nodes.add(nid)
        for _, nbr, _ in G.out_edges(nid, data=True):
            if G.nodes[nbr].get("type") in ("file","function","class","product","integration","ml_concept"):
                sub_nodes.add(nbr)
        for src, _, _ in G.in_edges(nid, data=True):
            if G.nodes[src].get("type") in ("file","function","class"):
                sub_nodes.add(src)

    sub = G.subgraph(list(sub_nodes)[:80]).copy()

    files_counter = Counter()
    for _, data in sub.nodes(data=True):
        f = data.get("file")
        if f:
            files_counter[f] += 1 + (data.get("degree",0)/10)

    files_ranked = [ {"file": f, "relevance": round(c,1)} for f,c in files_counter.most_common(15)]

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

    top_matches_payload = [{"label": m.get("label"), "type": m.get("type"), "file": m.get("file",""), "score": m.get("score"), "semantic": m.get("semantic_score")} for m in ranked[:10]]

    # Measured, not modeled — shared estimator with analyze.token_stats() so the two
    # never drift (was a line-for-line duplicate).
    from .analyze import naive_token_estimate, payload_tokens
    naive_tokens, basis = naive_token_estimate(G)
    scoped_tokens = payload_tokens({"top_matches": top_matches_payload,
                                    "files": files_ranked, "plan": plan})
    reduction = round(naive_tokens / max(scoped_tokens,1), 1)

    return {
        "task": task_description,
        "top_matches": top_matches_payload,
        "subgraph": {"nodes": sub.number_of_nodes(), "edges": sub.number_of_edges()},
        "files": files_ranked,
        "plan": plan,
        "token_estimate": {"naive": naive_tokens, "scoped": scoped_tokens, "reduction_x": reduction,
                            "basis": basis},
        "copy_paste_context": f"Task: {task_description}\nTop files: {', '.join([f['file'] for f in files_ranked[:5]])}\nGod nodes to check: see graphify-out/GRAPH_REPORT.md\nRelevant query: pgraphify query \"{task_description}\""
    }

def onboard_report(G: nx.MultiDiGraph, top_n_god: int = 10) -> Dict:
    degs = [(nid, G.degree(nid), G.nodes[nid]) for nid in G.nodes]
    degs.sort(key=lambda x: x[1], reverse=True)
    god = [{"id": nid, "label": d.get("label"), "type": d.get("type"), "file": d.get("file",""), "degree": deg} for nid, deg, d in degs[:top_n_god]]

    comm_counts = Counter([G.nodes[n].get("community",-1) for n in G.nodes])
    comm_summary = [{"community": c, "size": s} for c,s in comm_counts.most_common(10)]

    file_deg = Counter()
    for _, data in G.nodes(data=True):
        f = data.get("file")
        if f:
            file_deg[f] += data.get("degree", G.degree(data.get("id","")) if "id" in data else 0)
    hot_files = [{"file": f, "score": round(s,1)} for f,s in file_deg.most_common(15)]

    entry_points = []
    for nid, data in G.nodes(data=True):
        if data.get("type") == "file":
            out_d = G.out_degree(nid)
            in_d = G.in_degree(nid)
            if out_d > 5 and out_d > in_d*2:
                entry_points.append({"file": data.get("label"), "out": out_d, "in": in_d})
    entry_points = sorted(entry_points, key=lambda x: x["out"], reverse=True)[:10]

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

# -- formatting for CLI with cost logging --

def format_query_answer(G: nx.MultiDiGraph, query: str, graph_path: Path = None, semantic: bool = False, embed_model: str = _EMBED_MODEL_DEFAULT) -> str:
    sub = subgraph_for_query(G, query, semantic=semantic, embed_model=embed_model)
    mode_str = f"semantic:{embed_model}" if semantic else "lexical"

    if sub.number_of_nodes()==0:
        return f"No nodes found for query '{query}'. Try broader terms: Stripe, Turnover Shield, MTNN, Ava, Scout, Family Brain, Vector Hoops"

    # extra hint for semantic availability
    semantic_hint = " [semantic rerank ON]" if semantic else " [lexical] — try --semantic for Ollama mxbai-embed-large rerank"

    lines = []
    lines.append("Top matches:")
    for m in search_nodes(G, query, limit=12, semantic=semantic, embed_model=embed_model):
        extra = f" sem={m.get('semantic_score')}" if "semantic_score" in m else ""
        lines.append(f"- {m.get('label')} ({m.get('type')}) in {m.get('file','')} [comm {m.get('community',0)}] deg {m.get('degree',0)} score {m.get('score')}{extra}")

    lines.append("")
    lines.append("Edges (sample):")
    for u,v,d in list(sub.edges(data=True))[:20]:
        src_label = G.nodes[u].get("label",u)[:50]
        tgt_label = G.nodes[v].get("label",v)[:50]
        lines.append(f"  {src_label} --{d.get('type')} [{d.get('confidence')}]--> {tgt_label}")

    rationale_nodes = [nid for nid,d in sub.nodes(data=True) if d.get("type")=="rationale"]
    if rationale_nodes:
        lines.append("")
        lines.append(f"Rationale found: {len(rationale_nodes)} WHY/NOTE nodes — check explain")

    body = "\n".join(lines)

    # Measured, not modeled — same estimators task_compiler uses (analyze.py) so the
    # numbers in the answer, cost.json, and GRAPH_REPORT.md never drift.
    from .analyze import naive_token_estimate, payload_tokens
    naive, basis = naive_token_estimate(G)
    scoped = payload_tokens(body)
    red = round(naive / max(scoped,1), 1)
    if graph_path:
        try:
            log_query_cost(graph_path, query, naive, scoped, red, mode=mode_str, basis=basis)
        except Exception:
            pass

    header = (f"Query: '{query}' — {sub.number_of_nodes()} nodes, {sub.number_of_edges()} edges in scoped subgraph "
              f"(token-est ~{scoped} vs naive ~{naive} = {red}x reduction; {basis}){semantic_hint}")
    return header + "\n\n" + body

def format_path_answer(G: nx.MultiDiGraph, src_q: str, tgt_q: str, semantic: bool = False) -> str:
    path = shortest_path(G, src_q, tgt_q, semantic=semantic)
    if not path:
        return f"No path found between '{src_q}' and '{tgt_q}' (tried top-3 matches each, max 6 hops)."
    lines = [f"Shortest path {len(path)-1} hops between '{src_q}' and '{tgt_q}':", ""]
    for i in range(len(path)-1):
        u = path[i]; v = path[i+1]
        edata = {}
        if G.has_edge(u,v):
            edges = list(G.get_edge_data(u,v).values())
            edata = edges[0] if edges else {}
        elif G.has_edge(v,u):
            edges = list(G.get_edge_data(v,u).values())
            edata = edges[0] if edges else {}
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
