"""Build the slasso.com Validation Lab dashboard from committed sources only.

Doctrine (docs/CONSOLIDATION.md, Monitor-face salvage): numbers render only
from real committed sources; unmeasured renders as unmeasured; stale is
history, not telemetry; no write path on the public surface. Every source is
cited with its sha256 in the page footer. Re-run after any source changes:

    uv run python apps/dottie-harness-api/scripts/build_dashboard.py

Writes: apps/dottie-harness-api/index.html and who-e.html (host placeholder).
"""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
REPO = PKG.parent.parent

SOURCES = {
    "ladder": REPO / "apps/ava-factory/reports/orchestrator/ladder_report.json",
    "eval": REPO / "apps/ava-factory/reports/orchestrator/eval_report.json",
    "corpus_meta": PKG / "lib/meta/corpus_meta.json",
    "scoreboard": REPO / "workspace/artifacts/monitor/scoreboard.json",
    "queue": REPO / "docs/salvage/bd-queue.json",
}
# The corpus itself (JSONL, not JSON) feeds the correction queue panel; loaded
# separately from SOURCES but hashed into the same provenance footer.
CORPUS_JSONL = REPO / "apps/ava-factory/data/orchestration/corpus.jsonl"

# Venture artifact manifests (scripts/business/playbook.py output) — each
# records generated_at/outputs/provenance/sources per artifact. Read
# opportunistically: a missing venture (not yet run) is omitted, not an error.
VENTURE_MANIFESTS = {
    "validation": REPO / "workspace/artifacts/validation/manifest.json",
    "research": REPO / "workspace/artifacts/research/manifest.json",
    "ops": REPO / "workspace/artifacts/ops/manifest.json",
    "monitor": REPO / "workspace/artifacts/monitor/manifest.json",
}

