import { NextRequest, NextResponse } from "next/server";

import { readBoundedJson } from "@/lib/bounded-json";
import { jarvisFetch } from "@/lib/jarvis";
import {
  readSession,
  SESSION_COOKIE,
  validatePublicOrigin,
} from "@/lib/session.mjs";

export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 16 * 1024;
const METHODS = [
  "feedback.push",
  "scratchpad.write",
  "todo.create",
  "todo.move",
] as const;
type ConductorMethod = (typeof METHODS)[number];

function json(body: object, status = 200) {
  const response = NextResponse.json(body, { status });
  response.headers.set("cache-control", "no-store");
  return response;
}

function exactKeys(value: unknown, expected: string[]): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(value as object).sort();
  return keys.length === expected.length &&
    keys.every((key, index) => key === [...expected].sort()[index]);
}

function isConductorMethod(value: string): value is ConductorMethod {
  return METHODS.some((method) => method === value);
}

function validRequest(body: unknown): body is {
  method: ConductorMethod;
  params: Record<string, unknown>;
} {
  if (!exactKeys(body, ["method", "params"])) return false;
  if (typeof body.method !== "string" || !isConductorMethod(body.method)) return false;
  const params = body.params;
  switch (body.method) {
    case "feedback.push":
      return exactKeys(params, ["kind", "message", "strength"]);
    case "scratchpad.write":
      return exactKeys(params, ["text"]);
    case "todo.create":
      return exactKeys(params, ["priority", "text"]);
    case "todo.move":
      return exactKeys(params, ["id", "status"]);
    default: {
      const exhaustive: never = body.method;
      return exhaustive;
    }
  }
}

export async function POST(req: NextRequest) {
  const session = readSession(req.cookies.get(SESSION_COOKIE)?.value);
  if (!session || !session.caps.includes("conductor:write")) {
    return json({ ok: false, error: "invalid or expired session" }, 401);
  }
  const publicOrigin = validatePublicOrigin(process.env.ARXIVIQ_PUBLIC_ORIGIN);
  const fetchSite = req.headers.get("sec-fetch-site");
  if (
    !publicOrigin ||
    req.headers.get("origin") !== publicOrigin ||
    (fetchSite !== null && fetchSite !== "same-origin" && fetchSite !== "none")
  ) {
    return json({ ok: false, error: "same-origin request required" }, 403);
  }
  const parsed = await readBoundedJson(req, MAX_BODY_BYTES);
  if (!parsed.ok) return json({ ok: false, error: parsed.error }, parsed.status);
  const body = parsed.value;
  if (!validRequest(body)) {
    return json({ ok: false, error: "unsupported conductor request" }, 400);
  }
  const query = new URLSearchParams({
    repo: session.repo,
    mission: "default",
  });
  const proxied = await jarvisFetch(`/api/conductor/rpc?${query}`, {
    method: "POST",
    body: JSON.stringify(body),
    agentId: `arxiviq-session-${session.sid}`,
    ephemeralAuth: true,
  });
  if (proxied.ok) return json(proxied.data);
  return json(
    {
      ok: false,
      error: proxied.error,
      source: proxied.source,
      provenance: proxied.provenance,
    },
    proxied.status,
  );
}
