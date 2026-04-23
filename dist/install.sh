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
VIBEMON_VERSION="15"

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
      echo "Usage: curl -fsSL https://vibemon.dev/install.sh | sh -s -- YOUR_API_KEY [--no-commit-msg]" >&2
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
    echo "Usage: curl -fsSL https://vibemon.dev/install.sh | sh -s -- YOUR_API_KEY [--no-commit-msg]"
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
    # -L is critical: vibemon.dev → www.vibemon.dev is a 307 on Vercel,
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

# ─── Build envelope (privacy boundary lives entirely in Python) ──────
VIBEMON_EVT="$EVENT_TYPE" \
  VIBEMON_AGENT="$AGENT" \
  VIBEMON_CWD="$(pwd)" \
  VIBEMON_ROOT="${PROJECT_ROOT:-}" \
  VIBEMON_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  VIBEMON_FILE="$STDIN_FILE" \
  VIBEMON_NO_COMMIT_MSG="$NO_COMMIT_MSG" \
  python3 > "$ENV_FILE" 2>/dev/null << 'VIBEMON_PY'
"""
classify.py — Bash command classifier for VibeMon hook events.

Pure function — takes a shell command string, returns a category like
"git.commit" or "pkg.test" or "unknown". Never returns the original
command body. Safe to embed in notify.sh and to import for unit tests.
"""

import shlex


COMMIT_MSG_MAX = 200

# When a command is a shell chain ("git add . && git commit && git push"),
# classify every segment and prefer the most story-relevant category.
# Lower index = higher priority. Unlisted categories fall back to the
# first segment's classification.
_CHAIN_PRIORITY = [
    "git.commit",
    "deploy",
    "git.push",
    "test.run",
    "pkg.test",
    "infra.iac",
    "infra.k8s",
    "infra.docker",
    "github.pr_write",
    "git.rewrite",
    "git.branch",
    "db.client",
    "pkg.build",
    "build.sys",
    "lint.run",
    "pkg.lint",
    "pkg.install",
]


_CHAIN_SEPARATORS = frozenset({"&&", "||", ";", "|", "\n"})


def _chain_token_segments(cmd):
    """Tokenize a shell command into per-segment token lists.

    Uses `shlex.shlex(punctuation_chars=True)` so chain operators
    (`&&`, `||`, `;`, `|`) become their own tokens while quoted
    separators inside `git commit -m "a && b"` stay inside the message
    token. Backslash + POSIX quoting rules are handled by the stdlib.

    Returns `[[tokens], ...]`. A non-chained command becomes a single
    segment.
    """
    s = cmd or ""
    if not s.strip():
        return []
    try:
        lex = shlex.shlex(s, posix=True, punctuation_chars=True)
    except ValueError:
        return []
    segs, cur = [], []
    try:
        for tok in lex:
            if tok in _CHAIN_SEPARATORS:
                if cur:
                    segs.append(cur)
                    cur = []
            else:
                cur.append(tok)
    except ValueError:
        return segs  # best-effort on malformed input (unclosed quote etc.)
    if cur:
        segs.append(cur)
    return segs


def _commit_message_from_tokens(tokens):
    """Scan an already-tokenized `git commit ...` invocation for its `-m`
    argument. Returns the first line (COMMIT_MSG_MAX cap) or ""."""
    if len(tokens) < 2 or tokens[0] != "git" or tokens[1] != "commit":
        return ""
    i = 2
    while i < len(tokens):
        t = tokens[i]
        if t == "-m" or t == "--message":
            if i + 1 < len(tokens):
                return tokens[i + 1].split("\n", 1)[0][:COMMIT_MSG_MAX]
            return ""
        if t.startswith("--message="):
            return t[len("--message="):].split("\n", 1)[0][:COMMIT_MSG_MAX]
        # Combined short flags like -am / -ma / -vam — if "m" is present,
        # the next token is the message.
        if t.startswith("-") and not t.startswith("--") and "m" in t[1:]:
            if i + 1 < len(tokens):
                return tokens[i + 1].split("\n", 1)[0][:COMMIT_MSG_MAX]
            return ""
        i += 1
    return ""


