"""
report.py — GRAPH_REPORT.md
Solo personal project, no connection to employer, built with public/free-tier only
"""

from pathlib import Path

import networkx as nx


def generate_report(
    G: nx.MultiDiGraph,
    output_path: Path,
    god_nodes_list,
    surprises,
    comm_summaries,
    token_stats_dict,
):
    lines = []
    lines.append("# Personal Graphify Report")
    lines.append("")
    lines.append(
        "Solo personal project, no connection to employer, built with public/free-tier only."
    )
    lines.append("")
    lines.append(
        f"**Nodes:** {G.number_of_nodes()} · **Edges:** {G.number_of_edges()} · **Communities:** {len(comm_summaries)}"
    )
    lines.append("")
    lines.append(
        f"Token estimate: ~{token_stats_dict['query']} tokens per scoped query vs ~{token_stats_dict['naive']} naive → **{token_stats_dict['reduction']}× reduction** ({token_stats_dict.get('basis', 'measured')})."
    )
    lines.append("")
    lines.append("## God Nodes (highest-degree concepts)")
    lines.append("")
    for nid, data in god_nodes_list:
        deg = data.get("degree", G.degree(nid))
        lines.append(
            f"- **{data.get('label', nid)}** ({data.get('type', '')}) — degree {deg} — file `{data.get('file', '')}` — community {data.get('community', 0)}"
        )
    lines.append("")
    lines.append("## Communities")
    lines.append("")
    for comm in comm_summaries[:15]:
        lines.append(
            f"- **Community {comm['id']}** — {comm['size']} nodes — types {comm['types']} — sample: {', '.join(comm['sample_labels'][:5])}"
        )
    lines.append("")
    lines.append("## Surprising Connections (cross-community, cross-file)")
    lines.append("")
    for s in surprises[:12]:
        src_data = G.nodes[s["source"]]
        tgt_data = G.nodes[s["target"]]
        lines.append(
            f"- `{src_data.get('label', s['source'])}` [{s['data'].get('type')}] → `{tgt_data.get('label', s['target'])}` — [{s['data'].get('confidence')}] — files differ? {s['file_diff']} — communities {s['cross']}"
        )
    lines.append("")
    lines.append("## Suggested Questions (ask via `pgraphify query`)")
    lines.append("")
    lines.append('- `pgraphify query "what connects auth to database?"`')
    lines.append('- `pgraphify query "where is turnover retention logic?"`')
    lines.append(
        '- `pgraphify query "how does Ava J-space Planner interact with Critic?"`'
    )
    lines.append('- `pgraphify query "how does Scout connect to Ava?"`')
    lines.append('- `pgraphify query "trace Stripe webhook to Paid Users MRR"`')
    lines.append('- `pgraphify query "show MTNN heads 48→64→k"`')
    lines.append("")
    lines.append("## Rationale & Why")
    lines.append("")
    rationale_nodes = [
        (nid, d) for nid, d in G.nodes(data=True) if d.get("type") == "rationale"
    ]
    for nid, data in rationale_nodes[:15]:
        lines.append(
            f"- `{data.get('label')}` @ {data.get('file')}:{data.get('line')} — explains nearby code"
        )
    if not rationale_nodes:
        lines.append(
            "- No # NOTE / # WHY comments found. Consider adding them — they become first-class graph nodes linked to code."
        )
    lines.append("")
    lines.append("## Personal Ecosystem Overlay")
    lines.append("")
    lines.append(
        "- **Family Brain**: Joint accounts, Betterment buckets, Plaid 5 institutions, Emergency $136.5k"
    )
    lines.append(
        "- **Passive Lab**: Turnover Shield $79-$149/mo, 7-13 customers → $1k MRR, Stripe → Supabase → Workers free-tier"
    )
    lines.append(
        "- **Ava AGI**: multi_jspace_module.py 4 workspaces S1 hl=8 S2 hl=300 Critic hl=30 Planner hl=150, Router/veto"
    )
    lines.append(
        "- **Vector Hoops**: 12,966 player-seasons, MTNN v5_concat_b2_h160_t32_d48_mlp128, CQS 85.87, leakfree 0.7937 composite"
    )
    lines.append("")
    lines.append('> Use `pgraphify path "A" "B"` to trace any two concepts.')
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
