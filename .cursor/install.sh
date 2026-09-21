#!/usr/bin/env bash
# Cloud Agent install phase for dottie.
# Runs after the repository is checked out. Must be idempotent: it may run again
# against a cached/partially-prepared tree, and (with environment builds) it is
# what bakes the baseline snapshot. Long-running daemons belong in start.sh.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- uv (pinned installer) + Python toolchain -------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "install: fetching uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# Python 3.11 is the version CI pins (.python-version, ci.yml).
uv python install 3.11

# Light uv workspace (packages/* + apps/scout-cli + apps/jarvisd). --frozen asserts
# uv.lock still satisfies pyproject.toml, exactly as ci.yml does.
uv sync --all-groups --frozen

# Match CI's local-dev hook wiring; never fail the install if it is unavailable.
uv run pre-commit install || true

# --- Tailscale (userspace networking; connected in start.sh) ----------------
# Binaries are durable, so they are installed here and baked into the snapshot.
# The daemon itself is started per-boot by start.sh in userspace mode.
if ! command -v tailscaled >/dev/null 2>&1; then
  echo "install: fetching tailscale"
  curl -fsSL https://tailscale.com/install.sh | sudo sh
fi

# The packaged systemd unit uses TUN networking, which does not work inside the
# Cloud Agent VM (PID 1 is tini, not systemd). Disable it if systemd is present;
# start.sh runs tailscaled in userspace mode instead. Never fail on its absence.
sudo systemctl disable --now tailscaled 2>/dev/null || true

echo "install: complete"
