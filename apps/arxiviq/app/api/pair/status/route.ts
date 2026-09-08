import { NextRequest, NextResponse } from "next/server";
import { jarvisFetch } from "@/lib/jarvis";
import { allowPairRequest, resolvePairClient } from "@/lib/pair-rate";

export async function GET(req: NextRequest) {
  const pairClient = resolvePairClient(req, "status");
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
  if (!allowPairRequest(pairClient, 60)) {
    return NextResponse.json(
      {
        ok: false,
        paired: false,
        error: "pair status rate limited",
        source: "blocked",
        provenance: "edge_rate_limit",
      },
      { status: 429 }
    );
  }
  if (req.nextUrl.searchParams.has("code")) {
    return NextResponse.json(
      { ok: false, paired: false, error: "pair codes are accepted only in the POST body" },
      { status: 400 },
    );
  }
  const proxied = await jarvisFetch("/api/pair/status", {
    method: "GET",
    agentId: pairClient.agentId,
    ephemeralAuth: true,
  });
  if (proxied.ok) {
    return NextResponse.json({
      ok: true,
      count: Number(proxied.data?.count || 0),
      paired_count: Number(proxied.data?.paired_count || 0),
      source: "jarvis",
      provenance: "jarvisd",
    });
  }
  if (proxied.source === "jarvis" && proxied.data) {
    return NextResponse.json(
      { ok: false, paired: false, error: proxied.error, source: "jarvis", provenance: "jarvisd" },
      { status: proxied.status || 400 }
    );
  }
  return NextResponse.json(
    {
      ok: false,
      paired: false,
      error: proxied.error,
      source: proxied.source,
      provenance: proxied.provenance,
    },
    { status: proxied.status }
  );
}
