// glimmer-client.ts — Muse Glimmer local gateway
// Zero-deps, stdlib-only, honest 503, Apache 2.0 weights via Ollama/vLLM/llama.cpp/MLX
// 29.6B dense + 1.8B ViT-G/14, 131k context, text+images, low/med/high/xhigh reasoning
// Target backends in priority: OLLAMA (11434), vLLM (8000), llama.cpp (8080), MLX server
// Honest 503 if none available — never synthetic.

export type GlimmerReasoning = "low" | "medium" | "high" | "xhigh";
export type GlimmerBackend = "ollama" | "vllm" | "llamacpp" | "mlx" | "none";

export interface GlimmerConfig {
  backend?: GlimmerBackend;
  baseUrl?: string;
  model?: string; // default: muse-glimmer / glimmer / llama3.2-vision etc
  reasoning?: GlimmerReasoning;
  timeoutMs?: number;
}

export interface GlimmerJudgeRequest {
  prompt: string;
  images?: string[]; // base64 data URLs or http URLs, ViT-G/14 path
  system?: string;
  reasoning?: GlimmerReasoning;
  context?: Record<string, unknown>;
}

export interface GlimmerJudgeResult {
  ok: boolean;
  score?: number; // 0-10
  verdict?: "PASS" | "FAIL" | "PARTIAL";
  reasoning?: string;
  details?: Record<string, unknown>;
  backend?: GlimmerBackend;
  latency_ms?: number;
  error?: string;
  status?: number;
}

const DEFAULT_MODEL = process.env.GLIMMER_MODEL || "muse-glimmer";
const ENV_BASE = process.env.GLIMMER_BASE_URL || process.env.OLLAMA_HOST || "";

function detectBackend(cfg?: GlimmerConfig): { backend: GlimmerBackend; url: string } {
  if (cfg?.backend && cfg?.baseUrl) return { backend: cfg.backend, url: cfg.baseUrl };
  if (ENV_BASE) {
    if (ENV_BASE.includes("11434")) return { backend: "ollama", url: ENV_BASE };
    if (ENV_BASE.includes("8000")) return { backend: "vllm", url: ENV_BASE };
    return { backend: cfg?.backend || "ollama", url: ENV_BASE };
  }
  // default probe order handled by caller
  return { backend: "none", url: "" };
}

async function probe(url: string, timeoutMs = 2500): Promise<boolean> {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await fetch(url, { signal: ctrl.signal } as any);
    clearTimeout(t);
    return res.ok || res.status < 500;
  } catch {
    return false;
  }
}

export async function getAvailableBackend(): Promise<{ backend: GlimmerBackend; url: string }> {
  const candidates: Array<{ backend: GlimmerBackend; url: string }> = [
    { backend: "ollama", url: process.env.OLLAMA_HOST || "http://localhost:11434" },
    { backend: "vllm", url: process.env.VLLM_URL || "http://localhost:8000" },
    { backend: "llamacpp", url: process.env.LLAMA_URL || "http://localhost:8080" },
    { backend: "mlx", url: process.env.MLX_URL || "http://localhost:8081" },
  ];
  for (const c of candidates) {
    const healthPath = c.backend === "ollama" ? "/" : c.backend === "vllm" ? "/health" : "/health";
    if (await probe(c.url + healthPath, 1200)) return c;
  }
  return { backend: "none", url: "" };
}