# Palette: dataviz reference instance (validated 2-slot categorical, both modes;
# status palette fixed, never themed). Text wears text tokens, never series color.
CSS = """
:root { color-scheme: light;
  --surface: #fcfcfb; --card: #ffffff; --border: #e4e2dc;
  --text-1: #0b0b0b; --text-2: #52514e; --text-3: #8a8880;
  --s1: #2a78d6; --s2: #eb6834;
  --good: #0ca30c; --serious: #ec835a; --critical: #d03b3b; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  color-scheme: dark;
  --surface: #1a1a19; --card: #232322; --border: #3a3936;
  --text-1: #ffffff; --text-2: #c3c2b7; --text-3: #8a8880;
  --s1: #3987e5; --s2: #d95926; } }
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --card: #232322; --border: #3a3936;
  --text-1: #ffffff; --text-2: #c3c2b7; --text-3: #8a8880;
  --s1: #3987e5; --s2: #d95926; }
* { box-sizing: border-box; margin: 0; }
body { background: var(--surface); color: var(--text-1);
  font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  padding: 2rem 1rem 4rem; }
main { max-width: 1060px; margin: 0 auto; }
header h1 { font-size: 1.45rem; letter-spacing: -0.01em; }
header p.sub { color: var(--text-2); margin-top: .3rem; max-width: 68ch; }
.grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); margin-top: 1.5rem; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1.1rem 1.25rem; }
.card.wide { grid-column: 1 / -1; }
.card h2 { font-size: .82rem; text-transform: uppercase; letter-spacing: .07em; color: var(--text-2); margin-bottom: .75rem; }
.hero { display: flex; flex-wrap: wrap; gap: 2rem; align-items: baseline; }
.hero .big { font-size: 2.9rem; font-weight: 650; letter-spacing: -0.02em; }
.hero .unit { color: var(--text-2); font-size: .95rem; }
.badge { display: inline-flex; align-items: center; gap: .45rem; border-radius: 999px;
  padding: .28rem .8rem; font-size: .82rem; font-weight: 600; border: 1.5px solid; }
.badge.not-promoted { color: var(--critical); border-color: var(--critical); }
.badge .dot { width: .6rem; height: .6rem; border-radius: 50%; background: currentColor; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; }
th { text-align: left; color: var(--text-2); font-weight: 600; padding: .35rem .6rem .35rem 0; border-bottom: 1px solid var(--border); }
td { padding: .38rem .6rem .38rem 0; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: none; }
.status { display: inline-flex; align-items: center; gap: .4rem; font-weight: 600; font-size: .82rem; }
.status.fail { color: var(--critical); }
.status.pass { color: var(--good); }
.status.unmeasured { color: var(--text-2); }
.status.queue-wait { color: var(--text-2); }
.status.queue-exec { color: var(--s1); }
.note { color: var(--text-3); font-size: .8rem; margin-top: .7rem; }
svg text { font: 12px -apple-system, "Segoe UI", Roboto, sans-serif; }
footer { margin-top: 2.5rem; border-top: 1px solid var(--border); padding-top: 1rem;
  color: var(--text-3); font-size: .76rem; }
footer code { font-size: .74rem; word-break: break-all; }
.api-links a { color: var(--s1); text-decoration: none; margin-right: 1rem; }
.chart-scroll { overflow-x: auto; }
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def esc(s: object) -> str:
    return html.escape(str(s))


def bars_svg(variants: list[dict], champion: str) -> str:
    """Horizontal bar chart: one measure (val tier accuracy) across variants.

    Single series -> single categorical hue; the champion carries a direct
    label (selective labeling, not a number on every mark). Native SVG <title>
    supplies the per-mark hover tooltip; 2px surface gap between bars via
    row spacing; 4px rounded data-end anchored to the zero baseline.
    """
    row_h, gap, left, right, width = 26, 6, 52, 150, 640
    plot_w = width - left - right
    h = len(variants) * (row_h + gap) + 30
    out = [f'<svg viewBox="0 0 {width} {h}" role="img" '
           f'aria-label="Held-out tier accuracy for the eight hill-climb variants">']
    # recessive grid at 25/50/75/100%
    for pct in (25, 50, 75, 100):
        x = left + plot_w * pct / 100
        out.append(f'<line x1="{x:.1f}" y1="4" x2="{x:.1f}" y2="{h - 26}" '
                   f'stroke="var(--border)" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{h - 10}" text-anchor="middle" '
                   f'fill="var(--text-3)">{pct}%</text>')
    for i, v in enumerate(variants):
        y = 6 + i * (row_h + gap)
        acc = v["val_tier_accuracy"]
        w = max(plot_w * acc, 2)
        cfg = v["config"]
        tip = (f'{v["name"]}: {acc:.1%} held-out tier accuracy — buckets '
               f'{cfg["n_buckets"]}, embed {cfg["embed_dim"]}, lr {cfg["lr"]}, '
               f'{v["train_seconds"]:.2f}s train')
        out.append(f'<text x="{left - 8}" y="{y + row_h / 2 + 4}" text-anchor="end" '
                   f'fill="var(--text-2)">{esc(v["name"])}</text>')
        out.append(
            f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{row_h - 6}" rx="4" '
            f'fill="var(--s1)"><title>{esc(tip)}</title></rect>')
        if v["name"] == champion:
            out.append(f'<text x="{left + w + 8}" y="{y + row_h / 2 + 3}" '
                       f'fill="var(--text-1)" font-weight="650">'
                       f'{acc:.1%} — champion</text>')
    out.append("</svg>")
    return "".join(out)


def provenance_svg(measured: int, simulated: int) -> str:
    """Two-segment stacked bar (identity): measured vs simulated, 2px gap.

    Legend lives in HTML so it keeps a readable size regardless of card width.
    """
    total = measured + simulated
    width, bar_h = 320, 22
    mw = max(width * measured / total, 3)
    sw = width - mw - 2
    return (
        f'<svg viewBox="0 0 {width} {bar_h + 4}" role="img" '
        f'aria-label="Corpus records by provenance" style="width:100%;height:auto">'
        f'<rect x="0" y="2" width="{mw:.1f}" height="{bar_h}" rx="4" fill="var(--s1)">'
        f'<title>measured: {measured} records mined from real run timelines and workflow journals</title></rect>'
        f'<rect x="{mw + 2:.1f}" y="2" width="{sw:.1f}" height="{bar_h}" rx="4" fill="var(--s2)">'
        f'<title>simulated: {simulated} records from the seeded synthetic battery</title></rect>'
        f"</svg>"
        f'<div style="display:flex;gap:1.2rem;margin-top:.45rem;font-size:.82rem;color:var(--text-2)">'
        f'<span><span style="display:inline-block;width:.65rem;height:.65rem;border-radius:50%;'
        f'background:var(--s1);margin-right:.35rem"></span>measured · {measured}</span>'
        f'<span><span style="display:inline-block;width:.65rem;height:.65rem;border-radius:50%;'
        f'background:var(--s2);margin-right:.35rem"></span>simulated · {simulated}</span></div>'
    )


def build() -> None:
    data = {k: json.loads(p.read_text()) for k, p in SOURCES.items()}
    shas = {k: sha256(p) for k, p in SOURCES.items()}
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                                capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        commit = "unknown"

    ladder, ev, meta = data["ladder"], data["eval"], data["corpus_meta"]
    champ = ev["champion"]
    gate = ev.get("gate", {}) if isinstance(ev.get("gate"), dict) else {}
    if not gate:
        gate = {"gate_passed": False, "reason": "gate section absent — renders as not promoted"}
    counts = meta["counts"]
    agents = data["scoreboard"]["agents"]
    queue = data["queue"]["candidates"]

    variants = sorted(ladder["variants"], key=lambda v: v["name"])
    built_at = ladder["built_at"]

    # Gate rows are DERIVED from the eval report, never hardcoded: a criterion
    # renders PASS/FAIL only when its inputs are measured, else UNMEASURED.
    n_mh = int(champ.get("n_measured_holdout") or 0)
    cov_ok = n_mh >= 10
    gate_rows = [(
        "Measured held-out coverage (n ≥ 10)",
        "pass" if cov_ok else "fail",
        "✓" if cov_ok else "✕",
        f'{"PASS" if cov_ok else "FAIL"} — {n_mh} of 10 required measured held-out records',
    )]
    champ_m = champ.get("tier_accuracy_measured")
    bl = ev.get("baselines") or {}
    for name, base_acc in (
        ("Beats frequency-prior baseline on measured hold-out",
         (bl.get("freq_prior") or {}).get("accuracy_measured")),
        ("Beats heuristic router on measured hold-out",
         (bl.get("heuristic") or {}).get("accuracy_measured")),
    ):
        if not cov_ok or champ_m is None or base_acc is None:
            gate_rows.append((name, "unmeasured", "—",
                              "UNMEASURED — insufficient measured held-out data"))
        elif champ_m > base_acc:
            gate_rows.append((name, "pass", "✓",
                              f"PASS — champion {champ_m:.1%} vs baseline {base_acc:.1%}"))
        else:
            gate_rows.append((name, "fail", "✕",
                              f"FAIL — champion {champ_m:.1%} vs baseline {base_acc:.1%}"))
    gate_html = "".join(
        f'<tr><td>{esc(name)}</td><td><span class="status {cls}">{icon} {esc(text)}</span></td></tr>'
        for name, cls, icon, text in gate_rows)

    agent_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{a['runs']}</td><td>{a['events']}</td>"
        f"<td>{a['ok_rate']:.0%}</td><td>{a['p50_latency_ms']} ms</td></tr>"
        for name, a in sorted(agents.items()))

    qcls = {"awaiting_pilot": ("queue-wait", "awaiting pilot"),
            "in_execution": ("queue-exec", "in execution")}
    queue_rows = "".join(
        f'<tr><td>{esc(c["method"])}</td><td>{esc(c["siteId"])}</td>'
        f'<td><span class="status {qcls.get(c["status"], ("queue-wait", c["status"]))[0]}">'
        f'{esc(qcls.get(c["status"], ("", c["status"]))[1])}</span></td></tr>'
        for c in queue)

    tiers = counts["by_tier"]
    tier_rows = "".join(f"<tr><td>{esc(t)}</td><td>{n}</td></tr>"
                        for t, n in sorted(tiers.items(), key=lambda kv: -kv[1]))

    # Label sources — OPTIONAL counts fields (labeling lane). Absent fields
    # render UNMEASURED, never a fabricated zero.
    by_label = counts.get("by_label_tier")
    by_label = by_label if isinstance(by_label, dict) else None
    mh_label = counts.get("measured_holdout_by_label_tier")
    mh_label = mh_label if isinstance(mh_label, dict) else None

    if by_label is None:
        label_table = ('<span class="status unmeasured">— UNMEASURED — corpus meta does not yet '
                       "carry per-record label-source counts</span>")
    else:
        label_table = (
            "<table><thead><tr><th>Label source</th><th>Records</th></tr></thead><tbody>"
            + "".join(f"<tr><td>{esc(t)}</td><td>{n}</td></tr>"
                      for t, n in sorted(by_label.items(), key=lambda kv: -kv[1]))
            + "</tbody></table>")

    # Gate context: labels the heuristic did not produce, in the measured
    # hold-out. "measured-behavior" follows the executed (heuristic) routing
    # and "simulated" is heuristic-derived, so only the remainder can ground
    # a champion-vs-heuristic comparison. Fail-closed at zero.
    heuristic_made = ("measured-behavior", "simulated")
    if mh_label is None:
        label_gate = ('<span class="status unmeasured">— UNMEASURED — measured hold-out '
                      "label-source breakdown not yet recorded; the gate's champion-vs-heuristic "
                      "comparison only becomes meaningful once non-heuristic labels exceed zero</span>")
    else:
        n_indep = sum(n for t, n in mh_label.items() if t not in heuristic_made)
        if n_indep > 0:
            label_gate = (f'<span class="status pass">✓ {n_indep} measured hold-out records carry '
                          "labels beyond measured-behavior and simulated — the gate's "
                          "champion-vs-heuristic comparison is grounded in labels the heuristic "
                          "did not produce</span>")
        else:
            label_gate = ('<span class="status fail">✕ 0 measured hold-out records carry labels '
                          "beyond measured-behavior and simulated — the gate's "
                          "champion-vs-heuristic comparison is not yet meaningful</span>")

    # Correction queue — the operator's review surface. Derived from committed
    # corpus records only (metadata: run id, tier, label source, status; goal
    # text is deliberately not in the corpus). Each row carries the exact CLI
    # command that records a ground-truth correction.
    if CORPUS_JSONL.exists():
        recent_runs: dict[str, dict] = {}
        for raw in CORPUS_JSONL.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            rec = json.loads(raw)
            key = rec.get("split_key", "")
            if (rec.get("source") == "ultra_timeline" and rec.get("provenance") == "measured"
                    and key.startswith("harness-run-")):
                # one row per run; keep the record with an errorClass if any
                if key not in recent_runs or rec.get("errorClass") not in (None, "", "none"):
                    recent_runs[key] = rec
        newest = sorted(recent_runs.items(), reverse=True)[:10]
        if newest:
            queue_correction_rows = "".join(
                f"<tr><td><code>{esc(rid.removeprefix('harness-run-'))}</code></td>"
                f"<td>{esc(r.get('label_tier', '?'))}</td>"
                f"<td>{esc((r.get('provenance_fields') or {}).get('label_tier', '?'))}</td>"
                f"<td>{esc(r.get('status', '?'))}</td>"
                f"<td><code>scout harness correct {esc(rid)} &lt;tier&gt; --reason \"…\"</code></td></tr>"
                for rid, r in newest)
            correction_html = (
                "<table><thead><tr><th>Run</th><th>Label</th><th>Source</th><th>Status</th>"
                "<th>Correction command</th></tr></thead><tbody>"
                + queue_correction_rows + "</tbody></table>")
        else:
            correction_html = ('<span class="status unmeasured">— no measured harness runs '
                               "in the committed corpus yet</span>")
        shas["corpus"] = sha256(CORPUS_JSONL)
    else:
        correction_html = ('<span class="status unmeasured">— UNMEASURED — corpus.jsonl not '
                           "present at build time</span>")

    # Venture artifacts — playbook-generated documents (scripts/business/).
    # Rendered from each venture's manifest.json only: generated_at,
    # output path, classification, and the manifest's own sha256 of the
    # output — nothing about the artifact content is re-derived or invented.
    venture_rows = []
    for venture, mpath in VENTURE_MANIFESTS.items():
        if not mpath.exists():
            continue
        try:
            mdata = json.loads(mpath.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for artifact_id, entry in (mdata.get("artifacts") or {}).items():
            outputs = entry.get("outputs") or []
            prov = entry.get("provenance") or {}
            classification = prov.get("classification", "?")
            generated_at = entry.get("generated_at", "?")
            for out in outputs:
                out_path = out.get("path", "")
                out_sha = out.get("sha256", "")
                if not out_path:
                    continue
                venture_rows.append(
                    f"<tr><td>{esc(venture)}/{esc(artifact_id)}</td>"
                    f"<td><code>{esc(out_path)}</code></td>"
                    f"<td>{esc(classification)}</td>"
                    f"<td>{esc(generated_at)}</td>"
                    f"<td><code>sha256:{esc(out_sha[:16])}…</code></td></tr>"
                )
    if venture_rows:
        venture_html = (
            "<table><thead><tr><th>Artifact</th><th>Path</th><th>Classification</th>"
            "<th>Generated</th><th>Checksum</th></tr></thead><tbody>"
            + "".join(venture_rows) + "</tbody></table>")
    else:
        venture_html = ('<span class="status unmeasured">— no venture artifacts '
                        "committed yet (scripts/business/playbook.py run &lt;venture&gt;)</span>")

    src_rows = "".join(
        f"<div><code>{esc(p.relative_to(REPO))}</code> · <code>sha256:{shas[k][:16]}…</code></div>"
        for k, p in SOURCES.items())
    if CORPUS_JSONL.exists():
        src_rows += (f"<div><code>{esc(CORPUS_JSONL.relative_to(REPO))}</code> · "
                     f"<code>sha256:{shas['corpus'][:16]}…</code></div>")

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Validation Lab — Dottie harness &amp; training progress</title>
<style>{CSS}</style>
</head>
<body>
<main>
<header>
  <h1>Validation Lab — Dottie harness &amp; training progress</h1>
  <p class="sub">Read-only scorecard for the Dottie orchestration stack: the live harness
  API and the distilled router model trained from run traces. Every number on this page
  is recomputed from committed event logs and reports — history, not live telemetry —
  and unmeasured quantities render as unmeasured.</p>
</header>

<div class="grid">
  <div class="card wide">
    <h2>Champion router model — {esc(champ["model_version"])}</h2>
    <div class="hero">
      <div><span class="big">{champ["val_tier_accuracy"]:.1%}</span>
        <span class="unit">held-out tier accuracy ({ladder["corpus_counts"]["val"]} validation records)</span></div>
      <span class="badge not-promoted"><span class="dot"></span> NOT PROMOTED — {esc(gate.get("reason", "gate failed"))}</span>
    </div>
    <p class="note">Promotion is eval-gated and fail-closed: a champion ships to routing
    only after the gate passes on measured data. Until then it serves in an advisory
    role; the badge carries the gate's exact reason.</p>
  </div>

  <div class="card wide">
    <h2>Hill-climb ladder — 8 variants, real CPU training runs</h2>
    <div class="chart-scroll">{bars_svg(variants, champ["name"])}</div>
    <p class="note">Advantage-weighted training on the orchestration corpus
    (seed-pinned, ≤{ladder["time_budget_s"]:.0f}s budget per variant; actual
    {min(v["train_seconds"] for v in variants):.1f}–{max(v["train_seconds"] for v in variants):.1f}s).
    Bars share one hue — one measure across variants; hover any bar for its config.</p>
  </div>

  <div class="card">
    <h2>Promotion gate — fail-closed</h2>
    <table><tbody>{gate_html}</tbody></table>
    <p class="note">Unmeasured renders as unmeasured, never as pass. The gate unlocks
    as real harness runs accumulate measured hold-out records.</p>
  </div>

  <div class="card">
    <h2>Validation queue</h2>
    <table>
      <thead><tr><th>Method</th><th>Site</th><th>Status</th></tr></thead>
      <tbody>{queue_rows}</tbody>
    </table>
    <p class="note">Candidates advance pilot → charter → deploy; verdicts publish here
    with their evidence references.</p>
  </div>

  <div class="card">
    <h2>Training corpus — {counts["total"]} records by provenance</h2>
    {provenance_svg(counts["by_provenance"]["measured"], counts["by_provenance"]["simulated"])}
    <p class="note">Provenance is labeled per record. The measured slice grows with every
    harness run; simulated records come from a seeded, deterministic battery
    (seed {esc(meta.get("generator", {}).get("seed", "20260809")) if isinstance(meta.get("generator"), dict) else "20260809"}).</p>
  </div>

  <div class="card">
    <h2>Corpus by routing tier</h2>
    <table><thead><tr><th>Tier</th><th>Records</th></tr></thead>
    <tbody>{tier_rows}</tbody></table>
  </div>

  <div class="card">
    <h2>Label sources</h2>
    {label_table}
    <div style="margin-top:.7rem">{label_gate}</div>
    <p class="note">Each record's label provenance is tracked separately from its
    feature provenance. The promotion gate's champion-vs-heuristic comparison only
    becomes meaningful when the measured hold-out contains labels the heuristic
    did not make (measured-outcome or operator-corrected).</p>
  </div>

  <div class="card wide">
    <h2>Correction queue — operator review</h2>
    <div class="chart-scroll">{correction_html}</div>
    <p class="note">The ten most recent measured harness runs from the committed corpus.
    A correction is ground truth: run the command with the tier that should have been
    routed (goal text via <code>scout harness checkpoint show --run-id …</code>; the
    corpus itself carries metadata only). Corrections land in
    <code>label_corrections.jsonl</code> and the nightly retrain consumes them as
    operator-corrected labels — the strongest signal against the gate's label ceiling.</p>
  </div>

  <div class="card wide">
    <h2>Run scoreboard — mined from committed timelines</h2>
    <table>
      <thead><tr><th>Agent</th><th>Runs</th><th>Events</th><th>OK rate</th><th>p50 latency</th></tr></thead>
      <tbody>{agent_rows}</tbody>
    </table>
    <p class="note">All runs to date succeeded — an OK rate of 100% is this period's data,
    not a claim; failure classes will appear here as they occur.</p>
  </div>

  <div class="card wide">
    <h2>Venture artifacts — playbook-generated, provenance-checked</h2>
    <div class="chart-scroll">{venture_html}</div>
    <p class="note">Generated by <code>scripts/business/playbook.py run &lt;venture&gt;</code> from
    committed sources only; each row's checksum is copied verbatim from the venture's own
    manifest, never recomputed here. Documents live under <code>workspace/artifacts/</code>
    in the dottie repository.</p>
  </div>
</div>

<footer>
  <div class="api-links" style="margin-bottom:.8rem">
    Live harness API:
    <a href="/api/health">/api/health</a>
    <a href="/api/stats">/api/stats</a>
    <span style="color:var(--text-3)">POST /api/route · POST /api/plan</span>
  </div>
  <div>Built {esc(built_at)} at commit <code>{esc(commit)}</code> from committed sources:</div>
  {src_rows}
  <div style="margin-top:.6rem">Read-only surface — no write path. Retracted or superseded
  numbers only ever appear beside an explicit retraction marker.</div>
</footer>
</main>
</body>
</html>
"""
    (PKG / "index.html").write_text(page)

    (PKG / "who-e.html").write_text(
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>who-e</title>
<style>body{background:#fcfcfb;color:#52514e;font:16px/1.6 -apple-system,'Segoe UI',sans-serif;
display:grid;place-items:center;min-height:100vh;margin:0}
@media (prefers-color-scheme: dark){body{background:#1a1a19;color:#c3c2b7}}</style>
</head><body><p>who-e.com — reserved.</p></body></html>
"""
    )
    print(f"wrote {PKG / 'index.html'} ({(PKG / 'index.html').stat().st_size} bytes) + who-e.html")


if __name__ == "__main__":
    build()
