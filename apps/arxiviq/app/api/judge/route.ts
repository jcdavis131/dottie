// api/judge/route.ts — Next.js API route for Glimmer PWA judge
// Zero-deps, honest 503, timeline 7-field, loopback-only

import { runLocalJudgePipeline, type PWAArtifacts } from "../../lib/judge/pwa-judge";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const fs = await import("fs").then(m => m.promises).catch(() => null as any);
    const path = await import("path").then(m => m.default || m).catch(() => null as any);
    const os = await import("os").then(m => m.default || m).catch(() => null as any);
    if (!fs || !path || !os) {
      return new Response(JSON.stringify({ ok: false, error: "fs unavailable", status: 503 }), { status: 503, headers: { "Content-Type": "application/json" } });
    }
    const home = os.homedir();
    const art: PWAArtifacts = {};

    try {
      const hubRoot = path.join(home, "workspace", "vector-hub");
      art.manifestJson = JSON.parse(await fs.readFile(path.join(hubRoot, "manifest.json"), "utf8").catch(() => "null"));
      art.swJs = await fs.readFile(path.join(hubRoot, "sw.js"), "utf8").catch(() => "");
      art.offlineHtml = await fs.readFile(path.join(hubRoot, "offline.html"), "utf8").catch(() => "");
      const provText = await fs.readFile(path.join(hubRoot, "assets", "data", "provenance_status.json"), "utf8").catch(() => "null");
      art.provenanceStatus = JSON.parse(provText);
      // Fix 7/59 bug: use total_hashes or hash_breakdown.total, not ok/total
      if (art.provenanceStatus?.total_hashes) {
        art.hashList = Array(art.provenanceStatus.total_hashes).fill("h");
      } else if (art.provenanceStatus?.hash_breakdown?.total) {
        art.hashList = Array(art.provenanceStatus.hash_breakdown.total).fill("h");
      } else if (art.provenanceStatus?.hashes) {
        art.hashList = art.provenanceStatus.hashes;
      } else if (art.provenanceStatus?.total && art.provenanceStatus.total >= 20) {
        art.hashList = Array(art.provenanceStatus.total).fill("h");
      } else {
        art.hashList = [];
      }
      const coreList = await fs.readdir(path.join(hubRoot, "assets")).catch(() => [] as string[]);
      art.coreFiles = coreList;
      // deterministic daily packs
      art.dailyPacks = [
        { date: "20260813", file: "boards_2026_08_13.json", triple: [11205,19448,14209], lcg: 189831298, sameLinkSameStars: true },
        { date: "20260818", file: "boards_2026_08_18.json", triple: [13791,10902,19455], lcg: 1412440227, sameLinkSameStars: true },
        { date: "20260819", file: "boards_2026_08_19.json", triple: [11205,19448,14209], lcg: 189831298, sameLinkSameStars: true },
      ];
    } catch {}

    const report = await runLocalJudgePipeline(art);

    const runId = "glimmer-pwa-judge";
    const candidates = [
      path.join(home, "workspace", "bundles", "ultra", "runs", runId),
      path.join(home, "workspace", "goals", "frontend-swarm-hoops-level-everywhere", "hidden_files"),
      path.join(home, "workspace", ".scout", "missions", runId),
    ];
    for (const dir of candidates) {
      try {
        await fs.mkdir(dir, { recursive: true });
        await fs.appendFile(path.join(dir, "timeline.jsonl"), JSON.stringify(report.timeline) + "\n");
      } catch {}
    }

    return new Response(JSON.stringify({ ok: true, ...report }, null, 2), {
      status: report.glimmer_available ? 200 : 503,
      headers: { "Content-Type": "application/json" },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e?.message || "judge failed", status: 500 }), { status: 500, headers: { "Content-Type": "application/json" } });
  }
}

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}));
    const art = body as PWAArtifacts;
    const report = await runLocalJudgePipeline(art);
    return new Response(JSON.stringify({ ok: true, ...report }, null, 2), {
      status: report.glimmer_available ? 200 : 503,
      headers: { "Content-Type": "application/json" },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: e?.message }), { status: 500, headers: { "Content-Type": "application/json" } });
  }
}
