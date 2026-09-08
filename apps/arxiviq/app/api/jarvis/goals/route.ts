import { NextRequest, NextResponse } from "next/server";

import { jarvisFetch } from "@/lib/jarvis";
import { readSession, SESSION_COOKIE } from "@/lib/session.mjs";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const session = readSession(req.cookies.get(SESSION_COOKIE)?.value);
  if (!session) {
    const response = NextResponse.json(
      { ok: false, goals: [], source: "blocked", provenance: "edge_auth_required", error: "invalid or expired session" },
      { status: 401 },
    );
    response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, secure: true, sameSite: "strict", path: "/", maxAge: 0 });
    return response;
  }
  const status = req.nextUrl.searchParams.get("status");
  if (status !== null && !["open", "done", "dropped"].includes(status)) {
    return NextResponse.json({ ok: false, goals: [], error: "unsupported status filter" }, { status: 400 });
  }
  const params = new URLSearchParams({ repo: session.repo, status: status || "open" });
  const proxied = await jarvisFetch(`/api/goals?${params}`, {
    method: "GET",
    agentId: `arxiviq-session-${session.sid}`,
    ephemeralAuth: true,
  });
  if (proxied.ok) {
    return NextResponse.json({ ...proxied.data, source: "jarvis", provenance: "jarvisd" });
  }
  return NextResponse.json(
    { ...(proxied.data || { ok: false, goals: [], error: proxied.error }), source: proxied.source, provenance: proxied.provenance },
    { status: proxied.status },
  );
}
