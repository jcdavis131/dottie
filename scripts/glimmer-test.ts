// scripts/glimmer-test.ts — test Muse Glimmer 30B local harness
// Zero-deps, stdlib only, honest 503 if GPU blocked
// Usage: node --loader ts-node/esm scripts/glimmer-test.ts
// Or: npx tsx scripts/glimmer-test.ts
// Branch: scout/glimmer-dottie-harness

import { glimmerChat, detectProvider, isGlimmerAvailable, checkOfflineWeights, listAvailableModels, GLIMMER_DEFAULT_MODEL, GLIMMER_HF_REPO, OLLAMA_BASE_URL, LLAMA_CPP_URL } from "../apps/arxiviq/lib/glimmer.js";

const MODEL = process.env.GLIMMER_MODEL || GLIMMER_DEFAULT_MODEL;

async function main() {
  console.log("=== Glimmer Local Harness Test ===");
  console.log(`Model: ${MODEL}`);
  console.log(`HF Repo: ${GLIMMER_HF_REPO}`);
  console.log(`Ollama: ${OLLAMA_BASE_URL}`);
  console.log(`Llama.cpp: ${LLAMA_CPP_URL}`);
  console.log(`Time: ${new Date().toISOString()}`);
  console.log("");

  console.log("[1/4] Detecting provider...");
  const provider = await detectProvider();
  console.log(`Provider: ${provider}`);
  if (provider === "unavailable") {
    console.log("⚠ No local gateway — honest 503 expected");
    console.log(`  Pull via: ollama pull ${MODEL} OR huggingface-cli download ${GLIMMER_HF_REPO}`);
    console.log(`  Then re-run this test`);
    // Still check offline cache
  }

  console.log("");
  console.log("[2/4] Checking offline weights...");
  const offline = await checkOfflineWeights();
  console.log(`Offline ready: ${offline.offline_ready} — ${offline.note} — path: ${offline.path || "n/a"} — size: ${offline.size_mb || "?"} MB`);

  console.log("");
  console.log("[3/4] Listing models...");
  const models = await listAvailableModels();
  console.log(`Found ${models.length} models:`);
  models.forEach((m) => console.log(`  - ${m.name} (${m.provider}) ${m.size ? `${Math.round(m.size/1e9)}GB` : ""} ${m.modified_at || ""}`));
  if (models.length === 0) console.log("  (none — need ollama pull)");

  console.log("");
  console.log("[4/4] Testing agent loop (plan→tool→check→recover)...");
  const avail = await isGlimmerAvailable(MODEL);
  console.log(`Glimmer available: ${avail.available} provider=${avail.provider} info=${JSON.stringify(avail.info||{}).slice(0,200)}`);

  if (!avail.available && provider !== "unavailable") {
    console.log(`Model ${MODEL} not in Ollama library — attempting chat will 503 but provider is up. Pull first: ollama pull ${MODEL}`);
  }

  // Simple prompt that exercises planning loop
  const prompt = "You are testing the local Glimmer harness. List 2 benefits of running a 30B agent locally vs cloud, and call glimmer_health to verify gateway. If done, say DONE.";

  try {
    const res = await glimmerChat(prompt, { model: MODEL, reasoning: "low", maxSteps: 4 });
    console.log("");
    console.log("=== Agent Loop Result ===");
    console.log(`ok: ${res.ok} status: ${res.status} provider: ${res.provider} model: ${res.model} reasoning: ${res.reasoning} offline: ${res.offline} timeline_logged: ${res.timeline_logged}`);
    console.log(`steps: ${res.steps.length}`);
    res.steps.forEach((s, i) => {
      console.log(`  step ${i} ${s.status} tool=${s.tool||"—"} thought=${(s.thought||"").slice(0,120)} latency=${s.latency_ms}ms`);
      if (s.toolResult) console.log(`    result: ${JSON.stringify(s.toolResult).slice(0,200)}`);
    });
    console.log(`final: ${res.final.slice(0, 800)}`);
    if (res.error) console.log(`error: ${res.error}`);
  } catch (e: any) {
    console.log(`Agent loop threw: ${e?.message||e}`);
    console.log("Stack:", e?.stack?.slice(0, 500));
  }

  console.log("");
  console.log("=== Test Complete ===");
  console.log("Expected on Hatch CPU (no GPU): honest 503 with offline=false, provider=unavailable — not simulated success");
  console.log("Expected on Alienware Forge (GPU): provider=ollama or llamacpp, offline=true after pull, ok=true, steps>=2");
}

main().catch((e) => { console.error(e); process.exit(1); });
