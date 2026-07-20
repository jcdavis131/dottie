// Operations view: trainer live metrics, research ledger (:8100, optional),
// trust policy + tool catalog + telemetry. Every card carries a provenance
// chip; an unreachable source renders as an explicit unreachable block with
// the real error — never a stale number pretending to be fresh.

import { h, clear, chip, provChip, fmtNum, fmtInt, fmtCompact, fmtDur, ago } from "../dom.js";
import { live, bus } from "../state.js";
import { lineChart } from "../chart.js";

const TAIL = 120; // chart tail — enough shape without smearing the axis

function tile(k, v, u = "") {
  return h("div", { class: "tile" },
    h("div", { class: "k" }, k),
    h("div", { class: "v" }, v, u ? h("span", { class: "u" }, ` ${u}`) : null));
}

function unreachable(what, error, extra) {
  return h("div", { class: "unreach" },
    h("b", {}, "unreachable"), ` — ${what}`,
    h("div", {}, error || "no response"),
    extra ? h("div", { class: "note" }, extra) : null);
}

// ------------------------------------------------------------------ trainer

function trainerCard(subs) {
  const body = h("div", {});
  const card = h("section", { class: "card wide" },
    h("div", { class: "card-head" }, h("h2", {}, "Factory trainer"), h("span", { class: "prov-slot" })),
    body);

  function render(slot) {
    const provSlot = card.querySelector(".prov-slot");
    clear(provSlot).append(provChip({
      ok: slot.ok, label: "· GET /pipeline/status", at: slot.at,
      detail: slot.ok ? `preset ${slot.data?.preset}` : slot.error,
    }));
    clear(body);
    if (!slot.ok) {
      body.append(unreachable(":8000 /pipeline/status", slot.error));
      return;
    }
    const d = slot.data;
    const t = d.trainer || {};
    const last = t.last || {};
    const mode = d.mode || {};

    body.append(h("div", { class: `mode-banner ${mode.id || ""}` },
      h("b", {}, mode.label || "unknown mode"),
      t.age_s != null ? chip(`last event ${fmtDur(t.age_s)} ago`) : null,
      t.restarts_window ? chip(`${t.restarts_window} restarts in window`, t.restarts_window > 5 ? "stamp-warn" : "") : null,
      h("div", { class: "detail" }, mode.detail || "")));

    const phase = last.phase;
    body.append(h("div", { class: "tiles" },
      tile("step", fmtInt(last.step)),
      tile("lm loss", fmtNum(typeof last.lm_loss === "number" ? last.lm_loss : last.lm, 4)),
      tile("tok/s", typeof last.tok_s === "number" ? fmtInt(last.tok_s) : "—"),
      tile("phase", phase != null ? `P${phase}` : "—"),
      tile("tokens", fmtCompact(last.tokens)),
      tile("grad norm", fmtNum(last.grad_norm, 2)),
    ));

    const series = t.series || {};
    const xs = (series.step || []).slice(-TAIL);
    for (const [key, colorVar, unit, digits, title] of [
      ["lm_loss", "--chart-1", "", 4, "lm loss — current run"],
      ["tok_s", "--chart-2", "", 0, "throughput tok/s — current run"],
    ]) {
      const host = h("div", { class: "chart-host" });
      body.append(h("div", { class: "chart-block" },
        h("div", { class: "chart-title" },
          h("span", { class: "swatch", style: `background:var(${colorVar})` }), title),
        host));
      // Render after attach so clientWidth is real.
      requestAnimationFrame(() =>
        lineChart(host, { x: xs, y: (series[key] || []).slice(-TAIL), colorVar, unit, digits, xLabel: "step" }));
    }

    const timing = d.watch?.timing;
    const ckptFiles = d.ckpt?.files || [];
    const newest = ckptFiles[0];
    const kv = h("dl", { class: "kv" });
    if (timing) {
      kv.append(h("dt", {}, "eta"), h("dd", {},
        `${fmtDur(timing.eta_remaining_s)} remaining `,
        h("span", { class: "sub" }, `(median ${fmtInt(timing.tok_s)} tok/s, ${fmtCompact(timing.tokens_remaining)} tokens left)`)));
    }
    kv.append(h("dt", {}, "checkpoint"), h("dd", {},
      d.ckpt?.latest_pointer || "—",
      newest ? h("span", { class: "sub" }, ` · newest file ${newest.name} (${fmtDur(newest.age_s)} old)`) : null));
    kv.append(h("dt", {}, "preset"), h("dd", {}, `${d.preset || "—"}`,
      h("span", { class: "sub" }, ` · trainer phase P${d.flow?.trainer_phase ?? "—"} → target P${d.flow?.target_phase ?? "—"}`)));
    if (d.disk) {
      const low = d.disk.below_low_water;
      kv.append(h("dt", {}, "host disk"), h("dd", { class: low ? "" : "" },
        `${fmtNum(d.disk.free_gb, 1)} GB free `,
        h("span", { class: "sub" }, `(low-water ${d.disk.low_water_gb} GB)`),
        low ? " " : null, low ? chip("below low-water", "stamp-bad") : null));
    }
    body.append(kv);
  }

  subs.push(bus.on("pipeline", render));
  if (live.pipeline.at) render(live.pipeline);
  else body.append(h("div", { class: "chart-empty" }, "waiting for first /pipeline/status poll…"));
  return card;
}

