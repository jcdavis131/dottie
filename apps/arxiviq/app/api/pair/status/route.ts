import { NextRequest, NextResponse } from "next/server";
import { jarvisFetch, pairDemoEnabled, resolveJarvisBase } from "@/lib/jarvis";

const STORE = ((globalThis as any).__dottiePairStore as Map<string, any>) || new Map();
(globalThis as any).__dottiePairStore = STORE;

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const code = (url.searchParams.get("code") || "").toUpperCase().trim().slice(0, 6);
  const rawUrl = (process.env.JARVIS_URL || "").trim();
  const { base, reason } = resolveJarvisBase();
  const demo = pairDemoEnabled();

  if (base) {
    const path = code ? `/api/pair/status?code=${encodeURIComponent(code)}` : "/api/pair/status";
    const proxied = await jarvisFetch(path, { method: "GET" });
    if (proxied.ok) {
      return NextResponse.json({
        ...proxied.data,
        source: "jarvis",
        provenance: "jarvisd",
        demo: false,
      });
    }
    if (proxied.source === "jarvis" && proxied.data) {
      return NextResponse.json(
        { ...proxied.data, source: "jarvis", provenance: "jarvisd", demo: false },
        { status: proxied.status || 400 }
      );
    }
    if (proxied.source === "unreachable" && demo) {
      // fall through to demo store
    } else {
      return NextResponse.json(
        {
          ok: false,
          paired: false,
          code: code || undefined,
          unreachable: true,
          source: "unreachable",
          provenance: "unreachable",
          error: proxied.error,
          demo: false,
        },
        { status: 503 }
      );
    }
  } else if (rawUrl && !demo) {
    const blocked = !!reason?.includes("allowlisted");
    return NextResponse.json(
      {
        ok: false,
        paired: false,
        code: code || undefined,
        error: reason || "JARVIS_URL invalid",
        source: blocked ? "blocked" : "unreachable",
        provenance: blocked ? "ssrf_blocked" : "unreachable",
        demo: false,
      },
      { status: blocked ? 403 : 503 }
    );
  }

  if (code) {
    const rec = STORE.get(code);
    if (!rec) {
      return NextResponse.json({
        ok: false,
        paired: false,
        code,
        demo: true,
        source: "demo",
        provenance: "demo",
      });
    }
    return NextResponse.json({
      ok: true,
      paired: !!rec.paired,
      code,
      exp: rec.exp,
      count: STORE.size,
      demo: true,
      source: "demo",
      provenance: "demo",
    });
  }

  return NextResponse.json({
    ok: true,
    paired_count: STORE.size,
    demo: true,
    source: "demo",
    provenance: "demo",
    queue_demo: "fs /ws/.dottie/queue or redis dottie:queue or Supabase realtime",
    tandem: "local+docker+website link",
  });
}
