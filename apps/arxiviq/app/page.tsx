"use client";
import { useEffect, useMemo, useRef, useState } from "react";

type NodeType = "Paper" | "Organization" | "Person" | "Architecture" | "Topic";
type GraphNode = {
  id: string; type: string; label: string; title?: string; abstract?: string;
  name?: string; query_tag?: string; authors?: string[];
  x?: number; y?: number; vx?: number; vy?: number; pinned?: boolean;
};
type GraphEdge = { source: string; target: string; kind: string; weight?: number };
type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] };

const COLOR: Record<string,string> = {
  Person:"#0ea5e9", Organization:"#8b5cf6", Paper:"#111827", Architecture:"#f59e0b", Topic:"#10b981"
};
const TOPIC_LABELS: Record<string,string> = {
  world_models:"world models", jepa:"JEPA", imagebind:"ImageBind", v_jepa:"V-JEPA",
  pred_coding:"pred coding", hamiltonian:"Hamiltonian", train_dynamics:"train dyn", foundation_wm:"found. WM"
};

export default function Page(){
  const [graph,setGraph]=useState<GraphData>({nodes:[],edges:[]});
  const [papers,setPapers]=useState<any[]>([]);
  const [filterTopic,setFilterTopic]=useState("all");
  const [filterArch,setFilterArch]=useState("all");
  const [search,setSearch]=useState("");
  const [selected,setSelected]=useState<GraphNode|null>(null);
  const svgRef=useRef<SVGSVGElement>(null);
  const [dims,setDims]=useState({w:900,h:560});

  useEffect(()=>{
    fetch("/data/graph.json").then(r=>r.json()).then(setGraph).catch(()=>{});
    fetch("/data/papers.json").then(r=>r.json()).then(setPapers).catch(()=>{});
    if(!svgRef.current) return;
    const ro=new ResizeObserver(()=>{
      if(svgRef.current){ const rect=svgRef.current.getBoundingClientRect(); setDims({w:rect.width||900,h:rect.height||560}); }
    });
    ro.observe(svgRef.current);
    return ()=>ro.disconnect();
  },[]);

  // physics
  useEffect(()=>{
    if(!graph.nodes.length) return;
    let raf=0;
    const nodes=graph.nodes.map(n=>({...n, x:n.x??Math.random()*dims.w, y:n.y??Math.random()*dims.h, vx:0, vy:0}));
    const map=new Map(nodes.map(n=>[n.id,n]));
    const edges=graph.edges;
    const step=()=>{
      for(let i=0;i<nodes.length;i++) for(let j=i+1;j<nodes.length;j++){
        const a=nodes[i], b=nodes[j];
        if(a.pinned&&b.pinned) continue;
        const dx=a.x!-b.x!, dy=a.y!-b.y!;
        let d2=dx*dx+dy*dy+0.1, d=Math.sqrt(d2); if(d<1) d=1;
        const f=1800/d2;
        const fx=dx/d*f, fy=dy/d*f;
        if(!a.pinned){ a.vx!+=fx; a.vy!+=fy; }
        if(!b.pinned){ b.vx!-=fx; b.vy!-=fy; }
      }
      for(const e of edges){
        const a=map.get(e.source) as any, b=map.get(e.target) as any; if(!a||!b) continue;
        const dx=b.x-a.x, dy=b.y-a.y, dist=Math.sqrt(dx*dx+dy*dy)+0.1;
        let ideal=78; if(e.kind==="AUTHORED") ideal=68; if(e.kind==="USES_ARCHITECTURE") ideal=96;
        const f=(dist-ideal)*0.02; const fx=dx/dist*f, fy=dy/dist*f;
        if(!a.pinned){ a.vx!+=fx; a.vy!+=fy; } if(!b.pinned){ b.vx!-=fx; b.vy!-=fy; }
      }
      for(const n of nodes){ if(n.pinned) continue; n.vx!+=(dims.w/2-n.x!)*0.001; n.vy!+=(dims.h/2-n.y!)*0.001; n.vx!*=0.92; n.vy!*=0.92; n.x!+=n.vx!; n.y!+=n.vy!; n.x!=Math.max(18,Math.min(dims.w-18,n.x!)); n.y!=Math.max(18,Math.min(dims.h-18,n.y!)); }
      setGraph(prev=>({nodes:nodes.map(n=>({...n})), edges:prev.edges}));
      raf=requestAnimationFrame(step);
    };
    raf=requestAnimationFrame(step);
    return ()=>cancelAnimationFrame(raf);
  // eslint-disable-next-line
  },[graph.nodes.length?1:0, dims.w, dims.h]);

  const filtered=useMemo(()=>{
    let nodes=graph.nodes, edges=graph.edges;
    if(search){ const q=search.toLowerCase(); const keep=new Set(nodes.filter(n=> (n.label+" "+(n.title||"")+" "+(n.name||"")).toLowerCase().includes(q)).map(n=>n.id)); for(const e of edges){ if(keep.has(e.source)||keep.has(e.target)){keep.add(e.source); keep.add(e.target);} } nodes=nodes.filter(n=>keep.has(n.id)); edges=edges.filter(e=>keep.has(e.source)&&keep.has(e.target)); }
    if(filterTopic!=="all"){ const keep=new Set<string>(); nodes.forEach(n=>{ if(n.query_tag===filterTopic||n.id===`topic:${filterTopic}`) keep.add(n.id); }); nodes.filter(n=>n.query_tag===filterTopic).forEach(n=>keep.add(n.id)); for(const e of graph.edges) if(keep.has(e.source)||keep.has(e.target)){keep.add(e.source); keep.add(e.target);} nodes=graph.nodes.filter(n=>keep.has(n.id)); edges=graph.edges.filter(e=>keep.has(e.source)&&keep.has(e.target)); if(search){ const q=search.toLowerCase(); const keep2=new Set(nodes.filter(n=> (n.label+" "+(n.title||"")+" "+(n.name||"")).toLowerCase().includes(q)).map(n=>n.id)); for(const e of edges) if(keep2.has(e.source)||keep2.has(e.target)){keep2.add(e.source); keep2.add(e.target);} nodes=nodes.filter(n=>keep2.has(n.id)); edges=edges.filter(e=>keep2.has(e.source)&&keep2.has(e.target)); } }
    if(filterArch!=="all"){ const aid=`arch:${filterArch}`; const keep=new Set([aid]); for(const e of graph.edges) if(e.source===aid||e.target===aid){keep.add(e.source); keep.add(e.target);} let n=graph.nodes.filter(x=>keep.has(x.id)); let ed=graph.edges.filter(e=>e.source===aid||e.target===aid); if(filterTopic!=="all"||search){ const ids=new Set(nodes.map(x=>x.id)); n=n.filter(x=>ids.has(x.id)); ed=ed.filter(e=>ids.has(e.source)&&ids.has(e.target)); } nodes=n; edges=ed; }
    return {nodes, edges};
  },[graph, filterTopic, filterArch, search]);

  const stats=useMemo(()=>({papers:papers.length, nodes:graph.nodes.length, edges:graph.edges.length, archs:graph.nodes.filter(n=>n.type==="Architecture").length, topics:graph.nodes.filter(n=>n.type==="Topic").length}),[graph,papers]);

  return (
    <div className="min-h-screen bg-[#f8f7f4] text-zinc-900">
      <header className="border-b border-zinc-200 bg-white/80 backdrop-blur sticky top-0 z-20">
        <div className="mx-auto max-w-[1600px] px-4 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-7 w-7 rounded-full bg-zinc-900 text-white grid place-items-center text-[12px] font-mono">A</div>
            <div>
              <div className="text-[15px] font-semibold tracking-tight flex items-center gap-2">arxiviq — ACNE × Graphify <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-900 text-white">DEMO</span></div>
              <div className="text-[11px] font-mono text-zinc-500">papers → TLPG → architectures → traverse, no vectors • ML training intel</div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-[11px] font-mono">
            <span className="px-2 py-1 rounded-full bg-zinc-900 text-white">{stats.papers} papers • {stats.nodes} nodes • {stats.edges} edges</span>
            <span className="px-2 py-1 rounded-full bg-zinc-100 border">{stats.archs} archs • {stats.topics} topics</span>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1600px] grid grid-cols-12 min-h-[calc(100vh-64px)]">
        <aside className="col-span-12 lg:col-span-3 border-r bg-white border-zinc-200 flex flex-col">
          <div className="p-3 border-b border-zinc-100 flex items-center gap-2">
            <div className="relative flex-1"><span className="absolute left-2 top-1.5 text-zinc-400 text-xs">⌕</span><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="search papers, authors, archs" className="w-full pl-6 pr-2 py-1.5 rounded-full bg-zinc-50 border text-[12px] font-mono outline-none" /></div>
            <button onClick={()=>{setSearch(""); setFilterTopic("all"); setFilterArch("all");}} className="text-[11px] font-mono px-2 py-1 rounded-full border">Reset</button>
          </div>
          <div className="p-3 border-b">
            <div className="text-[11px] font-mono font-semibold text-zinc-500 mb-2">TOPICS</div>
            <div className="flex flex-wrap gap-1.5">
              <button onClick={()=>setFilterTopic("all")} className={`px-2 py-1 rounded-full border text-[11px] font-mono ${filterTopic==="all"?"bg-zinc-900 text-white":"bg-white"}`}>all</button>
              {Object.entries(TOPIC_LABELS).map(([k,v])=><button key={k} onClick={()=>setFilterTopic(k)} className={`px-2 py-1 rounded-full border text-[11px] font-mono ${filterTopic===k?"bg-emerald-600 text-white":"bg-white"}`}>{v}</button>)}
            </div>
          </div>
          <div className="p-3 border-b">
            <div className="text-[11px] font-mono font-semibold text-zinc-500 mb-2">ARCHITECTURES</div>
            <div className="flex flex-wrap gap-1.5">
              {["all","Dreamer","JEPA","V-JEPA","ImageBind","Hamiltonian NN","World Model","PredCoding"].map(a=><button key={a} onClick={()=>setFilterArch(a)} className={`px-2 py-1 rounded-full border text-[11px] font-mono ${filterArch===a?"bg-amber-500 text-white":"bg-white"}`}>{a}</button>)}
            </div>
          </div>
          <div className="flex-1 overflow-auto p-2 space-y-2">
            <div className="text-[11px] font-mono font-semibold text-zinc-500 px-1">PAPERS • {papers.length||filtered.nodes.filter(n=>n.type==="Paper").length}</div>
            {(papers.length?papers:filtered.nodes.filter(n=>n.type==="Paper").map(n=>({id:n.id.replace("paper:",""), title:n.title||n.label, summary:n.abstract, query_tag:n.query_tag, authors:n.authors}))).slice(0,12).map((p:any,i:number)=>(
              <div key={p.id||i} className="rounded-[12px] border bg-white p-2.5 hover:border-zinc-300 cursor-pointer" onClick={()=>{const node=graph.nodes.find(n=>n.id===`paper:${p.id}`||n.id===p.id); if(node) setSelected(node as any);}}>
                <div className="text-[12px] font-medium leading-tight line-clamp-2">{p.title}</div>
                <div className="mt-1 text-[11px] font-mono text-zinc-500 line-clamp-1">{p.authors?.join(", ")||"authors"}</div>
              </div>
            ))}
          </div>
        </aside>

        <main className="col-span-12 lg:col-span-6 bg-[#fdfcf8] relative flex flex-col">
          <div className="flex items-center justify-between px-3 py-2 border-b bg-white/60 text-[11px] font-mono">
            <div>Force graph • {filtered.nodes.length} nodes • {filtered.edges.length} edges</div>
            <button onClick={()=>window.location.reload()} className="px-2 py-1 rounded-full border bg-white">Reheat</button>
          </div>
          <div className="flex-1 relative overflow-hidden">
            <svg ref={svgRef} width="100%" height="560" className="block">
              {filtered.edges.map((e,i)=>{ const a=filtered.nodes.find(n=>n.id===e.source) as any, b=filtered.nodes.find(n=>n.id===e.target) as any; if(!a||!b) return null; const col=e.kind==="AUTHORED"?"#38bdf8":e.kind==="USES_ARCHITECTURE"?"#f59e0b":e.kind==="RELATED_TO"?"#a1a1aa":"#8b5cf6"; return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={col} strokeWidth={1} opacity={0.6} />})}
              {filtered.nodes.map((n)=>{const isSel=selected?.id===n.id, col=(COLOR as any)[n.type]||"#71717a", r=n.type==="Architecture"?14:n.type==="Paper"?10:n.type==="Topic"?12:8; return (<g key={n.id} transform={`translate(${n.x},${n.y})`} onClick={()=>setSelected(n)} className="cursor-pointer">{n.type==="Paper"?<rect x={-10} y={-7} width={20} height={14} rx={2} fill={isSel?"#111":"#111827"} stroke="white" strokeWidth={1.5} />:n.type==="Architecture"?<polygon points={`0,-${r} ${r*0.9},${r*0.5} ${-r*0.9},${r*0.5}`} fill={isSel?"#d97706":col} stroke="white" strokeWidth={1.5} />:n.type==="Topic"?<circle r={r} fill="white" stroke={col} strokeWidth={2} strokeDasharray="3 3" />:<circle r={r} fill={isSel?"#111827":col} stroke="white" strokeWidth={1.5} /> }<text y={r+12} textAnchor="middle" fontSize={10} fill="#3f3f46">{(n.label||"").slice(0,18)}</text></g>)})}
            </svg>
          </div>
        </main>

        <aside className="col-span-12 lg:col-span-3 border-l bg-white border-zinc-200 flex flex-col">
          <div className="p-3 border-b">
            <div className="text-[11px] font-mono font-semibold text-zinc-500">INSPECTOR</div>
            {!selected && <div className="mt-2 text-[12px] text-zinc-500">Click a node • papers show abstract, people show affiliations</div>}
            {selected && (<div className="mt-2"><div className="inline-flex gap-2"><span className="px-1.5 py-0.5 rounded-full text-[10px] font-mono border">{selected.type}</span><span className="text-[10px] font-mono text-zinc-500">{selected.id}</span></div><div className="mt-1 text-[13px] font-semibold">{selected.title||selected.label}</div>{selected.abstract && <div className="mt-2 text-[12px] text-zinc-700 line-clamp-6">{selected.abstract}</div>}</div>)}
          </div>
          <div className="p-3 text-[11px] font-mono text-zinc-600">
            <div className="font-semibold">ABOUT ARXIVIQ</div>
            <div className="mt-1">World models • JEPA • ImageBind • Hamiltonian nets • training dynamics — tracked as they relate to training neural nets and ML modeling architectures.</div>
            <div className="mt-2">ACNE 0.2.1 for people (trigger resolver), Graphify for structure (god nodes, Leiden-like).</div>
          </div>
        </aside>
      </div>
    </div>
  );
}
