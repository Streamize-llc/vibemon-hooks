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
VIBEMON_VERSION="30"

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
"""
classify.py — Bash command classifier for VibeMon hook events.

Pure function — takes a shell command string, returns a category like
"git.commit" or "pkg.test" or "unknown". Never returns the original
command body. Safe to embed in notify.sh and to import for unit tests.
"""

import re
import shlex


COMMIT_MSG_MAX = 200
HEAD_MAX = 32

# `KEY=VAL` env-var assignment prefix as recognised by the shell.
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Matches `$(cat <<[-]DELIM ... DELIM)` command substitution used by Claude Code
# et al. to pass multi-line commit messages via HEREDOC. Captures the DELIM in
# group(1) and the body (between the opening and closing DELIM lines) in group(2).
# Supports single/double-quoted delimiters and the `<<-` indented variant.
_HEREDOC_RE = re.compile(
    r"""\$\(\s*cat\s+          # $(cat
        <<-?\s*                # <<  or  <<-
        ['"]?(\w+)['"]?        # DELIM  (optionally quoted)
        \s*\n                  # newline after opener
        (.*?)                  # body (lazy)
        \n\s*\1\b              # closing DELIM on its own line (tab-trim allowed for <<-)
    """,
    re.DOTALL | re.VERBOSE,
)

# A `-m` token that *starts* like the HEREDOC opener but failed _HEREDOC_RE
# means shlex mangled it: double quotes inside the body toggle shlex's quote
# state, so the token ends at the first unquoted whitespace instead of the
# closing DELIM. Detected in extract_commit_message and recovered from the
# raw command string via _COMMIT_HEREDOC_RE below.
_HEREDOC_OPENER_PREFIX_RE = re.compile(r"^\$\(\s*cat\s+<<")

# Raw-command fallback for the mangled case above. Anchored to the message
# flag (`-m` / `-am` / `--message[=]`) immediately followed by `$(cat <<` so
# a heredoc belonging to a *different* command in the chain can never be
# mistaken for the commit message.
_COMMIT_HEREDOC_RE = re.compile(
    r"""(?<!\S)                # flag starts a word
        (?:--message|-[A-Za-z]*m)  # -m / -am / --message[=]
        [=\s]+["']?            # flag separator + optional opening quote
        \$\(\s*cat\s+          # $(cat
        <<-?\s*                # <<  or  <<-
        ['"]?(\w+)['"]?        # DELIM  (optionally quoted)
        \s*\n                  # newline after opener
        (.*?)                  # body (lazy)
        \n\s*\1\b              # closing DELIM
    """,
    re.DOTALL | re.VERBOSE,
)

_GIT_COMMIT_POS_RE = re.compile(r"\bgit\s+commit\b")


def _first_nonempty_line(body, cap=COMMIT_MSG_MAX):
    """Return the first stripped non-empty line of `body`, capped."""
    if not body:
        return ""
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped:
            return stripped[:cap]
    return ""


def _extract_message_from_arg(msg_token):
    """Given the literal `-m` argument as tokenized by shlex, return the
    commit title. Handles three forms:
      1. Plain string  `'feat: x'`                  → "feat: x"
      2. Multi-line    `'feat: header\\n\\nbody'`   → "feat: header"
      3. HEREDOC subst `$(cat <<'EOF'\\nfeat: x\\nEOF\\n)` → "feat: x"
    Returns "" if nothing parseable.
    """
    if not msg_token:
        return ""
    m = _HEREDOC_RE.search(msg_token)
    if m:
        return _first_nonempty_line(m.group(2))
    return _first_nonempty_line(msg_token)

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
        # Best-effort on malformed input (unclosed quote etc.) — keep the
        # in-flight segment too, so `git commit -m "$(…unbalanced ' or "…)"`
        # still classifies as git.commit instead of dropping the whole
        # command (category "" would lose the event downstream).
        if cur:
            segs.append(cur)
        return segs
    if cur:
        segs.append(cur)
    return segs


def _commit_message_from_tokens(tokens):
    """Scan an already-tokenized `git commit ...` invocation for its `-m`
    argument. Handles HEREDOC command substitution as used by Claude Code
    (`-m "$(cat <<'EOF' ... EOF)"`). Returns the first non-empty line
    (COMMIT_MSG_MAX cap) or ""."""
    # Skip any leading env-var assignments (`GIT_COMMITTER_DATE=... git commit`).
    start = 0
    while start < len(tokens) and _ENV_ASSIGN_RE.match(tokens[start]):
        start += 1
    if len(tokens) - start < 2 or tokens[start] != "git" or tokens[start + 1] != "commit":
        return ""
    i = start + 2
    while i < len(tokens):
        t = tokens[i]
        if t == "-m" or t == "--message":
            if i + 1 < len(tokens):
                return _extract_message_from_arg(tokens[i + 1])
            return ""
        if t.startswith("--message="):
            return _extract_message_from_arg(t[len("--message="):])
        # Combined short flags like -am / -ma / -vam — if "m" is present,
        # the next token is the message.
        if t.startswith("-") and not t.startswith("--") and "m" in t[1:]:
            if i + 1 < len(tokens):
                return _extract_message_from_arg(tokens[i + 1])
            return ""
        i += 1
    return ""


def extract_commit_message(cmd):
    """Extract the commit message title from a `git commit -m ...` command.

    Chain-aware: scans each `&&`/`||`/`;`/`|` segment so agent chains like
    `git add . && git commit -m "feat: x" && git push` still yield the
    message.

    Double quotes inside a HEREDOC body confuse the shlex pass (each `"`
    toggles its quote state mid-body): the `-m` token either comes back
    truncated at the opener (`$(cat <<'EOF'` — the very string v18 was
    meant to eliminate) or, with an odd quote count, tokenization aborts
    and the argument is lost. In both cases fall back to searching the raw
    command for the flag-anchored heredoc — the anchor guarantees only the
    heredoc that IS the message argument can ever match, never another
    command's heredoc in the chain.

    Returns the first line (COMMIT_MSG_MAX cap) or "".
    """
    cmd = cmd or ""
    for seg_tokens in _chain_token_segments(cmd):
        result = _commit_message_from_tokens(seg_tokens)
        if not result:
            continue
        if _HEREDOC_OPENER_PREFIX_RE.match(result):
            break  # mangled heredoc token — recover from the raw string below
        return result
    scope = _GIT_COMMIT_POS_RE.search(cmd)
    if scope:
        m = _COMMIT_HEREDOC_RE.search(cmd, scope.start())
        if m:
            return _first_nonempty_line(m.group(2))
    return ""


def safe_command_head(cmd, maxlen=HEAD_MAX):
    """Return the first *real* command token, skipping env-var assignments.

    Prevents secret leakage when agents run commands with inline env-var
    prefixes like `API_KEY=sk-xxx curl ...` — the naive `cmd.split()[0]`
    would leak the first 32 chars of the secret to `bash.head`.

    Transformations:
      `KEY=VAL cmd ...`        → `cmd`
      `KEY1=a KEY2=b cmd ...`  → `cmd`
      `SRK='sb_secret_xxx'`    → `<env>`  (all env, no command)
      `` (empty)               → ``
    """
    if not cmd or not cmd.strip():
        return ""
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        # Unclosed quote etc. — fall back to naive split, still env-aware.
        tokens = cmd.strip().split()
    i = 0
    while i < len(tokens) and _ENV_ASSIGN_RE.match(tokens[i]):
        i += 1
    if i >= len(tokens):
        return "<env>"
    return tokens[i][:maxlen]


