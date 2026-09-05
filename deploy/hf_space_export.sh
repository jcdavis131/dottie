#!/usr/bin/env sh
# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Assemble the minimal tree to push to a Hugging Face Docker Space:
#   the uv workspace (root pyproject.toml, uv.lock, apps/jarvisd, apps/scout-cli, packages/),
#   Dockerfile.jarvisd renamed to Dockerfile, its dockerignore renamed to .dockerignore,
#   and a README.md with the Space front matter (sdk: docker, app_port: 8790).
#
#   ./deploy/hf_space_export.sh /tmp/jarvisd-space [space-title]
set -eu

DEST=${1:?usage: hf_space_export.sh <dest-dir> [title]}
TITLE=${2:-jarvisd}
ROOT=$(cd "$(dirname "$0")/.." && pwd)

mkdir -p "$DEST"
# Same subtree the Dockerfile COPYs; the .dockerignore trims tests/docs/graphs at build.
for p in pyproject.toml uv.lock apps/jarvisd apps/scout-cli \
         packages/ava-skills packages/ava-open-harness packages/personal-graphify; do
    [ -e "$ROOT/$p" ] || { echo "hf_space_export.sh: missing $ROOT/$p" >&2; exit 1; }
    mkdir -p "$DEST/$(dirname "$p")"
    rm -rf "$DEST/$p"
    cp -R "$ROOT/$p" "$DEST/$p"
done
cp "$ROOT/Dockerfile.jarvisd" "$DEST/Dockerfile"
cp "$ROOT/Dockerfile.jarvisd.dockerignore" "$DEST/.dockerignore"

# Local junk the Space build would otherwise upload.
find "$DEST" \( -name __pycache__ -o -name '*.egg-info' -o -name .venv -o -name 'graphify-out*' \
             -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} + 2>/dev/null || true

cat > "$DEST/README.md" <<README
---
title: ${TITLE}
emoji: J
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 8790
pinned: false
---

jarvisd -- the Jarvis daemon (MCP + JSON API). Set secrets JARVIS_BEARER and, optionally,
ANTHROPIC_API_KEY in the Space settings; set variable JARVIS_PUBLIC_HOST to this Space's
\`<owner>-<space>.hf.space\` hostname. State under /data is ephemeral on free CPU basic.
README

echo "hf_space_export.sh: wrote $DEST"
du -sh "$DEST" 2>/dev/null || true
echo "next: cd $DEST && git init && git remote add origin https://huggingface.co/spaces/<owner>/${TITLE} && git add -A && git commit -m jarvisd && git push -u origin main"