def extract_commit_message(cmd):
    """Extract the commit message title from a `git commit -m ...` command.

    Chain-aware: scans each `&&`/`||`/`;`/`|`/newline segment so agent
    chains like `git add . && git commit -m "feat: x" && git push` still
    yield the message. Returns the first line (COMMIT_MSG_MAX cap) or ""
    if no segment contains a parseable `git commit -m`.
    """
    for seg_tokens in _chain_token_segments(cmd or ""):
        result = _commit_message_from_tokens(seg_tokens)
        if result:
            return result
    return ""


def _classify_single(cmd):
    """Classify a SINGLE command (no chain) by its first two tokens."""
    s = (cmd or "").strip()
    if not s:
        return ""
    parts = s.split()
    head = parts[0]
    sub = parts[1] if len(parts) > 1 else ""
    sub2 = parts[2] if len(parts) > 2 else ""

    if head == "git":
        if sub == "commit":
            return "git.commit"
        if sub == "push":
            return "git.push"
        if sub in ("pull", "fetch"):
            return "git.sync"
        if sub in ("diff", "log", "status", "show", "blame"):
            return "git.read"
        if sub in ("rebase", "merge", "cherry-pick", "revert", "reset"):
            return "git.rewrite"
        if sub in ("checkout", "switch", "branch", "stash"):
            return "git.branch"
        return "git.other"

    if head == "gh":
        if sub == "pr" and sub2 in ("create", "merge"):
            return "github.pr_write"
        return "github.other"

    if head in ("npm", "pnpm", "yarn", "bun"):
        target = sub2 if sub == "run" else sub
        if target in ("test", "t"):
            return "pkg.test"
        if target in ("install", "i", "add", "remove", "uninstall"):
            return "pkg.install"
        if target in ("build", "tsc", "typecheck"):
            return "pkg.build"
        if target in ("lint", "format", "prettier", "eslint", "biome"):
            return "pkg.lint"
        if target in ("dev", "start", "serve"):
            return "pkg.run"
        return "pkg.other"

    if head in ("pytest", "jest", "vitest", "mocha", "rspec", "phpunit"):
        return "test.run"
    if head == "go" and sub == "test":
        return "test.run"
    if head == "cargo" and sub == "test":
        return "test.run"

    if head in ("tsc", "eslint", "prettier", "ruff", "black", "mypy", "biome"):
        return "lint.run"
    if head == "docker":
        return "infra.docker"
    if head in ("kubectl", "helm", "k9s"):
        return "infra.k8s"
    if head in ("terraform", "tofu", "pulumi"):
        return "infra.iac"
    if head in ("curl", "wget", "http", "httpie"):
        return "net.request"
    if head in ("rm", "mv", "cp", "chmod", "chown"):
        return "fs.mutate"
    if head in ("ls", "cat", "head", "tail", "less", "more", "wc", "tree"):
        return "fs.read"
    if head in ("find", "grep", "rg", "fd", "ag", "fzf", "ack"):
        return "fs.search"
    if head in ("mkdir", "touch", "ln"):
        return "fs.create"
    if head in ("supabase", "psql", "sqlite3", "mysql", "redis-cli", "mongo", "mongosh"):
        return "db.client"
    if head in ("vercel", "netlify", "fly", "gcloud", "aws", "eb", "heroku", "railway"):
        return "deploy"
    if head in ("python", "python3", "node", "deno", "bun", "ruby", "go", "cargo", "rustc", "java"):
        return "runtime"
    if head in ("make", "cmake", "gradle", "mvn", "sbt", "ninja"):
        return "build.sys"
    if head in ("echo", "printf", "env", "export", "source", "alias"):
        return "shell.builtin"
    if head in ("cd", "pwd", "pushd", "popd"):
        return "shell.nav"
    if head in ("brew", "apt", "apt-get", "pacman", "yum", "dnf"):
        return "pkg.system"
    if head in ("ssh", "scp", "rsync"):
        return "net.transfer"
    if head in ("open", "code", "cursor", "nano", "vim", "emacs", "subl"):
        return "editor"
    if head == "expo":
        return "mobile.expo"
    if head in ("eas", "fastlane", "xcodebuild"):
        return "mobile.build"

    return "unknown"


