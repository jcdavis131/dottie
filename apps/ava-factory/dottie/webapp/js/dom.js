// DOM + formatting helpers. All data goes through textContent — never
// innerHTML — so model output and API payloads cannot inject markup.

/** h("div", {class: "x", onclick: fn}, child, "text", …) -> HTMLElement */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k in el && k !== "list" && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

/** A number, or the honest em-dash when the value isn't a real number. */
export function fmtNum(v, digits = 3) {
  if (typeof v !== "number" || !isFinite(v)) return "—";
  return v.toFixed(digits);
}

export function fmtInt(v) {
  if (typeof v !== "number" || !isFinite(v)) return "—";
  return Math.round(v).toLocaleString("en-US");
}

export function fmtCompact(v) {
  if (typeof v !== "number" || !isFinite(v)) return "—";
  if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (Math.abs(v) >= 1e4) return (v / 1e3).toFixed(0) + "k";
  return fmtInt(v);
}

/** Seconds -> "3s" / "4m 10s" / "2h 05m" / "1d 3h". */
export function fmtDur(s) {
  if (typeof s !== "number" || !isFinite(s) || s < 0) return "—";
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

/** Epoch ms -> "3s ago" style age. */
export function ago(t) {
  if (!t) return "never";
  return fmtDur((Date.now() - t) / 1000) + " ago";
}

/** Provenance chip — the page's signature honesty device. */
export function provChip({ ok, label, detail, at }) {
  const cls = ok ? "chip prov live" : "chip prov down";
  const parts = [h("span", { class: "dot", "aria-hidden": "true" })];
  parts.push(h("b", {}, ok ? "live" : "unreachable"));
  if (label) parts.push(` ${label}`);
  if (ok && at) parts.push(` · ${ago(at)}`);
  const chip = h("span", { class: cls, role: "status" }, ...parts);
  if (detail) chip.title = detail;
  return chip;
}

export function chip(text, cls = "") {
  return h("span", { class: `chip ${cls}` }, text);
}
