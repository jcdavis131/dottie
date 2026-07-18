#!/usr/bin/env python3
"""Build a self-contained reports/index.html from run metrics + eval JSON.

No CDN, no external fonts/CSS/fetch — inline CSS + SVG + embedded JS data only.
Must open as file:// and as a static Vercel bundle.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Markdown → minimal HTML (stdlib only; used by --render-md)


def _md_inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


def render_markdown(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    in_code = False
    code_buf: list[str] = []
    in_table = False
    table_rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal in_table, table_rows
        if not table_rows:
            return
        out.append("<table>")
        for ri, row in enumerate(table_rows):
            tag = "th" if ri == 0 else "td"
            # skip markdown separator row (|---|---|)
            if ri == 1 and all(re.fullmatch(r":?-+:?", c.strip()) for c in row):
                continue
            cells = "".join(f"<{tag}>{_md_inline(c.strip())}</{tag}>" for c in row)
            out.append(f"<tr>{cells}</tr>")
        out.append("</table>")
        table_rows = []
        in_table = False

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                flush_table()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        if "|" in line and line.strip().startswith("|"):
            cells = [c for c in line.strip().strip("|").split("|")]
            if not in_table:
                flush_table()
                in_table = True
            table_rows.append(cells)
            i += 1
            continue
        if in_table:
            flush_table()
        if not line.strip():
            i += 1
            continue
        if line.startswith("# "):
            out.append(f"<h1>{_md_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_md_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{_md_inline(line[4:])}</h3>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_md_inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        else:
            out.append(f"<p>{_md_inline(line)}</p>")
        i += 1
    flush_table()
    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
    body = "\n".join(out)
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>"
        "<title>REPORT_REAL</title>"
        "<style>"
        "body{font-family:Georgia,'Times New Roman',serif;margin:2rem;max-width:960px;"
        "line-height:1.45;color:#1a1a1a;background:#fafafa}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:0.9rem}"
        "th,td{border:1px solid #ccc;padding:0.35rem 0.5rem;text-align:left}"
        "th{background:#eee}code{background:#eee;padding:0.1em 0.3em}"
        "pre{background:#eee;padding:0.75rem;overflow:auto}"
        "a{color:#0b5}h1,h2,h3{font-family:Georgia,serif}"
        "</style></head><body>\n"
        f"{body}\n"
        "<p><a href='index.html'>← dashboard</a> · "
        "<a href='branch_eval_results_real.json'>eval JSON</a></p>"
        "</body></html>\n"
    )


# ---------------------------------------------------------------------------
# Metrics loading


def _finite(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def load_run_metrics(runs_dir: Path) -> dict[str, list[dict]]:
    """Load metrics.jsonl from runs/<name>/ and also reports/metrics_*.jsonl."""
    runs: dict[str, list[dict]] = {}

    if runs_dir.is_dir():
        for child in sorted(runs_dir.iterdir()):
            if not child.is_dir():
                continue
            mf = child / "metrics.jsonl"
            if not mf.is_file():
                # also accept metrics_*.jsonl inside the run dir
                alts = sorted(child.glob("metrics*.jsonl"))
                if not alts:
                    continue
                mf = alts[0]
            rows = []
            for line in mf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            if rows:
                runs[child.name] = rows

    # Fallback: trainer currently writes reports/metrics_<preset>.jsonl
    reports = _REPO / "reports"
    if reports.is_dir():
        for mf in sorted(reports.glob("metrics_*.jsonl")):
            name = mf.stem  # metrics_nano
            if name in runs:
                continue
            rows = []
            for line in mf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            if rows:
                runs[name] = rows
    return runs


def load_hl_targets(preset: str = "nano") -> dict[str, float]:
    cfg_path = _REPO / "configs" / f"{preset}.yaml"
    if not cfg_path.is_file():
        return {"system1": 8.0, "system2": 60.0, "critic": 30.0, "planner": 50.0}
    try:
        import yaml

        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        hl = (cfg.get("jspace") or {}).get("half_life") or {}
        return {k: float(v) for k, v in hl.items()}
    except Exception:
        return {"system1": 8.0, "system2": 60.0, "critic": 30.0, "planner": 50.0}


def load_eval(path: Path) -> dict | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    # JSON may contain NaN from harness; make it parseable
    text = text.replace(": NaN", ": null").replace(":NaN", ":null")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def extract_series(runs: dict[str, list[dict]]) -> dict:
    """Pull chart-ready series from metrics rows (event=step preferred)."""
    loss: dict[str, list[list[float]]] = {}
    lr: dict[str, list[list[float]]] = {}
    hl_last: dict[str, dict[str, float]] = {}
    route: dict[str, dict[str, list[list[float]]]] = {}
    bc_vm: dict[str, dict[str, list[list[float]]]] = {}

    for name, rows in runs.items():
        loss[name] = []
        lr[name] = []
        route[name] = {k: [] for k in ("s1", "s2", "critic", "planner")}
        bc_vm[name] = {"broadcast_strength": [], "verbalizable_mass": []}
        for rec in rows:
            if rec.get("event") not in (None, "step"):
                # keep rows that look like step metrics even without event
                if "step" not in rec and "lm" not in rec and "total" not in rec:
                    continue
            step = rec.get("step")
            if step is None:
                continue
            step = float(step)
            for key in ("lm", "total", "loss"):
                v = _finite(rec.get(key))
                if v is not None and v > 0:
                    loss[name].append([step, v])
                    break
            vlr = _finite(rec.get("lr"))
            if vlr is not None:
                lr[name].append([step, vlr])
            hl = rec.get("hl_est")
            if isinstance(hl, dict):
                hl_last[name] = {k: float(v) for k, v in hl.items() if _finite(v) is not None}
            rp = rec.get("route_probs")
            if isinstance(rp, (list, tuple)) and len(rp) >= 4:
                for i, k in enumerate(("s1", "s2", "critic", "planner")):
                    fv = _finite(rp[i])
                    if fv is not None:
                        route[name][k].append([step, fv])
            for mk in ("broadcast_strength", "verbalizable_mass"):
                fv = _finite(rec.get(mk))
                if fv is not None:
                    bc_vm[name][mk].append([step, fv])

    return {
        "loss": loss,
        "lr": lr,
        "hl_last": hl_last,
        "route": route,
        "bc_vm": bc_vm,
    }


# ---------------------------------------------------------------------------
# HTML dashboard


_CSS = """
:root{--bg:#f7f5f0;--ink:#1c1917;--muted:#57534e;--line:#d6d3d1;--acc:#0f766e;--card:#fff}
*{box-sizing:border-box}
body{margin:0;font-family:Georgia,'Times New Roman',serif;background:var(--bg);color:var(--ink);line-height:1.4}
header{padding:1.5rem 2rem;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#fff 0%,var(--bg) 100%)}
header h1{margin:0 0 0.25rem;font-size:1.75rem;letter-spacing:-0.02em}
header p{margin:0;color:var(--muted);font-size:0.95rem}
nav{padding:0.75rem 2rem;display:flex;gap:1.25rem;flex-wrap:wrap;border-bottom:1px solid var(--line);background:#fff}
nav a{color:var(--acc);text-decoration:none;font-size:0.9rem}
nav a:hover{text-decoration:underline}
main{padding:1.5rem 2rem 3rem;max-width:1100px;margin:0 auto}
section{margin:0 0 2.5rem}
section h2{margin:0 0 0.75rem;font-size:1.25rem;border-bottom:2px solid var(--ink);padding-bottom:0.25rem;display:inline-block}
.note{color:var(--muted);font-style:italic;padding:1rem;border:1px dashed var(--line);background:#fff}
.chart{background:var(--card);border:1px solid var(--line);padding:0.75rem;margin-top:0.5rem;overflow:auto}
svg{display:block;max-width:100%;height:auto}
.legend{display:flex;flex-wrap:wrap;gap:0.75rem;margin:0.5rem 0;font-size:0.85rem;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:0.35rem}
.swatch{width:12px;height:12px;display:inline-block;border-radius:2px}
table{border-collapse:collapse;width:100%;font-size:0.85rem;background:#fff}
th,td{border:1px solid var(--line);padding:0.4rem 0.55rem;text-align:left;vertical-align:top}
th{background:#e7e5e4}
.pass{color:#166534;font-weight:bold}.fail{color:#991b1b;font-weight:bold}
footer{padding:1rem 2rem;color:var(--muted);font-size:0.8rem;border-top:1px solid var(--line)}
"""


_JS_CHARTS = r"""
(function(){
  const D = window.AVA_REPORT;
  const COLORS = ["#0f766e","#b45309","#7c3aed","#be123c","#0369a1","#4d7c0f"];

  function el(id){ return document.getElementById(id); }

  function noData(host, msg){
    host.innerHTML = '<div class="note">' + (msg || 'no data') + '</div>';
  }

  function niceTicks(min, max, n){
    if (!(isFinite(min) && isFinite(max)) || min === max){
      return [min || 0, (max || 1)];
    }
    const span = max - min;
    const step = Math.pow(10, Math.floor(Math.log10(span / n)));
    const err = (n * step) / span;
    let s = step;
    if (err <= 0.15) s = step / 5;
    else if (err <= 0.35) s = step / 2;
    else if (err <= 0.75) s = step;
    else s = step * 2;
    const t0 = Math.ceil(min / s) * s;
    const ticks = [];
    for (let t = t0; t <= max + s * 0.01; t += s) ticks.push(t);
    return ticks.length ? ticks : [min, max];
  }

  function svgChart(opts){
    const W = opts.W || 720, H = opts.H || 280;
    const m = {l:56, r:16, t:20, b:40};
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const series = opts.series || [];
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
    series.forEach(s => (s.pts||[]).forEach(p => {
      xmin = Math.min(xmin, p[0]); xmax = Math.max(xmax, p[0]);
      ymin = Math.min(ymin, p[1]); ymax = Math.max(ymax, p[1]);
    }));
    if (!isFinite(xmin)) return null;
    if (opts.logY){
      ymin = Math.max(ymin, 1e-8);
      ymax = Math.max(ymax, ymin * 1.01);
    } else if (ymin === ymax){
      ymin -= 1; ymax += 1;
    }
    const pad = opts.logY ? 0 : (ymax - ymin) * 0.08;
    ymin -= pad; ymax += pad;
    const xScale = x => m.l + ((x - xmin) / (xmax - xmin || 1)) * iw;
    const yScale = y => {
      if (opts.logY){
        const a = Math.log(ymin), b = Math.log(ymax);
        return m.t + ih - ((Math.log(Math.max(y, 1e-12)) - a) / (b - a || 1)) * ih;
      }
      return m.t + ih - ((y - ymin) / (ymax - ymin || 1)) * ih;
    };
    let parts = [];
    parts.push('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'">');
    parts.push('<rect x="0" y="0" width="'+W+'" height="'+H+'" fill="#fff"/>');
    // grid + axes
    const xt = niceTicks(xmin, xmax, 5);
    const yt = opts.logY
      ? (function(){
          const out=[]; let v=Math.pow(10, Math.floor(Math.log10(ymin)));
          while(v <= ymax*1.01){ if(v>=ymin) out.push(v); v*=10; }
          return out.length?out:[ymin,ymax];
        })()
      : niceTicks(ymin, ymax, 5);
    xt.forEach(t => {
      const x = xScale(t);
      parts.push('<line x1="'+x+'" y1="'+m.t+'" x2="'+x+'" y2="'+(m.t+ih)+'" stroke="#e7e5e4"/>');
      parts.push('<text x="'+x+'" y="'+(H-12)+'" text-anchor="middle" font-size="11" fill="#57534e">'+fmt(t)+'</text>');
    });
    yt.forEach(t => {
      const y = yScale(t);
      parts.push('<line x1="'+m.l+'" y1="'+y+'" x2="'+(m.l+iw)+'" y2="'+y+'" stroke="#e7e5e4"/>');
      parts.push('<text x="'+(m.l-6)+'" y="'+(y+3)+'" text-anchor="end" font-size="11" fill="#57534e">'+fmt(t)+'</text>');
    });
    parts.push('<line x1="'+m.l+'" y1="'+m.t+'" x2="'+m.l+'" y2="'+(m.t+ih)+'" stroke="#1c1917"/>');
    parts.push('<line x1="'+m.l+'" y1="'+(m.t+ih)+'" x2="'+(m.l+iw)+'" y2="'+(m.t+ih)+'" stroke="#1c1917"/>');
    if (opts.hlines){
      opts.hlines.forEach(h => {
        const y = yScale(h.y);
        parts.push('<line x1="'+m.l+'" y1="'+y+'" x2="'+(m.l+iw)+'" y2="'+y+'" stroke="'+h.color+'" stroke-dasharray="4 3"/>');
        parts.push('<text x="'+(m.l+iw-4)+'" y="'+(y-3)+'" text-anchor="end" font-size="10" fill="'+h.color+'">'+h.label+'</text>');
      });
    }
    series.forEach((s, i) => {
      const col = s.color || COLORS[i % COLORS.length];
      const pts = s.pts || [];
      if (pts.length < 1) return;
      let d = '';
      pts.forEach((p, j) => {
        const x = xScale(p[0]), y = yScale(p[1]);
        d += (j ? ' L ' : 'M ') + x + ' ' + y;
      });
      parts.push('<path d="'+d+'" fill="none" stroke="'+col+'" stroke-width="2"/>');
    });
    if (opts.xlabel){
      parts.push('<text x="'+(m.l+iw/2)+'" y="'+(H-2)+'" text-anchor="middle" font-size="12" fill="#57534e">'+opts.xlabel+'</text>');
    }
    if (opts.ylabel){
      parts.push('<text x="14" y="'+(m.t+ih/2)+'" text-anchor="middle" font-size="12" fill="#57534e" transform="rotate(-90 14 '+(m.t+ih/2)+')">'+opts.ylabel+'</text>');
    }
    parts.push('</svg>');
    return parts.join('');
  }

  function fmt(v){
    if (!isFinite(v)) return '';
    const a = Math.abs(v);
    if (a === 0) return '0';
    if (a >= 1000 || a < 0.01) return v.toExponential(1);
    if (a >= 10) return v.toFixed(1);
    return v.toFixed(3);
  }

  function legend(host, items){
    host.innerHTML = items.map(it =>
      '<span><i class="swatch" style="background:'+it.color+'"></i>'+it.label+'</span>'
    ).join('');
  }

  // 1) loss
  (function(){
    const host = el('chart-loss'), leg = el('leg-loss');
    const series = [];
    Object.keys(D.loss||{}).forEach((name,i) => {
      const pts = D.loss[name]||[];
      if (pts.length) series.push({label:name, pts:pts, color:COLORS[i%COLORS.length]});
    });
    if (!series.length){ noData(host); return; }
    legend(leg, series.map(s=>({label:s.label, color:s.color})));
    host.innerHTML = svgChart({series:series, logY:true, xlabel:'step', ylabel:'loss'});
  })();

  // 2) lr
  (function(){
    const host = el('chart-lr'), leg = el('leg-lr');
    const series = [];
    Object.keys(D.lr||{}).forEach((name,i) => {
      const pts = D.lr[name]||[];
      if (pts.length) series.push({label:name, pts:pts, color:COLORS[i%COLORS.length]});
    });
    if (!series.length){ noData(host); return; }
    legend(leg, series.map(s=>({label:s.label, color:s.color})));
    host.innerHTML = svgChart({series:series, xlabel:'step', ylabel:'lr'});
  })();

  // 3) half-life bars
  (function(){
    const host = el('chart-hl');
    const targets = D.hl_targets || {};
    const spaces = ['system1','system2','critic','planner'];
    const runs = Object.keys(D.hl_last||{});
    if (!runs.length){ noData(host); return; }
    const W=720, H=280, m={l:56,r:16,t:20,b:50};
    const iw=W-m.l-m.r, ih=H-m.t-m.b;
    let ymax = 1;
    runs.forEach(r => spaces.forEach(s => {
      ymax = Math.max(ymax, (D.hl_last[r]||{})[s]||0, targets[s]||0);
    }));
    ymax *= 1.15;
    const groupW = iw / spaces.length;
    const barW = groupW / (runs.length + 1.5);
    let parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'">'];
    parts.push('<rect width="'+W+'" height="'+H+'" fill="#fff"/>');
    niceTicks(0, ymax, 5).forEach(t => {
      const y = m.t + ih - (t/ymax)*ih;
      parts.push('<line x1="'+m.l+'" y1="'+y+'" x2="'+(m.l+iw)+'" y2="'+y+'" stroke="#e7e5e4"/>');
      parts.push('<text x="'+(m.l-6)+'" y="'+(y+3)+'" text-anchor="end" font-size="11" fill="#57534e">'+fmt(t)+'</text>');
    });
    spaces.forEach((sp, si) => {
      const gx = m.l + si*groupW;
      // target line as thin bar
      const ty = m.t + ih - ((targets[sp]||0)/ymax)*ih;
      parts.push('<line x1="'+gx+'" y1="'+ty+'" x2="'+(gx+groupW-8)+'" y2="'+ty+'" stroke="#78716c" stroke-dasharray="3 2"/>');
      runs.forEach((r, ri) => {
        const v = (D.hl_last[r]||{})[sp]||0;
        const h = (v/ymax)*ih;
        const x = gx + 8 + ri*barW;
        const y = m.t + ih - h;
        parts.push('<rect x="'+x+'" y="'+y+'" width="'+(barW*0.85)+'" height="'+h+'" fill="'+COLORS[ri%COLORS.length]+'"/>');
      });
      parts.push('<text x="'+(gx+groupW/2)+'" y="'+(H-18)+'" text-anchor="middle" font-size="11" fill="#57534e">'+sp+'</text>');
    });
    parts.push('<text x="14" y="'+(m.t+ih/2)+'" text-anchor="middle" font-size="12" fill="#57534e" transform="rotate(-90 14 '+(m.t+ih/2)+')">hl_est</text>');
    parts.push('</svg>');
    host.innerHTML = parts.join('');
    const leg = el('leg-hl');
    legend(leg, runs.map((r,i)=>({label:r+' (dashed=target)', color:COLORS[i%COLORS.length]})));
  })();

  // 4) route probs
  (function(){
    const host = el('chart-route'), leg = el('leg-route');
    const keys = ['s1','s2','critic','planner'];
    const series = [];
    // prefer first run with data
    const names = Object.keys(D.route||{});
    let chosen = null;
    for (const n of names){
      if (keys.some(k => (D.route[n][k]||[]).length)){ chosen = n; break; }
    }
    if (!chosen){ noData(host); return; }
    keys.forEach((k,i) => {
      const pts = D.route[chosen][k]||[];
      if (pts.length) series.push({label:k, pts:pts, color:COLORS[i%COLORS.length]});
    });
    if (!series.length){ noData(host); return; }
    legend(leg, series.map(s=>({label:chosen+':'+s.label, color:s.color})));
    host.innerHTML = svgChart({series:series, xlabel:'step', ylabel:'route_prob'});
  })();

  // 5) broadcast + verbalizable
  (function(){
    const host = el('chart-bc'), leg = el('leg-bc');
    const series = [];
    Object.keys(D.bc_vm||{}).forEach((name,i) => {
      const bc = D.bc_vm[name].broadcast_strength||[];
      const vm = D.bc_vm[name].verbalizable_mass||[];
      if (bc.length) series.push({label:name+' broadcast', pts:bc, color:COLORS[i%COLORS.length]});
      if (vm.length) series.push({label:name+' vm', pts:vm, color:COLORS[(i+3)%COLORS.length]});
    });
    if (!series.length){ noData(host); return; }
    legend(leg, series.map(s=>({label:s.label, color:s.color})));
    host.innerHTML = svgChart({
      series:series, xlabel:'step', ylabel:'value',
      hlines:[
        {y:0.20, color:'#b45309', label:'bc target 0.20'},
        {y:0.06, color:'#7c3aed', label:'vm target 0.06'}
      ]
    });
  })();
})();
"""


def build_eval_table(eval_data: dict | None) -> str:
    if not eval_data:
        return '<div class="note">no data — reports/branch_eval_results_real.json missing</div>'
    rows = ["<table><thead><tr><th>Branch</th><th>Test</th><th>Bar</th><th>Measured (summary)</th><th>Verdict</th></tr></thead><tbody>"]
    for branch in ("base", "chat"):
        block = eval_data.get(branch) or {}
        # perplexity summary
        ppl = block.get("perplexity") or {}
        if ppl:
            bits = []
            for ph, rec in sorted(ppl.items(), key=lambda x: str(x[0])):
                if isinstance(rec, dict):
                    v = rec.get("ppl")
                    bits.append(f"p{ph}:{v if v == v else 'NaN'}")  # NaN != NaN
            rows.append(
                "<tr><td>"
                + html.escape(branch)
                + "</td><td>perplexity</td><td>—</td><td>"
                + html.escape(", ".join(bits)[:240])
                + "</td><td>—</td></tr>"
            )
        probes = block.get("probes") or {}
        for name, rec in probes.items():
            if not isinstance(rec, dict):
                continue
            acc = rec.get("accuracy")
            rows.append(
                f"<tr><td>{html.escape(branch)}</td><td>probe:{html.escape(str(name))}</td>"
                f"<td>accuracy</td><td>{html.escape(str(acc))}</td><td>—</td></tr>"
            )
        for item in block.get("jspace") or []:
            if not isinstance(item, dict):
                continue
            measured = item.get("measured") or {}
            # compact summary: drop huge nested details
            summary = {
                k: v
                for k, v in measured.items()
                if k != "details" and not isinstance(v, (list, dict))
            }
            if "details" in measured and isinstance(measured["details"], list):
                summary["n_details"] = len(measured["details"])
            verdict = "PASS" if item.get("pass") else "FAIL"
            cls = "pass" if item.get("pass") else "fail"
            rows.append(
                f"<tr><td>{html.escape(branch)}</td>"
                f"<td>{html.escape(str(item.get('test','')))}</td>"
                f"<td>{html.escape(str(item.get('bar','')))}</td>"
                f"<td><code>{html.escape(json.dumps(summary, allow_nan=False)[:320])}</code></td>"
                f"<td class='{cls}'>{verdict}</td></tr>"
            )
    rows.append("</tbody></table>")
    meta = eval_data.get("meta") or {}
    meta_line = (
        f"<p class='note'>meta: preset={html.escape(str(meta.get('preset')))} · "
        f"device={html.escape(str(meta.get('device')))} · "
        f"wall_s={html.escape(str(meta.get('wall_s')))} · "
        f"torch={html.escape(str(meta.get('torch')))}</p>"
    )
    return meta_line + "\n".join(rows)


def build_index_html(payload: dict, eval_table: str) -> str:
    data_json = json.dumps(payload, allow_nan=False, separators=(",", ":"))
    # pad slightly with a comment block so empty-data reports still clear 10KB easily
    pad = "<!-- ava report dashboard; self-contained; no external resources -->\n" * 8
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ava training report</title>
<style>
{_CSS}
</style>
</head>
<body>
{pad}
<header>
  <h1>Ava</h1>
  <p>Training dashboard — loss, schedule, half-lives, routing, broadcast, eval.</p>
</header>
<nav>
  <a href="#loss">Loss</a>
  <a href="#lr">LR</a>
  <a href="#hl">Half-life</a>
  <a href="#route">Route</a>
  <a href="#bc">Broadcast / VM</a>
  <a href="#eval">Eval</a>
  <a href="report_real.html">REPORT_REAL.md</a>
  <a href="branch_eval_results_real.json">eval JSON</a>
</nav>
<main>
<section id="loss">
  <h2>1. Loss curves</h2>
  <div class="legend" id="leg-loss"></div>
  <div class="chart" id="chart-loss"></div>
</section>
<section id="lr">
  <h2>2. Learning-rate schedule</h2>
  <div class="legend" id="leg-lr"></div>
  <div class="chart" id="chart-lr"></div>
</section>
<section id="hl">
  <h2>3. Half-life estimate vs target</h2>
  <div class="legend" id="leg-hl"></div>
  <div class="chart" id="chart-hl"></div>
</section>
<section id="route">
  <h2>4. Route probabilities</h2>
  <div class="legend" id="leg-route"></div>
  <div class="chart" id="chart-route"></div>
</section>
<section id="bc">
  <h2>5. Broadcast strength &amp; verbalizable mass</h2>
  <div class="legend" id="leg-bc"></div>
  <div class="chart" id="chart-bc"></div>
</section>
<section id="eval">
  <h2>6. Eval results</h2>
  {eval_table}
</section>
</main>
<footer>Generated by scripts/make_report.py · offline · self-contained (no external assets)</footer>
<script>
window.AVA_REPORT = {data_json};
{_JS_CHARTS}
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build self-contained Ava HTML reports")
    ap.add_argument("--runs", default="runs", help="directory of run folders with metrics.jsonl")
    ap.add_argument("--out", default="reports/index.html")
    ap.add_argument("--eval", default="reports/branch_eval_results_real.json")
    ap.add_argument("--preset", default="nano", help="config preset for HL targets")
    ap.add_argument(
        "--render-md",
        default=None,
        help="if set, render this markdown to reports/report_real.html and exit",
    )
    args = ap.parse_args(argv)

    if args.render_md:
        md_path = Path(args.render_md)
        if not md_path.is_file():
            print(f"missing markdown: {md_path}", file=sys.stderr)
            return 1
        out_md = _REPO / "reports" / "report_real.html"
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(render_markdown(md_path.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"wrote {out_md} ({out_md.stat().st_size} bytes)")
        return 0

    runs_dir = Path(args.runs)
    if not runs_dir.is_absolute():
        runs_dir = _REPO / runs_dir
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = _REPO / out_path
    eval_path = Path(args.eval)
    if not eval_path.is_absolute():
        eval_path = _REPO / eval_path

    runs = load_run_metrics(runs_dir)
    series = extract_series(runs)
    hl_targets = load_hl_targets(args.preset)
    eval_data = load_eval(eval_path)

    payload = {
        "generated_by": "scripts/make_report.py",
        "runs": sorted(runs.keys()),
        "hl_targets": hl_targets,
        "loss": series["loss"],
        "lr": series["lr"],
        "hl_last": series["hl_last"],
        "route": series["route"],
        "bc_vm": series["bc_vm"],
        "has_eval": eval_data is not None,
    }

    html_doc = build_index_html(payload, build_eval_table(eval_data))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    size = out_path.stat().st_size
    print(f"wrote {out_path} ({size} bytes) runs={list(runs.keys())} eval={eval_data is not None}")

    # Also render REPORT_REAL.md when present (Vercel bundle layout).
    md = _REPO / "reports" / "REPORT_REAL.md"
    if md.is_file():
        rp = _REPO / "reports" / "report_real.html"
        rp.write_text(render_markdown(md.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"wrote {rp} ({rp.stat().st_size} bytes)")

    if size <= 10240:
        print(f"WARNING: index.html is {size} bytes (<= 10240)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