def classify_bash(cmd):
    """Classify a Bash command. Chain-aware.

    For a single command, returns the first-token category. For a shell
    chain (`&&`/`||`/`;`/`|`), classifies every segment and picks the
    highest-priority category from _CHAIN_PRIORITY. If no priority match,
    falls back to the first segment's classification. Returns "" for
    empty input.
    """
    segments = _chain_token_segments(cmd or "")
    if not segments:
        return ""
    categories = [_classify_single(" ".join(tokens)) for tokens in segments]
    if len(categories) == 1:
        return categories[0]
    priority_index = {cat: i for i, cat in enumerate(_CHAIN_PRIORITY)}
    ranked = [c for c in categories if c in priority_index]
    if ranked:
        return min(ranked, key=lambda c: priority_index[c])
    return categories[0]
"""
extract.py — VibeMon envelope builder.

Reads a Claude Code / Gemini CLI / Cursor / Codex hook payload from a
file path given by env var VIBEMON_FILE, sanitizes all bodies, derives
behavioral signals, and prints the v2 envelope as JSON to stdout.

Privacy invariants (enforced by tests/test_privacy_canary.py):
  - No code content (Write content, Edit new_string/old_string)
  - No prompt body
  - No bash command string (only the head token + classified category)
  - No tool_response / stderr text
  - Only categories, lengths, booleans, file extensions, file paths

This module is also importable for unit tests:
  from extract import build_envelope, sanitize_payload, derive_signals
"""

import json
import os
import sys

try:
    import datetime
except Exception:
    datetime = None

# Embedded for build (notify.sh concatenates classify.py before this file).
# When imported as a module, classifier helpers come from the sibling import.
try:
    from classify import classify_bash, extract_commit_message  # type: ignore
except ImportError:
    # If running as a single concatenated script, these names are already
    # in the module's namespace — defined above by the build step.
    pass


# ─── Allowlists / forbidden keys ───────────────────────────────────────
SAFE_TOP_KEYS = {
    "tool_name", "tool", "session_id", "cwd", "timestamp", "client_version",
    "project_root", "agent", "subagent_type", "matcher", "transcript_path",
    "permission_mode", "hook_event_name", "tool_use_id", "model",
    "source", "agent_type", "command_name", "command_args", "command_source",
    "expansion_type", "notification_type", "title", "load_reason", "memory_type",
    "trigger_file_path", "parent_file_path", "globs", "config_source", "trigger",
    "is_interrupt",
}

FORBIDDEN_TOP_KEYS = {
    "prompt", "message", "user_input", "text",
    "tool_response", "response", "stderr", "stdout", "error",
}

FORBIDDEN_TI_KEYS = {
    "content", "new_string", "old_string", "new_source", "old_source",
    "command", "script",
}


# ─── Helpers ───────────────────────────────────────────────────────────
def count_nonblank_lines(s):
    """Count non-blank newline-separated lines in a string."""
    if not s:
        return 0
    return sum(1 for line in s.split(chr(10)) if line.strip())


def detect_lang_hint(body):
    """Crude language detection from first 500 chars. Returns 'ko'/'en'/'mixed'."""
    if not body:
        return ""
    sample = body[:500]
    han = sum(1 for c in sample if 0xAC00 <= ord(c) <= 0xD7AF)
    ascii_alpha = sum(1 for c in sample if c.isalpha() and ord(c) < 128)
    if han > 5 and han > ascii_alpha:
        return "ko"
    if ascii_alpha > 5:
        return "en"
    return "mixed"


def bucket_chars(n):
    """Bucket prompt char count into XS/S/M/L/XL."""
    if n < 50:
        return "XS"
    if n < 200:
        return "S"
    if n < 500:
        return "M"
    if n < 2000:
        return "L"
    return "XL"


def classify_failure(err):
    """Classify a failure error string into a kind. Returns 'other' as fallback.

    Order matters: the more specific patterns (string_mismatch's "string
    to replace not found") must be checked BEFORE the generic ones
    ("not found" → file_not_found).
    """
    if not err:
        return ""
    el = err.lower()
    if "string to replace" in el or "old_string" in el or "no matches" in el:
        return "string_mismatch"
    if "no such file" in el or "enoent" in el:
        return "file_not_found"
    if "permission" in el or "denied" in el or "eacces" in el:
        return "permission"
    if "not found" in el:
        return "file_not_found"
    if "syntax" in el or "unexpected token" in el or "parse error" in el:
        return "syntax"
    if "timeout" in el or "timed out" in el:
        return "timeout"
    if "network" in el or "econnrefused" in el or "enotfound" in el or " dns " in el:
        return "network"
    if "type" in el and ("error" in el or "mismatch" in el):
        return "type_error"
    return "other"


