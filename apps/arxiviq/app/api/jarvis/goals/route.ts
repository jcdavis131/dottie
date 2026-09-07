import { NextRequest, NextResponse } from "next/server";
import { jarvisFetch, resolveJarvisBase } from "@/lib/jarvis";

export async function GET(req: NextRequest) {
  const { base, reason } = resolveJarvisBase();
  if (!base) {
    return NextResponse.json({
      ok: false,
      goals: [],
      unreachable: true,
      source: "unreachable",
      provenance: "unreachable",
      error: reason || "JARVIS_URL unset",
    });
  }
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const path = qs ? `/api/goals?${qs}` : "/api/goals";
  const proxied = await jarvisFetch(path, { method: "GET" });
  if (!proxied.ok) {
    return NextResponse.json(
      {
        ok: false,
        goals: [],
        unreachable: true,
        source: "unreachable",
        provenance: "unreachable",
        error: proxied.error,
      },
      { status: 503 }
    );
  }
  return NextResponse.json({
    ...proxied.data,
    source: "jarvis",
    provenance: "jarvisd",
  });
}
