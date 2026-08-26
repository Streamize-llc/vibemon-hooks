#!/usr/bin/env bash
# VibeMon installer — curl one-liner setup
#
# Source: https://github.com/Streamize-llc/vibemon-hooks
# Docs:   https://vibemon.dev/docs
# This file is generated from src/install.sh by scripts/build.py.
#
# Usage: curl -fsSL https://vibemon.dev/install.sh | bash -s -- API_KEY

# The shebang above is ignored when this script arrives on stdin (`curl | sh`),
# so a POSIX sh such as dash — /bin/sh on Debian/Ubuntu — would reach the
# `set -o pipefail` below and die with a cryptic "Illegal option". Fail with an
# actionable message instead. Must stay ahead of the first bash-ism, and must
# itself be POSIX so dash can parse it.
if [ -z "${BASH_VERSION:-}" ]; then
  echo "❌ VibeMon's installer requires bash, not sh." >&2
  echo "   Run: curl -fsSL https://vibemon.dev/install.sh | bash -s -- YOUR_API_KEY" >&2
  exit 1
fi

set -euo pipefail

# ─── Pre-flight checks ───────────────────────────────────────────────
VIBEMON_VERSION="__VIBEMON_VERSION__"

# CLI args: one positional API_KEY + optional flags. Flags:
#   --no-commit-msg       force commit message collection OFF in config
#   --collect-commit-msg  force commit message collection ON in config
# When neither flag is given on a re-install, the existing config file
# is preserved as-is.
API_KEY=""
COMMIT_MSG_FLAG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-commit-msg)      COMMIT_MSG_FLAG=1 ;;
    --collect-commit-msg) COMMIT_MSG_FLAG=0 ;;
    --*)
      echo "❌ Unknown flag: $1" >&2
      echo "Usage: curl -fsSL https://vibemon.dev/install.sh | bash -s -- YOUR_API_KEY [--no-commit-msg]" >&2
      exit 1
      ;;
    *)
      if [ -z "$API_KEY" ]; then
        API_KEY="$1"
      else
        echo "❌ Unexpected argument: $1" >&2
        exit 1
      fi
      ;;
  esac
  shift
done

IS_UPDATE=false
if [ -z "$API_KEY" ]; then
  if [ -f "$HOME/.vibemon/api-key" ]; then
    API_KEY=$(cat "$HOME/.vibemon/api-key")
    IS_UPDATE=true
  else
    echo "❌ API key is required."
    echo "Usage: curl -fsSL https://vibemon.dev/install.sh | bash -s -- YOUR_API_KEY [--no-commit-msg]"
    exit 1
  fi
fi

for cmd in curl python3; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "❌ '$cmd' is not installed. Please install it first."
    exit 1
  fi
done

API_URL="https://sirpdtcwawcidhgtltps.supabase.co/functions/v1"

VIBEMON_DIR="$HOME/.vibemon"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
GEMINI_SETTINGS="$HOME/.gemini/settings.json"

# ─── Agent presence snapshot (v29) ───────────────────────────────────
# Taken BEFORE the merge sections below run their `mkdir -p`s. The old
# inline `[ -d "$HOME/.claude" ]` gate in section 5e was evaluated AFTER
# section 5a's mkdir had already created ~/.claude, so it was always true
# and Claude-less machines got MCP registrations for an agent they don't
# have. (Machines that ran v≤28 already have these dirs from our own
# earlier mkdirs — for those the snapshot keeps today's behavior; only
# fresh installs get the honest gate.)
HAS_CLAUDE=false
if command -v claude &>/dev/null || [ -d "$HOME/.claude" ]; then HAS_CLAUDE=true; fi
HAS_GEMINI=false
if command -v gemini &>/dev/null || [ -d "$HOME/.gemini" ]; then HAS_GEMINI=true; fi
HAS_CURSOR=false
if command -v cursor &>/dev/null || [ -d "$HOME/.cursor" ]; then HAS_CURSOR=true; fi
HAS_CODEX=false
if command -v codex &>/dev/null || [ -d "$HOME/.codex" ]; then HAS_CODEX=true; fi

if [ "$IS_UPDATE" = true ]; then
  echo "🐾 Updating VibeMon… (v$VIBEMON_VERSION)"
else
  echo "🐾 Installing VibeMon… (v$VIBEMON_VERSION)"
fi

# ─── 1. State directory ──────────────────────────────────────────────
mkdir -p "$VIBEMON_DIR"

