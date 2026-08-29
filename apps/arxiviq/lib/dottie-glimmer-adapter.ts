// dottie-glimmer-adapter.ts — thin wrapper exposing Glimmer as Dottie harness tier
// For Dottie closed-loop factory v2, so Dottie can route low/medium tasks to local Glimmer
// Zero-deps, stdlib only, honest 503

import { glimmerChat, glimmerAgentLoop, dottieToolRegistry, detectProvider, isGlimmerAvailable, GLIMMER_DEFAULT_MODEL, reasoningSystemPrompt } from "./glimmer";
import type { ReasoningLevel, GlimmerTool } from "./glimmer";

export type DottieTier = "deterministic" | "llm" | "deep_research" | "action_operator" | "agentic_epic";

export type DottieTask = {
  id: string;
  goal: string;
  tier_hint?: DottieTier;
  prompt: string;
  context?: Record<string, unknown>;
  reasoning?: ReasoningLevel;
};

export type DottieResult = {
  ok: boolean;
  status: number;
  tier: DottieTier;
  provider: string;
  model: string;
  output: string;
  steps: number;
  latency_ms: number;
  offline: boolean;
  error?: string;
  timeline_logged: boolean;
};

// Tier mapping — Glimmer handles llm + action_operator locally, epic still needs larger model or Forge
export function tierForGlimmer(tier_hint?: DottieTier): DottieTier {
  if (!tier_hint) return "llm";
  if (tier_hint === "deterministic") return "deterministic"; // don't route deterministic to LLM
  if (tier_hint === "agentic_epic") return "agentic_epic"; // may still need Spark 1.2 100B+ or Forge
  return tier_hint; // llm, deep_research, action_operator → Glimmer can handle
}

export async function isGlimmerTierAvailable(): Promise<boolean> {
  const p = await detectProvider();
  return p !== "unavailable";
}

// Main entry: route Dottie task to Glimmer if appropriate, else honest 503 so Dottie falls back
export async function runGlimmerTier(task: DottieTask): Promise<DottieResult> {
  const start = Date.now();
  const model = process.env.GLIMMER_MODEL || GLIMMER_DEFAULT_MODEL;
  const reasoning = task.reasoning || "medium";
  const tier = tierForGlimmer(task.tier_hint);

  // Deterministic tasks should not hit LLM — return honest pass-through
  if (tier === "deterministic") {
    return {
      ok: true,
      status: 200,
      tier,
      provider: "deterministic",
      model: "none",
      output: `deterministic tier — no LLM needed for ${task.id}: ${task.goal}`,
      steps: 0,
      latency_ms: Date.now() - start,
      offline: true,
      timeline_logged: false,
    };
  }

  const provider = await detectProvider();
  if (provider === "unavailable") {
    return {
      ok: false,
      status: 503,
      tier,
      provider,
      model,
      output: "",
      steps: 0,
      latency_ms: Date.now() - start,
      offline: false,
      error: `glimmer unavailable — no Ollama at http://localhost:11434 and no llama.cpp at http://localhost:8080. Pull ${model} via ollama pull. Honest 503, Dottie should fallback to cloud or Forge.`,
      timeline_logged: false,
    };
  }

  const avail = await isGlimmerAvailable(model);
  // If Ollama up but model not pulled, still try — Ollama will 503 with clear message
  const tools = dottieToolRegistry();

  // Add task-specific tools if context provides file paths
  if (task.context?.extraTools) {
    // extraTools expected as GlimmerTool[] — merge
    const extra = task.context.extraTools as GlimmerTool[];
    tools.push(...extra);
  }

  const prompt = `${task.prompt}\n\nGoal: ${task.goal}\nTask ID: ${task.id}\nTier: ${tier}\nReasoning: ${reasoning}\nSystem: ${reasoningSystemPrompt(reasoning).slice(0, 300)}`;

  const res = await glimmerAgentLoop(prompt, tools, { model, reasoning, maxSteps: tier === "agentic_epic" ? 8 : 5 });

  return {
    ok: res.ok,
    status: res.status,
    tier,
    provider: res.provider,
    model: res.model,
    output: res.final,
    steps: res.steps.length,
    latency_ms: Date.now() - start,
    offline: res.offline,
    error: res.error,
    timeline_logged: res.timeline_logged,
  };
}

// Simple LLM tier wrapper (no tools) for fast chat
export async function glimmerLLM(prompt: string, reasoning: ReasoningLevel = "low"): Promise<DottieResult> {
  const start = Date.now();
  const model = process.env.GLIMMER_MODEL || GLIMMER_DEFAULT_MODEL;
  const res = await glimmerChat(prompt, { model, reasoning, maxSteps: 2 });
  return {
    ok: res.ok,
    status: res.status,
    tier: "llm",
    provider: res.provider,
    model: res.model,
    output: res.final,
    steps: res.steps.length,
    latency_ms: Date.now() - start,
    offline: res.offline,
    error: res.error,
    timeline_logged: res.timeline_logged,
  };
}

// Export default adapter
const dottieGlimmerAdapter = {
  runGlimmerTier,
  glimmerLLM,
  tierForGlimmer,
  isGlimmerTierAvailable,
  GLIMMER_DEFAULT_MODEL,
};

export default dottieGlimmerAdapter;