export async function glimmerJudge(req: GlimmerJudgeRequest, cfg?: GlimmerConfig): Promise<GlimmerJudgeResult> {
  const start = Date.now();
  const reasoning = req.reasoning || cfg?.reasoning || "medium";
  const systemPreamble = `You are Muse Glimmer, a 30B open-weight judge (Apache 2.0) running locally. Reasoning effort: ${reasoning}. You judge PWA v67, offline13k, CORE20, and 59→73 hash provenance. Be concise, honest, zero-deps style. Return JSON only.`;
  const finalSystem = req.system ? `${systemPreamble}\n${req.system}` : systemPreamble;

  let backendInfo = cfg?.baseUrl ? { backend: cfg.backend || "ollama" as GlimmerBackend, url: cfg.baseUrl } : await getAvailableBackend();
  if (backendInfo.backend === "none") {
    return {
      ok: false,
      error: "glimmer unavailable - no local gateway at 11434/8000/8080/8081",
      status: 503,
      backend: "none",
      latency_ms: Date.now() - start,
    };
  }

  const model = cfg?.model || DEFAULT_MODEL;
  const timeoutMs = cfg?.timeoutMs ?? 15000;

  // Ollama path (primary)
  if (backendInfo.backend === "ollama") {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), timeoutMs);
      const body: any = {
        model,
        prompt: `${finalSystem}\n\nUSER: ${req.prompt}\nASSISTANT (JSON):`,
        stream: false,
        options: {
          num_ctx: 131072,
          temperature: 0.2,
        },
      };
      if (req.images?.length) body.images = req.images;
      const res = await fetch(`${backendInfo.url.replace(/\/$/, "")}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal as any,
      });
      clearTimeout(t);
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        if (res.status >= 500) {
          return { ok: false, error: "glimmer unavailable", status: 503, backend: "ollama", details: { txt: txt.slice(0, 400) } as any, latency_ms: Date.now() - start };
        }
        return { ok: false, error: txt.slice(0, 400), status: res.status as any, backend: "ollama", latency_ms: Date.now() - start };
      }
      const data: any = await res.json();
      const text = data.response || data.text || "";
      // Try parse JSON from response
      try {
        const parsed = JSON.parse(text);
        return {
          ok: true,
          score: parsed.score ?? parsed.verdict_score,
          verdict: parsed.verdict,
          reasoning: parsed.reasoning || parsed.explain,
          details: parsed,
          backend: "ollama",
          latency_ms: Date.now() - start,
        };
      } catch {
        // Extract score via regex fallback
        const m = text.match(/"score"\s*:\s*([0-9.]+)/) || text.match(/score\s*([0-9.]+)/i);
        return {
          ok: true,
          score: m ? Number(m[1]) : undefined,
          verdict: text.toLowerCase().includes("pass") ? "PASS" : text.toLowerCase().includes("fail") ? "FAIL" : "PARTIAL",
          reasoning: text.slice(0, 2000),
          details: { raw: text.slice(0, 4000) },
          backend: "ollama",
          latency_ms: Date.now() - start,
        };
      }
    } catch (e: any) {
      return { ok: false, error: e?.message || "fetch failed", status: 503, backend: "ollama", latency_ms: Date.now() - start };
    }
  }

  // vLLM OpenAI-compat fallback
  if (backendInfo.backend === "vllm") {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), timeoutMs);
      const res = await fetch(`${backendInfo.url.replace(/\/$/, "")}/v1/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model,
          messages: [
            { role: "system", content: finalSystem },
            { role: "user", content: req.prompt },
          ],
          max_tokens: 1024,
          temperature: 0.2,
        }),
        signal: ctrl.signal as any,
      });
      clearTimeout(t);
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        return { ok: false, error: txt.slice(0, 400), status: res.status as any, backend: "vllm", latency_ms: Date.now() - start };
      }
      const data: any = await res.json();
      const text = data.choices?.[0]?.message?.content || "";
      try {
        const parsed = JSON.parse(text);
        return { ok: true, score: parsed.score, verdict: parsed.verdict, reasoning: parsed.reasoning, details: parsed, backend: "vllm", latency_ms: Date.now() - start };
      } catch {
        return { ok: true, verdict: text.toLowerCase().includes("pass") ? "PASS" : "FAIL", reasoning: text.slice(0, 2000), details: { raw: text.slice(0, 4000) }, backend: "vllm", latency_ms: Date.now() - start };
      }
    } catch (e: any) {
      return { ok: false, error: e?.message, status: 503, backend: "vllm", latency_ms: Date.now() - start };
    }
  }

  return { ok: false, error: "no supported backend", status: 503, backend: backendInfo.backend, latency_ms: Date.now() - start };
}

// --- Judge presets for PWA v67 + hoops ---

export function pwaJudgePrompt(checks: {
  offline13k?: { present: boolean; size?: number; cacheName?: string };
  core20?: { count: number; expected: number; missing?: string[] };
  hashes?: { expected: number; actual: number; list?: string[]; provenanceFile?: string };
  manifest?: any;
  sw?: string;
  dailyPacks?: { date: string; count: number; sameLinkSameStars?: boolean }[];
}): string {
  return `Judge PWA v67 for dumbmodel.com / vector-hoops.

Context:
- PWA v67 void #080A0F 40px sticky nav, LOD4000/8000 DPR1, offline13k offline.html 13868B CORE20, 30 boards LIVE gate8.7
- Checks to validate:
${JSON.stringify(checks, null, 2)}

Return JSON:
{
  "score": 0-10,
  "verdict": "PASS"|"FAIL"|"PARTIAL",
  "reasoning": "one paragraph",
  "checks": {
    "offline13k": {"pass": bool, "explain": str},
    "core20": {"pass": bool, "explain": str, "missing": []},
    "hashes_59_73": {"pass": bool, "expected": 59, "actual": number, "explain": str},
    "manifest": {"pass": bool},
    "sw": {"pass": bool},
    "daily_packs": {"pass": bool, "same_link_same_stars": bool}
  },
  "suggestions": ["..."]
}

Be strict: 59 hashes is 7/7/0 spec PASS, 73 is expanded spec (10 hoops, 7 gridiron, 3 pitch, 7 equities, 14 tennis, 12 unified, 6 scout_cli, 14 schools). CORE20 is 20 files. offline13k must be 13868B-ish dark void #080A0F. No synthetic data, honest 503 if blocked.`;
}

export function hoopsJudgePrompt(input: {
  screenshotBase64?: string; // ViT-G/14 path
  chartData?: any;
  dailyPack?: any;
  mapState?: { lod: number; dpr: number; singleSelect: boolean; inertia?: number };
  provenance?: { ok: number; total: number; bad: number };
}): string {
  return `Judge vector-hoops 12,966 seasons as rotating map.

Input:
${JSON.stringify({ ...input, screenshotBase64: input.screenshotBase64 ? `[${input.screenshotBase64.length} chars base64]` : undefined }, null, 2)}

You have ViT-G/14 1.8B vision encoder. If screenshot present, describe map readability, contrast, DPR1 fillRect LOD4000/8000, single-select clears prev, legend, dark void #080A0F.

Return JSON:
{
  "score": 0-10,
  "verdict": "PASS"|"FAIL"|"PARTIAL",
  "reasoning": "paragraph",
  "visual": {"map_readable": bool, "contrast_ok": bool, "lod_ok": bool, "void": bool, "explain": str},
  "daily_pack": {"same_link_same_stars": bool, "lcg_ok": bool, "explain": str},
  "provenance": {"pass": bool},
  "suggestions": []
}`;
}
