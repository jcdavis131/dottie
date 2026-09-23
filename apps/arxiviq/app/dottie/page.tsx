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
  const statusLine = connected
    ? "jarvisd connected"
    : service.state === "checking"
      ? "checking pair service"
      : "unavailable";

  return (
    <main className="main room" id="main" tabIndex={-1}>
      <div className="container">
        <header className="room__head">
          <p className="label seq">Server-confirmed · no local fallback</p>
          <h1 className="display room__title seq" style={{ "--i": 1 } as React.CSSProperties}>
            Pair
          </h1>
          <p className="lede seq" style={{ "--i": 2 } as React.CSSProperties}>
            Pairing is available only through configured jarvisd. There is no local,
            in-memory, or accept-any fallback.
          </p>
        </header>

        <section className="panel" aria-labelledby="pair-heading">
          <div className="panel__bar">
            <h2 className="label" id="pair-heading" style={{ color: "var(--ink)" }}>
              Server-confirmed pairing
            </h2>
            <span className="chip">
              <span
                aria-hidden="true"
                className={connected ? "dot dot--ok dot--live" : service.state === "checking" ? "dot dot--live" : "dot"}
              />
              Pair service: {service.state}
            </span>
          </div>

          <div className="panel__body">
            <dl className="readout" role="status" aria-live="polite">
              <div>
                <dt>Status</dt>
                <dd>{statusLine}</dd>
              </div>
              <div>
                <dt>Provenance</dt>
                <dd className="mono">{service.provenance}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>
                  {service.source}
                  {service.checkedAt ? (
                    <span className="muted tnum"> · checked {new Date(service.checkedAt).toLocaleTimeString()}</span>
                  ) : null}
                </dd>
              </div>
            </dl>
            {service.error && <p className="notice">{service.error}</p>}

            <form onSubmit={verifyPair} style={{ display: "grid", gap: "var(--s2)" }}>
              <div className="field">
                <label htmlFor="pair-code">Pairing code</label>
                <input
                  className="input input--code"
                  id="pair-code"
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
                  spellCheck={false}
                />
              </div>
              <div className="actions" style={{ justifyContent: "flex-start" }}>
                <button
                  className="btn btn--primary"
                  type="submit"
                  disabled={pairState === "verifying" || !connected}
                  aria-busy={pairState === "verifying"}
                >
                  {pairState === "verifying" ? "Verifying…" : "Verify with jarvisd"}
                </button>
                {pairState === "paired" && (
                  <button
                    className="btn"
                    type="button"
                    onClick={async () => {
                      await fetch("/api/session", { method: "DELETE" }).catch(() => null);
                      setPairState("idle");
                    }}
                  >
                    Log out
                  </button>
                )}
                <a className="btn" href="/conductor?tandem=1">
                  Conductor
                </a>
              </div>
              <p
                id="pair-result"
                className={pairState === "error" ? "result result--error" : "result"}
                role={pairState === "error" ? "alert" : "status"}
                aria-live="polite"
              >
                {pairState === "paired" ? "Paired — jarvisd confirmed this code." : pairError}
              </p>
            </form>
          </div>
        </section>

        <section className="panel" aria-labelledby="measure-heading">
          <div className="panel__bar">
            <h2 className="label" id="measure-heading" style={{ color: "var(--ink)" }}>
              Integration measurements
            </h2>
          </div>
          <div className="panel__body">
            <dl className="readout">
              <div>
                <dt>Pair service</dt>
                <dd>{connected ? "Connected to jarvisd" : "Unavailable"}</dd>
              </div>
              <div>
                <dt>Pair state</dt>
                <dd>{pairState === "paired" ? "Server confirmed" : "Not paired"}</dd>
              </div>
              <div>
                <dt>Local conductor</dt>
                <dd className="muted">Not measured on this page</dd>
              </div>
              <div>
                <dt>Cloud Scout</dt>
                <dd className="muted">Not measured on this page</dd>
              </div>
              <div>
                <dt>Queue depth</dt>
                <dd className="muted">Not reported by the pair service</dd>
              </div>
              <div>
                <dt>Model/verifier metrics</dt>
                <dd className="muted">Not measured</dd>
              </div>
            </dl>
          </div>
        </section>
      </div>
    </main>
  );
}