def file_metadata(fp):
    """Extract file.* signals from a path. Returns (ext, depth, is_test, is_config, is_doc)."""
    if not isinstance(fp, str) or not fp:
        return ("", 0, False, False, False)
    base = fp.rsplit("/", 1)[-1]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    depth = fp.count("/")
    fl = fp.lower()
    bl = base.lower()
    is_test = (
        ".test." in fl or ".spec." in fl or "_test." in fl
        or "/test/" in fl or "/tests/" in fl or "__tests__" in fl
        or "_spec." in fl
    )
    is_config = (
        bl in ("package.json", "tsconfig.json", "dockerfile", "gemfile",
               "cargo.toml", "go.mod", "requirements.txt", "pyproject.toml")
        or bl.startswith(".env")
        or "tsconfig" in bl
        or bl.endswith(".yaml") or bl.endswith(".yml") or bl.endswith(".toml")
    )
    is_doc = ext in ("md", "mdx", "rst", "txt")
    return (ext, depth, is_test, is_config, is_doc)


# ─── Core: sanitize + derive ───────────────────────────────────────────
def sanitize_payload(payload):
    """Strip ALL bodies. Returns a dict with only allowlisted top-level
    keys plus a slimmed tool_input containing at most file_path."""
    if not isinstance(payload, dict):
        return {}
    out = {}
    for k, v in payload.items():
        if k in FORBIDDEN_TOP_KEYS:
            continue
        if k == "tool_input":
            ci = {}
            if isinstance(v, dict):
                fp = v.get("file_path")
                if isinstance(fp, str) and fp:
                    ci["file_path"] = fp
            out[k] = ci
            continue
        if k in SAFE_TOP_KEYS or k.startswith("hook_"):
            out[k] = v
    return out


def derive_signals(event, payload):
    """Derive sparse signals dict from raw payload. The payload may still
    contain bodies (this function reads them but never returns them — it
    extracts shape and discards)."""
    sig = {}
    if not isinstance(payload, dict):
        return sig

    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else None
    tn = (payload.get("tool_name") or payload.get("tool") or "").lower()

    # Lines added/removed
    la, lr = 0, 0
    if ti:
        if tn in ("write", "write_file"):
            la = count_nonblank_lines(ti.get("content"))
        elif tn in ("edit", "replace", "notebookedit"):
            nw = count_nonblank_lines(ti.get("new_string") or ti.get("new_source"))
            ol = count_nonblank_lines(ti.get("old_string") or ti.get("old_source"))
            la = max(0, nw - ol)
            lr = max(0, ol - nw)
    if la or lr:
        sig["lines.added"] = la
        sig["lines.removed"] = lr
        sig["lines.net"] = la - lr

    # File metadata
    fp = ti.get("file_path") if ti else None
    if isinstance(fp, str) and fp:
        ext, depth, is_test, is_config, is_doc = file_metadata(fp)
        if ext:
            sig["file.ext"] = ext
        sig["file.depth"] = depth
        if is_test:
            sig["file.is_test"] = True
        if is_config:
            sig["file.is_config"] = True
        if is_doc:
            sig["file.is_doc"] = True

    # Bash classification — body discarded, only category + head + length.
    # Exception: git commit messages (title only, first line, 200 char cap)
    # are captured by default. Opt out with VIBEMON_NO_COMMIT_MSG=1.
    if ti and tn in ("bash", "shell", "run_command"):
        cmd = ti.get("command") or ti.get("script") or ""
        if isinstance(cmd, str) and cmd:
            cat = classify_bash(cmd)
            head = cmd.strip().split()[0] if cmd.strip() else ""
            sig["bash.category"] = cat
            sig["bash.head"] = head[:32]
            sig["bash.byte_len"] = len(cmd)
            if cat == "git.commit" and os.environ.get("VIBEMON_NO_COMMIT_MSG", "") != "1":
                msg = extract_commit_message(cmd)
                if msg:
                    sig["commit.message"] = msg

    # Prompt shape — body discarded
    if event == "prompt":
        body = ""
        for k in ("prompt", "message", "user_input", "text"):
            v = payload.get(k)
            if isinstance(v, str) and v:
                body = v
                break
        if body:
            n = len(body)
            sig["prompt.chars"] = n
            sig["prompt.bucket"] = bucket_chars(n)
            sig["prompt.has_question"] = "?" in body
            sig["prompt.has_code_fence"] = "```" in body
            sig["prompt.line_count"] = body.count(chr(10)) + 1
            sig["prompt.lang_hint"] = detect_lang_hint(body)

    # Failure classification
    if event == "tool_failure":
        err = ""
        for k in ("error", "tool_response", "response", "message", "stderr"):
            v = payload.get(k)
            if isinstance(v, str) and v:
                err = v
                break
            if isinstance(v, dict):
                err = json.dumps(v)[:1000]
                break
        if err:
            sig["failure.kind"] = classify_failure(err)
            sig["failure.byte_len"] = len(err)

    # Tool meta
    if tn:
        sig["tool.name"] = tn
    if tn == "task":
        sig["tool.is_subagent"] = True

    return sig


