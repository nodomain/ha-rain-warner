#!/usr/bin/env bash
# deploy.sh — Sync the custom_component to the HA config volume,
#             optionally push the Lovelace dashboard via WebSocket API, and
#             optionally restart Home Assistant when code changed.
#
# Usage:
#   ./deploy.sh [options] [TARGET]
#
# Options:
#   -R, --restart   Restart Home Assistant after deploy if code changed.
#                   Required for custom_component changes (~60s downtime).
#   -f, --force     Restart even if code didn't change.
#   -h, --help      Show this help.
#
# TARGET defaults to $HA_CONFIG_MOUNT (see .env), or /Volumes/config.
#
# What it does:
#   1. Load .env (fail fast on missing required vars).
#   2. Ensure the HA config volume is mounted; auto-mount on macOS via
#      `osascript` + Keychain credentials when HA_CONFIG_SMB_URL is set.
#   3. rsync custom_components/rain_warner/ to the target.
#   4. If HA_URL + HA_TOKEN are set, push the dashboard to HA via
#      the Lovelace WebSocket API.
#   5. If --restart and code changed, restart HA via REST API.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

# --- Parse args ---
do_restart=false
force=false
TARGET=""

usage() {
  awk '
    NR == 1           { next }            # skip shebang
    /^$/              { exit }            # stop at first blank line
    /^#/              { sub(/^# ?/, ""); print; next }
                      { exit }            # stop at first non-comment line
  ' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -R|--restart) do_restart=true; shift ;;
    -f|--force)   force=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    -*)           echo "❌ Unknown option: $1" >&2; usage; exit 2 ;;
    *)
      if [[ -z "$TARGET" ]]; then
        TARGET="$1"; shift
      else
        echo "❌ Unexpected argument: $1" >&2; exit 2
      fi
      ;;
  esac
done

# --- Load .env ---
if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ .env file not found: $ENV_FILE" >&2
  echo "   Copy .env.example to .env and fill in your values." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

TARGET="${TARGET:-${HA_CONFIG_MOUNT:-/Volumes/config}}"

# --- Mount helpers ---
is_mounted() {
  mount | grep -Fq " on $1 ("
}

ensure_mounted() {
  if is_mounted "$TARGET" && [[ -r "$TARGET" ]]; then
    return 0
  fi

  if [[ -z "${HA_CONFIG_SMB_URL:-}" ]]; then
    echo "❌ Target not mounted: $TARGET" >&2
    echo "   Either mount it manually in Finder, or set HA_CONFIG_SMB_URL in" >&2
    echo "   .env (e.g. smb://user@host/share) to enable auto-mount." >&2
    exit 1
  fi

  echo "📡 Mounting $HA_CONFIG_SMB_URL ..."
  if ! osascript -e "mount volume \"$HA_CONFIG_SMB_URL\"" >/dev/null 2>&1; then
    echo "❌ Auto-mount failed." >&2
    echo "   Mount the share manually in Finder once so macOS caches the" >&2
    echo "   credentials in the Keychain, then retry." >&2
    exit 1
  fi

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if is_mounted "$TARGET" && [[ -r "$TARGET" ]]; then
      return 0
    fi
    sleep 0.3
  done

  echo "❌ Mount reported success but target is still not accessible: $TARGET" >&2
  exit 1
}

ensure_mounted

echo "🚀 Deploying rain_warner to $TARGET ..."

# --- Sync custom_component ---
SRC_DIR="$SCRIPT_DIR/custom_components/rain_warner"
DEST_DIR="$TARGET/custom_components/rain_warner"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "❌ Source not found: $SRC_DIR" >&2
  exit 1
fi

# Use rsync for efficient sync with change detection
# --inplace: write directly to destination (required for SMB shares)
# --no-perms/owner/group: SMB doesn't support Unix permissions
# --delete: remove files on target that no longer exist in source
RSYNC_OUT=$(rsync -rci --inplace --no-perms --no-owner --no-group --delete \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  "$SRC_DIR/" "$DEST_DIR/" 2>&1) || {
  echo "❌ rsync failed:" >&2
  echo "$RSYNC_OUT" >&2
  exit 1
}

