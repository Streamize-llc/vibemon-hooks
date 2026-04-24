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
        return segs  # best-effort on malformed input (unclosed quote etc.)
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
