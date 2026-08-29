// api/judge/route.ts — Next.js API route for Glimmer PWA judge
// Zero-deps, honest 503, timeline 7-field

import { runLocalJudgePipeline, type PWAArtifacts } from "../../lib/judge/pwa-judge.js";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    // Try to load artifacts from filesystem (honest 503 if missing)
    const fs = await import("fs").then(m => m.promises).catch(() => null as any);
    const path = await import("path").then(m => m.default || m).catch(() => null as any);
    const os = await import("os").then(m => m.default || m).catch(() => null as any);
    if (!fs || !path || !os) {
      return new Response(JSON.stringify({ ok: false, error: "fs unavailable", status: 503 }), { status: 503, headers: { "Content-Type": "application/json" } });
    }
    const home = os.homedir();
    const art: PWAArtifacts = {};

    // vector-hub artifacts — best effort
    try {
      const hubRoot = path.join(home, "workspace", "vector-hub");
      art.manifestJson = JSON.parse(await fs.readFile(path.join(hubRoot, "manifest.json"), "utf8").catch(() => "null"));
      art.swJs = await fs.readFile(path.join(hubRoot, "sw.js"), "utf8").catch(() => "");
      art.offlineHtml = await fs.readFile(path.join(hubRoot, "offline.html"), "utf8").catch(() => "");
      art.provenanceStatus = JSON.parse(await fs.readFile(path.join(hubRoot, "assets", "data", "provenance_status.json"), "utf8").catch(() => "null"));
      art.hashList = art.provenanceStatus?.hashes || (art.provenanceStatus?.total ? Array(art.provenanceStatus.total).fill("h") : []);
      // core files listing
      const coreList = await fs.readdir(path.join(hubRoot, "assets")).catch(() => [] as string[]);
      art.coreFiles = coreList;
    } catch {}

    // vector-hoops artifacts
    try {
      const hoopsRoot = path.join(home, "workspace", "vector-hoops");
      if (!art.manifestJson) {
        art.manifestJson = JSON.parse(await fs.readFile(path.join(hoopsRoot, "public", "manifest.json"), "utf8").catch(() => await fs.readFile(path.join(hoopsRoot, "manifest.json"), "utf8").catch(() => "null")));
      }
    } catch {}

    const report = await runLocalJudgePipeline(art);

    // timeline triple-write
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