def local_time_fields():
    """Return (local_hour, local_dow, local_tz) from system clock. Best-effort."""
    if datetime is None:
        return (None, None, "")
    try:
        now = datetime.datetime.now().astimezone()
        return (now.hour, now.weekday(), str(now.tzinfo) if now.tzinfo else "")
    except Exception:
        return (None, None, "")


def build_envelope(event, payload, agent, cwd, timestamp, project_root=""):
    """Assemble the v2 envelope from raw inputs. The payload here is the
    RAW Claude Code payload (with bodies). This function sanitizes and
    derives in one place."""
    payload = payload if isinstance(payload, dict) else {}

    # Compute signals from raw (we read bodies, but only emit shape)
    signals = derive_signals(event, payload)

    # Strip all bodies before persisting payload
    clean = sanitize_payload(payload)

    # Re-inject computed scalars for legacy compat (server uses these directly)
    la = signals.get("lines.added", 0)
    lr = signals.get("lines.removed", 0)
    if la or lr:
        clean["lines_added"] = la
        clean["lines_removed"] = lr

    if project_root:
        clean["project_root"] = project_root

    sid = clean.get("session_id")

    local_hour, local_dow, local_tz = local_time_fields()

    env = {
        "v": 2,
        "event": event,
        "agent": agent or "claude_code",
        "cwd": cwd or "",
        "timestamp": timestamp or "",
        "payload": clean,
        "signals": signals,
    }
    if project_root:
        env["project_root"] = project_root
    if sid:
        env["session_id"] = sid
    if local_hour is not None:
        env["local_hour"] = local_hour
    if local_dow is not None:
        env["local_dow"] = local_dow
    if local_tz:
        env["local_tz"] = local_tz

    return env


# ─── Script entry point (called by notify.sh) ──────────────────────────
def _read_stdin_json(file_path):
    try:
        with open(file_path) as f:
            raw = f.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def main():
    event = os.environ.get("VIBEMON_EVT", "unknown")
    agent = os.environ.get("VIBEMON_AGENT", "claude_code")
    cwd = os.environ.get("VIBEMON_CWD", "")
    timestamp = os.environ.get("VIBEMON_TS", "")
    project_root = os.environ.get("VIBEMON_ROOT", "")
    file_path = os.environ.get("VIBEMON_FILE", "")

    payload = _read_stdin_json(file_path) if file_path else {}
    env = build_envelope(event, payload, agent, cwd, timestamp, project_root)
    sys.stdout.write(json.dumps(env, ensure_ascii=False))


if __name__ == "__main__":
    main()
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
NOTIFY_SCRIPT

chmod 0755 "$VIBEMON_DIR/notify.sh"
echo "  ✓ notify.sh installed"

