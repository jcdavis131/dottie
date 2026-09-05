#!/usr/bin/env bash
# Solo personal project, no connection to employer, built with public/free-tier only.
#
# Start the jarvisd daemon (docker-compose.jarvisd.yml) on Linux/macOS and PROVE it
# answers on /api/health. --install registers it to come up at login/boot:
#   Linux : systemd --user unit ~/.config/systemd/user/jarvisd.service
#           (add `sudo loginctl enable-linger $USER` so it starts without a login session)
#   macOS : LaunchAgent ~/Library/LaunchAgents/com.dottie.jarvisd.plist
#
#   ./scripts/jarvisd_start.sh                 # up -d with the tunnel profile, wait for health
#   ./scripts/jarvisd_start.sh --no-tunnel     # daemon only (127.0.0.1:8790)
#   ./scripts/jarvisd_start.sh --build         # rebuild the image first (after a git pull)
#   ./scripts/jarvisd_start.sh --install [--no-tunnel]
#   ./scripts/jarvisd_start.sh --uninstall
#   ./scripts/jarvisd_start.sh --status
#   ./scripts/jarvisd_start.sh --down          # stop the stack, keep the data volume
#
# Exit codes: 0 ok; 2 deploy/.env missing or JARVIS_BEARER empty; 3 Docker never came up;
# 4 compose up failed; 5 daemon never reported healthy within WAIT_SECONDS.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT/docker-compose.jarvisd.yml"
ENV_FILE="$ROOT/deploy/.env"
ENV_EXAMPLE="$ROOT/deploy/.env.example"
HEALTH="http://127.0.0.1:8790/api/health"
SELF="$ROOT/scripts/jarvisd_start.sh"
WAIT_SECONDS=${WAIT_SECONDS:-120}
DOCKER_WAIT_SECONDS=${DOCKER_WAIT_SECONDS:-180}

INSTALL=0; UNINSTALL=0; NO_TUNNEL=0; BUILD=0; STATUS=0; DOWN=0; NO_WAIT=0
for a in "$@"; do
    case "$a" in
        --install) INSTALL=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --no-tunnel) NO_TUNNEL=1 ;;
        --build) BUILD=1 ;;
        --status) STATUS=1 ;;
        --down) DOWN=1 ;;
        --no-wait) NO_WAIT=1 ;;   # used by the systemd unit: return as soon as compose is up
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "unknown flag: $a" >&2; exit 1 ;;
    esac
done

compose() {
    # --env-file feeds ${VAR} substitution in the compose file; the service-level
    # env_file: only feeds the container. Both point at deploy/.env.
    if [ "$NO_TUNNEL" = 1 ]; then
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    else
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile tunnel "$@"
    fi
}

env_get() { # env_get KEY -> value or empty (skips comments; no inline-comment parsing)
    grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '[:space:]' || true
}

# ---- install / uninstall -----------------------------------------------------------------
if [ "$INSTALL" = 1 ] || [ "$UNINSTALL" = 1 ]; then
    FLAGS="--no-wait"
    [ "$NO_TUNNEL" = 1 ] && FLAGS="$FLAGS --no-tunnel"
    DOCKER_BIN=$(command -v docker || echo /usr/bin/docker)
    case "$(uname -s)" in
        Darwin)
            PLIST="$HOME/Library/LaunchAgents/com.dottie.jarvisd.plist"
            launchctl unload "$PLIST" 2>/dev/null || true
            if [ "$UNINSTALL" = 1 ]; then rm -f "$PLIST"; echo "removed $PLIST"; exit 0; fi
            mkdir -p "$(dirname "$PLIST")"
            {
                echo '<?xml version="1.0" encoding="UTF-8"?>'
                echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
                echo '<plist version="1.0"><dict>'
                echo '  <key>Label</key><string>com.dottie.jarvisd</string>'
                echo '  <key>ProgramArguments</key><array>'
                echo "    <string>/bin/bash</string><string>$SELF</string>"
                for f in $FLAGS; do echo "    <string>$f</string>"; done
                echo '  </array>'
                echo "  <key>WorkingDirectory</key><string>$ROOT</string>"
                echo '  <key>RunAtLoad</key><true/>'
                echo "  <key>StandardOutPath</key><string>$ROOT/deploy/jarvisd_start.log</string>"
                echo "  <key>StandardErrorPath</key><string>$ROOT/deploy/jarvisd_start.log</string>"
                echo '  <key>EnvironmentVariables</key><dict>'
                echo "    <key>PATH</key><string>$(dirname "$DOCKER_BIN"):/usr/local/bin:/usr/bin:/bin</string>"
                echo '  </dict>'
                echo '</dict></plist>'
            } > "$PLIST"
            launchctl load "$PLIST"
            echo "installed $PLIST (runs at login; Docker Desktop must also start at login)"
            ;;
        *)
            UNIT_DIR="$HOME/.config/systemd/user"
            UNIT="$UNIT_DIR/jarvisd.service"
            if [ "$UNINSTALL" = 1 ]; then
                systemctl --user disable --now jarvisd.service 2>/dev/null || true
                rm -f "$UNIT"; systemctl --user daemon-reload
                echo "removed $UNIT (containers were not touched; use --down to stop them)"
                exit 0
            fi
            mkdir -p "$UNIT_DIR"
            cat > "$UNIT" <<UNIT
