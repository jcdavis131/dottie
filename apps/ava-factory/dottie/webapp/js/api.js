// API client for the two Dottie backends. Pure fetch — no DOM, no storage —
// so this module is importable (and testable) outside a browser.
//
// House doctrine: every failure is surfaced as a typed ApiError with the
// server's own detail when one exists; nothing here fabricates a value.

export class ApiError extends Error {
  constructor(kind, message, { status = null, detail = null, url = "" } = {}) {
    super(message);
    this.name = "ApiError";
    this.kind = kind; // "http" | "network" | "timeout"
    this.status = status;
    this.detail = detail;
    this.url = url;
  }
  /** Operator-facing one-liner. */
  describe() {
    if (this.kind === "http") return `HTTP ${this.status} — ${this.detail || this.message}`;
    if (this.kind === "timeout") return `timed out — ${this.message}`;
    return `unreachable — ${this.message}`;
  }
}

async function request(url, { method = "GET", body = null, timeoutMs = 8000, headers = {} } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: { ...(body != null ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body != null ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    if (e && e.name === "AbortError") {
      throw new ApiError("timeout", `no response within ${(timeoutMs / 1000).toFixed(0)}s`, { url });
    }
    throw new ApiError("network", e && e.message ? e.message : "fetch failed", { url });
  }
  clearTimeout(timer);
  if (!res.ok) {
    let detail = null;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : j.detail != null ? JSON.stringify(j.detail) : j.error || null;
    } catch { /* non-JSON error body */ }
    throw new ApiError("http", `HTTP ${res.status}`, { status: res.status, detail, url });
  }
  try {
    return await res.json();
  } catch (e) {
    // Doctrine (top of file): every failure leaves this module as a typed ApiError.
    // A 2xx whose body is not JSON — a proxy error page, a truncated response, a
    // misrouted HTML 200 — used to escape as a raw SyntaxError and surface in the UI
    // as "Unexpected token <", which tells an operator nothing about what to fix.
    throw new ApiError("http", `HTTP ${res.status} but the body was not JSON`, {
      status: res.status,
      // describe() prefers `detail`, so the explanation belongs here, not in `message`.
      detail: `body was not JSON${e && e.message ? ` (${e.message})` : ""}`,
      url,
    });
  }
}

const trim = (base) => (base || "").replace(/\/+$/, "");

export function makeClient(settings) {
  const base = trim(settings.base);
  const research = trim(settings.researchBase);
  const token = settings.token || "";

  return {
    /** :8000 liveness + trainer state. Never 500s server-side. */
    pipelineStatus: () => request(`${base}/pipeline/status`, { timeoutMs: 8000 }),

    /** Brain badge, trust policy, tool catalog, telemetry. */
    assistantStatus: () => request(`${base}/assistant/status`, { timeoutMs: 10000 }),

    /** The ReAct tool loop. Bearer token attached only here, only when set. */
    assistant: (messages, { maxSteps = 4, timeoutMs = 180000 } = {}) =>
      request(`${base}/assistant`, {
        method: "POST",
        body: { messages, max_steps: maxSteps },
        timeoutMs, // no server-side streaming; a cold CPU generate is slow
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }),

    /** Plain single-shot chat (no tools, no token). */
    chat: (messages, { timeoutMs = 180000 } = {}) =>
      request(`${base}/chat`, {
        method: "POST",
        body: { messages },
        timeoutMs,
      }),

    /**
     * Research ledger from :8100 — optional and unreachable-tolerant.
     * Tries the browser-direct route first (works when :8100's CORS allows
     * this origin), then falls back to the :8000 server-side proxy
     * (GET /research/status) which avoids browser CORS entirely.
     * Returns { data, source: "direct"|"proxy", sourceUrl } or throws an
     * ApiError whose message names both failures.
     */
    researchStatus: async () => {
      let directErr;
      try {
        const data = await request(`${research}/research/status`, { timeoutMs: 6000 });
        return { data, source: "direct", sourceUrl: `${research}/research/status` };
      } catch (e) {
        directErr = e;
      }
      try {
        const wrapped = await request(`${base}/research/status`, { timeoutMs: 8000 });
        // Verified contract (server.py /research/status): 200 -> {ok, source, status},
        // failure -> 502, which `request` already converts to an ApiError. So `status` is
        // present today. Checked anyway because a 200 whose shape drifts would make
        // `wrapped.status` undefined and hand the UI an EMPTY research panel that looks
        // like a successful read — the one thing the doctrine at the top of this file
        // forbids. Defensive, not a live bug; the failure it prevents is silent.
        if (wrapped == null || typeof wrapped !== "object" || !("status" in wrapped)) {
          throw new ApiError("http", "proxy returned 200 without a `status` payload", {
            status: 200,
            detail: `unexpected shape: keys=${JSON.stringify(Object.keys(wrapped || {}))}`,
            url: `${base}/research/status`,
          });
        }
        return { data: wrapped.status, source: "proxy", sourceUrl: wrapped.source || `${base}/research/status` };
      } catch (proxyErr) {
        throw new ApiError(
          "network",
          `direct: ${directErr.describe()}; proxy: ${proxyErr.describe()}`,
          { url: `${research}/research/status` },
        );
      }
    },
  };
}
