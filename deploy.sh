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

# mDNS hostnames like `homeassistant.local` can be flaky during a long
# script run — the macOS resolver intermittently drops the lookup
# entirely, leading to per-probe 5 s timeouts even though HA is up.
# Resolve the hostname to an IP once and substitute it for the rest of
# the deploy. We export the rewritten HA_URL so child tools (the
# WebSocket helpers) inherit it too.
resolve_ha_url() {
  if [[ -z "${HA_URL:-}" ]]; then
    return 0
  fi
  local stripped host
  stripped="${HA_URL#http://}"
  stripped="${stripped#https://}"
  host="${stripped%%[:/]*}"
  if [[ -z "$host" || "$host" =~ ^[0-9.]+$ ]]; then
    return 0  # Already an IP, or empty
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    return 0  # No resolver available, fall through
  fi
  local ip
  ip=$(python3 -c "import socket,sys
try:
    print(socket.gethostbyname('$host'))
except OSError:
    sys.exit(1)" 2>/dev/null) || return 0
  if [[ -z "$ip" ]]; then
    return 0
  fi
  local resolved="${HA_URL//$host/$ip}"
  if [[ "$resolved" != "$HA_URL" ]]; then
    echo "🔍 Resolved $host → $ip (using $resolved for the rest of this run)"
    export HA_URL="$resolved"
  fi
}

resolve_ha_url

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

# --- Sync Lovelace card to <config>/www/ ---
# The custom card is a frontend resource served by HA at /local/...,
# so it must live in the config volume's www/ directory rather than in
# custom_components/. We use a content-hashed filename
# (`rain-warner-card.<hash>.js`) instead of a stable name + ?v=<hash>
# query string: aggressive PWA / mobile-app caches (HA Companion on
# iOS in particular) sometimes ignore query strings and keep serving
# the old module — a different *path* is the only thing they reliably
# treat as a fresh resource. Stale hashed copies and the legacy
# unhashed file are removed on every deploy.
CARD_SRC="$SCRIPT_DIR/dashboard/rain-warner-card.js"
CARD_DEST_DIR="$TARGET/www"

if [[ -f "$CARD_SRC" ]]; then
  CARD_HASH=$(shasum -a 256 "$CARD_SRC" | awk '{print $1}' | cut -c1-8)
  CARD_DEST="$CARD_DEST_DIR/rain-warner-card.$CARD_HASH.js"
  mkdir -p "$CARD_DEST_DIR"
  CARD_OUT=$(rsync -ci --inplace --no-perms --no-owner --no-group \
    "$CARD_SRC" "$CARD_DEST" 2>&1) || {
    echo "❌ Card rsync failed:" >&2
    echo "$CARD_OUT" >&2
    exit 1
  }
  if [[ -n "$CARD_OUT" ]]; then
    card_changed=true
    echo "✅ Lovelace card synced to $CARD_DEST"
  else
    card_changed=false
    echo "✅ Lovelace card up-to-date ($CARD_DEST)"
  fi

  # Cleanup older hashed copies and the legacy unhashed file. The glob
  # `rain-warner-card.*.js` matches `rain-warner-card.<anything>.js` but
  # NOT `rain-warner-card.js` (which only has one dot), so we handle
  # both cases. nullglob keeps the loop quiet when nothing matches.
  shopt -s nullglob
  for old in "$CARD_DEST_DIR"/rain-warner-card.*.js "$CARD_DEST_DIR"/rain-warner-card.js; do
    if [[ -f "$old" && "$old" != "$CARD_DEST" ]]; then
      rm -f "$old" && echo "🗑  removed stale card copy: $(basename "$old")"
    fi
  done
  shopt -u nullglob
else
  card_changed=false
  echo "ℹ️  No Lovelace card found at $CARD_SRC — skipping."
fi

# --- Optional: update the Lovelace JS resource URL via WebSocket API ---
# Path-based cache busting: the resource points at
# `/local/rain-warner-card.<hash>.js`. The helper finds whichever
# variant of the resource is currently registered (legacy unhashed,
# old `?v=...` query string, or older hash) and rewrites it to the
# current hashed path. Idempotent when the hash already matches.
cache_bust_card() {
  local card_file="$CARD_SRC"
  local stem_url="/local/rain-warner-card"
  local helper="$SCRIPT_DIR/tools/ha_update_card_resource.py"

  if [[ ! -f "$card_file" ]]; then
    return 0
  fi
  if [[ ! -x "$helper" ]]; then
    echo "⚠️  Cache-bust helper not executable: $helper — skipping." >&2
    return 0
  fi
  if ! command -v uv >/dev/null 2>&1; then
    echo "⚠️  'uv' not found in PATH — skipping cache-bust." >&2
    return 0
  fi
  echo ""
  echo "🔄 Updating Lovelace resource for $stem_url ..."
  "$helper" "$stem_url" "$card_file"
}

if [[ -n "${HA_URL:-}" && -n "${HA_TOKEN:-}" ]]; then
  cache_bust_card
fi

# --- HA REST helper ---
HA_SERVICE_TIMEOUT_S=180
# Override-able via .env: some hosts (lots of integrations, slow disks)
# legitimately need 5+ minutes to fully come back after a restart.
HA_RECOVERY_TIMEOUT_S="${HA_RECOVERY_TIMEOUT_S:-300}"

ha_is_alive() {
  curl --fail --silent --max-time 5 \
    -H "Authorization: Bearer $HA_TOKEN" \
    "${HA_URL%/}/api/config" >/dev/null 2>&1
}

ha_wait_until_alive() {
  local deadline=$(( $(date +%s) + HA_RECOVERY_TIMEOUT_S ))
  while [[ $(date +%s) -lt $deadline ]]; do
    if ha_is_alive; then
      return 0
    fi
    sleep 5
  done
  return 1
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

  # 502/503/504 during a restart call are expected: HA shuts down before
  # it can fully respond, so the proxy/server reports an upstream error.
  # Treat them as "restart accepted" and let the caller wait for HA to
  # come back online.
  case "$http_code" in
    200) return 0 ;;
    502|503|504)
      echo "⏳ HA returned HTTP $http_code (expected during restart) — will wait for recovery." >&2
      return 0
      ;;
    *)
      echo "❌ HA returned HTTP $http_code for $service." >&2
      return 1
      ;;
  esac
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

  if ! $code_changed && ! $card_changed && ! $force; then
    echo ""
    echo "ℹ️  Code unchanged — skipping restart (pass --force to restart anyway)."
  else
    echo ""
    echo "🔁 Calling homeassistant.restart on $HA_URL ..."
    echo "   HA will be unavailable for ~60 seconds."
    if ha_service_call "homeassistant.restart"; then
      echo "⏳ Waiting for HA to come back online (up to ${HA_RECOVERY_TIMEOUT_S}s)..."
      if ha_wait_until_alive; then
        echo "✅ HA is back online."
      else
        echo "⚠️  HA didn't return within ${HA_RECOVERY_TIMEOUT_S}s." >&2
        echo "   It may still be starting up — check the HA UI." >&2
        exit 1
      fi
    else
      echo "❌ Restart call failed." >&2
      exit 1
    fi
  fi
else
  if $code_changed || $card_changed; then
    echo ""
    echo "👉 Changes detected. Custom components require a restart to apply:"
    echo "     ./deploy.sh --restart   # ~60s downtime"
    echo "   …or restart via the HA UI."
  fi
fi
