import { NextResponse } from "next/server";
import { jarvisFetch } from "@/lib/jarvis";

export const dynamic = "force-dynamic";

export async function GET() {
  const proxied = await jarvisFetch("/api/health", { method: "GET" });
  if (!proxied.ok) {
    return NextResponse.json(
      {
        ok: false,
        unreachable: true,
        source: proxied.source,
        provenance: proxied.provenance,
        error: proxied.error,
      },
      { status: proxied.status }
    );
  }
  return NextResponse.json({
    ...proxied.data,
    source: "jarvis",
    provenance: "jarvisd",
  });
}