def _classify_single(cmd):
    """Classify a SINGLE command (no chain) by its first two tokens.

    Skips leading env-var assignments (`KEY=VAL cmd ...`) so that
    prefixed commands classify correctly — e.g. `GIT_COMMITTER_DATE=... git commit`
    must still be `git.commit`, not `unknown`.
    """
    s = (cmd or "").strip()
    if not s:
        return ""
    try:
        parts = shlex.split(s, posix=True)
    except ValueError:
        parts = s.split()
    i = 0
    while i < len(parts) and _ENV_ASSIGN_RE.match(parts[i]):
        i += 1
    if i >= len(parts):
        return ""  # all env-var assignments, no actual command to classify
    head = parts[i]
    sub = parts[i + 1] if i + 1 < len(parts) else ""
    sub2 = parts[i + 2] if i + 2 < len(parts) else ""

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
    from classify import classify_bash, extract_commit_message, safe_command_head  # type: ignore
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
    "duration_ms", "duration",
}

FORBIDDEN_TOP_KEYS = {
    "prompt", "message", "user_input", "text",
    "tool_response", "response", "stderr", "stdout", "error",
}

FORBIDDEN_TI_KEYS = {
    "content", "new_string", "old_string", "new_source", "old_source",
    "command", "script",
}


# ─── Cursor payload normalization (v29) ────────────────────────────────
# Cursor hook payloads have no `tool_name`, put `file_path`/`command` at
# the top level, and identify the conversation via `conversation_id`.
# The server's activity gate requires tool/tool_name, so we synthesize a
# Claude-compatible shape CLIENT-SIDE before sanitize/derive — the server
# stays untouched. Keyed on agent == "cursor" (set by the hook command),
# with the specific reshapes driven by `hook_event_name`.
CURSOR_EVENT_TOOL = {
    "afterFileEdit": "edit",
    "afterShellExecution": "bash",
}


def normalize_cursor_payload(payload):
    """Return a Claude-shaped copy of a raw Cursor hook payload.

    - synthesizes tool_name from hook_event_name (afterFileEdit → "edit",
      afterShellExecution → "bash"); postToolUseFailure already carries
      its own tool_name and is left as-is
    - lifts top-level file_path into tool_input.file_path (the one spot
      sanitize_payload preserves)
    - lifts afterShellExecution's top-level command into tool_input.command
      so bash classification runs (the body is then discarded by
      sanitize_payload — FORBIDDEN_TI_KEYS)
    - maps conversation_id → session_id: conversation_id is present on
      every Cursor payload while session_id only appears on
      sessionStart/sessionEnd, so keying on conversation_id gives ONE
      stable id across all events of a conversation (multi-session
      invariant #2 — useCodingState disambiguation)
    """
    if not isinstance(payload, dict):
        return payload
    p = dict(payload)
    hev = p.get("hook_event_name") or ""

    cid = p.get("conversation_id")
    if isinstance(cid, str) and cid:
        p["session_id"] = cid

    if not (p.get("tool_name") or p.get("tool")):
        tool = CURSOR_EVENT_TOOL.get(hev)
        if tool:
            p["tool_name"] = tool

    ti = dict(p["tool_input"]) if isinstance(p.get("tool_input"), dict) else {}
    fp = p.get("file_path")
    if isinstance(fp, str) and fp and not ti.get("file_path"):
        ti["file_path"] = fp
    cmd = p.get("command")
    if hev == "afterShellExecution" and isinstance(cmd, str) and cmd and not ti.get("command"):
        ti["command"] = cmd
    if ti:
        p["tool_input"] = ti
    return p


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

    # Gemini CLI sends the arguments as `tool_args`, not `tool_input` — same
    # shape, different key. Read whichever is present so shell classification
    # and line counts work for both.
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else None
    if ti is None and isinstance(payload.get("tool_args"), dict):
        ti = payload.get("tool_args")
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
    # Cursor afterFileEdit ships an `edits` array of {old_string, new_string}
    # pairs at the top level. The bodies are read for counting ONLY and never
    # leave this function (canary_cursor_edits fixture pins that).
    if not (la or lr) and tn == "edit" and isinstance(payload.get("edits"), list):
        for e in payload["edits"]:
            if not isinstance(e, dict):
                continue
            nw = count_nonblank_lines(e.get("new_string"))
            ol = count_nonblank_lines(e.get("old_string"))
            la += max(0, nw - ol)
            lr += max(0, ol - nw)
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
    if ti and tn in ("bash", "shell", "run_command", "run_shell_command"):
        cmd = ti.get("command") or ti.get("script") or ""
        if isinstance(cmd, str) and cmd:
            cat = classify_bash(cmd)
            sig["bash.category"] = cat
            sig["bash.head"] = safe_command_head(cmd)
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
        # error_message: Cursor postToolUseFailure's field name.
        for k in ("error", "error_message", "tool_response", "response", "message", "stderr"):
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

    # Tool duration — Claude Code v2.1.119+ emits `duration_ms` (PostToolUse +
    # PostToolUseFailure). Cursor postToolUse emits `duration` (also ms).
    # Gemini CLI / Codex CLI provide neither — mark unavailable so downstream
    # analytics can mask "no data" instead of misreading it as "instant tool".
    if event in ("activity", "tool_failure"):
        d_ms = payload.get("duration_ms")
        d = payload.get("duration")
        if isinstance(d_ms, (int, float)) and not isinstance(d_ms, bool):
            sig["tool.duration_ms"] = int(d_ms)
        elif isinstance(d, (int, float)) and not isinstance(d, bool):
            sig["tool.duration_ms"] = int(d)
        else:
            sig["tool.duration_unavailable"] = True

    return sig


def _iana_tz():
    """Best-effort IANA timezone name (e.g. 'Asia/Seoul'). Empty on failure."""
    env = os.environ.get("TZ", "")
    if env:
        clean = env.lstrip(":")
        if "/" in clean:
            return clean
    try:
        link = os.readlink("/etc/localtime")
        marker = "/zoneinfo/"
        i = link.find(marker)
        if i >= 0:
            return link[i + len(marker):]
    except (OSError, AttributeError):
        pass
    try:
        with open("/etc/timezone") as f:
            tz = f.read().strip()
            if "/" in tz:
                return tz
    except (IOError, OSError):
        pass
    return ""


def local_time_fields():
    """Return (local_hour, local_dow, local_tz) from system clock. Best-effort."""
    if datetime is None:
        return (None, None, "")
    try:
        now = datetime.datetime.now().astimezone()
        return (now.hour, now.weekday(), _iana_tz())
    except Exception:
        return (None, None, "")