if [[ -n "$RSYNC_OUT" ]]; then
  code_changed=true
  echo "✅ Code synced (changed files):"
  echo "$RSYNC_OUT" | sed 's/^/   /'
else
  code_changed=false
  echo "✅ Code synced (unchanged)"
fi

# --- HA REST helper ---
HA_SERVICE_TIMEOUT_S=180

ha_is_alive() {
  curl --fail --silent --max-time 5 \
    -H "Authorization: Bearer $HA_TOKEN" \
    "${HA_URL%/}/api/config" >/dev/null 2>&1
}

ha_service_call() {
  local service="$1"
  local url="${HA_URL%/}/api/services/${service/./\/}"
  local http_code

  http_code=$(
    curl --silent --show-error --max-time "$HA_SERVICE_TIMEOUT_S" \
      --output /dev/null --write-out '%{http_code}' \
      -X POST \
      -H "Authorization: Bearer $HA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{}' \
      "$url"
  ) || {
    local exit_code=$?
    if [[ $exit_code -eq 28 ]]; then
      echo "⏳ Service call exceeded ${HA_SERVICE_TIMEOUT_S}s — probing HA..." >&2
      sleep 3
      if ha_is_alive; then
        echo "ℹ️  HA is back and healthy; treating restart as completed." >&2
        return 0
      fi
      echo "❌ HA is not responding after timeout." >&2
      return 1
    fi
    echo "❌ curl failed with exit code $exit_code." >&2
    return 1
  }

  if [[ "$http_code" != "200" ]]; then
    echo "❌ HA returned HTTP $http_code for $service." >&2
    return 1
  fi
  return 0
}

# --- Optional: push dashboard via HA WebSocket API ---
push_dashboard() {
  local url_path="${HA_DASHBOARD_URL_PATH:-rain-warner}"
  local updater="$SCRIPT_DIR/tools/ha_update_dashboard.py"
  local rendered="$SCRIPT_DIR/dashboard/rain-warner-dashboard.yaml"

  if [[ ! -f "$rendered" ]]; then
    echo "ℹ️  No dashboard file found — skipping API push." >&2
    return 0
  fi
  if [[ ! -x "$updater" ]]; then
    echo "⚠️  Dashboard updater not executable: $updater — skipping API push." >&2
    return 0
  fi
  if ! command -v uv >/dev/null 2>&1; then
    echo "⚠️  'uv' not found in PATH — skipping API push." >&2
    echo "   Install: https://docs.astral.sh/uv/getting-started/installation/" >&2
    return 0
  fi

  echo ""
  echo "📡 Pushing dashboard '$url_path' to $HA_URL ..."
  "$updater" "$url_path" "$rendered"
}

if [[ -n "${HA_URL:-}" && -n "${HA_TOKEN:-}" ]]; then
  push_dashboard
else
  echo ""
  echo "ℹ️  Dashboard API push disabled (HA_URL / HA_TOKEN not set in .env)."
fi

# --- Optional: restart HA ---
# Custom components require a full restart (not just reload) to pick up code changes.
if $do_restart; then
  if [[ -z "${HA_URL:-}" || -z "${HA_TOKEN:-}" ]]; then
    echo "" >&2
    echo "❌ --restart requires HA_URL and HA_TOKEN in .env." >&2
    exit 1
  fi

  if ! $code_changed && ! $force; then
    echo ""
    echo "ℹ️  Code unchanged — skipping restart (pass --force to restart anyway)."
  else
    echo ""
    echo "🔁 Calling homeassistant.restart on $HA_URL ..."
    echo "   HA will be unavailable for ~60 seconds."
    if ha_service_call "homeassistant.restart"; then
      echo "✅ Restart triggered."
    else
      echo "❌ Restart call failed." >&2
      exit 1
    fi
  fi
else
  if $code_changed; then
    echo ""
    echo "👉 Code changed. Custom components require a restart to apply:"
    echo "     ./deploy.sh --restart   # ~60s downtime"
    echo "   …or restart via the HA UI."
  fi
fi