# ─── 2. Save API key ─────────────────────────────────────────────────
printf '%s' "$API_KEY" > "$VIBEMON_DIR/api-key"
chmod 0600 "$VIBEMON_DIR/api-key"
echo "  ✓ API key saved"

# ─── 3. Save version ─────────────────────────────────────────────────
printf '%s' "$VIBEMON_VERSION" > "$VIBEMON_DIR/version"
echo "  ✓ Version v$VIBEMON_VERSION recorded"

# ─── 3b. Initialize config file ──────────────────────────────────────
# Explicit flags (--no-commit-msg / --collect-commit-msg) overwrite the
# file so re-running install.sh from the app's toggle switches the
# setting atomically. Without a flag we preserve the user's existing
# config and only create one on first install.
_vibemon_write_config() {
  cat > "$VIBEMON_DIR/config" << VIBEMON_CONFIG_EOF
# VibeMon config — edit this file to change data-collection behavior.
# Changes take effect on the next hook fire (no restart needed).
#
# Disable git commit message collection (titles are sent by default,
# first line only, 200 char cap):
$1
VIBEMON_CONFIG_EOF
}
if [ "$COMMIT_MSG_FLAG" = "1" ]; then
  _vibemon_write_config "no_commit_msg=1"
  echo "  ✓ Config written (commit message collection: OFF)"
elif [ "$COMMIT_MSG_FLAG" = "0" ]; then
  _vibemon_write_config "# no_commit_msg=1"
  echo "  ✓ Config written (commit message collection: ON)"
elif [ ! -f "$VIBEMON_DIR/config" ]; then
  _vibemon_write_config "# no_commit_msg=1"
  echo "  ✓ Config file created ($VIBEMON_DIR/config)"
fi

# ─── 4. Write notify.sh ──────────────────────────────────────────────
cat > "$VIBEMON_DIR/notify.sh" << 'NOTIFY_SCRIPT'
# %%EMBED:notify.sh%%
NOTIFY_SCRIPT

chmod 0755 "$VIBEMON_DIR/notify.sh"
echo "  ✓ notify.sh installed"

# ─── 5a. Merge Claude Code hooks ─────────────────────────────────────
# lock.py is embedded above merge_claude.py so the FileLock symbol is
# already in module scope when the merge script's `from lock import
# FileLock` shim falls through to ImportError.
mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
python3 - "$CLAUDE_SETTINGS" << 'PYMERGE_CLAUDE'
# %%EMBED:lock.py%%
# %%EMBED:merge_claude.py%%
PYMERGE_CLAUDE
echo "  ✓ Claude Code hooks configured ($CLAUDE_SETTINGS)"

# ─── 5b. Merge Gemini CLI hooks ──────────────────────────────────────
mkdir -p "$(dirname "$GEMINI_SETTINGS")"
python3 - "$GEMINI_SETTINGS" << 'PYMERGE_GEMINI'
# %%EMBED:lock.py%%
# %%EMBED:merge_gemini.py%%
PYMERGE_GEMINI
echo "  ✓ Gemini CLI hooks configured ($GEMINI_SETTINGS)"

# ─── 5c. Merge Cursor hooks (if installed) ───────────────────────────
CURSOR_HOOKS="$HOME/.cursor/hooks.json"
if [ "$HAS_CURSOR" = true ]; then
  mkdir -p "$(dirname "$CURSOR_HOOKS")"
  python3 - "$CURSOR_HOOKS" << 'PYMERGE_CURSOR'
# %%EMBED:lock.py%%
# %%EMBED:merge_cursor.py%%
PYMERGE_CURSOR
  echo "  ✓ Cursor hooks configured ($CURSOR_HOOKS)"
fi

# ─── 5d. Write Codex CLI hooks (if installed) ────────────────────────
# Codex reads ~/.codex/hooks.json (NOT settings.json — v28 wrote there
# and Codex never saw it) and gates new hooks behind in-app approval.
CODEX_HOOKS="$HOME/.codex/hooks.json"
if [ "$HAS_CODEX" = true ]; then
  mkdir -p "$(dirname "$CODEX_HOOKS")"
  python3 - "$CODEX_HOOKS" << 'PYMERGE_CODEX'
# %%EMBED:lock.py%%
# %%EMBED:merge_codex.py%%
PYMERGE_CODEX
  echo "  ✓ Codex CLI hooks written ($CODEX_HOOKS)"
  echo "    ⚠ Codex requires approval: run codex, then /hooks, and trust the"
  echo "      vibemon entries to enable them."
fi

