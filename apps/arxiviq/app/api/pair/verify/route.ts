import { NextRequest, NextResponse } from "next/server";
import { jarvisFetch, pairDemoEnabled, resolveJarvisBase } from "@/lib/jarvis";

type PairRec = { code: string; exp: number; created: number; paired?: boolean };

const STORE = ((globalThis as any).__dottiePairStore as Map<string, PairRec>) || new Map<string, PairRec>();
(globalThis as any).__dottiePairStore = STORE;

const PAIR_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

function nowSec() {
  return Math.floor(Date.now() / 1000);
}

function normalizeCode(raw: string): string {
  return String(raw || "")
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, 6);
}

function codeValid(code: string): boolean {
  return code.length === 6 && [...code].every((c) => PAIR_ALPHABET.includes(c));
}

/** Accept-any demo path — ONLY when DOTTIE_PAIR_DEMO=1 or JARVIS_URL truly unset. */
function demoVerify(code: string) {
  const existing = STORE.get(code);
  if (existing && nowSec() > existing.exp) {
    STORE.delete(code);
    return NextResponse.json(
      {
        ok: false,
        paired: false,
        code,
        error: "expired (>10m) regenerate via scout pair create",
        demo: true,
        source: "demo",
        provenance: "demo",
      },
      { status: 410 }
    );
  }
  if (!existing) {
    const exp = nowSec() + 600;
    const rec: PairRec = { code, exp, created: nowSec(), paired: true };
    STORE.set(code, rec);
    if (STORE.size > 256) {
      const first = STORE.keys().next().value as string;
      STORE.delete(first);
    }
  } else {
    existing.paired = true;
    STORE.set(code, existing);
  }
  return NextResponse.json({
    ok: true,
    paired: true,
    code,
    exp: STORE.get(code)?.exp,
    tandem: true,
    demo: true,
    source: "demo",
    provenance: "demo",
  });
}

function failClosed(code: string | undefined, reason: string, blocked: boolean) {
  return NextResponse.json(
    {
      ok: false,
      paired: false,
      code,
      error: reason,
      source: blocked ? "blocked" : "unreachable",
      provenance: blocked ? "ssrf_blocked" : "unreachable",
      demo: false,
    },
    { status: blocked ? 403 : 503 }
  );
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const code = normalizeCode((body as any).code || "");
    if (!codeValid(code)) {
      return NextResponse.json(
        { ok: false, error: "code must be 6 chars A-Z2-9 excluding 0/O/1/I/L" },
        { status: 400 }
      );
    }

    const rawUrl = (process.env.JARVIS_URL || "").trim();
    const { base, reason } = resolveJarvisBase();
    const demo = pairDemoEnabled();

    if (base) {
      const proxied = await jarvisFetch("/api/pair/verify", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      if (proxied.ok) {
        return NextResponse.json({
          ...proxied.data,
          source: "jarvis",
          provenance: "jarvisd",
          demo: false,
        });
      }
      // Business error from jarvisd (unknown/expired) — forward honestly
      if (proxied.source === "jarvis" && proxied.data) {
        return NextResponse.json(
          {
            ...proxied.data,
            source: "jarvis",
            provenance: "jarvisd",
            demo: false,
          },
          { status: proxied.status || 400 }
        );
      }
      if (proxied.source === "unreachable" && demo) {
        return demoVerify(code);
      }
      return NextResponse.json(
        {
          ok: false,
          paired: false,
          code,
          error: proxied.error,
          source: proxied.source,
          provenance: proxied.provenance,
          unreachable: proxied.source === "unreachable",
          demo: false,
        },
        { status: proxied.status || 503 }
      );
    }

    // JARVIS_URL was set but invalid/blocked → fail closed (unless explicit demo)
    if (rawUrl && !demo) {
      const blocked = !!reason?.includes("allowlisted");
      return failClosed(code, reason || "JARVIS_URL invalid", blocked);
    }

    // Truly unset, or DOTTIE_PAIR_DEMO=1 → labeled demo
    return demoVerify(code);
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e?.message || "verify failed" }, { status: 500 });
  }
}

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const code = normalizeCode(url.searchParams.get("code") || "");
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
    if (!(proxied.source === "unreachable" && demo)) {
      return NextResponse.json(
        {
          ok: false,
          paired: false,
          code: code || undefined,
          error: proxied.error,
          source: proxied.source,
          provenance: proxied.provenance,
          unreachable: true,
          demo: false,
        },
        { status: proxied.status || 503 }
      );
    }
  } else if (rawUrl && !demo) {
    const blocked = !!reason?.includes("allowlisted");
    return failClosed(code || undefined, reason || "JARVIS_URL invalid", blocked);
  }

  if (!code) {
    return NextResponse.json({
      ok: true,
      count: STORE.size,
      demo: true,
      source: "demo",
      provenance: "demo",
      upgrade_hint: "set JARVIS_URL to proxy jarvisd",
    });
  }
  const rec = STORE.get(code);
  if (!rec) {
    return NextResponse.json({
      ok: false,
      paired: false,
      code,
      source: "demo",
      provenance: "demo",
      demo: true,
    });
  }
  return NextResponse.json({
    ok: true,
    paired: !!rec.paired,
    code,
    exp: rec.exp,
    age_sec: nowSec() - rec.created,
    demo: true,
    source: "demo",
    provenance: "demo",
  });
}