def build_envelope(
    event, payload, agent, cwd, timestamp, project_root="",
    repo_identifier="", branch="", head_sha="",
):
    """Assemble the v2 envelope from raw inputs. The payload here is the
    RAW Claude Code payload (with bodies). This function sanitizes and
    derives in one place."""
    payload = payload if isinstance(payload, dict) else {}

    # Cursor payloads arrive in a different dialect — reshape to the
    # Claude-compatible form first (tool_name synthesis, file_path /
    # command lift, conversation_id → session_id). All other agents pass
    # through untouched, so the Claude Code wire format cannot regress.
    if agent == "cursor":
        payload = normalize_cursor_payload(payload)

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
    if repo_identifier:
        env["repo_identifier"] = repo_identifier.lower()
    if branch:
        env["branch"] = branch
    if head_sha:
        env["head_sha"] = head_sha
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
        with open(file_path, encoding="utf-8") as f:
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
    repo_identifier = os.environ.get("VIBEMON_REPO", "")
    branch = os.environ.get("VIBEMON_BRANCH", "")
    head_sha = os.environ.get("VIBEMON_HEAD", "")
    file_path = os.environ.get("VIBEMON_FILE", "")

    payload = _read_stdin_json(file_path) if file_path else {}
    env = build_envelope(
        event, payload, agent, cwd, timestamp, project_root,
        repo_identifier, branch, head_sha,
    )
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
NOTIFY_SCRIPT

chmod 0755 "$VIBEMON_DIR/notify.sh"
echo "  ✓ notify.sh installed"

# ─── 5a. Merge Claude Code hooks ─────────────────────────────────────
# lock.py is embedded above merge_claude.py so the FileLock symbol is
# already in module scope when the merge script's `from lock import
# FileLock` shim falls through to ImportError.
mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
python3 - "$CLAUDE_SETTINGS" << 'PYMERGE_CLAUDE'
"""
lock.py — Cross-platform exclusive file lock.

Wraps fcntl.flock (Unix) and msvcrt.locking (Windows) behind a single
context manager so merge_*.py can stay platform-agnostic. Used by the
settings.json merge code path to prevent corruption under concurrent
install.sh / install.ps1 runs from multiple AI coding sessions.

See vibemon-app/CLAUDE.md "Multi-Session Concurrency Invariants" #3.

Stdlib only.
"""

import os


IS_WINDOWS = os.name == "nt"


class FileLock:
    """Blocking exclusive lock on a sentinel file.

    Usage:
        with FileLock(settings_path):
            # critical section — read, modify, atomic-rename settings.json

    The sentinel file (`<path>.vibemon.lock`) lives next to the protected
    file. Lock semantics are blocking on both platforms.
    """

    def __init__(self, base_path):
        self.path = base_path + ".vibemon.lock"
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "w", encoding="utf-8")
        if IS_WINDOWS:
            import msvcrt
            # LK_LOCK = blocking exclusive on a single byte at offset 0.
            # Retries indefinitely until acquired.
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if IS_WINDOWS:
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
"""
merge_claude.py — Idempotently merge VibeMon hooks into ~/.claude/settings.json.

Uses an exclusive FileLock + tempfile.mkstemp + os.replace for safety
against concurrent install.sh / install.ps1 runs from multiple AI
coding sessions (multi-session invariant — see vibemon-app/CLAUDE.md).
"""

import json
import os
import sys
import tempfile

# When this file is concatenated with lock.py (via build.py's
# # %%EMBED:lock.py%% marker inside install.sh), FileLock is already
# in module scope and this import is a harmless no-op fallback.
# When imported as a module (tests, install.py), src/ is on sys.path.
try:
    from lock import FileLock
except ImportError:
    pass


# Default notify command — preserved verbatim from pre-Windows-port
# behavior. install.sh runs merge_claude.py without arguments and gets
# the bash invocation; install.py (Windows) passes notify_prefix to
# substitute the Python invocation.
DEFAULT_NOTIFY_PREFIX = "bash ~/.vibemon/notify.sh"


def _build_hooks(notify_prefix):
    """Construct the VIBEMON_HOOKS dict for a given notify command prefix."""
    return {
        "PostToolUse": [
            {
                "matcher": "Edit|Write|NotebookEdit|Task",
                "hooks": [{"type": "command", "command": "%s activity claude_code" % notify_prefix}],
            },
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "%s bash claude_code" % notify_prefix}],
            },
        ],
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "%s prompt claude_code" % notify_prefix}]},
        ],
        "Stop": [
            {"hooks": [{"type": "command", "command": "%s stop claude_code" % notify_prefix}]},
        ],
        "Notification": [
            {
                "matcher": "permission_prompt",
                "hooks": [{"type": "command", "command": "%s permission claude_code" % notify_prefix}],
            },
        ],
        "SessionStart": [
            {"hooks": [{"type": "command", "command": "%s session_start claude_code" % notify_prefix}]},
        ],
        "SessionEnd": [
            {"hooks": [{"type": "command", "command": "%s session_end claude_code" % notify_prefix}]},
        ],
        "PostToolUseFailure": [
            {
                "matcher": "Edit|Write|NotebookEdit|Task",
                "hooks": [{"type": "command", "command": "%s tool_failure claude_code" % notify_prefix}],
            },
            # Bash failures (failed tests / broken builds / deploy errors) are the
            # most salient "tripping" moments for the slime mirror. PostToolUse and
            # PostToolUseFailure are mutually exclusive (success vs failure), so a
            # failed Bash fires here as tool_failure, never as event='bash' — no
            # double-count. extract.py classifies failure.kind from the error.
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "%s tool_failure claude_code" % notify_prefix}],
            },
        ],
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    """Detect any vibemon hook by 'vibemon' substring in the command.

    Substring match catches both the bash form (bash ~/.vibemon/notify.sh)
    and the Python form ("py" "...\\.vibemon\\notify.py"), so re-installs
    cleanly replace entries from either runtime.
    """
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def merge(settings_path, notify_prefix=None, hooks_def=None):
    """Merge VibeMon hooks into the given settings file. Idempotent.

    notify_prefix overrides the default bash command (used by Windows
    installer where bash is not present).
    """
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS if notify_prefix is None else _build_hooks(notify_prefix)

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    with FileLock(settings_path):
        settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                try:
                    settings = json.load(f)
                except json.JSONDecodeError:
                    # Don't clobber a file we don't own — skip and say so.
                    print(
                        f"  ⚠ Could not parse {settings_path}; skipping Claude Code hook registration.",
                        file=sys.stderr,
                    )
                    return False

        if not isinstance(settings, dict):
            print(
                f"  ⚠ {settings_path} is not a JSON object; skipping Claude Code hook registration.",
                file=sys.stderr,
            )
            return False

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
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, settings_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_claude.py <settings_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
PYMERGE_CLAUDE
echo "  ✓ Claude Code hooks configured ($CLAUDE_SETTINGS)"

# ─── 5b. Merge Gemini CLI hooks ──────────────────────────────────────
mkdir -p "$(dirname "$GEMINI_SETTINGS")"
python3 - "$GEMINI_SETTINGS" << 'PYMERGE_GEMINI'
"""
lock.py — Cross-platform exclusive file lock.

Wraps fcntl.flock (Unix) and msvcrt.locking (Windows) behind a single
context manager so merge_*.py can stay platform-agnostic. Used by the
settings.json merge code path to prevent corruption under concurrent
install.sh / install.ps1 runs from multiple AI coding sessions.

See vibemon-app/CLAUDE.md "Multi-Session Concurrency Invariants" #3.

Stdlib only.
"""

import os


IS_WINDOWS = os.name == "nt"


