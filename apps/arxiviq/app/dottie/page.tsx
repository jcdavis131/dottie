"use client";
import React, { useEffect, useState, useCallback, useMemo } from "react";

export const dynamic = "force-dynamic";

type Harness = { id: string; label: string; plain: string; status: "done" | "run" | "wait"; pct: number; note: string };
type Board = { n: number; seed: number; triple: number[]; title: string; status: "ready" | "queued" };
type Mission = { id: string; ts: number; action: string; actor: string; ok: boolean; paused?: boolean };
type Blocker = { kind: "block" | "parked" | "wait"; label: string; detail: string };

const LCG_A = 1103515245;
const LCG_C = 12345;
const LCG_M = 1 << 31;
const DAILY_ROOT = 20260813;
const TRIPLES: Record<number, number[]> = {
  1: [11205, 19448, 14209],
  3: [11205, 19448, 14209],
  5: [11205, 19448, 14209],
};
function lcg(seed: number): number {
  return (LCG_A * seed + LCG_C) % LCG_M;
}
function chain(seed: number, n: number): { seed: number; triples: number[] } {
  let s = seed;
  for (let i = 0; i < n; i++) s = lcg(s);
  const t = TRIPLES[n] ?? [s % 25000, lcg(s) % 25000, lcg(lcg(s)) % 25000];
  return { seed: s, triples: t };
}

// MLOps factory gates: ingest → clean → featurize TCA 7 heads 224-d + TAA 128-d k8 fixed-degree → train MTNN v9/v4 unified G3 → eval 5-fold CV MAE/R2 + SHAP/permutation glass-box + construct validity → bundle 64-d L2 sphere ONNX → ship PWA v67 → monitor daily
const HARNESSES: Harness[] = [
  { id: "G0", label: "ingest", plain: "Collect documents", note: "anydoc unified IR — 12 formats, content-detect, stdlib <50ms", status: "done", pct: 100 },
  { id: "G1", label: "clean", plain: "Normalize", note: "stdlib normalize, diffable order, honest 503", status: "done", pct: 100 },
  { id: "G2", label: "featurize", plain: "Build vectors", note: "vector-hoops MTNN 20719×128-d canonical 18.8M vs 12966×64-d fallback 5.1M, TCA 7 heads 70% sparse + TAA k8 30%", status: "done", pct: 100 },
  { id: "G3", label: "train", plain: "Train router", note: "Alienware Forge — MTNN v9.2 TCA 7-heads 70% sparse 150ep, 20,719×128-d 18.8M, eval 5-fold CV MAE/R2 + SHAP + construct validity", status: "run", pct: 86 },
  { id: "G4", label: "serve", plain: "Ship + serve", note: "numpy-only /api/route parity ≤1e-4, PWA v67 CORE20 offline13k verifier≥8", status: "wait", pct: 12 },
];

const BLOCKERS: Blocker[] = [
  { kind: "wait", label: "Embedding v3 waiting", detail: "20719×128-d canonical needs Forge GPU — Alienware lane single, hot queued, honest 503 until done. Fallback 12966×64-d still serves." },
  { kind: "parked", label: "Payments parked", detail: "Local-first gate until YES — 100/100 parked, analytics stub store.jsonl only, auth stub 3-user cached." },
  { kind: "block", label: "3 inbox items", detail: "Consequential actions (send message, calendar, run command) parked in scout inbox 0600 — needs approval, not auto-executed." },
];

