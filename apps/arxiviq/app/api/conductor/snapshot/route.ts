import { NextRequest, NextResponse } from "next/server";

import { jarvisFetch } from "@/lib/jarvis";
import { readSession, SESSION_COOKIE } from "@/lib/session.mjs";

export const dynamic = "force-dynamic";

function json(body: object, status = 200) {
  const response = NextResponse.json(body, { status });
  response.headers.set("cache-control", "no-store");
  return response;
}

export async function GET(req: NextRequest) {
  const session = readSession(req.cookies.get(SESSION_COOKIE)?.value);
  if (!session || !session.caps.includes("conductor:read")) {
    return json({ ok: false, error: "invalid or expired session" }, 401);
  }
  const query = new URLSearchParams({
    repo: session.repo,
    mission: "default",
  });
  const proxied = await jarvisFetch(`/api/conductor/snapshot?${query}`, {
    method: "GET",
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
