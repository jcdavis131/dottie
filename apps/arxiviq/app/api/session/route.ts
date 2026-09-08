import { NextRequest, NextResponse } from "next/server";

import {
  readSession,
  SESSION_COOKIE,
  validateSessionConfig,
} from "@/lib/session.mjs";

export const dynamic = "force-dynamic";

function clear(response: NextResponse) {
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
  return response;
}

export async function GET(req: NextRequest) {
  try {
    validateSessionConfig();
  } catch {
    return NextResponse.json(
      { ok: false, error: "authenticated sessions are not configured" },
      { status: 503 },
    );
  }
  const claims = readSession(req.cookies.get(SESSION_COOKIE)?.value);
  if (!claims) {
    return clear(
      NextResponse.json(
        { ok: false, error: "invalid or expired session" },
        { status: 401 },
      ),
    );
  }
  return NextResponse.json({
    ok: true,
    authenticated: true,
    expires_at: claims.exp,
    caps: claims.caps,
    repo: claims.repo,
  });
}

export async function DELETE() {
  return clear(NextResponse.json({ ok: true, authenticated: false }));
}
