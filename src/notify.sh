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
# Supabase project URL is public information (also visible in
# NEXT_PUBLIC_SUPABASE_URL on vibemon.dev and inside the mobile app).
# Hardcoded so vibemon.dev can serve install.sh as a simple 302 redirect
# to the GitHub Release artifact, without any server-side string substitution.
API_URL="https://sirpdtcwawcidhgtltps.supabase.co/functions/v1"

if [ ! -f "$API_KEY_FILE" ]; then
  echo "[vibemon] API key not found at $API_KEY_FILE" >&2
  exit 1
fi

API_KEY=$(cat "$API_KEY_FILE")
VIBEMON_VER=$(cat "$VIBEMON_DIR/version" 2>/dev/null || echo "0")
EVENT_TYPE="${1:-unknown}"
AGENT="${2:-claude_code}"

# ─── Read user config (opt-outs) ─────────────────────────────────────
# ~/.vibemon/config is a simple key=value file. Supported keys:
#   no_commit_msg=1   → strip git commit message from the envelope.
NO_COMMIT_MSG=""
if [ -f "$VIBEMON_DIR/config" ]; then
  while IFS='=' read -r _key _val; do
    case "$_key" in
      \#*|"") continue ;;
      no_commit_msg) NO_COMMIT_MSG="$_val" ;;
    esac
  done < "$VIBEMON_DIR/config"
fi

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
    # NOT `local` (v23): the single-quoted EXIT trap below expands at fire
    # time — after this function has returned, when a local would already
    # be out of scope. With `local` the trap ran `rmdir ''` (a no-op), so
    # the lock was NEVER released and every install's auto-update died
    # permanently after its first daily check.
    LOCK_DIR="$VIBEMON_DIR/update.lock"
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      # Stale-lock recovery (v23): a checker killed before its cleanup trap
      # (sleep / SIGKILL / shutdown) leaves the dir behind and would
      # otherwise disable auto-update FOREVER — observed in production
      # (a machine stuck on v18 for six weeks). A live check holds the
      # lock for seconds; anything older than 60 minutes is garbage.
      if find "$LOCK_DIR" -maxdepth 0 -mmin +60 2>/dev/null | grep -q .; then
        rmdir "$LOCK_DIR" 2>/dev/null || true
      fi
      # Contention (another session holds a live lock) is normal, not an
      # error — return 0 so the failed mkdir's status doesn't propagate.
      mkdir "$LOCK_DIR" 2>/dev/null || return 0
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
    # -L is critical: /install.sh?v is a 302 to raw.githubusercontent.com,
    # without -L curl returns "Redirecting..." and the version compare breaks.
    LATEST=$(curl -fsSL "https://vibemon.dev/install.sh?v" 2>/dev/null || true)
    local CURRENT=""
    [ -f "$VIBEMON_DIR/version" ] && CURRENT=$(cat "$VIBEMON_DIR/version")
    # Sanity: LATEST must be a short numeric/version-ish string, not an HTML body.
    if [ -n "$LATEST" ] && [ ${#LATEST} -le 16 ] && [ "$LATEST" != "$CURRENT" ]; then
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
REPO_IDENTIFIER=""
case "$PROJECT_ROOT" in */*) REPO_IDENTIFIER="$PROJECT_ROOT" ;; esac
GIT_BRANCH=$(git -C "$(pwd)" branch --show-current 2>/dev/null || true)
GIT_HEAD=$(git -C "$(pwd)" rev-parse HEAD 2>/dev/null || true)

# ─── Build envelope (privacy boundary lives entirely in Python) ──────
# `|| true` on the python3 call: under `set -e` a broken python3 (pyenv
# shim, removed CLT) would otherwise kill the script right here, making
# the empty-envelope fallback below unreachable dead code.
#
# Nothing may sit between the backslash-continued env prefix and the
# `python3` line — not even a comment. A comment there is valid bash, so
# `bash -n` accepts it, but it ends the logical line: the assignments
# become plain shell variables, python3 inherits none of them, and every
# envelope silently degrades to the empty fallback. v28 and v29 shipped
# exactly that, which broke production collection from 2026-08-26.
# tests/test_static.py pins both halves of this.
VIBEMON_EVT="$EVENT_TYPE" \
  VIBEMON_AGENT="$AGENT" \
  VIBEMON_CWD="$(pwd)" \
  VIBEMON_ROOT="${PROJECT_ROOT:-}" \
  VIBEMON_REPO="${REPO_IDENTIFIER:-}" \
  VIBEMON_BRANCH="${GIT_BRANCH:-}" \
  VIBEMON_HEAD="${GIT_HEAD:-}" \
  VIBEMON_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  VIBEMON_FILE="$STDIN_FILE" \
  VIBEMON_NO_COMMIT_MSG="$NO_COMMIT_MSG" \
  python3 > "$ENV_FILE" 2>/dev/null << 'VIBEMON_PY' || true
# %%EMBED:classify.py%%
# %%EMBED:extract.py%%
VIBEMON_PY

HOOK_BODY=$(cat "$ENV_FILE")
if [ -z "$HOOK_BODY" ]; then
  HOOK_BODY="{\"v\":2,\"event\":\"$EVENT_TYPE\",\"payload\":{},\"signals\":{},\"cwd\":\"$(pwd)\",\"agent\":\"$AGENT\"}"
fi

if [ "$EVENT_TYPE" = "test" ]; then
  # Synchronous — connection probe.
  HTTP_CODE=$(curl -s --max-time 10 -o /dev/null -w "%{http_code}" -X POST "$API_URL/hook" \
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
  # nohup: disown only stops bash from forwarding HUP — the child keeps the
  # parent's process group, so a closing terminal still kills an in-flight
  # curl (measured). nohup makes curl ignore HUP outright, which is what
  # session_end needs: it fires at the exact moment the terminal goes away.
  (nohup curl -s --max-time 15 -X POST "$API_URL/hook" \
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
