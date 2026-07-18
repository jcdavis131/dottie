"""
loader.py — dynamic skill loader, J-Space routed, half-life aware, Tool Graph RAG + wRRF + ShardMemo
v2.1.0 — adds PRECEDES/REQUIRES/COMPLEMENTARY graph resolution, wRRF reranking, scope-before-routing

Solo personal project, no connection to employer, built with public/free-tier only
Public pip only, free-tier
"""
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Set
import os, pathlib, re, sys, json, math, importlib.util
from collections import defaultdict, deque

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

def _parse_frontmatter(text: str) -> tuple[Dict[str,Any], str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_raw = m.group(1)
    body = text[m.end():]
    try:
        import yaml
        fm = yaml.safe_load(fm_raw) or {}
    except Exception:
        fm = {}
        for line in fm_raw.splitlines():
            if ":" in line:
                k,v = line.split(":",1)
                fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body

def describe_from_manifest(skill_dir: str | pathlib.Path) -> Dict[str, Any]:
    """Build a skill's describe() payload from its SKILL.md frontmatter.

    The manifest is the single source of truth for routing metadata
    (j_space_target, half_life, triggers, graph edges); skill.py modules call
    this instead of hardcoding values that can drift from the manifest.
    """
    skill_dir = pathlib.Path(skill_dir)
    md = skill_dir / "SKILL.md"
    meta, _ = _parse_frontmatter(md.read_text(encoding="utf-8", errors="ignore"))
    return {
        "name": meta.get("name", skill_dir.name),
        "description": meta.get("description", ""),
        "j_space_target": meta.get("j_space_target", "Router"),
        "half_life": int(meta.get("half_life", meta.get("half-life", 80))),
        "triggers": meta.get("triggers", []) or [],
        "version": meta.get("version", "1.0.0"),
        "precedes": meta.get("precedes", []) or [],
        "requires": meta.get("requires", []) or [],
        "complementary": meta.get("complementary", []) or [],
    }

class Skill:
    def __init__(self, name: str, path: pathlib.Path, meta: Dict[str,Any], body: str):
        self.name = name
        self.path = path
        self.meta = meta
        self.body = body
        self.j_target = meta.get("j_space_target", "Router")
        self.hl = int(meta.get("half_life", meta.get("half-life", 80)))
        self.triggers = meta.get("triggers", [])
        self.deps = meta.get("dependencies", [])
        self.version = meta.get("version", "1.0.0")
        # Tool Graph RAG fields
        self.precedes: List[str] = meta.get("precedes", []) or []
        self.requires: List[str] = meta.get("requires", []) or []
        self.complementary: List[str] = meta.get("complementary", []) or []
        self.broadcast_target = float(meta.get("broadcast_target", 0.22))
        self.reportability_target = float(meta.get("reportability_target", 0.065))
        self._module = None

    def load_module(self):
        skill_py = self.path / "skill.py"
        if not skill_py.exists():
            return None
        spec = importlib.util.spec_from_file_location(f"skills.{self.name}.skill", skill_py)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)  # type: ignore
            self._module = mod
            return mod
        return None

    def run(self, **kwargs) -> Dict[str,Any]:
        mod = self._module or self.load_module()
        if mod is None:
            return {"skill": self.name, "error": "no skill.py"}
        if hasattr(mod, "Skill"):
            inst = mod.Skill()
            if hasattr(inst, "run"):
                return inst.run(**kwargs)
        if hasattr(mod, "run"):
            return mod.run(**kwargs)
        return {"skill": self.name, "error": "no run()"}

    def decay(self, steps: int) -> float:
        return math.exp(-steps / max(1, self.hl))