# ─── 5a. Merge Claude Code hooks ─────────────────────────────────────
mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
python3 - "$CLAUDE_SETTINGS" << 'PYMERGE_CLAUDE'
"""
merge_claude.py — Idempotently merge VibeMon hooks into ~/.claude/settings.json.

Uses fcntl.flock + tempfile.mkstemp + os.replace for safety against
concurrent install.sh runs from multiple sessions (multi-session
invariant — see vibemon-app/CLAUDE.md).
"""

import fcntl
import json
import os
import sys
import tempfile


VIBEMON_HOOKS = {
    "PostToolUse": [
        {
            "matcher": "Edit|Write|NotebookEdit",
            "hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh activity claude_code"}],
        },
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh bash claude_code"}],
        },
    ],
    "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh prompt claude_code"}]},
    ],
    "Stop": [
        {"hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh stop claude_code"}]},
    ],
    "Notification": [
        {
            "matcher": "permission_prompt",
            "hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh permission claude_code"}],
        },
    ],
    "SessionStart": [
        {"hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh session_start claude_code"}]},
    ],
    "SessionEnd": [
        {"hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh session_end claude_code"}]},
    ],
    "PostToolUseFailure": [
        {
            "matcher": "Edit|Write|NotebookEdit",
            "hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh tool_failure claude_code"}],
        },
    ],
}


def _is_vibemon_entry(entry):
    """Detect any vibemon hook by 'vibemon' substring in the command."""
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def merge(settings_path, hooks_def=None):
    """Merge VibeMon hooks into the given settings file. Idempotent.

    Strips any existing vibemon entries before adding the current set,
    so re-running upgrades cleanly. Uses an exclusive flock and atomic
    rename to survive concurrent install runs.
    """
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS

    lock_path = settings_path + ".vibemon.lock"
    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    lock_f = open(lock_path, "w")
    fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
    try:
        settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                try:
                    settings = json.load(f)
                except json.JSONDecodeError:
                    settings = {}

        hooks = settings.setdefault("hooks", {})

        for event_name, new_entries in hooks_def.items():
            existing = hooks.get(event_name, [])
            existing = [e for e in existing if not _is_vibemon_entry(e)]
            existing.extend(new_entries)
            hooks[event_name] = existing

        settings["hooks"] = hooks

        dir_path = os.path.dirname(settings_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".settings.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, settings_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    finally:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_claude.py <settings_path>\n")
        sys.exit(2)
    merge(sys.argv[1])
PYMERGE_CLAUDE
echo "  ✓ Claude Code hooks configured ($CLAUDE_SETTINGS)"

# ─── 5b. Merge Gemini CLI hooks ──────────────────────────────────────
mkdir -p "$(dirname "$GEMINI_SETTINGS")"
python3 - "$GEMINI_SETTINGS" << 'PYMERGE_GEMINI'
"""
merge_gemini.py — Idempotently merge VibeMon hooks into ~/.gemini/settings.json.
"""

import fcntl
import json
import os
import sys
import tempfile


VIBEMON_HOOKS = {
    "AfterTool": [
        {
            "matcher": "write_file|replace",
            "hooks": [{
                "name": "vibemon-exp",
                "type": "command",
                "command": "bash ~/.vibemon/notify.sh activity gemini_cli",
                "timeout": 5000,
            }],
        },
    ],
    "SessionStart": [
        {"hooks": [{
            "name": "vibemon-session-start",
            "type": "command",
            "command": "bash ~/.vibemon/notify.sh session_start gemini_cli",
            "timeout": 5000,
        }]},
    ],
    "SessionEnd": [
        {"hooks": [{
            "name": "vibemon-session-end",
            "type": "command",
            "command": "bash ~/.vibemon/notify.sh session_end gemini_cli",
            "timeout": 5000,
        }]},
    ],
    "BeforeAgent": [
        {"hooks": [{
            "name": "vibemon-prompt",
            "type": "command",
            "command": "bash ~/.vibemon/notify.sh prompt gemini_cli",
            "timeout": 5000,
        }]},
    ],
    "AfterAgent": [
        {"hooks": [{
            "name": "vibemon-stop",
            "type": "command",
            "command": "bash ~/.vibemon/notify.sh stop gemini_cli",
            "timeout": 5000,
        }]},
    ],
}