// ------------------------------------------------------------------ research

function researchCard(subs) {
  const body = h("div", {});
  const card = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Research ledger"), h("span", { class: "prov-slot" })),
    body);

  function render(slot) {
    const provSlot = card.querySelector(".prov-slot");
    clear(provSlot).append(provChip({
      ok: slot.ok,
      label: slot.ok ? `· :8100 via ${slot.source}` : "· :8100",
      at: slot.at,
      detail: slot.ok ? slot.sourceUrl : slot.error,
    }));
    clear(body);
    if (!slot.ok) {
      body.append(unreachable("research service (:8100 /research/status)", slot.error,
        "Optional service — the console runs fine without it. Direct fetch needs this origin in DOTTIE_CORS_ORIGINS; the /research/status proxy on :8000 needs the service reachable from the server container."));
      return;
    }
    const d = slot.data || {};
    const b = d.baseline;
    const counts = d.counts || {};
    body.append(h("div", { class: "tiles" },
      tile("baseline", b ? fmtNum(b.metric_value, 5) : "—"),
      tile("sota", fmtInt(counts.sota)),
      tile("experiments", fmtInt(counts.total)),
    ));
    const kv = h("dl", { class: "kv" });
    if (b) {
      kv.append(h("dt", {}, "metric"), h("dd", {}, `${b.metric_name} ${b.higher_is_better ? "(higher wins)" : "(lower wins)"}`));
      if (b.notes) kv.append(h("dt", {}, "sota note"), h("dd", {}, h("span", { class: "sub" }, b.notes)));
      if (b.updated_ts) kv.append(h("dt", {}, "updated"), h("dd", {}, ago(b.updated_ts * 1000)));
    } else {
      kv.append(h("dt", {}, "baseline"), h("dd", {}, "none recorded yet"));
    }
    kv.append(h("dt", {}, "states"), h("dd", {}, h("span", { class: "sub" },
      ["pending", "ready_for_training", "evaluation_pending", "rejected", "failed_validation", "failed_training"]
        .filter((k) => counts[k])
        .map((k) => `${k.replace(/_/g, " ")} ${counts[k]}`)
        .join(" · ") || "—")));
    body.append(kv);

    const exps = (d.experiments || []).slice(0, 5);
    if (exps.length) {
      body.append(h("table", { class: "tbl" },
        h("thead", {}, h("tr", {}, h("th", {}, "experiment"), h("th", {}, "state"), h("th", { class: "num" }, "Δ"))),
        h("tbody", {}, exps.map((e) => h("tr", {},
          h("td", { title: e.id || "" }, e.name || e.id || "—"),
          h("td", { class: "mono" },
            e.state === "sota" ? chip("SOTA", "stamp-ok")
            : e.state?.startsWith("failed") ? chip(e.state, "stamp-warn")
            : e.state === "rejected" ? chip("rejected", "stamp-bad")
            : chip(e.state || "—")),
          h("td", { class: "num" }, e.delta != null ? fmtNum(e.delta, 4) : "—"))))));
    }
    if (d.note) body.append(h("div", { class: "note" }, d.note));
  }

  subs.push(bus.on("research", render));
  if (live.research.at) render(live.research);
  else body.append(h("div", { class: "chart-empty" }, "waiting for first research poll…"));
  return card;
}

