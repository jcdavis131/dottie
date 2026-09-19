#!/usr/bin/env bash
# Cloud Agent start phase for dottie.
# Runs on every boot. Must be idempotent, tolerate restarts, avoid duplicate
# processes, reach a clear success/failure state, and then return.
#
# Responsibility: bring up Tailscale in userspace networking mode so this VM can
# reach the operator's machines (e.g. the local RTX/Alienware GPU box) over the
# tailnet. TUN networking is unavailable in the Cloud Agent VM, so we use
# --tun=userspace-networking with a local SOCKS5 + HTTP proxy. Traffic is only
# routed over the tailnet for processes that explicitly opt in via the proxy env
# written below; normal egress is left untouched.
set -uo pipefail

TS_DIR="$HOME/.config/tailscale"
TS_SOCK="$TS_DIR/tailscaled.sock"
TS_PROXY_PORT="${TS_PROXY_PORT:-1055}"
TS_LOG="$TS_DIR/tailscaled.log"
PROXY_ENV="$HOME/.config/dottie/tailscale-proxy.env"

ts() { tailscale --socket="$TS_SOCK" "$@"; }

write_proxy_env() {
  mkdir -p "$(dirname "$PROXY_ENV")"
  cat > "$PROXY_ENV" <<EOF
# Source this to route a single process's traffic over the tailnet:
#   set -a; . "$PROXY_ENV"; set +a
# Do NOT source it globally — it would push all egress through Tailscale.
export ALL_PROXY=socks5://localhost:${TS_PROXY_PORT}
export HTTP_PROXY=http://localhost:${TS_PROXY_PORT}
export HTTPS_PROXY=http://localhost:${TS_PROXY_PORT}
export http_proxy=http://localhost:${TS_PROXY_PORT}
export https_proxy=http://localhost:${TS_PROXY_PORT}
export NO_PROXY=localhost,127.0.0.1,::1
EOF
}

start_tailscale() {
  if ! command -v tailscaled >/dev/null 2>&1; then
    echo "tailscale: not installed (run .cursor/install.sh); skipping"
    return 0
  fi

  mkdir -p "$TS_DIR"

  # Start the userspace daemon once. pgrep keeps this idempotent across restarts.
  if pgrep -x tailscaled >/dev/null 2>&1; then
    echo "tailscale: daemon already running"
  else
    echo "tailscale: starting userspace daemon on localhost:${TS_PROXY_PORT}"
    nohup tailscaled \
      --tun=userspace-networking \
      --socks5-server=localhost:"${TS_PROXY_PORT}" \
      --outbound-http-proxy-listen=localhost:"${TS_PROXY_PORT}" \
      --statedir="$TS_DIR" \
      --socket="$TS_SOCK" \
      >"$TS_LOG" 2>&1 &
    for _ in $(seq 1 15); do [ -S "$TS_SOCK" ] && break; sleep 1; done
  fi

  write_proxy_env

  # Already authenticated (persisted state survives snapshots)? Nothing to do.
  if ts status >/dev/null 2>&1; then
    echo "tailscale: already connected"
    ts status 2>&1 | head -20 || true
    return 0
  fi

  local key="${TS_AUTHKEY:-${TAILSCALE_AUTHKEY:-}}"
  if [ -z "$key" ]; then
    echo "tailscale: TS_AUTHKEY not set — daemon is up in userspace mode but not"
    echo "           authenticated. Add TS_AUTHKEY as a Cloud Agent secret to"
    echo "           connect this VM to your tailnet. This is non-fatal."
    return 0
  fi

  echo "tailscale: authenticating as ${TS_HOSTNAME:-cursor-cloud-agent}"
  if ts up \
    --authkey="$key" \
    --hostname="${TS_HOSTNAME:-cursor-cloud-agent}" \
    --accept-routes \
    --accept-dns=false; then
    ts status 2>&1 | head -20 || true
  else
    echo "tailscale: 'up' failed; see $TS_LOG (non-fatal, continuing)"
  fi
}

start_tailscale
echo "start: complete"
