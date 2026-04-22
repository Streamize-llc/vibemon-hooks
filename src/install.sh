#!/usr/bin/env bash
# VibeMon installer — curl one-liner setup
#
# Source: https://github.com/Streamize-llc/vibemon-hooks
# Docs:   https://vibemon.dev/docs
# This file is generated from src/install.sh by scripts/build.sh.
#
# Usage: curl -fsSL https://vibemon.dev/install.sh | sh -s -- API_KEY

set -euo pipefail

# ─── Pre-flight checks ───────────────────────────────────────────────
VIBEMON_VERSION="__VIBEMON_VERSION__"
API_KEY="${1:-}"
IS_UPDATE=false
if [ -z "$API_KEY" ]; then
  if [ -f "$HOME/.vibemon/api-key" ]; then
    API_KEY=$(cat "$HOME/.vibemon/api-key")
    IS_UPDATE=true
  else
    echo "❌ API key is required."
    echo "Usage: curl -fsSL https://vibemon.dev/install.sh | sh -s -- YOUR_API_KEY"
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

# ─── 4. Write notify.sh ──────────────────────────────────────────────
cat > "$VIBEMON_DIR/notify.sh" << 'NOTIFY_SCRIPT'
# %%EMBED:notify.sh%%
NOTIFY_SCRIPT

chmod 0755 "$VIBEMON_DIR/notify.sh"
echo "  ✓ notify.sh installed"

# ─── 5a. Merge Claude Code hooks ─────────────────────────────────────
mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
python3 - "$CLAUDE_SETTINGS" << 'PYMERGE_CLAUDE'
# %%EMBED:merge_claude.py%%
PYMERGE_CLAUDE
echo "  ✓ Claude Code hooks configured ($CLAUDE_SETTINGS)"

# ─── 5b. Merge Gemini CLI hooks ──────────────────────────────────────
mkdir -p "$(dirname "$GEMINI_SETTINGS")"
python3 - "$GEMINI_SETTINGS" << 'PYMERGE_GEMINI'
# %%EMBED:merge_gemini.py%%
PYMERGE_GEMINI
echo "  ✓ Gemini CLI hooks configured ($GEMINI_SETTINGS)"

# ─── 5c. Merge Cursor hooks (if installed) ───────────────────────────
CURSOR_HOOKS="$HOME/.cursor/hooks.json"
if command -v cursor &>/dev/null || [ -d "$HOME/.cursor" ]; then
  mkdir -p "$(dirname "$CURSOR_HOOKS")"
  python3 - "$CURSOR_HOOKS" << 'PYMERGE_CURSOR'
# %%EMBED:merge_cursor.py%%
PYMERGE_CURSOR
  echo "  ✓ Cursor hooks configured ($CURSOR_HOOKS)"
fi

# ─── 5d. Merge Codex CLI hooks (if installed) ────────────────────────
CODEX_SETTINGS="$HOME/.codex/settings.json"
if command -v codex &>/dev/null || [ -d "$HOME/.codex" ]; then
  mkdir -p "$(dirname "$CODEX_SETTINGS")"
  python3 - "$CODEX_SETTINGS" << 'PYMERGE_CODEX'
# %%EMBED:merge_codex.py%%
PYMERGE_CODEX
  echo "  ✓ Codex CLI hooks configured ($CODEX_SETTINGS)"
fi

# ─── 6. Test connection ──────────────────────────────────────────────
echo ""
echo "🔗 Testing connection…"
bash "$VIBEMON_DIR/notify.sh" test

echo ""
if [ "$IS_UPDATE" = true ]; then
  echo "🎉 VibeMon updated successfully! (v$VIBEMON_VERSION)"
else
  echo "🎉 VibeMon installed successfully!"
  echo "   Your slime will grow as you code with Claude Code, Gemini CLI, Cursor, or Codex."
fi
