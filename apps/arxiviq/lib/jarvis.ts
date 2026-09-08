/**
 * Server-only jarvisd client for arxiviq BFF routes.
 * Never import from client components — keeps JARVIS_BEARER off the wire.
 * (No `server-only` package in arxiviq deps — enforce by import path: app/api only.)
 */

import { createHmac, randomBytes } from "node:crypto";
import { isIP } from "node:net";

type JsonRecord = Record<string, unknown>;

export type JarvisFetchResult =
  | { ok: true; status: number; data: JsonRecord; source: "jarvis"; provenance: "jarvisd" }
  | {
      ok: false;
      status: number;
      error: string;
      source: "unreachable" | "blocked" | "unset" | "invalid" | "jarvis";
      provenance: "unreachable" | "ssrf_blocked" | "unconfigured" | "configuration_error" | "jarvisd";
      data?: JsonRecord;
    };

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"]);

function isJsonRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

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
  if (url.username || url.password || url.hash) {
    return { base: null, reason: "JARVIS_URL must not contain credentials or a fragment" };
  }
  const configuredOrigins = (process.env.JARVIS_ALLOWED_ORIGINS || "")
    .split(",")
    .map((origin) => origin.trim().replace(/\/$/, ""))
    .filter(Boolean);
  const allowedOrigins = new Set<string>();
  for (const origin of configuredOrigins) {
    try {
      const parsed = new URL(origin);
      if (parsed.protocol !== "https:" || parsed.origin !== origin || parsed.pathname !== "/") {
        return { base: null, reason: "JARVIS_ALLOWED_ORIGINS must contain exact HTTPS origins" };
      }
      allowedOrigins.add(parsed.origin);
    } catch {
      return { base: null, reason: "JARVIS_ALLOWED_ORIGINS contains an invalid origin" };
    }
  }
  const metadataHost = url.hostname === "169.254.169.254" || url.hostname.toLowerCase() === "fd00:ec2::254";
  const trustedRemote = url.protocol === "https:" && allowedOrigins.has(url.origin);
  if (metadataHost || (!isAllowedJarvisHost(url.hostname) && !trustedRemote)) {
    return { base: null, reason: `JARVIS_URL host not allowlisted: ${url.hostname}` };
  }
  return { base: raw.replace(/\/$/, "") };
}

export async function jarvisFetch(
  path: string,
  init: RequestInit & { agentId?: string; ephemeralAuth?: boolean } = {}
): Promise<JarvisFetchResult> {
  const { base, reason } = resolveJarvisBase();
  if (!base) {
    const blocked = reason?.includes("allowlisted");
    const unset = reason === "JARVIS_URL unset";
    return {
      ok: false,
      status: blocked ? 403 : 503,
      error: blocked
        ? "jarvisd target blocked"
        : unset
          ? "jarvisd is not configured"
          : "jarvisd configuration is invalid",
      source: blocked ? "blocked" : unset ? "unset" : "invalid",
      provenance: blocked ? "ssrf_blocked" : unset ? "unconfigured" : "configuration_error",
    };
  }
  const headers = new Headers(init.headers || {});
  headers.set("Content-Type", headers.get("Content-Type") || "application/json");
  const bearer = (process.env.JARVIS_BEARER || "").trim();
  if (bearer) {
    let token = bearer;
    if (init.ephemeralAuth) {
      const timestamp = Math.floor(Date.now() / 1000);
      const nonce = randomBytes(8).toString("hex");
      const signature = createHmac("sha256", bearer)
        .update(`${timestamp}:${nonce}`)
        .digest("hex")
        .slice(0, 16);
      token = `${signature}:${timestamp}:${nonce}`;
    }
    headers.set("Authorization", `Bearer ${token}`);
  }
  const agent = init.agentId || process.env.DOTTIE_AGENT_ID || process.env.JARVIS_AGENT || "arxiviq";
  headers.set("X-Agent-Id", agent);
  const cleanInit: RequestInit & { agentId?: string; ephemeralAuth?: boolean } = { ...init };
  delete cleanInit.agentId;
  delete cleanInit.ephemeralAuth;
  try {
    const res = await fetch(`${base}${path.startsWith("/") ? path : `/${path}`}`, {
      ...cleanInit,
      headers,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    const data: unknown = await res.json().catch(() => ({}));
    if (!res.ok) {
      // jarvisd uses HTTP 400 for ok:false business errors — pass through, not "unreachable"
      if (res.status < 500 && isJsonRecord(data)) {
        return {
          ok: false,
          status: res.status,
          error: typeof data.error === "string" ? data.error : `jarvisd HTTP ${res.status}`,
          source: "jarvis",
          provenance: "jarvisd",
          data,
        };
      }
      return {
        ok: false,
        status: 503,
        error: "jarvisd unavailable",
        source: "unreachable",
        provenance: "unreachable",
      };
    }
    return {
      ok: true,
      status: res.status,
      data: isJsonRecord(data) ? data : {},
      source: "jarvis",
      provenance: "jarvisd",
    };
  } catch {
    return {
      ok: false,
      status: 503,
      error: "jarvisd unavailable",
      source: "unreachable",
      provenance: "unreachable",
    };
  }
}
