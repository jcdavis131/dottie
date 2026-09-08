#!/usr/bin/env bash
# Install jarvisd as a systemd service on the home box.
#
# Idempotent: safe to re-run to upgrade the code in place. It will NEVER overwrite
# an existing /etc/jarvisd/jarvisd.env — your secrets survive an upgrade, and a
# re-run that silently blanked them would be the worst bug this script could have.
#
#   sudo ./deploy/install.sh            # install or upgrade
#   sudo ./deploy/install.sh --dry-run  # print what it would do, touch nothing
#
# It deliberately does NOT start the service on a first install: the unit needs a
# bearer in the env file that only you can supply, and starting a daemon whose
# config you have not written yet is how something ends up running wide open. It
# tells you the two commands to run when you are ready.
set -euo pipefail

APP_USER=jarvisd
APP_GROUP=jarvisd
PREFIX=/opt/jarvisd
VENV="${PREFIX}/venv"
STATE=/var/lib/jarvisd
CONF_DIR=/etc/jarvisd
CONF="${CONF_DIR}/jarvisd.env"
UNIT=/etc/systemd/system/jarvisd.service

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(dirname -- "${HERE}")"        # apps/jarvisd

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

say()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
run()  {
  if (( DRY_RUN )); then
    printf '  would: %s\n' "$*"
  else
    "$@"
  fi
}

# ---- preflight, before anything is written ----------------------------------------
step "preflight"
if (( ! DRY_RUN )) && [[ ${EUID} -ne 0 ]]; then
  echo "install.sh must run as root (it writes ${UNIT} and ${CONF_DIR})." >&2
  exit 1
fi
command -v systemctl >/dev/null 2>&1 || { echo "systemd not found; this script targets a systemd host." >&2; exit 1; }
PYTHON="$(command -v python3 || true)"
[[ -n ${PYTHON} ]] || { echo "python3 not found." >&2; exit 1; }
# jarvisd's pyproject targets 3.11+; catch that here rather than in a traceback later.
"${PYTHON}" - <<'PY' || { echo "python3 >= 3.11 required." >&2; exit 1; }
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
[[ -f "${SRC}/pyproject.toml" ]] || { echo "cannot find jarvisd sources at ${SRC}" >&2; exit 1; }
say "python:  ${PYTHON} ($(${PYTHON} -V 2>&1))"
say "sources: ${SRC}"
(( DRY_RUN )) && say "DRY RUN — nothing will be written"

# ---- service account ---------------------------------------------------------------
step "service account"
if id -u "${APP_USER}" >/dev/null 2>&1; then
  say "user ${APP_USER} already exists"
else
  say "creating system user ${APP_USER} (no login shell, no home)"
  run useradd --system --no-create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

# ---- directories ---------------------------------------------------------------------
step "directories"
run install -d -m 0755 -o root -g root "${PREFIX}"
run install -d -m 0700 -o "${APP_USER}" -g "${APP_GROUP}" "${STATE}"
run install -d -m 0700 -o "${APP_USER}" -g "${APP_GROUP}" "${STATE}/workspace"
run install -d -m 0750 -o root -g root "${CONF_DIR}"
say "state ${STATE} is 0700 — audit.jsonl and the SQLite store live there"

# ---- virtualenv + package -------------------------------------------------------------
step "virtualenv"
if [[ -x "${VENV}/bin/python" ]]; then
  say "reusing ${VENV}"
else
  run "${PYTHON}" -m venv "${VENV}"
fi
run "${VENV}/bin/python" -m pip install --quiet --upgrade pip
say "installing jarvisd from ${SRC}"
run "${VENV}/bin/python" -m pip install --quiet "${SRC}"
if (( ! DRY_RUN )); then
  "${VENV}/bin/jarvisd" --help >/dev/null || { echo "jarvisd did not install cleanly." >&2; exit 1; }
  say "installed: $("${VENV}"/bin/python -c 'import jarvisd; print("jarvisd", jarvisd.__version__)')"
fi

# ---- config, never clobbered ------------------------------------------------------------
step "config"
FRESH_CONFIG=0
if [[ -f ${CONF} ]]; then
  say "${CONF} exists — left exactly as it is"
else
  FRESH_CONFIG=1
  say "seeding ${CONF} from jarvisd.env.example (0600 root:root)"
  run install -m 0600 -o root -g root "${HERE}/jarvisd.env.example" "${CONF}"
fi

# ---- unit ---------------------------------------------------------------------------------
step "systemd unit"
run install -m 0644 -o root -g root "${HERE}/jarvisd.service" "${UNIT}"
run systemctl daemon-reload
say "installed ${UNIT}"

# ---- what to do next -----------------------------------------------------------------------
step "next"
if (( DRY_RUN )); then
  say "dry run complete; nothing was written."
  exit 0
fi

if (( FRESH_CONFIG )); then
  cat <<EOF

  Not started, on purpose: ${CONF} has no bearer yet, and a daemon started
  without one has auth off.

    1. sudoedit ${CONF}
         JARVIS_BEARER=\$(openssl rand -hex 32)
         JARVIS_SLACK_SIGNING_SECRET=   # optional; blank keeps Slack ingress shut
    2. sudo systemctl enable --now jarvisd
    3. curl -fsS http://127.0.0.1:8790/api/health

EOF
else
  say "config already present; restarting to pick up the new code"
  run systemctl restart jarvisd
  sleep 1
  systemctl is-active --quiet jarvisd \
    && say "jarvisd is active — curl -fsS http://127.0.0.1:8790/api/health" \
    || { echo "  jarvisd did not come up; journalctl -u jarvisd -n 50" >&2; exit 1; }
fi
