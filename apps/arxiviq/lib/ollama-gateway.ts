// apps/arxiviq/lib/ollama-gateway.ts
// Ollama local gateway adapter — stdlib-only, zero-deps, honest 503 if unavailable
// Target: http://localhost:11434 (env OLLAMA_HOST or OLLAMA_BASE_URL override)
// Pattern: simple fetch wrapper, no heavy deps, matches AGENTS.md zero-deps rule

function _isAllowedGatewayUrl(raw: string): boolean {
  try {
    const u = new URL(raw);
    if (!["http:", "https:"].includes(u.protocol)) return false;
    const host = u.hostname;
    if (["localhost","127.0.0.1","::1","host.docker.internal"].includes(host)) return true;
    if (host.startsWith("10.") || host.startsWith("192.168.") || host.startsWith("172.")) return true;
    if (process.env.ALLOW_REMOTE_GATEWAY === "1") return true;
    return false;
  } catch { return false; }
}

function _safeBaseUrl(raw: string, fallback: string): string {
  if (!raw) return fallback;
  if (_isAllowedGatewayUrl(raw)) return raw;
  console.warn(`[ollama-gateway] blocked non-local URL ${raw} — using fallback`);
  return fallback;
}

const _RAW_OLLAMA = process.env.OLLAMA_BASE_URL || process.env.OLLAMA_HOST || "http://localhost:11434";
export const OLLAMA_BASE_URL = _safeBaseUrl(_RAW_OLLAMA, "http://localhost:11434");

export type OllamaOk<T> = { ok: true; data: T; status: number };
export type OllamaErr = { ok: false; error: string; status: 503 | 500 | 400; details?: string };
export type OllamaResult<T> = OllamaOk<T> | OllamaErr;

type FetchOpts = {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
};

async function ollamaFetch<T>(path: string, opts: FetchOpts = {}): Promise<OllamaResult<T>> {
  const url = `${OLLAMA_BASE_URL.replace(/\/$/, "")}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? 8000);

  try {
    const res = await fetch(url, {
      method: opts.method ?? "GET",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal ?? controller.signal,
    } as RequestInit);

    clearTimeout(timeout);

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      // If Ollama is down, it typically refuses connection before reaching here,
      // but handle HTTP 5xx as unavailable for honest 503 mapping
      if (res.status >= 500) {
        return {
          ok: false,
          error: "ollama unavailable",
          status: 503,
          details: text.slice(0, 500) || `HTTP ${res.status}`,
        };
      }
      return {
        ok: false,
        error: text.slice(0, 500) || `ollama error HTTP ${res.status}`,
        status: res.status as 400,
      };
    }

    // Some endpoints (e.g. /api/generate streaming) return newline-delimited JSON.
    // For zero-deps simplicity, we handle non-streaming JSON only here.
    // Callers needing streaming should use generateStream directly.
    const data = (await res.json().catch(async () => {
      const txt = await res.text().catch(() => "");
      return txt as unknown as T;
    })) as T;

    return { ok: true, data, status: res.status };
  } catch (e: any) {
    clearTimeout(timeout);
    const msg = e?.name === "AbortError" ? "ollama timeout" : e?.message || "fetch failed";
    const isConnRefused =
      msg.includes("ECONNREFUSED") ||
      msg.includes("fetch failed") ||
      msg.includes("Failed to fetch") ||
      msg.includes("connect");

    if (isConnRefused) {
      return {
        ok: false,
        error: "ollama unavailable - no local gateway at " + OLLAMA_BASE_URL,
        status: 503,
        details: msg.slice(0, 500),
      };
    }

    return {
      ok: false,
      error: "ollama unavailable",
      status: 503,
      details: msg.slice(0, 500),
    };
  }
}

// ——— Public API ———

export async function healthCheck(): Promise<OllamaResult<{ status: string }>> {
  // GET / — Ollama returns "Ollama is running"
  try {
    const url = `${OLLAMA_BASE_URL.replace(/\/$/, "")}/`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(url, { signal: controller.signal } as RequestInit);
    clearTimeout(timeout);
    if (!res.ok) {
      return { ok: false, error: "ollama unavailable", status: 503, details: `HTTP ${res.status}` };
    }
    const text = await res.text();
    if (text.toLowerCase().includes("ollama is running")) {
      return { ok: true, data: { status: "running" }, status: 200 };
    }
    return { ok: true, data: { status: text.slice(0, 200) }, status: 200 };
  } catch (e: any) {
    return {
      ok: false,
      error: "ollama unavailable - no local gateway at " + OLLAMA_BASE_URL,
      status: 503,
      details: e?.message?.slice(0, 500),
    };
  }
}

export async function listModels(): Promise<OllamaResult<{ models: Array<{ name: string; modified_at: string; size: number }> }>> {
  return ollamaFetch("/api/tags");
}

export async function showModel(name: string): Promise<OllamaResult<any>> {
  return ollamaFetch("/api/show", { method: "POST", body: { name } });
}

export async function generate(opts: {
  model: string;
  prompt: string;
  system?: string;
  stream?: false;
  options?: Record<string, unknown>;
}): Promise<OllamaResult<{ model: string; response: string; done: boolean; context?: number[] }>> {
  return ollamaFetch("/api/generate", {
    method: "POST",
    body: { ...opts, stream: false },
    timeoutMs: 60000,
  });
}

export async function chat(opts: {
  model: string;
  messages: Array<{ role: "system" | "user" | "assistant"; content: string }>;
  stream?: false;
  options?: Record<string, unknown>;
}): Promise<OllamaResult<{ model: string; message: { role: string; content: string }; done: boolean }>> {
  return ollamaFetch("/api/chat", {
    method: "POST",
    body: { ...opts, stream: false },
    timeoutMs: 60000,
  });
}

export async function embeddings(opts: {
  model: string;
  prompt: string;
  options?: Record<string, unknown>;
}): Promise<OllamaResult<{ embedding: number[] }>> {
  return ollamaFetch("/api/embeddings", {
    method: "POST",
    body: opts,
    timeoutMs: 30000,
  });
}

// Streaming variant — returns ReadableStream if available, else honest 503
export async function generateStream(opts: {
  model: string;
  prompt: string;
  system?: string;
  options?: Record<string, unknown>;
}): Promise<ReadableStream<Uint8Array> | OllamaErr> {
  const url = `${OLLAMA_BASE_URL.replace(/\/$/, "")}/api/generate`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...opts, stream: true }),
    } as RequestInit);

    if (!res.ok || !res.body) {
      return {
        ok: false,
        error: "ollama unavailable",
        status: 503,
        details: `HTTP ${res.status}`,
      };
    }
    return res.body as ReadableStream<Uint8Array>;
  } catch (e: any) {
    return {
      ok: false,
      error: "ollama unavailable - no local gateway at " + OLLAMA_BASE_URL,
      status: 503,
      details: e?.message?.slice(0, 500),
    };
  }
}

// Convenience: check if gateway is reachable, honest boolean
export async function isAvailable(): Promise<boolean> {
  const h = await healthCheck();
  return h.ok;
}

// Default export for ergonomic import
const ollamaGateway = {
  OLLAMA_BASE_URL,
  healthCheck,
  listModels,
  showModel,
  generate,
  chat,
  embeddings,
  generateStream,
  isAvailable,
};

export default ollamaGateway;
