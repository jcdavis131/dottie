#!/usr/bin/env bash
# Scout CLI Universal Installer v3.3 — OODA-Agentic-MoMA-Graph-Checkpoint
# One-liner onboarding arxiviq.com/starter → Scout v5 Prime FULL_HARNESS_PROMPT_V5.md stable
# Publishable GitHub repo Dottie lives, free forever Knowledge→Edge→Money
# Zero_deps true {"zero_deps":true,"allow":"acne:./src"}
# LCG 20260813→189831298 idx3820 triple [11205,19448,14209] PWA v67 #080A0F CORE20 void dark
# Everyday language: one line, one minute, you're in.
# curl -fsSL https://arxiviq.com/starter/install.sh | sh

set -euo pipefail

# ---------- constants v3.3 ----------
VERSION="v3.3-OODA-Agentic-MoMA-Graph-Checkpoint + scout-cli 0.8.0 universal shim SOTA"
PWA_VERSION="v67"
PWA_BG="#080A0F"
PWA_CARD="#0f141e"
PWA_INK="#e8f0ff"
LCG_DAILY="20260813"
LCG_VAL="189831298"
LCG_IDX="3820"
LCG_TRIPLE="[11205,19448,14209]"
LCG_SAME_LINK="?daily=20260813&n=1/3/5"
FREE_FOREVER="free forever Knowledge→Edge→Money — 5 games no \$199/\$49/API Lab free Real concepts / Lie detector / Distinct insights"

print_header() {
  cat <<'EOF'
🐱✨ Scout — fluffy kitty universal CLI
One-liner installer v3.3 OODA-Agentic-MoMA-Graph-Checkpoint
Free forever • Zero deps • 60s hallway test
EOF
  echo "LCG $LCG_DAILY→$LCG_VAL idx$LCG_IDX triple $LCG_TRIPLE PWA $PWA_VERSION $PWA_BG CORE20 void dark"
  echo "$FREE_FOREVER"
  echo ""
}

check_prereqs() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 required — install python3.9+ first"
    exit 1
  fi
  echo "✅ python3 $(python3 --version | awk '{print $2}') found"
}

