import { NextResponse } from "next/server";
import { glimmerApiHandler, detectProvider, isGlimmerAvailable, checkOfflineWeights, GLIMMER_DEFAULT_MODEL, GLIMMER_HF_REPO, OLLAMA_BASE_URL, LLAMA_CPP_URL } from "../../lib/glimmer";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// GET /api/glimmer — health + model list, honest 503 if down
export async function GET() {
  const provider = await detectProvider();
  const avail = await isGlimmerAvailable(GLIMMER_DEFAULT_MODEL);
  const offline = await checkOfflineWeights();

  if (provider === "unavailable") {
    return NextResponse.json(
      {
        ok: false,
        status: 503,
        provider,
        model: GLIMMER_DEFAULT_MODEL,
        hf_repo: GLIMMER_HF_REPO,
        ollama_url: OLLAMA_BASE_URL,
        llamacpp_url: LLAMA_CPP_URL,
        offline,
        error: "glimmer unavailable — no local gateway",
        hint: `ollama pull ${GLIMMER_DEFAULT_MODEL} OR huggingface-cli download ${GLIMMER_HF_REPO}`,
        policy: "honest-503-never-synthetic",
        timestamp: new Date().toISOString(),
      },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  return NextResponse.json(
    {
      ok: true,
      provider,
      model: GLIMMER_DEFAULT_MODEL,
      available: avail.available,
      info: avail.info,
      offline,
      hf_repo: GLIMMER_HF_REPO,
      endpoints: { ollama: OLLAMA_BASE_URL, llamacpp: LLAMA_CPP_URL },
      reasoning_levels: ["low", "medium", "high", "xhigh"],
      loop: "plan→tool→check→recover",
      timestamp: new Date().toISOString(),
    },
    { headers: { "Cache-Control": "no-store" } }
  );
}

// POST /api/glimmer — agent loop
export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}));
    const { prompt, reasoning, model } = body as { prompt?: string; reasoning?: "low"|"medium"|"high"|"xhigh"; model?: string };
    const result = await glimmerApiHandler({ prompt, reasoning, model });
    return NextResponse.json(result.body, { status: result.status, headers: { "Cache-Control": "no-store" } });
  } catch (e: any) {
    return NextResponse.json({ ok: false, status: 500, error: e?.message || String(e) }, { status: 500 });
  }
}