[Unit]
Description=jarvisd (docker compose, docs/JARVISD_SPEC.md)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$ROOT
Environment=PATH=$(dirname "$DOCKER_BIN"):/usr/local/bin:/usr/bin:/bin
ExecStart=/bin/bash $SELF $FLAGS
ExecStop=$DOCKER_BIN compose --env-file $ENV_FILE -f $COMPOSE_FILE --profile tunnel down
TimeoutStartSec=600

[Install]
WantedBy=default.target
UNIT
            systemctl --user daemon-reload
            systemctl --user enable jarvisd.service
            echo "installed $UNIT"
            echo "start now:      systemctl --user start jarvisd"
            echo "survive logout: sudo loginctl enable-linger $USER"
            echo "logs:           journalctl --user -u jarvisd -f"
            ;;
    esac
    exit 0
fi

# ---- preconditions -----------------------------------------------------------------------
echo "[1] Preconditions"
if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"; chmod 600 "$ENV_FILE"
    echo "  created deploy/.env from the example. Set JARVIS_BEARER in it and re-run."
    echo "  generate one:  python3 -c \"import secrets; print('jv_' + secrets.token_urlsafe(32))\""
    exit 2
fi
if [ -z "$(env_get JARVIS_BEARER)" ]; then
    echo "  JARVIS_BEARER is empty in deploy/.env. jarvisd refuses a non-loopback bind without it." >&2
    exit 2
fi
if [ "$NO_TUNNEL" = 0 ] && [ -z "$(env_get CLOUDFLARE_TUNNEL_TOKEN)" ]; then
    echo "  CLOUDFLARE_TUNNEL_TOKEN is empty: starting the daemon only (pass --no-tunnel to silence this)."
    NO_TUNNEL=1
fi
echo "  deploy/.env ok (bearer set, tunnel: $([ "$NO_TUNNEL" = 1 ] && echo no || echo yes))"

# Docker may still be booting right after login (Docker Desktop) or boot (dockerd).
deadline=$(( $(date +%s) + DOCKER_WAIT_SECONDS ))
launched=0
until docker info >/dev/null 2>&1; do
    if [ "$launched" = 0 ] && [ "$(uname -s)" = Darwin ] && [ -d "/Applications/Docker.app" ]; then
        echo "  Docker engine not answering; launching Docker Desktop"
        open -a Docker || true
        launched=1
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "  Docker engine did not come up within ${DOCKER_WAIT_SECONDS}s." >&2
        exit 3
    fi
    sleep 5
done
echo "  docker engine up"

# ---- status / down -----------------------------------------------------------------------
if [ "$STATUS" = 1 ]; then
    compose ps
    if curl -fsS --max-time 5 "$HEALTH"; then echo; else echo "  health: NOT answering on $HEALTH" >&2; exit 5; fi
    exit 0
fi
if [ "$DOWN" = 1 ]; then
    echo "[2] compose down (volume kept)"
    compose down
    exit 0
fi

# ---- up ----------------------------------------------------------------------------------
echo "[2] compose up"
UP=(up -d)
[ "$BUILD" = 1 ] && UP+=(--build)
compose "${UP[@]}" || { echo "  compose up failed." >&2; exit 4; }
[ "$NO_WAIT" = 1 ] && exit 0

# ---- prove it ----------------------------------------------------------------------------
echo "[3] Verify /api/health (up to ${WAIT_SECONDS}s)"
deadline=$(( $(date +%s) + WAIT_SECONDS ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    sleep 3
    if body=$(curl -fsS --max-time 5 "$HEALTH" 2>/dev/null); then
        echo "  HEALTHY: $body"
        if [ "$NO_TUNNEL" = 0 ]; then
            echo "  tunnel: docker compose ... logs cloudflared   (look for 'Registered tunnel connection')"
            pub=$(env_get JARVIS_PUBLIC_HOST)
            [ -n "$pub" ] && echo "  public check: curl https://$pub/api/health"
        fi
        exit 0
    fi
done
echo "  NO healthy response within ${WAIT_SECONDS}s." >&2
echo "  docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml logs jarvisd" >&2
exit 5