// ------------------------------------------------------------------ trust

function trustCard(subs) {
  const body = h("div", {});
  const card = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Trust policy · tools"), h("span", { class: "prov-slot" })),
    body);

  function render(slot) {
    const provSlot = card.querySelector(".prov-slot");
    clear(provSlot).append(provChip({ ok: slot.ok, label: "· GET /assistant/status", at: slot.at, detail: slot.error || "" }));
    clear(body);
    if (!slot.ok) {
      body.append(unreachable(":8000 /assistant/status", slot.error));
      return;
    }
    const d = slot.data;
    const tr = d.trust || {};
    body.append(h("div", { class: "mode-row", style: "margin-bottom:.6rem" },
      chip(tr.enforcement || "enforcement unknown"),
      chip(`auth ${tr.auth || "?"}`, tr.auth === "on" ? "stamp-ok" : ""),
      chip(`${tr.read_only_tools ?? "?"} read-only`),
      chip(`${tr.sandboxed_tools ?? "?"} sandboxed`)));
    const tools = d.tools || [];
    body.append(h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, h("th", {}, "signature"), h("th", {}, "does"), h("th", {}, ""))),
      h("tbody", {}, tools.map((t) => h("tr", {},
        h("td", { class: "mono" }, t.signature || t.name),
        h("td", {}, h("span", { class: "sub" }, t.description || "")),
        h("td", {}, t.sandboxed === "True" ? chip("sandboxed", "stamp-ok") : null))))));
    if (tr.sandbox_root) body.append(h("div", { class: "note" }, "sandbox root: ", h("code", {}, tr.sandbox_root)));
  }

  subs.push(bus.on("assistant", render));
  if (live.assistant.at) render(live.assistant);
  else body.append(h("div", { class: "chart-empty" }, "waiting for first /assistant/status poll…"));
  return card;
}

// ------------------------------------------------------------------ telemetry

function telemetryCard(subs) {
  const body = h("div", {});
  const card = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Assistant telemetry"), h("span", { class: "prov-slot" })),
    body);

  function render(slot) {
    const provSlot = card.querySelector(".prov-slot");
    clear(provSlot).append(provChip({ ok: slot.ok, label: "· audit ledger tail", at: slot.at, detail: slot.error || "" }));
    clear(body);
    if (!slot.ok) {
      body.append(unreachable(":8000 /assistant/status", slot.error));
      return;
    }
    const tel = slot.data?.telemetry || {};
    const events = (tel.recent || []).slice(-10).reverse();
    const counts = tel.counts || {};
    body.append(h("div", { class: "mode-row", style: "margin-bottom:.6rem" },
      chip(`${tel.total_seen ?? 0} events in tail`),
      ...Object.entries(counts).map(([k, v]) => chip(`${k} ${v}`))));
    if (!events.length) {
      body.append(h("div", { class: "chart-empty" }, "no events in the audit tail yet — talk to Dottie and they will appear here"));
      return;
    }
    body.append(h("div", { class: "feed" }, events.map((e) => h("div", { class: "ev" },
      h("span", { class: "ts" }, (e.ts || "").replace("T", " ").replace(/\.\d+Z?$/, "")),
      h("b", {}, e.action || "?"),
      h("span", { class: "tgt" }, e.target || ""),
      e.status === "denied" ? chip("denied", "stamp-bad") : e.status && e.status !== "ok" ? chip(e.status, "stamp-warn") : null))));
  }

  subs.push(bus.on("assistant", render));
  if (live.assistant.at) render(live.assistant);
  return card;
}

export function mountOps(root) {
  const subs = [];
  const grid = h("div", { class: "ops-grid" },
    trainerCard(subs), researchCard(subs), trustCard(subs), telemetryCard(subs));
  clear(root).append(h("div", { class: "ops" }, grid));
  return () => subs.forEach((u) => u());
}