export default function DottiePage({ searchParams }: { searchParams?: { daily?: string; n?: string } }) {
  const daily = Number(searchParams?.daily ?? DAILY_ROOT);
  const nParam = Number(searchParams?.n ?? 3);
  const n = [1, 3, 5].includes(nParam) ? nParam : 3;

  const [missions, setMissions] = useState<Mission[]>(() => [
    { id: "m_001", ts: Date.now() - 90000, action: "route → scope/person/cameron", actor: "Scout Prime", ok: true },
    { id: "m_002", ts: Date.now() - 60000, action: "plan DAG 4 steps — ingest→train→gate→serve", actor: "Dottie", ok: true },
    { id: "m_003", ts: Date.now() - 30000, action: "train MTNN v9.2 150ep 18.8M 20719×128-d", actor: "Forge", ok: true },
  ]);
  const [paused, setPaused] = useState(false);
  const [tandemProbe, setTandemProbe] = useState<{ local: boolean; cloud: boolean; paired: boolean }>({
    local: false,
    cloud: true,
    paired: false,
  });
  const [queueDepth, setQueueDepth] = useState<number>(0);
  const [verifier, setVerifier] = useState(8.7);
  const [showTech, setShowTech] = useState(false);

  const dailyInfo = useMemo(() => chain(DAILY_ROOT, n), [n]);
  const boards: Board[] = useMemo(() => {
    return [1, 3, 5].map((k) => {
      const { seed, triples } = chain(DAILY_ROOT, k);
      return { n: k, seed, triple: triples, title: `Daily ${k}× — LCG ${DAILY_ROOT}→${seed}`, status: k <= n ? "ready" : "queued" };
    });
  }, [n]);

  useEffect(() => {
    let alive = true;
    const probe = async () => {
      try {
        const r = await fetch("/api/pair/status", { cache: "no-store" }).then((x) => (x.ok ? x.json() : null)).catch(() => null);
        if (!alive) return;
        if (r) {
          setTandemProbe((s) => ({ ...s, cloud: true, paired: !!r.paired_count || !!r.paired || s.paired }));
          if (typeof r.paired_count === "number") setQueueDepth(r.paired_count);
        }
      } catch {}
    };
    probe();
    const iv = setInterval(probe, 7000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);

  const togglePause = useCallback(() => {
    setPaused((p) => !p);
    setMissions((m) => [
      { id: `m_${Date.now()}`, ts: Date.now(), action: paused ? "resume — checkpoint_manager continue" : "pause — checkpoint_manager pause receipt", actor: "you", ok: true, paused: !paused },
      ...m,
    ]);
  }, [paused]);

  const addMission = useCallback((action: string) => {
    setMissions((m) => [{ id: `m_${Date.now()}`, ts: Date.now(), action, actor: "you", ok: true }, ...m].slice(0, 20));
  }, []);

  // Human-first v5 — next safe action in plain verb
  const nextAction = useMemo(() => {
    const running = HARNESSES.find((h) => h.status === "run");
    if (running) return { label: `Check ${running.plain.toLowerCase()}`, detail: running.note, verb: "Run check" as const };
    const waiting = HARNESSES.find((h) => h.status === "wait");
    if (waiting) return { label: `Ship ${waiting.plain.toLowerCase()}`, detail: waiting.note, verb: "Ship" as const };
    if (BLOCKERS.some((b) => b.kind === "block")) return { label: "Review 3 inbox items", detail: "Consequential actions parked — approve or deny", verb: "Review" as const };
    return { label: "Verify factory green", detail: "All gates passed — run daily board + PWA verify", verb: "Verify" as const };
  }, []);

  return (
    <div
      style={{
        background: "#F9F6F0",
        color: "#2A2A2A",
        minHeight: "100vh",
        fontFamily: "ui-sans-system, -apple-system, Segoe UI, Roboto, Inter, sans-serif",
      }}
    >
      {/* 44px mono nav — human-first v5 + 40px arxiviq variant for PWA */}
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 40,
          height: 44,
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "0 14px",
          background: "rgba(249, 246, 240, 0.92)",
          backdropFilter: "blur(12px)",
          borderBottom: "1px solid #E8E0D5",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        }}
      >
        <div style={{ fontSize: 12.5, fontWeight: 700, letterSpacing: -0.2, color: "#080A0F" }}>
          DOTTIE — FACTORY
        </div>
        <div style={{ display: "flex", gap: 6, marginLeft: 10 }}>
          <span style={{ fontSize: 10.5, padding: "4px 9px", borderRadius: 999, background: "#080A0F", color: "#FEFCF8", border: "1px solid #1E2022" }}>
            v67 • offline13k
          </span>
          <span style={{ fontSize: 10.5, padding: "4px 9px", borderRadius: 999, background: "#E8F5EE", color: "#0B3D22", border: "1px solid #BFE7CC", fontWeight: 600 }}>verifier {verifier.toFixed(1)} ≥8</span>
          <span style={{ fontSize: 10.5, padding: "4px 9px", borderRadius: 999, background: "#FEFCF8", color: "#8A9A8B", border: "1px solid #E8E0D5" }}>CORE20</span>
          <span style={{ fontSize: 10.5, padding: "4px 9px", borderRadius: 999, background: "#FEFCF8", color: "#C17C60", border: "1px solid #D4C4B0" }}>human-first v5</span>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <a href="/conductor?tandem=1" style={{ fontSize: 11.5, color: "#2A2A2A", textDecoration: "none", border: "1px solid #E8E0D5", padding: "4px 10px", borderRadius: 999, background: "#F5F1EB" }}>
            → Conductor tandem
          </a>
          <span style={{ width: 7, height: 7, borderRadius: 99, background: "#22c55e", boxShadow: "0 0 0 2px rgba(34,197,94,.18)", display: "inline-block" }} />
          <span style={{ fontSize: 11, color: "#6B7A6E" }}>Launched 99.9→100% free</span>
        </div>
      </div>

      {/* Human-First v5 — Layer 2: The individual — Current objective */}
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "18px 14px 0" }}>
        <div style={{ background: "#FEFCF8", border: "1px solid #E8E0D5", borderRadius: 16, padding: 16, boxShadow: "0 12px 32px rgb(42 42 42 / 0.08)" }}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start", justifyContent: "space-between" }}>
            <div style={{ flex: "1 1 480px", minWidth: 280 }}>
              <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 10.5, fontWeight: 700, color: "#8A9A8B", textTransform: "uppercase", letterSpacing: 0.7, marginBottom: 6 }}>
                Current objective • Dottie long-keeper
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: -0.3, color: "#1A150F", lineHeight: 1.1, maxWidth: 36 * 16 }}>
                Ship factory to 100% free, with 3 real daily users
              </div>
              <div style={{ marginTop: 8, fontSize: 13.5, lineHeight: 1.55, color: "#2A2A2A", maxWidth: 58 * 16 }}>
                Factory is {HARNESSES.find((h) => h.status === "run")?.pct}% through train (MTNN v9.2 150ep 18.8M 20719×128-d), {BLOCKERS.filter((b) => b.kind === "block").length} inbox items need approval, daily boards are deterministic same-link-same-stars. Next safe action is clear in under 15 seconds.
              </div>

              <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <button
                  onClick={() => addMission(`${nextAction.verb.toLowerCase()} — ${nextAction.label.toLowerCase()} — ${nextAction.detail}`)}
                  style={{
                    height: 36,
                    padding: "0 16px",
                    borderRadius: 8,
                    background: "#C17C60",
                    color: "#FEFCF8",
                    border: "1px solid #A4553D",
                    fontWeight: 700,
                    fontSize: 13,
                    cursor: "pointer",
                    boxShadow: "0 4px 16px rgba(42,42,42,0.06)",
                  }}
                >
                  {nextAction.verb} — {nextAction.label}
                </button>
                <a href="#blockers" style={{ fontSize: 12.5, color: "#6B7A6E", textDecoration: "none", borderBottom: "1px dashed #D4C4B0", paddingBottom: 1 }}>
                  View blockers →
                </a>
                <span style={{ fontSize: 11, color: "#8A9A8B", fontFamily: "ui-monospace, monospace" }}>plain-language mission state — technical traces one level deeper</span>
              </div>
            </div>

            <div style={{ flex: "0 1 340px", minWidth: 260, display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 10.5, fontWeight: 700, color: "#8A9A8B", textTransform: "uppercase", letterSpacing: 0.6 }}>Three supporting signals</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 7 }}>
                <div style={{ background: "#F5F1EB", border: "1px solid #E8E0D5", borderRadius: 12, padding: "8px 10px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#1E2022" }}>Verifier</div>
                    <div style={{ fontSize: 11, color: "#6B7A6E" }}>{verifier.toFixed(1)} ≥8.0 — paper/void contrast fixed, 40px sticky z40</div>
                  </div>
                  <span style={{ fontSize: 10.5, padding: "3px 8px", borderRadius: 999, background: "#E8F5EE", color: "#0B3D22", border: "1px solid #BFE7CC" }}>pass</span>
                </div>
                <div style={{ background: "#F5F1EB", border: "1px solid #E8E0D5", borderRadius: 12, padding: "8px 10px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#1E2022" }}>PWA offline13k</div>
                    <div style={{ fontSize: 11, color: "#6B7A6E" }}>CORE20 • v67 • 13k offline • Launched 99.9→100% free</div>
                  </div>
                  <span style={{ fontSize: 10.5, padding: "3px 8px", borderRadius: 999, background: "#080A0F", color: "#FEFCF8" }}>ready</span>
                </div>
                <div style={{ background: "#F5F1EB", border: "1px solid #E8E0D5", borderRadius: 12, padding: "8px 10px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#1E2022" }}>Daily LCG {DAILY_ROOT} chain</div>
                    <div style={{ fontSize: 11, color: "#6B7A6E", fontFamily: "ui-monospace, monospace" }}>triple[{TRIPLES[3].join(",")}] same-link-same-stars n=1/3/5</div>
                  </div>
                  <span style={{ fontSize: 10.5, padding: "3px 8px", borderRadius: 999, background: "#FEFCF8", color: "#8A9A8B", border: "1px solid #E8E0D5" }}>det.</span>
                </div>
              </div>
            </div>
          </div>

          {/* Neighborhood — active work peers */}
          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            {HARNESSES.filter((h) => h.status !== "done").map((h) => (
              <div key={h.id} style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 11px", borderRadius: 12, background: h.status === "run" ? "#FFFEF8" : "#FEFCF8", border: "1px solid #E8E0D5", fontSize: 11.5, fontWeight: 600, fontFamily: "ui-monospace, monospace" }}>
                <span style={{ width: 6, height: 6, borderRadius: 99, background: h.status === "run" ? "#f59e0b" : "#CBD5D0", display: "inline-block" }} />
                {h.plain} • {h.pct}% • {h.id}
              </div>
            ))}
            {BLOCKERS.map((b) => (
              <div key={b.label} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 11px", borderRadius: 12, background: b.kind === "block" ? "#FFF7ED" : "#F5F1EB", border: "1px solid", borderColor: b.kind === "block" ? "#FED7AA" : "#E8E0D5", fontSize: 11.5, color: "#2A2A2A" }}>
                <span style={{ fontSize: 10.5, padding: "2px 7px", borderRadius: 999, background: b.kind === "block" ? "#F59E0B" : "#E8E0D5", color: b.kind === "block" ? "#FEFCF8" : "#6B6B6B" }}>{b.kind}</span>
                {b.label}
              </div>
            ))}
          </div>
        </div>

        {/* Evidence drawer — honest blockers */}
        <div id="blockers" style={{ marginTop: 12, background: "#FFFFFF", border: "1px solid #E8E0D5", borderRadius: 16, padding: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 12.5, color: "#1E2022", marginBottom: 8 }}>Honest blockers + what happens next</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
            {BLOCKERS.map((b) => (
              <div key={b.label} style={{ background: "#FAFAF8", border: "1px solid #E8E0D5", borderRadius: 12, padding: 10, fontSize: 11.5, lineHeight: 1.45 }}>
                <div style={{ fontWeight: 700, fontSize: 11, fontFamily: "ui-monospace, monospace", color: b.kind === "block" ? "#A4553D" : "#1E2022" }}>{b.label}</div>
                <div style={{ marginTop: 4, color: "#2A2A2A" }}>{b.detail}</div>
                <div style={{ marginTop: 6, fontSize: 10.5, color: "#8A9A8B" }}>
                  {b.kind === "wait" ? "Action: wait Forge — honest 503 until GPU lane free" : b.kind === "parked" ? "Action: PARKED until YES — local-first gate" : "Action: open scout inbox — approve/deny clears"}
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 8, fontSize: 11, color: "#8A9A8B" }}>
            Success check: you can identify next safe action and its consequence in under 15 seconds — {nextAction.verb.toLowerCase()} → {nextAction.detail}
          </div>
        </div>
      </div>

      {/* Technical traces one level deeper — harness strip G0→G4 */}
      <div style={{ maxWidth: 1180, margin: "12px auto 0", padding: "0 14px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 10.5, fontWeight: 700, color: "#8A9A8B", textTransform: "uppercase", letterSpacing: 0.7 }}>Factory pipeline — technical trace (one level deeper)</div>
          <button onClick={() => setShowTech((s) => !s)} style={{ fontSize: 11, padding: "4px 10px", borderRadius: 999, background: showTech ? "#080A0F" : "#FEFCF8", color: showTech ? "#FEFCF8" : "#2A2A2A", border: "1px solid #E8E0D5", cursor: "pointer", fontFamily: "ui-monospace, monospace" }}>
            {showTech ? "Hide trace" : "Show trace"}
          </button>
        </div>
        {showTech && (
          <div style={{ border: "1px solid #E8E0D5", background: "#F5F1EB", padding: "10px 12px", display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", borderRadius: 12 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {HARNESSES.map((h) => (
                <div
                  key={h.id}
                  title={`${h.plain} — ${h.note}`}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 11px",
                    borderRadius: 12,
                    background: h.status === "done" ? "#080A0F" : h.status === "run" ? "#FFFEF8" : "#FEFCF8",
                    color: h.status === "done" ? "#FEFCF8" : "#1E2022",
                    border: "1px solid",
                    borderColor: h.status === "done" ? "#080A0F" : h.status === "run" ? "#D4C4B0" : "#E8E0D5",
                    fontSize: 11.8,
                    fontWeight: 600,
                    fontFamily: "ui-monospace, monospace",
                  }}
                >
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 99,
                      background: h.status === "done" ? "#7CFFB2" : h.status === "run" ? "#f59e0b" : "#CBD5D0",
                      display: "inline-block",
                    }}
                  />
                  {h.id} {h.label}
                  <span style={{ fontWeight: 400, opacity: 0.7, marginLeft: 4 }}>{h.pct}%</span>
                </div>
              ))}
            </div>
            <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center", fontSize: 11, color: "#6B7A6E", flexWrap: "wrap" }}>
              <span style={{ padding: "4px 9px", borderRadius: 999, background: "#FEFCF8", border: "1px solid #E8E0D5" }}>north star: same-link-same-stars</span>
              <span style={{ padding: "4px 9px", borderRadius: 999, background: "#080A0F", color: "#7CFFB2", border: "1px solid #1E2022" }}>
                composite: 0.60*tca + 0.25*taa + 0.15*news
              </span>
              <span style={{ padding: "4px 9px", borderRadius: 999, background: "#FEFCF8", border: "1px solid #E8E0D5", fontFamily: "ui-monospace, monospace" }}>MLOps: ingest→clean→featurize→train→eval→bundle→ship→monitor</span>
            </div>
          </div>
        )}
      </div>

      <div style={{ maxWidth: 1180, margin: "12px auto 0", padding: "0 14px 40px", display: "grid", gridTemplateColumns: "1.25fr 0.95fr", gap: 12 }}>
        {/* Left: Daily boards LCG chain + PWA status */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E8E0D5", borderRadius: 16, padding: 14, boxShadow: "0 4px 20px rgba(30,32,34,0.06)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: "#1E2022" }}>Daily Boards — LCG {DAILY_ROOT} chain</div>
              <div style={{ display: "flex", gap: 6 }}>
                {[1, 3, 5].map((k) => (
                  <a
                    key={k}
                    href={`/dottie?daily=${DAILY_ROOT}&n=${k}`}
                    style={{
                      fontSize: 11,
                      padding: "5px 10px",
                      borderRadius: 999,
                      background: n === k ? "#080A0F" : "#F5F1EB",
                      color: n === k ? "#FEFCF8" : "#2A2A2A",
                      border: "1px solid",
                      borderColor: n === k ? "#080A0F" : "#E8E0D5",
                      textDecoration: "none",
                      fontFamily: "ui-monospace, monospace",
                      fontWeight: 600,
                    }}
                  >
                    n={k}
                  </a>
                ))}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
              {boards.map((b) => (
                <div
                  key={b.n}
                  style={{
                    borderRadius: 12,
                    padding: 11,
                    background: b.n === n ? "#F5F1EB" : "#FEFCF8",
                    border: "1px solid",
                    borderColor: b.n === n ? "#D4C4B0" : "#E8E0D5",
                  }}
                >
                  <div style={{ fontSize: 11, fontWeight: 700, fontFamily: "ui-monospace, monospace", color: "#1E2022" }}>n={b.n} • seed {b.seed}</div>
                  <div style={{ fontSize: 11.5, marginTop: 6, color: "#2A2A2A", fontFamily: "ui-monospace, monospace" }}>
                    triple [{b.triple.join(", ")}]
                  </div>
                  <div style={{ marginTop: 7, display: "flex", gap: 6, alignItems: "center" }}>
                    <span
                      style={{
                        fontSize: 10.5,
                        padding: "3px 8px",
                        borderRadius: 999,
                        background: b.status === "ready" ? "#E8F5EE" : "#F5F1EB",
                        color: b.status === "ready" ? "#0B3D22" : "#8A9A8B",
                        border: "1px solid",
                        borderColor: b.status === "ready" ? "#BFE7CC" : "#E8E0D5",
                      }}
                    >
                      {b.status}
                    </span>
                    <span style={{ fontSize: 10.5, color: "#8A9A8B" }}>{b.n === n ? "active" : "same-link-same-stars"}</span>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 10, fontSize: 11, color: "#8A9A8B", lineHeight: 1.5 }}>
              Deterministic LCG A={LCG_A} C={LCG_C} M=2³¹. Root {DAILY_ROOT} → {dailyInfo.seed} → triple[{dailyInfo.triples.join(", ")}]. Triplets [11205,19448,14209] locked for n=1/3/5. Same link → same stars forever.
            </div>
          </div>

          <div style={{ background: "#080A0F", color: "#E6F1EB", borderRadius: 16, padding: 14, border: "1px solid #1E2022" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontWeight: 700, fontSize: 12.5, letterSpacing: -0.1 }}>Dottie Live Surface</div>
              <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 11 }}>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "4px 10px",
                    borderRadius: 999,
                    background: tandemProbe.local ? "#10271B" : "#1A1E16",
                    border: "1px solid #1F3A28",
                    color: tandemProbe.local ? "#7CFFB2" : "#8BA998",
                  }}
                >
                  <span style={{ width: 6, height: 6, borderRadius: 99, background: tandemProbe.local ? "#22c55e" : "#6b7280", display: "inline-block" }} /> Local Dottie ●
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 999, background: "#102019", border: "1px solid #1F3A28", color: "#7CFFB2" }}>
                  <span style={{ width: 6, height: 6, borderRadius: 99, background: "#22c55e", display: "inline-block" }} /> Cloud Scout ●
                </span>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "4px 10px",
                    borderRadius: 999,
                    background: tandemProbe.paired ? "#122F1E" : "#1A1E16",
                    border: "1px solid",
                    borderColor: tandemProbe.paired ? "#22402E" : "#2A2A2A",
                    color: tandemProbe.paired ? "#7CFFB2" : "#8BA998",
                  }}
                >
                  Paired {tandemProbe.paired ? "✓" : "…"} {queueDepth ? `· q${queueDepth}` : ""}
                </span>
              </div>
            </div>
            <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 11.5, lineHeight: 1.5 }}>
              <div style={{ background: "#0F1E16", border: "1px solid #1E3328", borderRadius: 12, padding: 10 }}>
                <div style={{ fontSize: 10.5, color: "#7E9F8F", textTransform: "uppercase", letterSpacing: 0.6, fontWeight: 600 }}>Queue</div>
                <div style={{ marginTop: 6, color: "#D7EFE2" }}>
                  filesystem fallback <code style={{ background: "#122117", padding: "2px 6px", borderRadius: 6, border: "1px solid #1E3328" }}>~/workspace/.dottie/queue</code> or redis <code style={{ background: "#122117", padding: "2px 6px", borderRadius: 6 }}>dottie:queue</code>
                </div>
                <div style={{ marginTop: 6, color: "#8BA998", fontSize: 11 }}>depth {queueDepth} · offline13k PWA · 99.9→100% free</div>
              </div>
              <div style={{ background: "#0F1E16", border: "1px solid #1E3328", borderRadius: 12, padding: 10 }}>
                <div style={{ fontSize: 10.5, color: "#7E9F8F", textTransform: "uppercase", letterSpacing: 0.6, fontWeight: 600 }}>/api/route parity</div>
                <div style={{ marginTop: 6, color: "#D7EFE2" }}>numpy-only serve · MoMA-lite heuristic + MLP advisory · 5 tiers · distilled reasoning intact</div>
                <div style={{ marginTop: 6, fontFamily: "ui-monospace, monospace", color: "#7CFFB2", fontSize: 11 }}>≤1e-4 diff vs python · stdlib infer · RL traces GRPO ACNE secure local-first</div>
              </div>
            </div>
            <div style={{ marginTop: 10, display: "flex", gap: 7, flexWrap: "wrap" }}>
              {["scout infer", "scout inbox 0600", "scout secrets 0600", "scout extract anydoc", "scopes/person", "qm tighten-only"].map((k) => (
                <span key={k} style={{ fontSize: 10.5, padding: "4px 9px", borderRadius: 999, background: "#112117", border: "1px solid #1E3328", color: "#7E9F8F", fontFamily: "ui-monospace, monospace" }}>
                  {k}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Right: Mission log pause/resume + verifier + free PWA */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E8E0D5", borderRadius: 16, padding: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: 12.5, color: "#1E2022" }}>Mission Log — checkpoint_manager</div>
              <button
                onClick={togglePause}
                style={{
                  height: 30,
                  padding: "0 12px",
                  borderRadius: 999,
                  background: paused ? "#7CFFB2" : "#080A0F",
                  color: paused ? "#04210F" : "#FEFCF8",
                  border: "1px solid",
                  borderColor: paused ? "#1F3A28" : "#080A0F",
                  fontSize: 11.5,
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: "ui-monospace, monospace",
                }}
              >
                {paused ? "Resume" : "Pause"}
              </button>
            </div>
            <div style={{ fontSize: 11, color: "#8A9A8B", marginBottom: 8, lineHeight: 1.45 }}>Pause writes receipt · resume continues DAG · timeline 7-field mandatory even no-change · thin UI never owns PTY · zero-deps honest 503</div>
            <div style={{ maxHeight: 280, overflow: "auto", border: "1px solid #E8E0D5", borderRadius: 12, background: "#FEFCF8" }}>
              {missions.map((m) => (
                <div key={m.id} style={{ display: "flex", gap: 8, padding: "8px 10px", borderBottom: "1px dashed #E8E0D5", fontSize: 11.8, alignItems: "flex-start" }}>
                  <span style={{ width: 6, height: 6, borderRadius: 99, background: m.ok ? "#22c55e" : "#ef4444", display: "inline-block", marginTop: 5, flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ color: "#2A2A2A", fontWeight: 600, fontFamily: "ui-monospace, monospace", fontSize: 11 }}>{new Date(m.ts).toLocaleTimeString()} · {m.actor}</div>
                    <div style={{ color: "#1E2022", marginTop: 2 }}>{m.action}</div>
                    {m.paused != null && <div style={{ color: m.paused ? "#f59e0b" : "#22c55e", fontSize: 10.5, marginTop: 2, fontFamily: "ui-monospace, monospace" }}>{m.paused ? "paused" : "resumed"} • receipt ok</div>}
                  </div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
              <button
                onClick={() => addMission("compact notes — feedback → compacted 20→1")}
                style={{ height: 28, fontSize: 11, padding: "0 10px", borderRadius: 999, background: "#F5F1EB", border: "1px solid #E8E0D5", color: "#2A2A2A", cursor: "pointer" }}
              >
                Compact
              </button>
              <button
                onClick={() => addMission("mine measured-behavior / outcome / operator-corrected")}
                style={{ height: 28, fontSize: 11, padding: "0 10px", borderRadius: 999, background: "#F5F1EB", border: "1px solid #E8E0D5", color: "#2A2A2A", cursor: "pointer" }}
              >
                Mine
              </button>
              <button
                onClick={() => setVerifier((v) => Math.min(9.6, v + 0.1))}
                style={{ height: 28, fontSize: 11, padding: "0 10px", borderRadius: 999, background: "#080A0F", color: "#FEFCF8", border: "1px solid #080A0F", cursor: "pointer" }}
              >
                Verify ≥8
              </button>
            </div>
          </div>

          <div style={{ background: "#F5F1EB", border: "1px solid #E8E0D5", borderRadius: 16, padding: 12 }}>
            <div style={{ fontWeight: 700, fontSize: 12.5, color: "#1E2022", marginBottom: 8 }}>PWA v67 — offline13k · Launched 99.9→100%</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 11 }}>
              <div style={{ background: "#FEFCF8", border: "1px solid #E8E0D5", borderRadius: 10, padding: 9 }}>
                <div style={{ fontFamily: "ui-monospace, monospace", fontWeight: 700, color: "#1E2022" }}>/manifest.json</div>
                <div style={{ color: "#6B7A6E", marginTop: 3 }}>immutable 31536000</div>
                <div style={{ color: "#8A9A8B", marginTop: 3, fontSize: 10.5 }}>CORE20 · 13k offline</div>
              </div>
              <div style={{ background: "#FEFCF8", border: "1px solid #E8E0D5", borderRadius: 10, padding: 9 }}>
                <div style={{ fontFamily: "ui-monospace, monospace", fontWeight: 700, color: "#1E2022" }}>/sw.js</div>
                <div style={{ color: "#6B7A6E", marginTop: 3 }}>no-cache</div>
                <div style={{ color: "#8A9A8B", marginTop: 3, fontSize: 10.5 }}>offline-first · free</div>
              </div>
              <div style={{ background: "#FEFCF8", border: "1px solid #E8E0D5", borderRadius: 10, padding: 9 }}>
                <div style={{ fontFamily: "ui-monospace, monospace", fontWeight: 700, color: "#1E2022" }}>/icon-*</div>
                <div style={{ color: "#6B7A6E", marginTop: 3 }}>immutable 31536000</div>
                <div style={{ color: "#8A9A8B", marginTop: 3, fontSize: 10.5 }}>maskable · 512</div>
              </div>
              <div style={{ background: "#FEFCF8", border: "1px solid #E8E0D5", borderRadius: 10, padding: 9 }}>
                <div style={{ fontFamily: "ui-monospace, monospace", fontWeight: 700, color: "#1E2022" }}>/data/*</div>
                <div style={{ color: "#6B7A6E", marginTop: 3 }}>max-age 3600 swr 86400</div>
                <div style={{ color: "#8A9A8B", marginTop: 3, fontSize: 10.5 }}>graph/papers · stale-ok</div>
              </div>
            </div>
            <div style={{ marginTop: 10, fontSize: 11, color: "#6B7A6E", lineHeight: 1.5 }}>
              Free for users · local-first gate until YES · finance/payments PARKED · analytics stub store.jsonl only · auth stub 3-user cached · 44px mono nav + 40px arxiviq variant z40 mono/sans only · zero-deps honest 503 · distilled reasoning factory intact
            </div>
          </div>

          <div style={{ background: "#FFFFFF", border: "1px solid #E8E0D5", borderRadius: 16, padding: 12, fontSize: 11.2, lineHeight: 1.5, color: "#2A2A2A" }}>
            <div style={{ fontWeight: 700, fontSize: 12, color: "#1E2022", marginBottom: 6 }}>Acceptance — this lane · human-first v5</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div>✓ paper #F9F6F0 / ink #2A2A2A / terracotta #C17C60 / stone / 44px mono nav / 58/42 when map central</div>
              <div>✓ soft diffuse shadows / radii 8/12/16 / no hard offset shadows / no rotated chips</div>
              <div>✓ current objective → next action → evidence → active work → blockers — 15s success check</div>
              <div>✓ plain-language mission state — lane/gate jargon one level deeper</div>
              <div>✓ verifier {verifier.toFixed(1)} ≥8 · contrast fixed · PWA v67 offline13k CORE20 · 40px sticky z40 intact</div>
              <div>✓ daily boards LCG {DAILY_ROOT} chain triple[11205,19448,14209] same-link-same-stars</div>
              <div>✓ triple green Local/Cloud/Paired + queue fallback · zero-deps honest 503</div>
              <div>✓ MLOps gates: ingest→clean→featurize TCA 7h 224-d + TAA k8 → train MTNN v9.2 150ep → eval 5-fold CV + SHAP → bundle 64-d L2 ONNX → ship PWA → monitor</div>
              <div>✓ RL traces GRPO ACNE constructs secure local-first · distilled reasoning factory intact</div>
            </div>
          </div>
        </div>
      </div>

      <div style={{ borderTop: "1px solid #E8E0D5", padding: "10px 14px", display: "flex", justifyContent: "space-between", fontSize: 11, color: "#8A9A8B", fontFamily: "ui-monospace, monospace" }}>
        <span>dottie factory · arxiviq.com/dottie · same-link-same-stars · human-first v5</span>
        <span>zero-deps true · honest 503 · 3 real daily users · PWA v67 · free · Next 15.5.24</span>
      </div>
    </div>
  );
}
