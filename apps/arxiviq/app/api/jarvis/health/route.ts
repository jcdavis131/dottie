import { NextResponse } from "next/server";
import { jarvisFetch, resolveJarvisBase } from "@/lib/jarvis";

export async function GET() {
  const { base, reason } = resolveJarvisBase();
  if (!base) {
    return NextResponse.json({
      ok: false,
      unreachable: true,
      source: "unreachable",
      provenance: "unreachable",
      error: reason || "JARVIS_URL unset",
    });
  }
  const proxied = await jarvisFetch("/api/health", { method: "GET" });
  if (!proxied.ok) {
    return NextResponse.json(
      {
        ok: false,
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
