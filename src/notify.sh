#!/usr/bin/env bash
# VibeMon notify.sh — agent hook thin client
#
# Fired by Claude Code / Gemini CLI / Cursor / Codex. Sanitizes the
# payload, derives behavioral signals, POSTs the envelope to /hook.
#
# Source: https://github.com/Streamize-llc/vibemon-hooks
# This file is generated from src/notify.sh by scripts/build.sh.
# Privacy invariants enforced by tests/test_privacy_canary.py.

set -euo pipefail

VIBEMON_DIR="$HOME/.vibemon"
API_KEY_FILE="$VIBEMON_DIR/api-key"
API_URL="__SUPABASE_URL__/functions/v1"

if [ ! -f "$API_KEY_FILE" ]; then
  echo "[vibemon] API key not found at $API_KEY_FILE" >&2
  exit 1
fi

API_KEY=$(cat "$API_KEY_FILE")
VIBEMON_VER=$(cat "$VIBEMON_DIR/version" 2>/dev/null || echo "0")
EVENT_TYPE="${1:-unknown}"
AGENT="${2:-claude_code}"

# Save stdin + reserve envelope output file (the python heredoc body
# contains triple backticks which break bash's $(...) parser, so we route
# the output through a temp file instead of command substitution).
STDIN_FILE=$(mktemp)
ENV_FILE=$(mktemp)
trap "rm -f $STDIN_FILE $ENV_FILE" EXIT
if [ ! -t 0 ]; then
  cat > "$STDIN_FILE"
fi

# ─── Auto-update check (session_start only, non-blocking) ────────────
# Atomic mkdir-based lock prevents concurrent updates from multiple sessions.
if [ "$EVENT_TYPE" = "session_start" ]; then
  _vibemon_update_check() {
    local LOCK_DIR="$VIBEMON_DIR/update.lock"
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      return
    fi
    trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT
    local LAST_CHECK="$VIBEMON_DIR/last-update-check"
    local NOW=$(date +%s)
    if [ -f "$LAST_CHECK" ]; then
      local LAST=$(cat "$LAST_CHECK")
      if [ $(( NOW - LAST )) -lt 86400 ]; then
        return
      fi
    fi
    printf '%s' "$NOW" > "$LAST_CHECK"
    local LATEST
    LATEST=$(curl -sf "https://vibemon.dev/install.sh?v" 2>/dev/null || true)
    local CURRENT=""
    [ -f "$VIBEMON_DIR/version" ] && CURRENT=$(cat "$VIBEMON_DIR/version")
    if [ -n "$LATEST" ] && [ "$LATEST" != "$CURRENT" ]; then
      curl -fsSL "https://vibemon.dev/install.sh" 2>/dev/null | bash -s 2>/dev/null
    fi
  }
  (_vibemon_update_check </dev/null >/dev/null 2>&1) & disown 2>/dev/null || true
fi

# ─── Detect project identifier (owner/repo from git remote, or dir) ──
PROJECT_ROOT=""
_url=$(git -C "$(pwd)" remote get-url origin 2>/dev/null || true)
if [ -n "$_url" ]; then
  _url="${_url%.git}"
  case "$_url" in
    *://*) PROJECT_ROOT="$(basename "$(dirname "$_url")")/$(basename "$_url")" ;;
    *)     PROJECT_ROOT="${_url#*:}" ;;
  esac
elif _root=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null) && [ -n "$_root" ]; then
  PROJECT_ROOT=$(basename "$_root")
fi

# ─── Build envelope (privacy boundary lives entirely in Python) ──────
VIBEMON_EVT="$EVENT_TYPE" \
  VIBEMON_AGENT="$AGENT" \
  VIBEMON_CWD="$(pwd)" \
  VIBEMON_ROOT="${PROJECT_ROOT:-}" \
  VIBEMON_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  VIBEMON_FILE="$STDIN_FILE" \
  python3 > "$ENV_FILE" 2>/dev/null << 'VIBEMON_PY'
# %%EMBED:classify.py%%
# %%EMBED:extract.py%%
VIBEMON_PY

HOOK_BODY=$(cat "$ENV_FILE")
if [ -z "$HOOK_BODY" ]; then
  HOOK_BODY="{\"v\":2,\"event\":\"$EVENT_TYPE\",\"payload\":{},\"signals\":{},\"cwd\":\"$(pwd)\",\"agent\":\"$AGENT\"}"
fi

if [ "$EVENT_TYPE" = "test" ]; then
  # Synchronous — connection probe.
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/hook" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $API_KEY" \
    -H "X-Vibemon-Version: $VIBEMON_VER" \
    -d "$HOOK_BODY")
  if [ "$HTTP_CODE" = "200" ]; then
    echo "[vibemon] ✓ Connection successful"
  else
    echo "[vibemon] ✗ Connection failed (HTTP $HTTP_CODE)" >&2
    exit 1
  fi
else
  # Fire-and-forget. disown + </dev/null prevents SIGHUP loss when the
  # parent agent process exits right after firing the hook (critical for
  # session_end which fires immediately before the agent disappears).
  (curl -s -X POST "$API_URL/hook" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $API_KEY" \
    -H "X-Vibemon-Version: $VIBEMON_VER" \
    -d "$HOOK_BODY" \
    </dev/null >/dev/null 2>&1) & disown 2>/dev/null || true
fi

# Gemini CLI requires a JSON stdout response to allow the hook to proceed.
if [ "$AGENT" = "gemini_cli" ]; then
  echo '{"decision":"allow"}'
fi
