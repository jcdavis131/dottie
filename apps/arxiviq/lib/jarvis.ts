/**
 * Server-only jarvisd client for arxiviq BFF routes.
 * Never import from client components — keeps JARVIS_BEARER off the wire.
 * (No `server-only` package in arxiviq deps — enforce by import path: app/api only.)
 */

import { isIP } from "node:net";

export type JarvisFetchResult =
  | { ok: true; status: number; data: any; source: "jarvis"; provenance: "jarvisd" }
  | {
      ok: false;
      status: number;
      error: string;
      source: "unreachable" | "blocked" | "unset" | "jarvis";
      provenance: "unreachable" | "ssrf_blocked" | "demo" | "jarvisd";
      demo?: boolean;
      data?: any;
    };

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"]);

/** True when host is loopback or RFC1918 / link-local / unique-local (private). */
export function isAllowedJarvisHost(host: string): boolean {
  const h = host.trim().toLowerCase().replace(/^\[|\]$/g, "");
  if (!h) return false;
  if (LOOPBACK_HOSTS.has(h)) return true;
  // bare hostname that is not an IP — refuse (public DNS would be SSRF)
  const ipVersion = isIP(h);
  if (!ipVersion) return false;
  const parts = h.includes(":") ? null : h.split(".").map((x) => Number(x));
  if (parts && parts.length === 4 && parts.every((n) => Number.isInteger(n) && n >= 0 && n <= 255)) {
    const [a, b] = parts;
    if (a === 127) return true; // loopback /8
    if (a === 10) return true; // 10/8
    if (a === 192 && b === 168) return true; // 192.168/16
    if (a === 172 && b >= 16 && b <= 31) return true; // 172.16/12
    // deny 169.254/16 link-local (cloud metadata SSRF)
    return false;
  }
  // IPv6: ::1 + fc00::/7 ULA only — deny fe80::/10 link-local
  if (ipVersion === 6) {
    const lower = h.toLowerCase();
    if (lower === "::1") return true;
    if (lower.startsWith("fc") || lower.startsWith("fd")) return true;
    return false;
  }
  return false;
}

export function resolveJarvisBase(): { base: string | null; reason?: string } {
  let raw = (process.env.JARVIS_URL || "").trim().replace(/\/$/, "");
  if (!raw) return { base: null, reason: "JARVIS_URL unset" };
  for (const suffix of ["/mcp", "/sse"]) {
    if (raw.endsWith(suffix)) raw = raw.slice(0, -suffix.length);
  }
  if (!/^https?:\/\//i.test(raw)) {
    return { base: null, reason: `JARVIS_URL must be http(s), got ${raw}` };
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { base: null, reason: "JARVIS_URL is not a valid URL" };
  }
  if (!isAllowedJarvisHost(url.hostname)) {
    return { base: null, reason: `JARVIS_URL host not allowlisted (loopback/private only): ${url.hostname}` };
  }
  return { base: raw.replace(/\/$/, "") };
}

export function pairDemoEnabled(): boolean {
  const v = (process.env.DOTTIE_PAIR_DEMO || "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

export async function jarvisFetch(
  path: string,
  init: RequestInit & { agentId?: string } = {}
): Promise<JarvisFetchResult> {
  const { base, reason } = resolveJarvisBase();
  if (!base) {
    const blocked = reason?.includes("allowlisted");
    return {
      ok: false,
      status: blocked ? 403 : 503,
      error: reason || "JARVIS_URL unset",
      source: blocked ? "blocked" : "unset",
      provenance: blocked ? "ssrf_blocked" : "demo",
      demo: !blocked,
    };
  }
  const headers = new Headers(init.headers || {});
  headers.set("Content-Type", headers.get("Content-Type") || "application/json");
  const bearer = (process.env.JARVIS_BEARER || "").trim();
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);
  const agent = init.agentId || process.env.DOTTIE_AGENT_ID || process.env.JARVIS_AGENT || "arxiviq";
  headers.set("X-Agent-Id", agent);
  const { agentId: _a, ...rest } = init;
  try {
    const res = await fetch(`${base}${path.startsWith("/") ? path : `/${path}`}`, {
      ...rest,
      headers,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // jarvisd uses HTTP 400 for ok:false business errors — pass through, not "unreachable"
      if (res.status < 500 && data && typeof data === "object") {
        return {
          ok: false,
          status: res.status,
          error: (data as any)?.error || `jarvisd HTTP ${res.status}`,
          source: "jarvis",
          provenance: "jarvisd",
          data,
        };
      }
      return {
        ok: false,
        status: res.status,
        error: (data as any)?.error || `jarvisd HTTP ${res.status}`,
        source: "unreachable",
        provenance: "unreachable",
      };
    }
    return { ok: true, status: res.status, data, source: "jarvis", provenance: "jarvisd" };
  } catch (e: any) {
    return {
      ok: false,
      status: 503,
      error: e?.message || "jarvisd unreachable",
      source: "unreachable",
      provenance: "unreachable",
    };
  }
}
