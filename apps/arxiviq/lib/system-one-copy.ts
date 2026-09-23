export const SITE_NAME = "arxiviq.com";
export const PRODUCT_NAME = "dottie-os";

export const HERO_TITLE = "dottie-os";
export const HERO_SUBHEAD =
  "local System One decisions for tools and pair-programming";
export const HERO_LEDE =
  "State + typed questions → Choice / Score / Noul, with the probability named as a probability. Runs on your GPU (Laya champion). Not a chat bot.";

export const META_TITLE = "dottie-os — local System One decisions · arxiviq.com";
export const META_DESCRIPTION =
  "State + typed questions → Choice, Score, and Noul — a named probability, not a hedge. Local Laya champion on your tailnet. Not a chat bot. Solo personal project, MIT, free-tier.";

export const OG_TITLE = "dottie-os — local System One decisions";
export const OG_DESCRIPTION =
  "A local System One sidecar for tools and pair-programming. Choice · Score · Noul. Laya champion on your tailnet. Solo, MIT, free-tier.";

export const CHOICE_OPTIONS = ["execute", "escalate", "halt", "other"] as const;

export const PRIMITIVES = [
  {
    name: "Choice",
    symbol: "execute | escalate | halt | other",
    body: "One closed action for a pair-programmer step. The sidecar picks a label instead of drafting a paragraph you have to parse.",
  },
  {
    name: "Score",
    symbol: "severity",
    body: "An ordered severity level for the step in front of you. A rubric, not a vibe word from a chat model.",
  },
  {
    name: "Noul",
    symbol: "P(safe)",
    body: "The probability the next action is safe to take. A named probability — not a hedge buried in prose.",
  },
] as const;

export const CHAMPION = {
  helper: "Laya",
  mode: "CHAMPION",
  decide: "/decide",
  surface: "on your tailnet",
  smoke: "local /decide check — this page does not curl a private host",
  ckpt_id: "not published on this page",
  pack_rows: "not published as a live meter",
  provenance: "static stamp",
  as_of: "2026-09-21",
  note: "Cam stamps held-out bench before promote. No public MagicDNS.",
} as const;

export const FLYWHEEL_STEPS = [
  {
    n: "01",
    title: "Gather",
    body: "Public Hugging Face plus observed pair-programming traces. Honest inputs only — no synthetic champion rows.",
  },
  {
    n: "02",
    title: "Curate",
    body: "Choice / Score / Noul factory: honest HELPER rows, Nimble contrastive flips (≤8 words), then staging JSONL.",
  },
  {
    n: "03",
    title: "Stamp",
    body: "Fine-tune, then a held-out bench. Cam stamps before anything is champion. Nothing auto-promotes.",
  },
] as const;

export const REFUSALS = [
  "Synthetic rows do not train a champion.",
  "Checkpoints do not auto-promote.",
  "Bots do not approve merge or ship.",
] as const;

export const NOT_CHAT_LEAD =
  "This is a decision sidecar, not a chat train control plane.";
export const NOT_CHAT_VERB = "decide";
export const NOT_CHAT_VERB_GLOSS = "calibrated probabilities, not a transcript to parse.";
export const NOT_CHAT_ARCHIVE =
  "LLMVM chat and watch-the-box-train dashboards are lab archive, not this product.";
export const NOT_CHAT = `${NOT_CHAT_LEAD} The verb is ${NOT_CHAT_VERB} — ${NOT_CHAT_VERB_GLOSS} ${NOT_CHAT_ARCHIVE}`;

export const DISCLAIMER =
  "Solo personal project, no connection to employer, built with public/free-tier only. Hosted on Vercel Hobby. MIT.";

export const LAB_ARCHIVE =
  "Older WSD / base1b / YaRN / J-Space / Alienware telemetry pages are lab archive. They are not the homepage story.";
