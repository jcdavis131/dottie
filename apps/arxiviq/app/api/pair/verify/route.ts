import { NextRequest, NextResponse } from "next/server";

import { readBoundedJson } from "@/lib/bounded-json";
import { jarvisFetch } from "@/lib/jarvis";
import { allowPairRequest, resolvePairClient } from "@/lib/pair-rate";
import {
  createSession,
  SESSION_COOKIE,
  validatePublicOrigin,
  validateSessionConfig,
} from "@/lib/session.mjs";

const PAIR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const MAX_PAIR_BODY_BYTES = 1024;

function normalizeCode(raw: string): string {
  return String(raw || "")
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, 6);
}

function codeValid(code: string): boolean {
  return code.length === 6 && [...code].every((c) => PAIR_ALPHABET.includes(c));
}

function failClosed(
  _code: string | undefined,
  error: string,
  source: "unreachable" | "blocked" | "unset" | "invalid",
  provenance: "unreachable" | "ssrf_blocked" | "unconfigured" | "configuration_error",
  status: number
) {
  return NextResponse.json(
    {
      ok: false,
      paired: false,
      error,
      source,
      provenance,
    },
    { status }
  );
}

export async function POST(req: NextRequest) {
  try {
    try {
      validateSessionConfig();
    } catch {
      return failClosed(
        undefined,
        "authenticated pairing is not configured",
        "unset",
        "unconfigured",
        503
      );
    }
    const publicOrigin = validatePublicOrigin(process.env.ARXIVIQ_PUBLIC_ORIGIN);
    if (!publicOrigin) {
      return failClosed(
        undefined,
        "ARXIVIQ_PUBLIC_ORIGIN must be an exact HTTPS origin or exact loopback HTTP origin",
        "unset",
        "unconfigured",
        503
      );
    }
    const fetchSite = req.headers.get("sec-fetch-site");
    if (
      req.headers.get("origin") !== publicOrigin ||
      (fetchSite !== null && fetchSite !== "same-origin" && fetchSite !== "none")
    ) {
      return failClosed(
        undefined,
        "pair verification requires the configured same origin",
        "blocked",
        "configuration_error",
        403
      );
    }
    const pairClient = resolvePairClient(req, "verify");
    if (!pairClient.ok) {
      return NextResponse.json(
        {
          ok: false,
          paired: false,
          error: pairClient.error,
          source: "blocked",
          provenance: "edge_client_identity",
        },
        { status: 403 }
      );
    }
    const parsed = await readBoundedJson(req, MAX_PAIR_BODY_BYTES);
    if (!parsed.ok) {
      return NextResponse.json(
        { ok: false, paired: false, error: parsed.error },
        { status: parsed.status }
      );
    }
    if (!allowPairRequest(pairClient, 10)) {
      return NextResponse.json(
        {
          ok: false,
          paired: false,
          error: "pair verification rate limited",
          source: "blocked",
          provenance: "edge_rate_limit",
        },
        { status: 429 }
      );
    }
    const body =
      parsed.value && typeof parsed.value === "object"
        ? (parsed.value as { code?: unknown })
        : {};
    const code = normalizeCode(typeof body.code === "string" ? body.code : "");
    if (!codeValid(code)) {
      return NextResponse.json(
        { ok: false, error: "code must be 6 chars A-Z2-9 excluding 0/O/1/I/L" },
        { status: 400 }
      );
    }

    const proxied = await jarvisFetch("/api/pair/verify", {
      method: "POST",
      body: JSON.stringify({ code }),
      agentId: pairClient.agentId,
      ephemeralAuth: true,
    });
    if (proxied.ok) {
      const session = createSession({
        agent: String(proxied.data?.agent || ""),
        pairExp: Number(proxied.data?.exp),
      });
      const response = NextResponse.json({
        ok: true,
        paired: true,
        expires_at: session.claims.exp,
        source: "jarvis",
        provenance: "jarvisd",
      });
      response.cookies.set(SESSION_COOKIE, session.token, {
        httpOnly: true,
        secure: true,
        sameSite: "strict",
        path: "/",
        maxAge: session.maxAge,
      });
      return response;
    }
    if (proxied.source === "jarvis") {
      return NextResponse.json(
        {
          ok: false,
          paired: false,
          error: proxied.error,
          source: "jarvis",
          provenance: "jarvisd",
        },
        { status: proxied.status || 400 }
      );
    }
    const provenance = proxied.provenance === "jarvisd" ? "unreachable" : proxied.provenance;
    return failClosed(code, proxied.error, proxied.source, provenance, proxied.status);
  } catch (error: unknown) {
    return NextResponse.json(
      {
        ok: false,
        paired: false,
        error: error instanceof Error ? error.message : "verify failed",
        source: "unreachable",
        provenance: "unreachable",
      },
      { status: 500 }
    );
  }
}
