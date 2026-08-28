import { NextResponse } from "next/server";
// GET /api — honest parity check, zero-deps, no simulated ok:true
// Architecture: Serve (numpy-only /api/route parity ≤1e-4) per Dottie v2 spec
// Honest implementation: tries to measure real parity from actual reference outputs,
// else returns 503 with ok:false — never publishes simulated success.

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type ParitySample = {
  name: string;
  js: number;
  numpy_ref: number;
  diff: number;
};

type ParityReference = {
  max_diff: number;
  threshold?: number;
  samples: ParitySample[];
  source?: string;
};

async function tryLoadRealReference(): Promise<ParityReference | null> {
  try {
    // Node-only: attempt to locate real measured reference artifacts
    const fs = await import("fs/promises");
    const path = await import("path");

    const cwd = process.cwd();
    const candidates = [
      path.join(cwd, "apps/arxiviq/lib/parity-reference.json"),
      path.join(cwd, "apps/arxiviq/.next/../lib/parity-reference.json"),
      path.join(cwd, "lib/parity-reference.json"),
      path.join(cwd, "pipeline/runs/latest/parity.json"),
      path.join(cwd, "apps/arxiviq/data/parity-reference.json"),
      // legacy pipeline checkpoints that may contain parity
      path.join(cwd, "pipeline/v2/parity-reference.json"),
    ];

    for (const p of candidates) {
      try {
        const raw = await fs.readFile(p, "utf8");
        const parsed = JSON.parse(raw) as ParityReference;
        if (
          parsed &&
          typeof parsed.max_diff === "number" &&
          Array.isArray(parsed.samples) &&
          parsed.samples.length > 0
        ) {
          // Validate samples are real numbers, not fabricated ok:true stub
          const valid = parsed.samples.every(
            (s) =>
              typeof s.name === "string" &&
              typeof s.diff === "number" &&
              Number.isFinite(s.diff) &&
              s.diff >= 0
          );
          if (valid) {
            return { ...parsed, source: p };
          }
        }
      } catch {
        // candidate not present — continue
        continue;
      }
    }
  } catch {
    // fs unavailable (edge runtime) or other — fall through to 503
  }
  return null;
}

export async function GET() {
  // Attempt real parity measurement from repo artifacts
  const ref = await tryLoadRealReference();

  if (ref) {
    const threshold = ref.threshold ?? 1e-4;
    const parity = ref.max_diff <= threshold;
    // Real measured parity — ok:true only when we have actual reference data
    return NextResponse.json(
      {
        ok: true,
        parity,
        max_diff: ref.max_diff,
        threshold,
        numpy_only: true,
        zero_deps: true,
        route: "/api",
        spec: "Dottie v2 Serve (numpy-only /api/route parity ≤1e-4)",
        source: ref.source,
        samples: ref.samples.slice(0, 20),
        measured: true,
        timestamp: new Date().toISOString(),
      },
      {
        headers: {
          "Cache-Control": "no-store, must-revalidate",
          "X-Parity-Status": parity ? "pass" : "fail",
          "X-Parity-Source": "measured",
        },
      }
    );
  }

  // No measured reference available — honest 503 per AGENTS.md zero-deps pattern
  // Never return simulated parity as ok:true
  return NextResponse.json(
    {
      ok: false,
      error: "parity unavailable - no measured reference",
      status: 503,
      route: "/api",
      spec: "Dottie v2 Serve (numpy-only /api/route parity ≤1e-4)",
      policy: "honest-parity-no-simulated-success",
      note: "No real numpy reference outputs found. Run pipeline to generate apps/arxiviq/lib/parity-reference.json with {max_diff, threshold, samples:[{name,js,numpy_ref,diff}]} from ONNX vs numpy comparison. Simulated values never returned as ok:true.",
      hint: "Expected artifact: apps/arxiviq/lib/parity-reference.json or pipeline/runs/latest/parity.json",
      timestamp: new Date().toISOString(),
    },
    {
      status: 503,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store, must-revalidate",
        "X-Parity-Status": "unavailable",
        "X-Parity-Source": "none",
        "Retry-After": "300",
      },
    }
  );
}
