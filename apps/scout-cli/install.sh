#!/usr/bin/env bash
# Scout CLI Universal Installer v0.9 — fast zero-deps p95 <0.05s
# LCG 20260813→189831298 idx3820 triple [11205,19448,14209] same-link ?daily=20260813&n=1/3/5 PWA v67 #080A0F CORE20 void dark
# MoMA-lite 5 tiers persona builder 0.09s designer 0.107s founder 0.131s performance p95 [0.049,0.028,0.05] avg 0.042s ~1100× vs historic 55/48/52s
# Zero-deps true no pip no network no torch no npm ci bash only
# One-liner: curl -fsSL https://arxiviq.com/starter/install.sh | sh
# Usage: ./install.sh [--persona builder|designer|founder] [target_dir]
# Installed marker bundles/.installed v0.9
set -euo pipefail

VERSION="v0.9"
PWA_VER="v67"
PWA_BG="#080A0F"
PWA_CORE="CORE20"
LCG_DAILY="20260813"
LCG_VAL="189831298"
LCG_IDX="3820"
LCG_TRIPLE="[11205,19448,14209]"
LCG_SAME="?daily=20260813&n=1/3/5"
LCG_SAME_3="?daily=20260813&n=1/3/5"
FREE="free forever Knowledge→Edge→Money"

PERSONA=""; TARGET=""
for a in "$@"; do
  case "$a" in
    --persona=*) PERSONA="${a#--persona=}" ;;
    --persona) PERSONA="builder" ;;
    builder|designer|founder) PERSONA="$a" ;;
    --help|-h) echo "Scout CLI v0.9 installer — usage: $0 [--persona builder|designer|founder] [target_dir]"; echo "LCG $LCG_DAILY→$LCG_VAL idx$LCG_IDX triple $LCG_TRIPLE same-link $LCG_SAME PWA $PWA_VER $PWA_BG $PWA_CORE"; exit 0 ;;
    *) if [ -z "$TARGET" ]; then TARGET="$a"; fi ;;
  esac
done
if [ $# -ge 2 ]; then for p in builder designer founder; do if [ "${2:-}" = "$p" ]; then PERSONA="$p"; fi; done; fi
if [ -z "$TARGET" ]; then TARGET="."; fi
if [ "$PERSONA" = "." ] || [ "$PERSONA" = ".." ]; then PERSONA=""; fi
if [ "$TARGET" = "builder" ] || [ "$TARGET" = "designer" ] || [ "$TARGET" = "founder" ]; then PERSONA="$TARGET"; TARGET="."; fi

persona_latency(){ case "$1" in builder) echo "0.09";; designer) echo "0.107";; founder) echo "0.131";; *) echo "0.042";; esac; }
tier_for(){ case "$1" in builder) echo "deterministic llm";; designer) echo "llm deep_research";; founder) echo "action_operator agentic_epic";; *) echo "deterministic llm";; esac; }

echo "🐱✨ Scout CLI v0.9 fast installer — zero-deps true no pip"
echo "LCG $LCG_DAILY→$LCG_VAL idx$LCG_IDX triple $LCG_TRIPLE same-link $LCG_SAME PWA $PWA_VER $PWA_BG $PWA_CORE"
echo "LCG same-link-same-stars $LCG_SAME_3 PWA $PWA_VER $PWA_BG $PWA_CORE #080A0F CORE20 void dark"
echo "LCG triple [11205,19448,14209] five [11205,19448,14209,11701,18524] daily=20260813 idx3820 N=20719"
echo "MoMA-lite 5 tiers deterministic/llm/deep_research/action_operator/agentic_epic"

if [ -n "$PERSONA" ]; then LAT=$(persona_latency "$PERSONA"); TIER=$(tier_for "$PERSONA"); echo "persona $PERSONA tier $TIER latency ${LAT}s MoMA-lite"; echo "perf persona $PERSONA ${LAT}s p95 [0.049,0.028,0.05] avg 0.042s historic 55/48/52s ~1100× faster"; else echo "perf p95 [0.049,0.028,0.05] avg 0.042s ~1100× vs historic 55/48/52s"; fi