def _is_vibemon_entry(entry):
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def merge(settings_path, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS

    lock_path = settings_path + ".vibemon.lock"
    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    lock_f = open(lock_path, "w")
    fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
    try:
        settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                try:
                    settings = json.load(f)
                except json.JSONDecodeError:
                    settings = {}

        hooks = settings.setdefault("hooks", {})
        for event_name, new_entries in hooks_def.items():
            existing = hooks.get(event_name, [])
            existing = [e for e in existing if not _is_vibemon_entry(e)]
            existing.extend(new_entries)
            hooks[event_name] = existing
        settings["hooks"] = hooks

        dir_path = os.path.dirname(settings_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".settings.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, settings_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    finally:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_gemini.py <settings_path>\n")
        sys.exit(2)
    merge(sys.argv[1])
PYMERGE_GEMINI
echo "  ✓ Gemini CLI hooks configured ($GEMINI_SETTINGS)"

# ─── 5c. Merge Cursor hooks (if installed) ───────────────────────────
CURSOR_HOOKS="$HOME/.cursor/hooks.json"
if command -v cursor &>/dev/null || [ -d "$HOME/.cursor" ]; then
  mkdir -p "$(dirname "$CURSOR_HOOKS")"
  python3 - "$CURSOR_HOOKS" << 'PYMERGE_CURSOR'
"""
merge_cursor.py — Merge VibeMon hooks into ~/.cursor/hooks.json.

Cursor's hook config is shallower than Claude/Gemini: each event maps
directly to a list of {command, timeout} entries with no nested 'hooks' array.
"""

import json
import os
import sys


VIBEMON_HOOKS = {
    "afterFileEdit": [
        {"command": "bash ~/.vibemon/notify.sh activity cursor", "timeout": 5000},
    ],
    "afterFileCreate": [
        {"command": "bash ~/.vibemon/notify.sh activity cursor", "timeout": 5000},
    ],
}


def _is_vibemon_entry(entry):
    return "vibemon" in entry.get("command", "")


def merge(hooks_path, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS

    os.makedirs(os.path.dirname(hooks_path) or ".", exist_ok=True)
    config = {}
    if os.path.exists(hooks_path):
        with open(hooks_path, "r") as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                config = {}

    hooks = config.setdefault("hooks", {})
    for event_name, new_entries in hooks_def.items():
        existing = hooks.get(event_name, [])
        existing = [e for e in existing if not _is_vibemon_entry(e)]
        existing.extend(new_entries)
        hooks[event_name] = existing
    config["hooks"] = hooks

    with open(hooks_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_cursor.py <hooks_path>\n")
        sys.exit(2)
    merge(sys.argv[1])
PYMERGE_CURSOR
  echo "  ✓ Cursor hooks configured ($CURSOR_HOOKS)"
fi

# ─── 5d. Merge Codex CLI hooks (if installed) ────────────────────────
CODEX_SETTINGS="$HOME/.codex/settings.json"
if command -v codex &>/dev/null || [ -d "$HOME/.codex" ]; then
  mkdir -p "$(dirname "$CODEX_SETTINGS")"
  python3 - "$CODEX_SETTINGS" << 'PYMERGE_CODEX'
"""
merge_codex.py — Merge VibeMon session hooks into ~/.codex/settings.json.

Codex CLI only exposes session-level events.
"""

import json
import os
import sys


VIBEMON_HOOKS = {
    "SessionStart": [
        {"command": "bash ~/.vibemon/notify.sh session_start codex_cli", "timeout": 5000},
    ],
    "SessionEnd": [
        {"command": "bash ~/.vibemon/notify.sh session_end codex_cli", "timeout": 5000},
    ],
}


def _is_vibemon_entry(entry):
    return "vibemon" in entry.get("command", "")


def merge(settings_path, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    settings = {}
    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            try:
                settings = json.load(f)
            except json.JSONDecodeError:
                settings = {}

    hooks = settings.setdefault("hooks", {})
    for event_name, new_entries in hooks_def.items():
        existing = hooks.get(event_name, [])
        existing = [e for e in existing if not _is_vibemon_entry(e)]
        existing.extend(new_entries)
        hooks[event_name] = existing
    settings["hooks"] = hooks

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_codex.py <settings_path>\n")
        sys.exit(2)
    merge(sys.argv[1])
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
