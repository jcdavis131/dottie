import { NextRequest, NextResponse } from "next/server";

import { jarvisFetch } from "@/lib/jarvis";
import { readSession, SESSION_COOKIE } from "@/lib/session.mjs";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const session = readSession(req.cookies.get(SESSION_COOKIE)?.value);
  if (!session) {
    const response = NextResponse.json(
      { ok: false, claims: [], source: "blocked", provenance: "edge_auth_required", error: "invalid or expired session" },
      { status: 401 },
    );
    response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, secure: true, sameSite: "strict", path: "/", maxAge: 0 });
    return response;
  }
  const released = req.nextUrl.searchParams.get("released");
  if (released !== null && released !== "0" && released !== "1") {
    return NextResponse.json({ ok: false, claims: [], error: "unsupported released filter" }, { status: 400 });
  }
  const params = new URLSearchParams({ repo: session.repo });
  if (released === "1") params.set("released", "1");
  const proxied = await jarvisFetch(`/api/claims?${params}`, {
    method: "GET",
    agentId: `arxiviq-session-${session.sid}`,
    ephemeralAuth: true,
  });
  if (proxied.ok) {
    return NextResponse.json({ ...proxied.data, source: "jarvis", provenance: "jarvisd" });
  }
  return NextResponse.json(
    { ...(proxied.data || { ok: false, claims: [], error: proxied.error }), source: proxied.source, provenance: proxied.provenance },
    { status: proxied.status },
  );
}