class FileLock:
    """Blocking exclusive lock on a sentinel file.

    Usage:
        with FileLock(settings_path):
            # critical section — read, modify, atomic-rename settings.json

    The sentinel file (`<path>.vibemon.lock`) lives next to the protected
    file. Lock semantics are blocking on both platforms.
    """

    def __init__(self, base_path):
        self.path = base_path + ".vibemon.lock"
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "w", encoding="utf-8")
        if IS_WINDOWS:
            import msvcrt
            # LK_LOCK = blocking exclusive on a single byte at offset 0.
            # Retries indefinitely until acquired.
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if IS_WINDOWS:
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
"""
merge_gemini.py — Idempotently merge VibeMon hooks into ~/.gemini/settings.json.
"""

import json
import os
import sys
import tempfile

# See merge_claude.py for the FileLock import shim explanation.
try:
    from lock import FileLock
except ImportError:
    pass


DEFAULT_NOTIFY_PREFIX = "bash ~/.vibemon/notify.sh"


def _build_hooks(notify_prefix):
    return {
        "AfterTool": [
            {
                "matcher": "write_file|replace",
                "hooks": [{
                    "name": "vibemon-exp",
                    "type": "command",
                    "command": "%s activity gemini_cli" % notify_prefix,
                    "timeout": 5000,
                }],
            },
            # Shell runs are observation-only (`bash` event, no XP) — same
            # economy as Claude Code's Bash. Without this matcher, Gemini
            # users have no commits, no bash categories and understated
            # coding time (the tool_use+bash invariant).
            {
                "matcher": "run_shell_command",
                "hooks": [{
                    "name": "vibemon-shell",
                    "type": "command",
                    "command": "%s bash gemini_cli" % notify_prefix,
                    "timeout": 5000,
                }],
            },
        ],
        "SessionStart": [
            {"hooks": [{
                "name": "vibemon-session-start",
                "type": "command",
                "command": "%s session_start gemini_cli" % notify_prefix,
                "timeout": 5000,
            }]},
        ],
        "SessionEnd": [
            {"hooks": [{
                "name": "vibemon-session-end",
                "type": "command",
                "command": "%s session_end gemini_cli" % notify_prefix,
                "timeout": 5000,
            }]},
        ],
        "BeforeAgent": [
            {"hooks": [{
                "name": "vibemon-prompt",
                "type": "command",
                "command": "%s prompt gemini_cli" % notify_prefix,
                "timeout": 5000,
            }]},
        ],
        "AfterAgent": [
            {"hooks": [{
                "name": "vibemon-stop",
                "type": "command",
                "command": "%s stop gemini_cli" % notify_prefix,
                "timeout": 5000,
            }]},
        ],
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def merge(settings_path, notify_prefix=None, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS if notify_prefix is None else _build_hooks(notify_prefix)

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    with FileLock(settings_path):
        settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                try:
                    settings = json.load(f)
                except json.JSONDecodeError:
                    # Don't clobber a file we don't own — skip and say so.
                    print(
                        f"  ⚠ Could not parse {settings_path}; skipping Gemini CLI hook registration.",
                        file=sys.stderr,
                    )
                    return False

        if not isinstance(settings, dict):
            print(
                f"  ⚠ {settings_path} is not a JSON object; skipping Gemini CLI hook registration.",
                file=sys.stderr,
            )
            return False

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
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, settings_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_gemini.py <settings_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
PYMERGE_GEMINI
echo "  ✓ Gemini CLI hooks configured ($GEMINI_SETTINGS)"

# ─── 5c. Merge Cursor hooks (if installed) ───────────────────────────
CURSOR_HOOKS="$HOME/.cursor/hooks.json"
if [ "$HAS_CURSOR" = true ]; then
  mkdir -p "$(dirname "$CURSOR_HOOKS")"
  python3 - "$CURSOR_HOOKS" << 'PYMERGE_CURSOR'
"""
lock.py — Cross-platform exclusive file lock.

Wraps fcntl.flock (Unix) and msvcrt.locking (Windows) behind a single
context manager so merge_*.py can stay platform-agnostic. Used by the
settings.json merge code path to prevent corruption under concurrent
install.sh / install.ps1 runs from multiple AI coding sessions.

See vibemon-app/CLAUDE.md "Multi-Session Concurrency Invariants" #3.

Stdlib only.
"""

import os


IS_WINDOWS = os.name == "nt"


class FileLock:
    """Blocking exclusive lock on a sentinel file.

    Usage:
        with FileLock(settings_path):
            # critical section — read, modify, atomic-rename settings.json

    The sentinel file (`<path>.vibemon.lock`) lives next to the protected
    file. Lock semantics are blocking on both platforms.
    """

    def __init__(self, base_path):
        self.path = base_path + ".vibemon.lock"
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "w", encoding="utf-8")
        if IS_WINDOWS:
            import msvcrt
            # LK_LOCK = blocking exclusive on a single byte at offset 0.
            # Retries indefinitely until acquired.
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if IS_WINDOWS:
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
"""
merge_cursor.py — Merge VibeMon hooks into ~/.cursor/hooks.json.

Cursor's hook config is shallower than Claude/Gemini: each event maps
directly to a list of {command, timeout} entries with no nested 'hooks'
array, plus a top-level "version": 1.

v29 rewired the events against Cursor's real hook surface (ground truth:
a hand-wired working hooks.json + the official hooks docs). The old
config registered `afterFileCreate` — an event Cursor does not have —
and used timeout 5000, copy-pasted from Gemini's milliseconds. Cursor
timeouts are SECONDS (5000 = 83 minutes). Result: zero production
events had ever arrived through this wiring.

Event map (cursor event → vibemon event):
  sessionStart        → session_start
  sessionEnd          → session_end
  beforeSubmitPrompt  → prompt
  stop                → stop
  afterFileEdit       → activity
  afterShellExecution → bash
  postToolUseFailure  → tool_failure

Uses an exclusive FileLock + tempfile.mkstemp + os.replace for safety
against concurrent install.sh / install.ps1 runs from multiple AI
coding sessions (multi-session invariant — see vibemon-app/CLAUDE.md).
"""

import json
import os
import sys
import tempfile

# When this file is concatenated with lock.py (via build.py's
# # %%EMBED:lock.py%% marker inside install.sh), FileLock is already
# in module scope and this import is a harmless no-op fallback.
try:
    from lock import FileLock
except ImportError:
    pass


DEFAULT_NOTIFY_PREFIX = "bash ~/.vibemon/notify.sh"

# Seconds, not milliseconds (Cursor docs; the working hand-wired config
# on record uses 10). Keep small: hooks fire on every edit/shell run.
CURSOR_TIMEOUT_S = 10

# cursor event name → vibemon event name. This dict is the single source
# the merge builds from; tests/test_merge_events.py pins it so a ghost
# event (afterFileCreate…) can never come back.
EVENT_MAP = {
    "sessionStart": "session_start",
    "sessionEnd": "session_end",
    "beforeSubmitPrompt": "prompt",
    "stop": "stop",
    "afterFileEdit": "activity",
    "afterShellExecution": "bash",
    "postToolUseFailure": "tool_failure",
}


def _build_hooks(notify_prefix):
    return {
        cursor_event: [
            {
                "command": "%s %s cursor" % (notify_prefix, vibemon_event),
                "timeout": CURSOR_TIMEOUT_S,
            },
        ]
        for cursor_event, vibemon_event in EVENT_MAP.items()
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    return "vibemon" in entry.get("command", "")


def merge(hooks_path, notify_prefix=None, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS if notify_prefix is None else _build_hooks(notify_prefix)

    os.makedirs(os.path.dirname(hooks_path) or ".", exist_ok=True)
    with FileLock(hooks_path):
        config = {}
        if os.path.exists(hooks_path):
            with open(hooks_path, "r", encoding="utf-8") as f:
                try:
                    config = json.load(f)
                except json.JSONDecodeError:
                    # Don't clobber a file we don't own — skip and say so.
                    print(
                        f"  ⚠ Could not parse {hooks_path}; skipping Cursor hook registration.",
                        file=sys.stderr,
                    )
                    return False

        if not isinstance(config, dict):
            print(
                f"  ⚠ {hooks_path} is not a JSON object; skipping Cursor hook registration.",
                file=sys.stderr,
            )
            return False

        hooks = config.setdefault("hooks", {})

        # Sweep vibemon entries from EVERY event first — not just the ones
        # we register. This is what removes the v28 ghost (`afterFileCreate`)
        # on upgrade instead of leaving it behind forever.
        for event_name in list(hooks.keys()):
            entries = hooks.get(event_name)
            if not isinstance(entries, list):
                continue
            kept = [e for e in entries if not (isinstance(e, dict) and _is_vibemon_entry(e))]
            if kept:
                hooks[event_name] = kept
            else:
                del hooks[event_name]

        for event_name, new_entries in hooks_def.items():
            existing = hooks.get(event_name, [])
            existing.extend(new_entries)
            hooks[event_name] = existing
        config["hooks"] = hooks
        # Cursor's schema carries a top-level version; write it on fresh
        # files, preserve whatever an existing file declares.
        config.setdefault("version", 1)

        dir_path = os.path.dirname(hooks_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".hooks.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, hooks_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_cursor.py <hooks_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
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
"""
lock.py — Cross-platform exclusive file lock.

Wraps fcntl.flock (Unix) and msvcrt.locking (Windows) behind a single
context manager so merge_*.py can stay platform-agnostic. Used by the
settings.json merge code path to prevent corruption under concurrent
install.sh / install.ps1 runs from multiple AI coding sessions.

See vibemon-app/CLAUDE.md "Multi-Session Concurrency Invariants" #3.

Stdlib only.
"""

import os


IS_WINDOWS = os.name == "nt"


class FileLock:
    """Blocking exclusive lock on a sentinel file.

    Usage:
        with FileLock(settings_path):
            # critical section — read, modify, atomic-rename settings.json

    The sentinel file (`<path>.vibemon.lock`) lives next to the protected
    file. Lock semantics are blocking on both platforms.
    """

    def __init__(self, base_path):
        self.path = base_path + ".vibemon.lock"
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "w", encoding="utf-8")
        if IS_WINDOWS:
            import msvcrt
            # LK_LOCK = blocking exclusive on a single byte at offset 0.
            # Retries indefinitely until acquired.
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if IS_WINDOWS:
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
"""
merge_codex.py — Write VibeMon hooks into ~/.codex/hooks.json.

v29 made this integration real. The old code wrote flat {command,timeout}
entries into ~/.codex/settings.json — a file Codex CLI does not read.
Codex discovers hooks in ~/.codex/hooks.json (or [hooks] in config.toml),
with the nested Claude-style shape and a REQUIRED "type" field:

  {"hooks": {"EventName": [{"matcher"?, "hooks": [{"type": "command",
                                                   "command": …,
                                                   "timeout": …}]}]}}

Codex rejects unknown fields, so entries stay minimal (no "name" key).

TRUST GATE (important): Codex skips new/changed non-managed hooks until
the user reviews them with `/hooks` inside codex. There is NO honest way
to auto-approve — the trusted_hash registry in config.toml is Codex's
internal format and must never be written by us. The installer therefore
says "written — trust to enable", not "configured".

Event map (codex event → vibemon event), conservative per official docs:
  SessionStart                          → session_start
  SessionEnd                            → session_end
  UserPromptSubmit                      → prompt
  Stop                                  → stop
  PostToolUse (Edit|Write|apply_patch)  → activity
  PostToolUse (Bash|shell)              → bash

Uses an exclusive FileLock + tempfile.mkstemp + os.replace for safety
against concurrent install.sh / install.ps1 runs from multiple AI
coding sessions (multi-session invariant — see vibemon-app/CLAUDE.md).
"""

import json
import os
import sys
import tempfile

# When this file is concatenated with lock.py (via build.py's
# # %%EMBED:lock.py%% marker inside install.sh), FileLock is already
# in module scope and this import is a harmless no-op fallback.
try:
    from lock import FileLock
except ImportError:
    pass


DEFAULT_NOTIFY_PREFIX = "bash ~/.vibemon/notify.sh"

# Seconds (Codex default is 600; SessionEnd defaults to 1 — set explicitly).
CODEX_TIMEOUT_S = 10


def _cmd(notify_prefix, event):
    return {
        "type": "command",
        "command": "%s %s codex_cli" % (notify_prefix, event),
        "timeout": CODEX_TIMEOUT_S,
    }


def _build_hooks(notify_prefix):
    return {
        "SessionStart": [
            {"hooks": [_cmd(notify_prefix, "session_start")]},
        ],
        "SessionEnd": [
            {"hooks": [_cmd(notify_prefix, "session_end")]},
        ],
        "UserPromptSubmit": [
            {"hooks": [_cmd(notify_prefix, "prompt")]},
        ],
        "Stop": [
            {"hooks": [_cmd(notify_prefix, "stop")]},
        ],
        "PostToolUse": [
            # Matchers are regexes over the tool name (docs list Edit /
            # Write / apply_patch / Bash as Codex tool names; "shell" is
            # included defensively for older builds — an unmatched
            # alternative is harmless).
            {"matcher": "Edit|Write|apply_patch", "hooks": [_cmd(notify_prefix, "activity")]},
            {"matcher": "Bash|shell", "hooks": [_cmd(notify_prefix, "bash")]},
        ],
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def _is_legacy_vibemon_entry(entry):
    """v28 wrote FLAT entries ({command, timeout}, no nested hooks list)."""
    return isinstance(entry, dict) and "vibemon" in entry.get("command", "")


def _scrub_legacy_settings(hooks_path):
    """Remove the dead v28 vibemon entries from ~/.codex/settings.json.

    Codex never read that file, but leaving our stale hooks in it invites
    confusion (and would be picked up if Codex ever starts reading it).
    Only strips vibemon entries; never creates the file, never touches
    anything else in it, and skips silently when unparseable.
    """
    legacy_path = os.path.join(os.path.dirname(hooks_path) or ".", "settings.json")
    if os.path.abspath(legacy_path) == os.path.abspath(hooks_path):
        return  # caller pointed merge() at settings.json itself — nothing legacy
    if not os.path.exists(legacy_path):
        return
    try:
        with FileLock(legacy_path):
            with open(legacy_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if not isinstance(settings, dict):
                return
            hooks = settings.get("hooks")
            if not isinstance(hooks, dict):
                return
            changed = False
            for event_name in list(hooks.keys()):
                entries = hooks.get(event_name)
                if not isinstance(entries, list):
                    continue
                kept = [
                    e for e in entries
                    if not (_is_legacy_vibemon_entry(e)
                            or (isinstance(e, dict) and _is_vibemon_entry(e)))
                ]
                if len(kept) != len(entries):
                    changed = True
                    if kept:
                        hooks[event_name] = kept
                    else:
                        del hooks[event_name]
            if not changed:
                return
            if not hooks:
                settings.pop("hooks", None)
            dir_path = os.path.dirname(legacy_path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".settings.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(settings, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                os.replace(tmp_path, legacy_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
    except (json.JSONDecodeError, OSError):
        # Not ours / not parseable — leave it alone.
        return


def merge(hooks_path, notify_prefix=None, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS if notify_prefix is None else _build_hooks(notify_prefix)

    os.makedirs(os.path.dirname(hooks_path) or ".", exist_ok=True)
    with FileLock(hooks_path):
        config = {}
        if os.path.exists(hooks_path):
            with open(hooks_path, "r", encoding="utf-8") as f:
                try:
                    config = json.load(f)
                except json.JSONDecodeError:
                    # Don't clobber a file we don't own — skip and say so.
                    print(
                        f"  ⚠ Could not parse {hooks_path}; skipping Codex CLI hook registration.",
                        file=sys.stderr,
                    )
                    return False

        if not isinstance(config, dict):
            print(
                f"  ⚠ {hooks_path} is not a JSON object; skipping Codex CLI hook registration.",
                file=sys.stderr,
            )
            return False

        hooks = config.setdefault("hooks", {})

        # Sweep vibemon entries from EVERY event first, so renamed/removed
        # registrations don't linger across upgrades.
        for event_name in list(hooks.keys()):
            entries = hooks.get(event_name)
            if not isinstance(entries, list):
                continue
            kept = [
                e for e in entries
                if not (isinstance(e, dict)
                        and (_is_vibemon_entry(e) or _is_legacy_vibemon_entry(e)))
            ]
            if kept:
                hooks[event_name] = kept
            else:
                del hooks[event_name]

        for event_name, new_entries in hooks_def.items():
            existing = hooks.get(event_name, [])
            existing.extend(new_entries)
            hooks[event_name] = existing
        config["hooks"] = hooks

        dir_path = os.path.dirname(hooks_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".hooks.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, hooks_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # Outside the hooks.json lock (separate file, separate sentinel).
    _scrub_legacy_settings(hooks_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_codex.py <hooks_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
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
"""
lock.py — Cross-platform exclusive file lock.

Wraps fcntl.flock (Unix) and msvcrt.locking (Windows) behind a single
context manager so merge_*.py can stay platform-agnostic. Used by the
settings.json merge code path to prevent corruption under concurrent
install.sh / install.ps1 runs from multiple AI coding sessions.

See vibemon-app/CLAUDE.md "Multi-Session Concurrency Invariants" #3.

Stdlib only.
"""

import os


IS_WINDOWS = os.name == "nt"


class FileLock:
    """Blocking exclusive lock on a sentinel file.

    Usage:
        with FileLock(settings_path):
            # critical section — read, modify, atomic-rename settings.json

    The sentinel file (`<path>.vibemon.lock`) lives next to the protected
    file. Lock semantics are blocking on both platforms.
    """

    def __init__(self, base_path):
        self.path = base_path + ".vibemon.lock"
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "w", encoding="utf-8")
        if IS_WINDOWS:
            import msvcrt
            # LK_LOCK = blocking exclusive on a single byte at offset 0.
            # Retries indefinitely until acquired.
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if IS_WINDOWS:
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
"""Add the VibeMon HTTP MCP server to a Claude / Cursor / Gemini config JSON.

Claude Code (~/.claude.json), Cursor (~/.cursor/mcp.json) and Gemini CLI
(~/.gemini/settings.json) all keep a top-level `mcpServers` object whose keys
are MCP server names. We merge our entry idempotently:

  {
    "mcpServers": {
      "vibemon": {
        "type":    "http",                          # Claude Code only — see below
        "url":     "https://vibemon.dev/api/mcp",
        "headers": { "Authorization": "Bearer vbm_xxx" }
      },
      ...
    }
  }

Usage (inside install.sh): `python3 - <target.json> <api_key> [claude|cursor|gemini]`

Shape per target:
  - claude: {"type": "http", "url", "headers"} — exactly what
    `claude mcp add --transport http` writes to user scope.
  - cursor: {"url", "headers"} — Cursor's docs define remote servers by `url`
    alone (its `type` enum is for stdio), so we omit the field rather than
    feed an undocumented value to a possibly strict parser.
  - gemini: {"httpUrl", "headers"} — Gemini CLI's docs use `httpUrl` for the
    streamable-HTTP transport (`url` there means SSE), headers as an object.

(Codex CLI is intentionally absent: its MCP registry is `[mcp_servers]` in
~/.codex/config.toml — TOML, which the stdlib can read but not write, in
Codex's PRIMARY config file holding trust hashes and project state. A
hand-rolled TOML writer corrupting that file is a worse outcome than asking
for one manual step, so the installer prints a manual hint instead.)

The script is idempotent — re-running with the same args is a no-op (apart from
updating the Authorization header when the API key rotates). The targets are
NOT vibemon-owned files (~/.claude.json holds all of Claude Code's user state),
so on any parse doubt we skip registration and leave the file untouched —
never "treat as empty and overwrite" like the hook merges do for their own
settings files.
"""

import json
import os
import sys
import tempfile

# When concatenated with lock.py (via build.py's # %%EMBED:lock.py%% marker
# inside install.sh) FileLock is already in module scope, so this import raises
# ImportError and the `pass` keeps the embedded class. When imported as a module
# (tests / install.py) src/ is on sys.path so the import succeeds. Mirrors
# merge_claude/cursor/codex: a missing lock must fail loudly (NameError), never
# silently degrade to a no-op lock that defeats the multi-session write invariant.
try:
    from lock import FileLock  # type: ignore
except ImportError:
    pass


MCP_URL = "https://vibemon.dev/api/mcp"

# Per-target entry shapes — see module docstring for the doc citations.
KINDS = ("claude", "cursor", "gemini")


def _desired_entry(api_key: str, kind: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if kind == "gemini":
        return {"httpUrl": MCP_URL, "headers": headers}
    if kind == "cursor":
        return {"url": MCP_URL, "headers": headers}
    return {"type": "http", "url": MCP_URL, "headers": headers}


def merge(target_path: str, api_key: str, kind: str = "claude") -> bool:
    """Insert/update the vibemon entry. Returns True if the file changed.

    kind selects the entry shape: "claude" (type+url+headers),
    "cursor" (url+headers), "gemini" (httpUrl+headers).
    """
    target_dir = os.path.dirname(target_path) or "."
    os.makedirs(target_dir, exist_ok=True)

    # FileLock appends ".vibemon.lock" itself — pass the protected path,
    # same convention as the merge_{claude,gemini,cursor,codex} callers.
    with FileLock(target_path):
        # Read existing
        data = {}
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                    data = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, OSError):
                # Don't corrupt invalid JSON — surface and exit
                print(f"  ⚠ Could not parse {target_path}; skipping MCP registration.", file=sys.stderr)
                return False

        if not isinstance(data, dict):
            print(f"  ⚠ {target_path} is not a JSON object; skipping MCP registration.", file=sys.stderr)
            return False

        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            print(f"  ⚠ mcpServers in {target_path} is not an object; skipping MCP registration.", file=sys.stderr)
            return False

        existing = servers.get("vibemon")
        desired = _desired_entry(api_key, kind)

        if existing == desired:
            return False  # already up to date

        servers["vibemon"] = desired

        # Atomic write — temp file in same dir then os.replace
        fd, tmp = tempfile.mkstemp(dir=target_dir, prefix=".vibemon.", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, target_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    return True


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: merge_mcp.py <target_path> <api_key> [claude|cursor|gemini]", file=sys.stderr)
        return 2
    target_path = sys.argv[1]
    api_key = sys.argv[2]
    kind = sys.argv[3] if len(sys.argv) > 3 else "claude"
    if kind not in KINDS:
        print(f"  ⚠ Unknown MCP target kind {kind!r}; skipping MCP registration.", file=sys.stderr)
        return 0
    if not api_key.startswith("vbm_"):
        print("  ⚠ API key does not start with 'vbm_'; skipping MCP registration.", file=sys.stderr)
        return 0
    changed = merge(target_path, api_key, kind=kind)
    if changed:
        print(f"  ✓ MCP server 'vibemon' registered in {target_path}")
    else:
        print(f"  · MCP server already up-to-date in {target_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYMERGE_CLAUDE_MCP
fi

# Cursor gets the docs-exact remote-server shape (url + headers, no "type").
CURSOR_MCP_CONFIG="$HOME/.cursor/mcp.json"
if [ "$HAS_CURSOR" = true ]; then
  python3 - "$CURSOR_MCP_CONFIG" "$API_KEY" cursor << 'PYMERGE_CURSOR_MCP'
"""
lock.py — Cross-platform exclusive file lock.

Wraps fcntl.flock (Unix) and msvcrt.locking (Windows) behind a single
context manager so merge_*.py can stay platform-agnostic. Used by the
settings.json merge code path to prevent corruption under concurrent
install.sh / install.ps1 runs from multiple AI coding sessions.

See vibemon-app/CLAUDE.md "Multi-Session Concurrency Invariants" #3.

Stdlib only.
"""

import os


IS_WINDOWS = os.name == "nt"


class FileLock:
    """Blocking exclusive lock on a sentinel file.

    Usage:
        with FileLock(settings_path):
            # critical section — read, modify, atomic-rename settings.json

    The sentinel file (`<path>.vibemon.lock`) lives next to the protected
    file. Lock semantics are blocking on both platforms.
    """

    def __init__(self, base_path):
        self.path = base_path + ".vibemon.lock"
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "w", encoding="utf-8")
        if IS_WINDOWS:
            import msvcrt
            # LK_LOCK = blocking exclusive on a single byte at offset 0.
            # Retries indefinitely until acquired.
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if IS_WINDOWS:
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
"""Add the VibeMon HTTP MCP server to a Claude / Cursor / Gemini config JSON.

Claude Code (~/.claude.json), Cursor (~/.cursor/mcp.json) and Gemini CLI
(~/.gemini/settings.json) all keep a top-level `mcpServers` object whose keys
are MCP server names. We merge our entry idempotently:

  {
    "mcpServers": {
      "vibemon": {
        "type":    "http",                          # Claude Code only — see below
        "url":     "https://vibemon.dev/api/mcp",
        "headers": { "Authorization": "Bearer vbm_xxx" }
      },
      ...
    }
  }

Usage (inside install.sh): `python3 - <target.json> <api_key> [claude|cursor|gemini]`

Shape per target:
  - claude: {"type": "http", "url", "headers"} — exactly what
    `claude mcp add --transport http` writes to user scope.
  - cursor: {"url", "headers"} — Cursor's docs define remote servers by `url`
    alone (its `type` enum is for stdio), so we omit the field rather than
    feed an undocumented value to a possibly strict parser.
  - gemini: {"httpUrl", "headers"} — Gemini CLI's docs use `httpUrl` for the
    streamable-HTTP transport (`url` there means SSE), headers as an object.

(Codex CLI is intentionally absent: its MCP registry is `[mcp_servers]` in
~/.codex/config.toml — TOML, which the stdlib can read but not write, in
Codex's PRIMARY config file holding trust hashes and project state. A
hand-rolled TOML writer corrupting that file is a worse outcome than asking
for one manual step, so the installer prints a manual hint instead.)

The script is idempotent — re-running with the same args is a no-op (apart from
updating the Authorization header when the API key rotates). The targets are
NOT vibemon-owned files (~/.claude.json holds all of Claude Code's user state),
so on any parse doubt we skip registration and leave the file untouched —
never "treat as empty and overwrite" like the hook merges do for their own
settings files.
"""

import json
import os
import sys
import tempfile

# When concatenated with lock.py (via build.py's # %%EMBED:lock.py%% marker
# inside install.sh) FileLock is already in module scope, so this import raises
# ImportError and the `pass` keeps the embedded class. When imported as a module
# (tests / install.py) src/ is on sys.path so the import succeeds. Mirrors
# merge_claude/cursor/codex: a missing lock must fail loudly (NameError), never
# silently degrade to a no-op lock that defeats the multi-session write invariant.
try:
    from lock import FileLock  # type: ignore
except ImportError:
    pass


MCP_URL = "https://vibemon.dev/api/mcp"

# Per-target entry shapes — see module docstring for the doc citations.
KINDS = ("claude", "cursor", "gemini")


def _desired_entry(api_key: str, kind: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if kind == "gemini":
        return {"httpUrl": MCP_URL, "headers": headers}
    if kind == "cursor":
        return {"url": MCP_URL, "headers": headers}
    return {"type": "http", "url": MCP_URL, "headers": headers}


def merge(target_path: str, api_key: str, kind: str = "claude") -> bool:
    """Insert/update the vibemon entry. Returns True if the file changed.

    kind selects the entry shape: "claude" (type+url+headers),
    "cursor" (url+headers), "gemini" (httpUrl+headers).
    """
    target_dir = os.path.dirname(target_path) or "."
    os.makedirs(target_dir, exist_ok=True)

    # FileLock appends ".vibemon.lock" itself — pass the protected path,
    # same convention as the merge_{claude,gemini,cursor,codex} callers.
    with FileLock(target_path):
        # Read existing
        data = {}
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                    data = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, OSError):
                # Don't corrupt invalid JSON — surface and exit
                print(f"  ⚠ Could not parse {target_path}; skipping MCP registration.", file=sys.stderr)
                return False

        if not isinstance(data, dict):
            print(f"  ⚠ {target_path} is not a JSON object; skipping MCP registration.", file=sys.stderr)
            return False

        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            print(f"  ⚠ mcpServers in {target_path} is not an object; skipping MCP registration.", file=sys.stderr)
            return False

        existing = servers.get("vibemon")
        desired = _desired_entry(api_key, kind)

        if existing == desired:
            return False  # already up to date

        servers["vibemon"] = desired

        # Atomic write — temp file in same dir then os.replace
        fd, tmp = tempfile.mkstemp(dir=target_dir, prefix=".vibemon.", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, target_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    return True


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: merge_mcp.py <target_path> <api_key> [claude|cursor|gemini]", file=sys.stderr)
        return 2
    target_path = sys.argv[1]
    api_key = sys.argv[2]
    kind = sys.argv[3] if len(sys.argv) > 3 else "claude"
    if kind not in KINDS:
        print(f"  ⚠ Unknown MCP target kind {kind!r}; skipping MCP registration.", file=sys.stderr)
        return 0
    if not api_key.startswith("vbm_"):
        print("  ⚠ API key does not start with 'vbm_'; skipping MCP registration.", file=sys.stderr)
        return 0
    changed = merge(target_path, api_key, kind=kind)
    if changed:
        print(f"  ✓ MCP server 'vibemon' registered in {target_path}")
    else:
        print(f"  · MCP server already up-to-date in {target_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYMERGE_CURSOR_MCP
fi

# Gemini CLI: streamable-HTTP servers use `httpUrl` (its `url` means SSE).
# Same settings.json the hook merge (5b) already lock-writes.
if [ "$HAS_GEMINI" = true ]; then
  python3 - "$GEMINI_SETTINGS" "$API_KEY" gemini << 'PYMERGE_GEMINI_MCP'
"""
lock.py — Cross-platform exclusive file lock.

Wraps fcntl.flock (Unix) and msvcrt.locking (Windows) behind a single
context manager so merge_*.py can stay platform-agnostic. Used by the
settings.json merge code path to prevent corruption under concurrent
install.sh / install.ps1 runs from multiple AI coding sessions.

See vibemon-app/CLAUDE.md "Multi-Session Concurrency Invariants" #3.

Stdlib only.
"""

import os


IS_WINDOWS = os.name == "nt"


class FileLock:
    """Blocking exclusive lock on a sentinel file.

    Usage:
        with FileLock(settings_path):
            # critical section — read, modify, atomic-rename settings.json

    The sentinel file (`<path>.vibemon.lock`) lives next to the protected
    file. Lock semantics are blocking on both platforms.
    """

    def __init__(self, base_path):
        self.path = base_path + ".vibemon.lock"
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.fh = open(self.path, "w", encoding="utf-8")
        if IS_WINDOWS:
            import msvcrt
            # LK_LOCK = blocking exclusive on a single byte at offset 0.
            # Retries indefinitely until acquired.
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if IS_WINDOWS:
                import msvcrt
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None
"""Add the VibeMon HTTP MCP server to a Claude / Cursor / Gemini config JSON.

Claude Code (~/.claude.json), Cursor (~/.cursor/mcp.json) and Gemini CLI
(~/.gemini/settings.json) all keep a top-level `mcpServers` object whose keys
are MCP server names. We merge our entry idempotently:

  {
    "mcpServers": {
      "vibemon": {
        "type":    "http",                          # Claude Code only — see below
        "url":     "https://vibemon.dev/api/mcp",
        "headers": { "Authorization": "Bearer vbm_xxx" }
      },
      ...
    }
  }

Usage (inside install.sh): `python3 - <target.json> <api_key> [claude|cursor|gemini]`

Shape per target:
  - claude: {"type": "http", "url", "headers"} — exactly what
    `claude mcp add --transport http` writes to user scope.
  - cursor: {"url", "headers"} — Cursor's docs define remote servers by `url`
    alone (its `type` enum is for stdio), so we omit the field rather than
    feed an undocumented value to a possibly strict parser.
  - gemini: {"httpUrl", "headers"} — Gemini CLI's docs use `httpUrl` for the
    streamable-HTTP transport (`url` there means SSE), headers as an object.

(Codex CLI is intentionally absent: its MCP registry is `[mcp_servers]` in
~/.codex/config.toml — TOML, which the stdlib can read but not write, in
Codex's PRIMARY config file holding trust hashes and project state. A
hand-rolled TOML writer corrupting that file is a worse outcome than asking
for one manual step, so the installer prints a manual hint instead.)

The script is idempotent — re-running with the same args is a no-op (apart from
updating the Authorization header when the API key rotates). The targets are
NOT vibemon-owned files (~/.claude.json holds all of Claude Code's user state),
so on any parse doubt we skip registration and leave the file untouched —
never "treat as empty and overwrite" like the hook merges do for their own
settings files.
"""

import json
import os
import sys
import tempfile

# When concatenated with lock.py (via build.py's # %%EMBED:lock.py%% marker
# inside install.sh) FileLock is already in module scope, so this import raises
# ImportError and the `pass` keeps the embedded class. When imported as a module
# (tests / install.py) src/ is on sys.path so the import succeeds. Mirrors
# merge_claude/cursor/codex: a missing lock must fail loudly (NameError), never
# silently degrade to a no-op lock that defeats the multi-session write invariant.
try:
    from lock import FileLock  # type: ignore
except ImportError:
    pass


MCP_URL = "https://vibemon.dev/api/mcp"

# Per-target entry shapes — see module docstring for the doc citations.
KINDS = ("claude", "cursor", "gemini")


def _desired_entry(api_key: str, kind: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if kind == "gemini":
        return {"httpUrl": MCP_URL, "headers": headers}
    if kind == "cursor":
        return {"url": MCP_URL, "headers": headers}
    return {"type": "http", "url": MCP_URL, "headers": headers}


def merge(target_path: str, api_key: str, kind: str = "claude") -> bool:
    """Insert/update the vibemon entry. Returns True if the file changed.

    kind selects the entry shape: "claude" (type+url+headers),
    "cursor" (url+headers), "gemini" (httpUrl+headers).
    """
    target_dir = os.path.dirname(target_path) or "."
    os.makedirs(target_dir, exist_ok=True)

    # FileLock appends ".vibemon.lock" itself — pass the protected path,
    # same convention as the merge_{claude,gemini,cursor,codex} callers.
    with FileLock(target_path):
        # Read existing
        data = {}
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                    data = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, OSError):
                # Don't corrupt invalid JSON — surface and exit
                print(f"  ⚠ Could not parse {target_path}; skipping MCP registration.", file=sys.stderr)
                return False

        if not isinstance(data, dict):
            print(f"  ⚠ {target_path} is not a JSON object; skipping MCP registration.", file=sys.stderr)
            return False

        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            print(f"  ⚠ mcpServers in {target_path} is not an object; skipping MCP registration.", file=sys.stderr)
            return False

        existing = servers.get("vibemon")
        desired = _desired_entry(api_key, kind)

        if existing == desired:
            return False  # already up to date

        servers["vibemon"] = desired

        # Atomic write — temp file in same dir then os.replace
        fd, tmp = tempfile.mkstemp(dir=target_dir, prefix=".vibemon.", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, target_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    return True


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: merge_mcp.py <target_path> <api_key> [claude|cursor|gemini]", file=sys.stderr)
        return 2
    target_path = sys.argv[1]
    api_key = sys.argv[2]
    kind = sys.argv[3] if len(sys.argv) > 3 else "claude"
    if kind not in KINDS:
        print(f"  ⚠ Unknown MCP target kind {kind!r}; skipping MCP registration.", file=sys.stderr)
        return 0
    if not api_key.startswith("vbm_"):
        print("  ⚠ API key does not start with 'vbm_'; skipping MCP registration.", file=sys.stderr)
        return 0
    changed = merge(target_path, api_key, kind=kind)
    if changed:
        print(f"  ✓ MCP server 'vibemon' registered in {target_path}")
    else:
        print(f"  · MCP server already up-to-date in {target_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
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
