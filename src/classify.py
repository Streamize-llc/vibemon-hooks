"""
classify.py — Bash command classifier for VibeMon hook events.

Pure function — takes a shell command string, returns a category like
"git.commit" or "pkg.test" or "unknown". Never returns the original
command body. Safe to embed in notify.sh and to import for unit tests.
"""


def classify_bash(cmd):
    """Classify a Bash command into a category by its first token.

    Returns a string like "git.commit", "pkg.test", "fs.read", or
    "unknown" if no rule matched. Returns "" for empty input.
    """
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