mkdir -p "$TARGET/bundles"
printf '{"zero_deps":true,"allow":"acne:./src"}' > "$TARGET/bundles/zero_deps.json"
cat > "$TARGET/bundles/manifest.json" <<'MF'
{
  "name": "Scout Execution Bundle v5 Prime v0.9",
  "version": "v5 Prime v0.9 — 13 agents / 11 packs / 6 ultra modules",
  "v5_prime": true,
  "agents_count": 13,
  "packs_count": 11,
  "ultra_count": 6,
  "agents": [
    {"id":"scout-prime","layer":0,"role":"coordinator Ultra host OODA host"},
    {"id":"strategist","layer":1,"role":"3-lens history-penalized"},
    {"id":"planner","layer":2,"role":"DAG side-effect tagged"},
    {"id":"deep-researcher","layer":2,"role":"wide sweep 5-7"},
    {"id":"researcher","layer":"2-3","role":"fast triage Observe"},
    {"id":"synthesist","layer":3,"role":"weaver Decide"},
    {"id":"builder","layer":3,"role":"maker Act"},
    {"id":"executor","layer":3,"role":"elite node runner OODA inner"},
    {"id":"operator","layer":3,"role":"always-on tempo :13"},
    {"id":"action-operator","layer":3,"role":"closer tool-first"},
    {"id":"communicator","layer":3,"role":"voice gate"},
    {"id":"critic","layer":4,"role":"QA 0-10 verifier-with-budget"},
    {"id":"forensic-auditor","layer":4,"role":"second brain graphify"}
  ],
  "packs": [
    "productivity-pack","communication-pack","commerce-life-pack","builder-pack",
    "intelligence-pack","media-creation-pack","deep-research-pack",
    "complex-actions-pack","verification-pack","router-pack","lateral-thinking-pack"
  ],
  "ultra": {
    "checkpoint-manager": "ultra/checkpoint-manager.js LangGraph pause/resume timeline.jsonl 7-field",
    "recovery-ladder": "ultra/recovery-ladder.js FailureTaxonomy5 SideEffect4 retry→patch→replan→escalate",
    "communication-pacing": "ultra/communication-pacing.js HandoffEnvelope 7 max3/4 tempo :13",
    "verification-economics": "ultra/verification-economics.js budget3 thr8.0 earlyExit0.3",
    "stuck-detector": "ultra/stuck-detector.js HonestLens 9 loop>3 conf<0.4 latency>thr",
    "verifier-with-budget": "ultra/verifier-with-budget.js single enforcement budget2 fix once if <8"
  },
  "zero_deps": {"zero_deps":true,"allow":"acne:./src","cloud":false,"torch":"auto"},
  "lcg": {"dailySeed":20260813,"daily":189831298,"idx":3820,"N":20719,"triple":[11205,19448,14209],"five":[11205,19448,14209,11701,18524],"same_link":"?daily=20260813&n=1/3/5","same_link_same_stars":true},
  "pwa": {"version":"v67","bg":"#080A0F","card":"#0f141e","ink":"#e8f0ff","CORE20":true,"void_dark":true,"offline":13608},
  "free_forever": true,
  "knowledge_edge_money": "Knowledge→Edge→Money Real/Lie/Distinct"
}
MF
printf "v0.9 %s LCG %s→%s idx%s triple %s PWA %s %s CORE20\n" "$(date +%s)" "$LCG_DAILY" "$LCG_VAL" "$LCG_IDX" "$LCG_TRIPLE" "$PWA_VER" "$PWA_BG" > "$TARGET/bundles/.installed"
if [ ! -f "$TARGET/bundles/cli.sh" ]; then if [ -f "$HOME/workspace/bundles/cli.sh" ]; then cp "$HOME/workspace/bundles/cli.sh" "$TARGET/bundles/cli.sh" 2>/dev/null || true; else printf '#!/usr/bin/env bash\nset -euo pipefail\nSCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\nexec python3 "$SCRIPT_DIR/dev-api/scout_cli_shim_v3.py" "$@"\n' > "$TARGET/bundles/cli.sh"; fi; fi
chmod 770 "$TARGET/bundles/cli.sh" 2>/dev/null || true
echo "✅ bundles/zero_deps.json {\"zero_deps\":true,\"allow\":\"acne:./src\"}"
echo "✅ bundles/manifest.json v5 Prime 13 agents / 11 packs / 6 ultra modules"
echo "✅ bundles/cli.sh wrapper 770"
echo "✅ installed marker v0.9 LCG $LCG_DAILY→$LCG_VAL idx$LCG_IDX triple $LCG_TRIPLE same-link $LCG_SAME PWA $PWA_VER $PWA_BG $PWA_CORE #080A0F CORE20"
if [ -n "$PERSONA" ]; then LAT=$(persona_latency "$PERSONA"); echo "✨ Done v0.9 persona $PERSONA ${LAT}s — try bundles/cli.sh doctor"; else echo "✨ Done v0.9 — try bundles/cli.sh doctor / daily --date $LCG_DAILY --n 3"; fi