class SkillLoader:
    def __init__(self, skills_dir: str | pathlib.Path | None = None):
        if skills_dir is None:
            here = pathlib.Path(__file__).parent
            skills_dir = here
        self.skills_dir = pathlib.Path(skills_dir)
        self.skills: Dict[str, Skill] = {}
        self.scan()

    def scan(self):
        self.skills.clear()
        if not self.skills_dir.exists():
            return
        for sub in self.skills_dir.iterdir():
            if not sub.is_dir():
                continue
            if sub.name == "__pycache__":
                continue
            md = sub / "SKILL.md"
            if not md.exists():
                continue
            text = md.read_text(encoding="utf-8", errors="ignore")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name", sub.name)
            self.skills[name] = Skill(name=name, path=sub, meta=meta, body=body)

    def build_tool_graph(self) -> Dict[str, Dict[str, List[str]]]:
        """Build Tool Graph RAG with PRECEDES/REQUIRES/COMPLEMENTARY edges.
        Returns {skill: {precedes, requires, complementary}}
        """
        graph = {}
        for name, skill in self.skills.items():
            graph[name] = {
                "precedes": list(skill.precedes),
                "requires": list(skill.requires),
                "complementary": list(skill.complementary),
                "version": skill.version,
            }
        return graph

    def topological_sort(self) -> List[str]:
        """Topological sort respecting REQUIRES and PRECEDES, for deterministic execution order.
        Implements Kahn's algorithm.
        """
        # Build dependency graph: edge required -> dependent and precedes -> successor
        in_degree: Dict[str, int] = {name: 0 for name in self.skills}
        adj: Dict[str, List[str]] = defaultdict(list)

        for name, skill in self.skills.items():
            for req in skill.requires:
                if req in self.skills:
                    # req must come before name
                    adj[req].append(name)
                    in_degree[name] += 1
            for succ in skill.precedes:
                if succ in self.skills:
                    # name must come before succ
                    adj[name].append(succ)
                    in_degree[succ] += 1

        # Kahn
        q = deque([n for n, deg in in_degree.items() if deg == 0])
        order = []
        while q:
            # deterministic: sort queue
            q = deque(sorted(q))
            cur = q.popleft()
            order.append(cur)
            for nb in adj.get(cur, []):
                in_degree[nb] -= 1
                if in_degree[nb] == 0:
                    q.append(nb)

        # If cycle, append remaining arbitrarily sorted
        if len(order) != len(self.skills):
            remaining = sorted(set(self.skills.keys()) - set(order))
            order.extend(remaining)

        return order

    def wrrf_rerank(self, query: str, k: int = 60, weights: Dict[str,float] | None = None) -> List[Tuple[str,float]]:
        """Weighted Reciprocal Rank Fusion for Tool Graph RAG.
        Combines three ranking signals:
        - trigger match score (BM25F-like overlap with triggers + description)
        - half_life decay relevance (prefer hl matched to query complexity)
        - graph centrality (complementary + precedes degree)
        A former fourth signal — broadcast_target proximity to 0.22 — was removed:
        every manifest sets broadcast_target to exactly 0.22, so the signal was a
        constant 1.0 (identical rank for all skills, pure dead weight). Its 0.2
        fusion weight was redistributed to the trigger (+0.1) and graph (+0.1)
        signals. No accuracy/token-savings figures are claimed here: none have
        been measured for this reranker.
        Returns list of (skill_name, fused_score) sorted descending.
        """
        if weights is None:
            weights = {"trigger": 0.6, "hl": 0.15, "graph": 0.25}

        q_lower = query.lower()
        # Compute per-signal rankings
        trigger_scores: Dict[str, float] = {}
        hl_scores: Dict[str, float] = {}

        for name, skill in self.skills.items():
            # trigger BM25F-like: count trigger overlaps
            trig = " ".join(skill.triggers).lower()
            overlap = sum(1 for tok in q_lower.split() if tok in trig)
            # also check description
            desc = skill.meta.get("description","").lower()
            overlap += sum(0.5 for tok in q_lower.split() if tok in desc)
            trigger_scores[name] = overlap + 0.1  # smoothing

            # half-life relevance: prefer hl close to query complexity (long query -> high hl)
            q_len = len(q_lower.split())
            ideal_hl = 30 if q_len <= 3 else 150 if q_len <= 8 else 300
            hl_scores[name] = 1.0 / (1.0 + abs(skill.hl - ideal_hl)/100.0)

        # Rank per signal (descending)
        def rank_dict(scores: Dict[str,float]) -> Dict[str,int]:
            sorted_names = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return {name: rank+1 for rank, (name, _) in enumerate(sorted_names)}

        r_trigger = rank_dict(trigger_scores)
        r_hl = rank_dict(hl_scores)

        # Graph centrality: complementary degree
        graph_centrality: Dict[str,float] = {}
        for name, skill in self.skills.items():
            graph_centrality[name] = len(skill.complementary) + len(skill.precedes)*0.5
        r_graph = rank_dict(graph_centrality)

        # WRRF fusion: score = sum w_i / (k + rank_i)
        fused: Dict[str,float] = {}
        for name in self.skills:
            fused[name] = (
                weights["trigger"] / (k + r_trigger.get(name, 999)) +
                weights["hl"] / (k + r_hl.get(name, 999)) +
                weights["graph"] / (k + r_graph.get(name, 999))
            )

        # Sort descending fused score
        ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return ranked

    def list(self) -> List[Dict[str,Any]]:
        order = self.topological_sort()
        result = []
        for name in order:
            s = self.skills[name]
            result.append({
                "name": s.name,
                "target": s.j_target,
                "hl": s.hl,
                "version": s.version,
                "triggers": s.triggers,
                "desc": s.meta.get("description",""),
                "precedes": s.precedes,
                "requires": s.requires,
                "complementary": s.complementary,
            })
        return result

    def load_all(self):
        for s in self.skills.values():
            s.load_module()

    def run(self, name: str, **kwargs) -> Dict[str,Any]:
        if name not in self.skills:
            raise KeyError(f"skill {name!r} not found, available {list(self.skills.keys())}")
        return self.skills[name].run(**kwargs)

    def run_with_graph(self, query: str, **kwargs) -> List[Dict[str,Any]]:
        """Run skills in graph-resolved order with wRRF reranking for query.
        Implements progressive disclosure: top wRRF skills first, then dependencies.
        """
        ranked = self.wrrf_rerank(query)
        # progressive disclosure: top 3 + their requires + complementary
        top_names = [n for n,_ in ranked[:3]]
        # expand with required dependencies
        expanded: Set[str] = set(top_names)
        for n in top_names:
            if n in self.skills:
                expanded.update(self.skills[n].requires)
                # add complementary top 1
                if self.skills[n].complementary:
                    expanded.add(self.skills[n].complementary[0])

        # order by topological sort filtered
        topo = self.topological_sort()
        ordered = [n for n in topo if n in expanded]

        # Scope-before-routing, Tier A: the safety gate always executes first when it
        # is part of the resolved graph. Topo order already places it before its
        # dependents, but Kahn's sorted queue can emit unrelated zero-in-degree
        # skills (e.g. memory-mint) ahead of it; pin it to position 0 explicitly.
        if "safety-scanner" in ordered and ordered[0] != "safety-scanner":
            ordered.remove("safety-scanner")
            ordered.insert(0, "safety-scanner")

        results = []
        for name in ordered:
            try:
                res = self.run(name, **kwargs)
                results.append(res)
            except Exception as e:
                results.append({"skill": name, "error": str(e), "pass": False})
        return results