# ─── 5e. Register VibeMon MCP server (Claude Code + Cursor + Gemini) ─
# Phase 2: enable AI agents to read/write TODOs via Model Context Protocol.
# Endpoint: https://vibemon.dev/api/mcp (Streamable HTTP transport)
# Gates use the pre-mkdir snapshot above — the merge sections have already
# created ~/.claude and ~/.gemini by this point.
CLAUDE_MCP_CONFIG="$HOME/.claude.json"
if [ "$HAS_CLAUDE" = true ]; then
  python3 - "$CLAUDE_MCP_CONFIG" "$API_KEY" << 'PYMERGE_CLAUDE_MCP'
# %%EMBED:lock.py%%
# %%EMBED:merge_mcp.py%%
PYMERGE_CLAUDE_MCP
fi

# Cursor gets the docs-exact remote-server shape (url + headers, no "type").
CURSOR_MCP_CONFIG="$HOME/.cursor/mcp.json"
if [ "$HAS_CURSOR" = true ]; then
  python3 - "$CURSOR_MCP_CONFIG" "$API_KEY" cursor << 'PYMERGE_CURSOR_MCP'
# %%EMBED:lock.py%%
# %%EMBED:merge_mcp.py%%
PYMERGE_CURSOR_MCP
fi

# Gemini CLI: streamable-HTTP servers use `httpUrl` (its `url` means SSE).
# Same settings.json the hook merge (5b) already lock-writes.
if [ "$HAS_GEMINI" = true ]; then
  python3 - "$GEMINI_SETTINGS" "$API_KEY" gemini << 'PYMERGE_GEMINI_MCP'
# %%EMBED:lock.py%%
# %%EMBED:merge_mcp.py%%
PYMERGE_GEMINI_MCP
fi

# Codex MCP ([mcp_servers] in ~/.codex/config.toml) is intentionally NOT
# auto-written: config.toml is Codex's primary config (trust hashes, model,
# per-project state) in TOML, which Python's stdlib can read but not write.
# A hand-rolled writer corrupting that file is worse than one manual step —
# a hint is printed at the end instead.

# ─── 6. Test connection ──────────────────────────────────────────────
echo ""
echo "🔗 Testing connection…"
# </dev/null is REQUIRED (v24): in piped installs (`curl … | sh`) stdin is
# the pipe still holding the REST OF THIS SCRIPT; notify.sh's `cat >` would
# slurp it and the install would silently end right here.
# The claude_code probe is the strict one — an invalid API key must fail
# the install here (agent arg was previously omitted, so the server's
# script_install_status only ever learned about claude_code).
bash "$VIBEMON_DIR/notify.sh" test claude_code </dev/null

# Per-agent install probes (v29) — one script_install_status row per
# configured agent, so the server knows WHICH agents this machine wired.
# Best-effort + quiet: a probe hiccup must not fail a good install.
PROBE_AGENTS="gemini_cli"
[ "$HAS_CURSOR" = true ] && PROBE_AGENTS="$PROBE_AGENTS cursor"
[ "$HAS_CODEX" = true ] && PROBE_AGENTS="$PROBE_AGENTS codex_cli"
for _probe_agent in $PROBE_AGENTS; do
  bash "$VIBEMON_DIR/notify.sh" test "$_probe_agent" </dev/null >/dev/null 2>&1 || true
done
echo "  ✓ Install probes sent (claude_code $PROBE_AGENTS)"

echo ""
if [ "$IS_UPDATE" = true ]; then
  echo "🎉 VibeMon updated successfully! (v$VIBEMON_VERSION)"
else
  echo "🎉 VibeMon installed successfully!"
  echo "   Your slime will grow as you code with Claude Code, Gemini CLI, Cursor, or Codex."
  echo ""
  if [ "$COMMIT_MSG_FLAG" = "1" ]; then
    echo "   ℹ Git commit message collection: OFF (--no-commit-msg)"
    echo "     Re-enable anytime: edit ~/.vibemon/config"
  else
    echo "   ℹ Git commit message titles (first line, 200 chars) are collected to power"
    echo "     your activity feed. Opt out anytime:"
    echo "       echo 'no_commit_msg=1' >> ~/.vibemon/config"
  fi
fi
echo ""
echo "   ℹ MCP: restart any running Claude Code / Cursor / Gemini CLI session to"
echo "     load the 'vibemon' MCP server (verify with /mcp in Claude Code)."
if [ "$HAS_CODEX" = true ]; then
  echo "   ℹ Codex MCP is manual (config.toml is TOML — we won't rewrite it):"
  echo "     add [mcp_servers.vibemon] to ~/.codex/config.toml if you want it."
fi
