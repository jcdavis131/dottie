"""
export.py — export graph.json + graph.html
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
import networkx as nx
from pathlib import Path
from .security import sanitize_label
import html

def export_json(G: nx.MultiDiGraph, out_path: Path):
    # serializable
    data = {
        "nodes": [{"id": nid, **G.nodes[nid]} for nid in G.nodes],
        "edges": [{"source": u, "target": v, **d} for u, v, d in G.edges(data=True)],
        "meta": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges()}
    }
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_path

def export_html(G: nx.MultiDiGraph, out_path: Path):
    # Build simple vis-network HTML (free CDN, no build step)
    nodes_json = []
    for nid, d in G.nodes(data=True):
        label = sanitize_label(str(d.get("label", nid))[:80])
        community = d.get("community", 0)
        # color by community using Okabe-Ito palette (AAA)
        palette = ["#0072B2","#D55E00","#009E73","#CC79A7","#F0E442","#56B4E9","#E69F00","#000000"]
        color = palette[community % len(palette)]
        nodes_json.append({
            "id": nid,
            "label": label,
            "group": community,
            "color": color,
            "title": f"{d.get('type','')} | {d.get('file','')} | deg {d.get('degree',0)}"
        })
    edges_json = []
    for u, v, d in G.edges(data=True):
        conf = d.get("confidence","INFERRED")
        # style by confidence
        dash = False if conf=="EXTRACTED" else True
        edges_json.append({
            "from": u, "to": v,
            "label": d.get("type",""),
            "dashes": dash,
            "title": f"{d.get('type')} [{conf}]"
        })

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Personal Graphify — Graph</title>
<script type="importmap">
{{"imports": {{"vis-network": "https://cdn.jsdelivr.net/npm/vis-network@9.1.6/dist/vis-network.min.js"}}}}
</script>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
body {{ margin:0; font-family: ui-sans-system, -apple-system, sans-serif; background:#fafafa; }}
#mynetwork {{ width:100vw; height:90vh; border:1px solid #ddd; }}
#header {{ padding:12px 20px; background:white; border-bottom:2px solid black; display:flex; justify-content:space-between; align-items:center; }}
#header h1 {{ margin:0; font-size:18px; }}
#legend {{ font-size:12px; color:#555; }}
input {{ padding:6px 10px; border:2px solid black; border-radius:6px; width:260px; }}
</style>
</head>
<body>
<div id="header">
<h1>🐾 Personal Graphify — {G.number_of_nodes()} nodes {G.number_of_edges()} edges</h1>
<div id="legend"><input id="search" placeholder="Search node…" /> | EXTRACTED solid / INFERRED dashed | Colors = communities | Solo personal project</div>
</div>
<div id="mynetwork"></div>
<script>
const nodes = new vis.DataSet({nodes_json});
const edges = new vis.DataSet({edges_json});
const container = document.getElementById('mynetwork');
const data = {{nodes, edges}};
const options = {{
  nodes: {{shape:'dot', size:12, font:{{size:11}}}},
  edges: {{arrows:'to', font:{{size:9}}}},
  physics: {{solver:'forceAtlas2Based', stabilization:{{iterations:200}} }},
  groups: {{}}
}};
const network = new vis.Network(container, data, options);
document.getElementById('search').addEventListener('input', e=>{{
  const term = e.target.value.toLowerCase();
  if(!term){{nodes.forEach(n=>nodes.update({{id:n.id, hidden:false}})); return;}}
  nodes.forEach(n=>{{
    const match = n.label.toLowerCase().includes(term);
    nodes.update({{id:n.id, hidden:!match}});
  }});
}});
</script>
</body>
</html>
"""
    # json dumps need proper escaping; we already built JSON via python repr? Let's insert via json dumps
    html_content = html_content.replace("{nodes_json}", json.dumps(nodes_json)).replace("{edges_json}", json.dumps(edges_json))
    out_path.write_text(html_content, encoding="utf-8")
    return out_path
