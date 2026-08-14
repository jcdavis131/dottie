#!/usr/bin/env bash
# Dottie local + Docker — open-source Hatch equivalent (Dottie model + harness with Scout CLI)
# One-liner: curl -fsSL https://arxiviq.com/starter/install.sh | sh   (or raw github)
# Also: curl -fsSL https://raw.githubusercontent.com/jcdavis131/dottie/main/install.sh | sh
# MIT, solo, free-tier only, zero-deps true (uv optional, docker optional)
set -euo pipefail

DOT_VER="v6.5-dottie-tandem"
DOT_NAME="Dottie model + harness with Scout CLI tool"
PWA_V="v67"
PWA_BG="#080A0F"
TANDEM="local + docker + website link"

echo "🐱✨ Dottie $DOT_VER — $DOT_NAME"
echo "Tandem: $TANDEM | PWA $PWA_V $PWA_BG CORE20 void dark #080A0F"
echo "Dottie is the open-source Hatch you run from your local machine + Docker and link to arxiviq.com/dottie so it works together with your Hatch cloud agent."

# 1) Scout CLI fast universal shim — zero-deps install
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/apps/scout-cli/install.sh" ]; then
  bash "$SCRIPT_DIR/apps/scout-cli/install.sh" "$@"
elif [ -f "./apps/scout-cli/install.sh" ]; then
  bash ./apps/scout-cli/install.sh "$@"
else
  echo "-> installing Scout CLI universal shim (bundles/cli.sh 770 zero_deps true)"
  mkdir -p bundles
  printf '{"zero_deps":true,"allow":"acne:./src"}' > bundles/zero_deps.json
  cat > bundles/cli.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$ROOT/apps/scout-cli/bigbang/cli.py" ]; then
  exec python3 -m bigbang.cli "$@"
else
  exec python3 "$ROOT/apps/scout-cli/bigbang/cli.py" "$@" 2>/dev/null || echo "scout shim: pip install -e apps/scout-cli needed"
fi
SH
  chmod 770 bundles/cli.sh
fi

# 2) Python uv workspace sync (optional but recommended)
if command -v uv >/dev/null 2>&1; then
  echo "-> uv sync (workspace members)"
  uv sync --all-groups --frozen 2>&1 | tail -5 || true
else
  echo "-> uv not found (optional). Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh — continuing with fallback"
fi

# 3) Docker compose up -- tandem local half
if command -v docker >/dev/null 2>&1; then
  # generate dev bearer if missing
  CFG_DIR="$HOME/.config/dottie"
  mkdir -p "$CFG_DIR"
  ENV_FILE="$CFG_DIR/.env"
  if [ ! -f "$ENV_FILE" ]; then
    BEARER="dm_dev_$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-24)"
    printf "DOTTIE_DEV_BEARER=%s\n" "$BEARER" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "-> wrote $ENV_FILE (0600) Bearer ${BEARER:0:10}****"
  fi
  # load bearer for compose
  # shellcheck disable=SC1090
  . "$ENV_FILE" 2>/dev/null || true
  export DOTTIE_DEV_BEARER="${DOTTIE_DEV_BEARER:-dm_dev_local}"
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose -f docker-compose.dottie.yml"
  else
    COMPOSE_CMD="docker-compose -f docker-compose.dottie.yml"
  fi
  if [ -f docker-compose.dottie.yml ]; then
    echo "-> $COMPOSE_CMD up -d (dottie-api :8787 localhost-only, harness, redis)"
    $COMPOSE_CMD up -d
    echo "-> waiting for 127.0.0.1:8787 health..."
    for i in 1 2 3 4 5 6 7 8 9 10; do
      if curl -fsS http://127.0.0.1:8787/api/dev/health >/dev/null 2>&1; then echo "✅ api healthy at http://127.0.0.1:8787/api/dev/health"; break; fi
      sleep 1
    done
  else
    echo "-> docker-compose.dottie.yml not found at repo root (expected). Skipping docker up — run manually: docker compose -f docker-compose.dottie.yml up -d"
  fi
else
  echo "-> docker not found — tandem queue will use filesystem fallback ~/workspace/.dottie/queue. Install Docker Desktop to get full daemon supervise."
fi

# 4) Pairing quickstart
echo ""
echo "TANDEM QUICKSTART — link local Dottie to arxiviq.com/dottie"
echo "  1) Create pairing code (local, 6 chars, 10m expiry):"
echo "     curl -X POST http://127.0.0.1:8787/api/dev/pair/create -H 'Authorization: Bearer \$DOTTIE_DEV_BEARER' | jq .code"
echo "     # or: uv run scout pair create"
echo "  2) Open arxiviq.com/dottie?pair=1 and paste code → Verify (POST /api/pair/verify)"
echo "  3) When Paired=TRUE, cloud Scout can push tasks:"
echo "     POST http://127.0.0.1:8787/api/dev/queue/push  {\"task\": \"build PWA offsite\"}"
echo "     Local harness consumes from /ws/.dottie/queue and replies."
echo "  4) Check tandem UI: arxiviq.com/conductor?tandem=1  shows Local Dottie ● / Cloud Scout ● / Paired ✓"
echo ""
echo "Extensible: replace filesystem queue with redis stream 'dottie:queue' or Supabase Realtime. Spec in your_files/dottie-tandem-bridge/index.html + README."
echo ""
echo "✅ Done $DOT_VER — $DOT_NAME tandem ready. Try: uv run scout --json harness route \"hello world\""