def main():
    import argparse
    ap = argparse.ArgumentParser(description="ava-skills loader v2.1.0 with Tool Graph RAG + wRRF + ShardMemo")
    ap.add_argument("cmd", nargs="?", default="list", help="list|graph|rerank|run|run-graph|test")
    ap.add_argument("skill", nargs="?", help="skill name or query for rerank")
    ap.add_argument("--mode", default="mock")
    ap.add_argument("--wiki-path", default=None)
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--query", default="", help="query for wRRF rerank")
    args = ap.parse_args()

    loader = SkillLoader()
    if args.cmd == "list":
        print(json.dumps(loader.list(), indent=2))
    elif args.cmd == "graph":
        graph = loader.build_tool_graph()
        print(json.dumps(graph, indent=2))
        print(f"\nTopological order: {loader.topological_sort()}")
    elif args.cmd == "rerank":
        q = args.query or args.skill or "inspect jspace safety"
        ranked = loader.wrrf_rerank(q)
        print(f"Query: {q}")
        print(json.dumps([{"name": n, "score": round(s,5)} for n,s in ranked], indent=2))
    elif args.cmd == "run":
        if not args.skill:
            print("Need skill name")
            sys.exit(1)
        res = loader.run(args.skill, mode=args.mode, wiki_path=args.wiki_path, ckpt=args.ckpt, query=args.query)
        print(json.dumps(res, indent=2))
    elif args.cmd == "run-graph":
        q = args.query or args.skill or "safety check then inspect jspace"
        results = loader.run_with_graph(q, mode=args.mode, wiki_path=args.wiki_path, ckpt=args.ckpt)
        print(json.dumps(results, indent=2))
    elif args.cmd == "test":
        loader.load_all()
        for name, skill in loader.skills.items():
            if args.skill and args.skill!=name:
                continue
            try:
                res = skill.run(mode="mock", query=args.query)
                print(f"{name}: PASS {str(res)[:200]}")
            except Exception as e:
                print(f"{name}: FAIL {e}")
    else:
        print("unknown cmd, use list|graph|rerank|run|run-graph|test")

if __name__ == "__main__":
    main()
