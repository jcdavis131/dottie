"use client";

import React, { useCallback, useEffect, useState } from "react";

export const dynamic = "force-dynamic";

type PairServiceState = {
  state: "checking" | "connected" | "unavailable";
  provenance: string;
  source: string;
  error?: string;
  checkedAt?: number;
};

export default function DottiePage() {
  const [service, setService] = useState<PairServiceState>({
    state: "checking",
    provenance: "not measured",
    source: "not measured",
  });
  const [pairCode, setPairCode] = useState("");
  const [pairState, setPairState] = useState<"idle" | "verifying" | "paired" | "error">("idle");
  const [pairError, setPairError] = useState("");

  const probePairService = useCallback(async () => {
    try {
      const response = await fetch("/api/pair/status", { cache: "no-store" });
      const result = await response.json().catch(() => null);
      const connected = response.ok && result?.provenance === "jarvisd";
      setService({
        state: connected ? "connected" : "unavailable",
        provenance: result?.provenance || "unavailable",
        source: result?.source || "unavailable",
        error: connected ? undefined : result?.error || `Pair service returned HTTP ${response.status}.`,
        checkedAt: Date.now(),
      });
    } catch (error) {
      setService({
        state: "unavailable",
        provenance: "unreachable",
        source: "unreachable",
        error: error instanceof Error ? error.message : "Pair service unreachable.",
        checkedAt: Date.now(),
      });
    }
  }, []);

  const probeSession = useCallback(async () => {
    const response = await fetch("/api/session", { cache: "no-store" }).catch(() => null);
    if (!response) {
      setPairState("idle");
      return;
    }
    const result = await response.json().catch(() => null);
    setPairState(response.ok && result?.authenticated ? "paired" : "idle");
  }, []);

  useEffect(() => {
    const runProbes = () => {
      void probePairService();
      void probeSession();
    };
    const initialProbe = window.setTimeout(runProbes, 0);
    const interval = window.setInterval(runProbes, 7000);
    return () => {
      window.clearTimeout(initialProbe);
      window.clearInterval(interval);
    };
  }, [probePairService, probeSession]);

  const verifyPair = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const code = pairCode.trim().toUpperCase();
      setPairState("verifying");
      setPairError("");
      try {
        const response = await fetch("/api/pair/verify", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ code }),
        });
        const result = await response.json().catch(() => null);
        if (!response.ok || !result?.ok || !result?.paired || result?.provenance !== "jarvisd") {
          throw new Error(result?.error || "Pairing was not confirmed by jarvisd.");
        }
        setPairCode("");
        await Promise.all([probePairService(), probeSession()]);
      } catch (error) {
        setPairState("error");
        setPairError(error instanceof Error ? error.message : "Pairing could not be verified.");
      }
    },
    [pairCode, probePairService, probeSession]
  );

  const connected = service.state === "connected";

  return (
    <div
      style={{
        background: "#FAFAF8",
        color: "#1E2022",
        minHeight: "100vh",
        fontFamily: "ui-sans-system, -apple-system, Segoe UI, Roboto, Inter, sans-serif",
      }}
    >
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 40,
          height: 40,
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "0 14px",
          background: "rgba(250,250,248,0.92)",
          backdropFilter: "blur(12px)",
          borderBottom: "1px solid #E8E0D5",
        }}
      >
        <div style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12.5, fontWeight: 700 }}>
          ARXIVIQ — DOTTIE
        </div>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            padding: "4px 9px",
            borderRadius: 999,
            background: connected ? "#E8F5EE" : "#F5F1EB",
            color: connected ? "#0B3D22" : "#6B7280",
            border: `1px solid ${connected ? "#BFE7CC" : "#E8E0D5"}`,
          }}
        >
          Pair service: {service.state}
        </span>
        <a
          href="/conductor?tandem=1"
          style={{ fontSize: 11.5, color: "#2A2A2A", textDecoration: "none", border: "1px solid #E8E0D5", padding: "4px 10px", borderRadius: 999 }}
        >
          Conductor
        </a>
      </header>

      <main style={{ maxWidth: 820, margin: "0 auto", padding: "24px 14px 48px", display: "grid", gap: 14 }}>
        <section style={{ background: "#080A0F", color: "#E6F1EB", borderRadius: 16, padding: 18, border: "1px solid #1E2022" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span
              aria-hidden="true"
              style={{ width: 8, height: 8, borderRadius: 99, background: connected ? "#22c55e" : "#6b7280", display: "inline-block" }}
            />
            <h1 style={{ margin: 0, fontSize: 18 }}>Server-confirmed pairing</h1>
            <span style={{ marginLeft: "auto", color: "#8BA998", fontFamily: "ui-monospace, monospace", fontSize: 10.5 }}>
              provenance: {service.provenance}
            </span>
          </div>

          <p style={{ color: "#AFC8BB", fontSize: 12.5, lineHeight: 1.55, margin: "10px 0 0" }}>
            Pairing is available only through configured jarvisd. There is no local, in-memory, or accept-any fallback.
          </p>

          <div role="status" aria-live="polite" style={{ marginTop: 12, padding: 11, borderRadius: 10, background: "#0F1E16", border: "1px solid #1E3328", fontSize: 12 }}>
            <div>
              <strong>Status:</strong> {connected ? "jarvisd connected" : service.state === "checking" ? "checking pair service" : "unavailable"}
            </div>
            <div style={{ color: "#8BA998", marginTop: 4 }}>
              Source: {service.source}
              {service.checkedAt ? ` · checked ${new Date(service.checkedAt).toLocaleTimeString()}` : ""}
            </div>
            {service.error && <div style={{ color: "#FFB4B4", marginTop: 5 }}>{service.error}</div>}
          </div>

          <form onSubmit={verifyPair} style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 5, flex: "1 1 230px", fontSize: 11, color: "#AFC8BB", fontWeight: 600 }}>
              Pairing code
              <input
                value={pairCode}
                onChange={(event) => {
                  setPairCode(event.target.value.toUpperCase());
                  setPairError("");
                  if (pairState !== "verifying") setPairState("idle");
                }}
                autoComplete="one-time-code"
                inputMode="text"
                maxLength={6}
                required
                aria-describedby="pair-result"
                placeholder="ABC234"
                style={{ height: 36, borderRadius: 8, border: "1px solid #1F3A28", background: "#0F1E16", color: "#E6F1EB", padding: "0 10px", fontFamily: "ui-monospace, monospace", textTransform: "uppercase" }}
              />
            </label>
            <button
              type="submit"
              disabled={pairState === "verifying" || !connected}
              style={{
                height: 36,
                padding: "0 15px",
                borderRadius: 8,
                border: "1px solid #1F3A28",
                background: connected ? "#7CFFB2" : "#4B5B52",
                color: connected ? "#04210F" : "#D1D5DB",
                fontWeight: 700,
                cursor: pairState === "verifying" ? "wait" : connected ? "pointer" : "not-allowed",
              }}
            >
              {pairState === "verifying" ? "Verifying…" : "Verify with jarvisd"}
            </button>
            <span
              id="pair-result"
              role={pairState === "error" ? "alert" : "status"}
              aria-live="polite"
              style={{ flexBasis: "100%", color: pairState === "error" ? "#FF9A9A" : "#7CFFB2", fontSize: 11.5 }}
            >
              {pairState === "paired" ? "Paired — jarvisd confirmed this code." : pairError}
            </span>
            {pairState === "paired" && (
              <button
                type="button"
                onClick={async () => {
                  await fetch("/api/session", { method: "DELETE" }).catch(() => null);
                  setPairState("idle");
                }}
                style={{ height: 36, padding: "0 12px", borderRadius: 8, border: "1px solid #1F3A28", background: "transparent", color: "#AFC8BB" }}
              >
                Log out
              </button>
            )}
          </form>
        </section>

        <section style={{ background: "#FFFFFF", border: "1px solid #E8E0D5", borderRadius: 16, padding: 16 }}>
          <h2 style={{ margin: 0, fontSize: 14 }}>Integration measurements</h2>
          <dl style={{ display: "grid", gridTemplateColumns: "minmax(150px, 0.7fr) 1fr", gap: "9px 14px", margin: "12px 0 0", fontSize: 12.5 }}>
            <dt style={{ fontWeight: 700 }}>Pair service</dt>
            <dd style={{ margin: 0 }}>{connected ? "Connected to jarvisd" : "Unavailable"}</dd>
            <dt style={{ fontWeight: 700 }}>Pair state</dt>
            <dd style={{ margin: 0 }}>{pairState === "paired" ? "Server confirmed" : "Not paired"}</dd>
            <dt style={{ fontWeight: 700 }}>Local conductor</dt>
            <dd style={{ margin: 0, color: "#6B7280" }}>Not measured on this page</dd>
            <dt style={{ fontWeight: 700 }}>Cloud Scout</dt>
            <dd style={{ margin: 0, color: "#6B7280" }}>Not measured on this page</dd>
            <dt style={{ fontWeight: 700 }}>Queue depth</dt>
            <dd style={{ margin: 0, color: "#6B7280" }}>Not reported by the pair service</dd>
            <dt style={{ fontWeight: 700 }}>Model/verifier metrics</dt>
            <dd style={{ margin: 0, color: "#6B7280" }}>Not measured</dd>
          </dl>
        </section>
      </main>
    </div>
  );
}