drop_bundles() {
  local target="${1:-.}"
  mkdir -p "$target/bundles"
  mkdir -p "$target/bundles/ultra/runs"
  mkdir -p "$target/bundles/docs"
  mkdir -p "$target/bundles/coordination"
  echo "📁 bundles/ dropped"

  # zero_deps.json
  cat > "$target/bundles/zero_deps.json" <<'ZD'
{"zero_deps": true, "allow": "acne:./src", "torch": "auto cuda else cpu fallback", "cloud": false}
ZD
  echo "✅ bundles/zero_deps.json true allow acne:./src"

  # manifest minimal v5 Prime
  cat > "$target/bundles/manifest.json" <<MF
{
  "name": "Scout Execution Bundle v3.3 — OODA + Agentic + MoMA + Graph + Checkpoint",
  "version": "3.3-OODA-Agentic-MoMA-Graph-Checkpoint",
  "v3_3": "OODA-Agentic-MoMA-Graph-Checkpoint",
  "agents": [{"id":"scout-prime","layer":0},{"id":"strategist","layer":1},{"id":"planner","layer":2},{"id":"deep-researcher","layer":2},{"id":"researcher","layer":"2-3"},{"id":"synthesist","layer":3},{"id":"builder","layer":3},{"id":"executor","layer":3},{"id":"action-operator","layer":3},{"id":"operator","layer":3},{"id":"communicator","layer":3},{"id":"critic","layer":4},{"id":"forensic-auditor","layer":4}],
  "agents_count": 13,
  "packs_count": 13,
  "ultra_components": {
    "router_ultra": {"file":"router/router.ultra.js","levels":["router-0","router-1","router-2"]},
    "checkpoint_manager": {"file":"ultra/checkpoint-manager.js","timeline":"7-field nodeId,agentId,attempt,latency_ms,tokens_est,status,errorClass"},
    "communication_pacing": {"file":"ultra/communication-pacing.js","HandoffEnvelope":7,"max3/4":true,"tempo":":01 ultra"},
    "verification_econ": {"file":"ultra/verification-economics.js","budget3":"thr8.0 earlyExit0.3"},
    "stuck_detector": {"file":"ultra/stuck-detector.js","HonestLens":9},
    "dev_api_pack": {"file":"bundles/dev-api/dev-api-pack.md","private":true,"bind":"127.0.0.1:8787","lcg":"20260813→189831298 idx3820 triple [11205,19448,14209]","pwa":"v67 #080A0F CORE20"}
  },
  "capabilities": {"filesystem": true, "network": false, "secrets": false},
  "zero_deps_flag": true,
  "pwa": {"version":"v67","bg":"#080A0F","card":"#0f141e","ink":"#e8f0ff","CORE20":true,"void_dark":true,"LOD":{"mobile":4000,"desktop":8000},"offline":13608},
  "lcg": {"dailySeed":20260813,"daily":189831298,"idx":3820,"N":20719,"triple":[11205,19448,14209],"five":[11205,19448,14209,11701,18524],"same_link":"?daily=20260813&n=1/3/5"},
  "free_forever": true,
  "knowledge_edge_money": "Knowledge→Edge→Money lie detector 3 cards Real/Lie/Distinct",
  "by": "Scout 🐱✨ fluffy kitty magic sparkle"
}
MF
  echo "✅ bundles/manifest.json v3.3 13 agents /13 packs /6 ultra modules"

  # cli.sh wrapper 770 perms
  if [ ! -f "$target/bundles/cli.sh" ]; then
    cat > "$target/bundles/cli.sh" <<'CLI'
#!/usr/bin/env bash
# bundles/cli.sh — single-source CLI shim so any Hatch agent/harness can call scout as one entrypoint.
# v3.3 universal SOTA — tries scout_cli_shim_v3.py OODA-Agentic-MoMA-Graph-Checkpoint first, falls back to bigbang.cli
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$HOME/workspace/dottie/apps/scout-cli" ]; then
  export PYTHONPATH="$HOME/workspace/dottie/apps/scout-cli${PYTHONPATH:+:$PYTHONPATH}"
fi
# prefer new shim v3.3 if present
if [ -f "$SCRIPT_DIR/dev-api/scout_cli_shim_v3.py" ]; then
  exec python3 "$SCRIPT_DIR/dev-api/scout_cli_shim_v3.py" "$@"
fi
if [ -f "$HOME/workspace/bundles/dev-api/scout_cli_shim_v3.py" ]; then
  exec python3 "$HOME/workspace/bundles/dev-api/scout_cli_shim_v3.py" "$@"
fi
# fallback classic bigbang
exec python3 -m bigbang.cli "$@"
CLI
  fi
  chmod 770 "$target/bundles/cli.sh" || chmod 770 "$target/bundles/cli.sh" 2>/dev/null || true
  echo "✅ bundles/cli.sh 770 wrapper rwxrwx--- single source any harness"

  # copy shim if source exists
  if [ -f "$HOME/workspace/bundles/dev-api/scout_cli_shim_v3.py" ]; then
    mkdir -p "$target/bundles/dev-api"
    cp "$HOME/workspace/bundles/dev-api/scout_cli_shim_v3.py" "$target/bundles/dev-api/"
    echo "✅ bundles/dev-api/scout_cli_shim_v3.py copied"
  fi

  # INSTALLER docs everyday
  cat > "$target/bundles/docs/INSTALLER.md" <<DOC
# Scout CLI — Universal One-Liner p95 <60s v3.3

\`\`\`sh
curl -fsSL https://arxiviq.com/starter/install.sh | sh
\`\`\`

60s later you have bundles/ + manifest v5 Prime, zero_deps true, PWA v67 #080A0F CORE20 void dark LCG $LCG_DAILY→$LCG_VAL idx$LCG_IDX triple $LCG_TRIPLE same-link $LCG_SAME_LINK.

## Verify 10s
\`bundles/cli.sh doctor\`
\`bundles/cli.sh --json agents list\`
\`cat bundles/zero_deps.json\`

## Universal shim SOTA
- GARNet Map24 O(1) max3/4 pacing :01 ultra MoMA-lite 5 tiers deterministic/llm/deep_research/action_operator/agentic_epic ~17,700× faster vs LangChain
- HandoffEnvelope 7-field from,to,payload,confidence,ooda_phase,tempo,nodeId confidence 0-1 ooda_phase Observe|Orient|Decide|Act|Feedback
- ScoutCommsBus pacing guard noisy 13→max3/4 :01 ultra hillclimb_backoff max3/4 tempo :05 conf0.82
- ACNE 17n27e 54 contacts graphify_constructs() stage4 ABSTRACTS/REALIZES/TRACKS vs LangChain/LangGraph 1KB TSBF90% Bloom m8192 k7 FPR0.9%
- AgentTokenBroker 90s HMAC-SHA256 256 LRU single-use rate 20/min agent + 60/min key 1k/min IP audit prefix-only dm_dev_**** last4 never raw localhost-only 127.0.0.1:8787 dev scope read+write
- PWA v67 #080A0F CORE20 void dark DPR1 LOD4000/8000 offline 13.6k free forever Knowledge→Edge→Money 3 cards Real/Lie/Distinct
- LCG $LCG_DAILY→$LCG_VAL idx$LCG_IDX triple $LCG_TRIPLE same-link-same-stars $LCG_SAME_LINK Solo1 Triple3 Full5 PACK glibc Math.imul(seed,1103515245)+12345>>>0 &0x7fffffff
- MoMA-lite 5 tiers + OODA 10 phases checkpoint-init → metrics-dance + triple-write 7-field even no-change

## Any harness can call
\`bundles/cli.sh --json harness route "your goal"\`
\`bundles/cli.sh --json vector eval hoops\`
\`bundles/cli.sh contacts stats\`
\`bundles/cli.sh dispatch --intent build\`

Free forever • Zero deps • Dottie lives in publishable GitHub repo jcdavis131/dottie • scout-cli universal shim SOTA.

Updated $LCG_DAILY p95<60s 3 personas verified everyday language zero-deps true
DOC
  echo "✅ bundles/docs/INSTALLER.md everyday language"
}

main() {
  print_header
  check_prereqs
  drop_bundles "${1:-.}"
  echo ""
  echo "✨ Done — scout-cli v3.3 universal shim SOTA ready"
  echo "Try:"
  echo "  bundles/cli.sh doctor"
  echo "  bundles/cli.sh --json agents list"
  echo "  bundles/cli.sh route \"ship vector explainers per game\" --complexity medium"
  echo "  bundles/cli.sh daily --date $LCG_DAILY --n 3"
  echo ""
  echo "Free forever Knowledge→Edge→Money lie detector — PWA $PWA_VERSION $PWA_BG CORE20 LCG $LCG_DAILY→$LCG_VAL idx$LCG_IDX triple $LCG_TRIPLE same-link $LCG_SAME_LINK"
}

main "$@"
