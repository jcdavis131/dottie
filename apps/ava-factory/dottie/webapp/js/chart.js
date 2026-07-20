// Minimal SVG line chart following the dataviz mark specs: 2px line,
// recessive grid, selective direct label (last value only), crosshair +
// tooltip on hover, honest empty state. Single series per chart — the title
// names it, so no legend box (per the skill's ≥2-series rule).

import { h, clear, fmtNum } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/**
 * Render (or re-render) a line chart into `host`.
 * @param host    element with class chart-host
 * @param opts    { x: number[], y: (number|null)[], colorVar, unit, digits, xLabel }
 */
export function lineChart(host, opts) {
  clear(host);
  const { x = [], y = [], colorVar = "--chart-1", unit = "", digits = 3, xLabel = "step" } = opts;

  // Pair and drop nulls — a gap in telemetry is a gap, not a zero.
  const pts = [];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const xv = x[i], yv = y[i];
    if (typeof xv === "number" && isFinite(xv) && typeof yv === "number" && isFinite(yv)) {
      pts.push([xv, yv]);
    }
  }
  if (pts.length < 2) {
    host.append(h("div", { class: "chart-empty" },
      pts.length === 1
        ? `only one point so far (${xLabel} ${pts[0][0]}: ${fmtNum(pts[0][1], digits)}${unit}) — a line needs two`
        : "no step metrics in the current window"));
    return;
  }

  const W = Math.max(240, host.clientWidth || 320);
  const H = 96;
  const padL = 6, padR = 58, padT = 10, padB = 14;

  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  let xMin = Math.min(...xs), xMax = Math.max(...xs);
  let yMin = Math.min(...ys), yMax = Math.max(...ys);
  if (xMax === xMin) xMax = xMin + 1;
  if (yMax === yMin) { yMax += Math.abs(yMax) * 0.05 || 1; yMin -= Math.abs(yMin) * 0.05 || 1; }
  const yPad = (yMax - yMin) * 0.08;
  yMin -= yPad; yMax += yPad;

  const sx = (v) => padL + ((v - xMin) / (xMax - xMin)) * (W - padL - padR);
  const sy = (v) => padT + (1 - (v - yMin) / (yMax - yMin)) * (H - padT - padB);

  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, width: W, height: H,
    role: "img", "aria-label": `${xLabel} series, latest ${fmtNum(ys[ys.length - 1], digits)}${unit}`,
  });

  const css = getComputedStyle(document.documentElement);
  const stroke = css.getPropertyValue(colorVar).trim() || "#2160a4";
  const gridColor = css.getPropertyValue("--line-soft").trim() || "#e7e2d2";
  const faint = css.getPropertyValue("--faint").trim() || "#97917e";

  // Recessive grid: three horizontal hairlines with min/mid/max labels.
  const gridVals = [yMin + yPad, (yMin + yMax) / 2, yMax - yPad];
  for (const gv of gridVals) {
    const gy = sy(gv);
    svg.append(svgEl("line", { x1: padL, x2: W - padR + 4, y1: gy, y2: gy, stroke: gridColor, "stroke-width": 1 }));
    const lbl = svgEl("text", { x: W - padR + 8, y: gy + 3, "font-size": 9, fill: faint, "font-family": "Cascadia Mono, Consolas, monospace" });
    lbl.textContent = fmtNum(gv, digits <= 1 ? digits : Math.min(digits, 2));
    svg.append(lbl);
  }

  const d = pts.map(([px, py], i) => `${i ? "L" : "M"}${sx(px).toFixed(1)},${sy(py).toFixed(1)}`).join("");
  svg.append(svgEl("path", { d, fill: "none", stroke, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

  // Direct label: last value only (selective labeling, never every point).
  const [lx, ly] = pts[pts.length - 1];
  svg.append(svgEl("circle", { cx: sx(lx), cy: sy(ly), r: 3, fill: stroke, stroke: css.getPropertyValue("--card").trim() || "#fff", "stroke-width": 2 }));
  const endLbl = svgEl("text", {
    x: Math.min(sx(lx) + 6, W - 2), y: Math.max(10, sy(ly) - 6),
    "font-size": 10, "font-weight": 600, fill: stroke,
    "font-family": "Cascadia Mono, Consolas, monospace",
  });
  endLbl.textContent = fmtNum(ly, digits) + unit;
  svg.append(endLbl);

  // Hover layer: crosshair + tooltip, hit target = whole plot.
  const cross = svgEl("line", { y1: padT, y2: H - padB, stroke: faint, "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" });
  const hoverDot = svgEl("circle", { r: 3.5, fill: stroke, stroke: css.getPropertyValue("--card").trim() || "#fff", "stroke-width": 2, visibility: "hidden" });
  svg.append(cross, hoverDot);
  const tip = h("div", { class: "chart-tip", hidden: true });
  host.append(svg, tip);

  svg.addEventListener("pointermove", (ev) => {
    const rect = svg.getBoundingClientRect();
    const px = ((ev.clientX - rect.left) / rect.width) * W;
    let best = 0, bestD = Infinity;
    for (let i = 0; i < pts.length; i++) {
      const dd = Math.abs(sx(pts[i][0]) - px);
      if (dd < bestD) { bestD = dd; best = i; }
    }
    const [bx, by] = pts[best];
    cross.setAttribute("x1", sx(bx)); cross.setAttribute("x2", sx(bx));
    cross.setAttribute("visibility", "visible");
    hoverDot.setAttribute("cx", sx(bx)); hoverDot.setAttribute("cy", sy(by));
    hoverDot.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.textContent = `${xLabel} ${bx} · ${fmtNum(by, digits)}${unit}`;
    tip.style.left = `${(sx(bx) / W) * rect.width}px`;
    tip.style.top = `${(sy(by) / H) * rect.height}px`;
  });
  svg.addEventListener("pointerleave", () => {
    cross.setAttribute("visibility", "hidden");
    hoverDot.setAttribute("visibility", "hidden");
    tip.hidden = true;
  });
}

/** Keep a chart sized to its host; re-renders with the latest data. */
export function autoChart(host, getOpts) {
  const render = () => lineChart(host, getOpts());
  if (typeof ResizeObserver !== "undefined") {
    let w = host.clientWidth;
    const ro = new ResizeObserver(() => {
      if (Math.abs(host.clientWidth - w) > 24) { w = host.clientWidth; render(); }
    });
    ro.observe(host);
  }
  render();
  return render;
}
