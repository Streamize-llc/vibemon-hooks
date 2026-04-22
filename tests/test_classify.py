"""Unit tests for classify_bash. The single most important categorical
function — every signal-driven narrative depends on this being correct."""

from classify import classify_bash


def test_empty():
    assert classify_bash("") == ""
    assert classify_bash("   ") == ""
    assert classify_bash(None) == ""


def test_git_subcommands():
    assert classify_bash("git commit -m 'x'") == "git.commit"
    assert classify_bash("git push origin main") == "git.push"
    assert classify_bash("git pull --rebase") == "git.sync"
    assert classify_bash("git fetch") == "git.sync"
    assert classify_bash("git log --oneline") == "git.read"
    assert classify_bash("git diff HEAD") == "git.read"
    assert classify_bash("git status") == "git.read"
    assert classify_bash("git rebase -i HEAD~3") == "git.rewrite"
    assert classify_bash("git merge feature/x") == "git.rewrite"
    assert classify_bash("git checkout main") == "git.branch"
    assert classify_bash("git switch -c new-branch") == "git.branch"
    assert classify_bash("git stash pop") == "git.branch"
    assert classify_bash("git unknown") == "git.other"
    assert classify_bash("git") == "git.other"


def test_gh():
    assert classify_bash("gh pr create --fill") == "github.pr_write"
    assert classify_bash("gh pr merge 123") == "github.pr_write"
    assert classify_bash("gh issue list") == "github.other"
    assert classify_bash("gh") == "github.other"


def test_npm_family():
    # Direct subcommand
    assert classify_bash("npm test") == "pkg.test"
    assert classify_bash("npm t") == "pkg.test"
    assert classify_bash("pnpm install") == "pkg.install"
    assert classify_bash("yarn add react") == "pkg.install"
    assert classify_bash("bun build") == "pkg.build"
    # Via `run`
    assert classify_bash("npm run test") == "pkg.test"
    assert classify_bash("npm run build") == "pkg.build"
    assert classify_bash("npm run dev") == "pkg.run"
    assert classify_bash("yarn run lint") == "pkg.lint"
    # Unknown subcommand falls back
    assert classify_bash("npm whatever") == "pkg.other"


def test_test_runners():
    assert classify_bash("pytest tests/") == "test.run"
    assert classify_bash("jest --watch") == "test.run"
    assert classify_bash("vitest") == "test.run"
    assert classify_bash("go test ./...") == "test.run"
    assert classify_bash("cargo test") == "test.run"
    # 'go test' specifically; 'go run' should not match
    assert classify_bash("go run main.go") == "runtime"


def test_lint_and_build():
    assert classify_bash("eslint src/") == "lint.run"
    assert classify_bash("prettier --write .") == "lint.run"
    assert classify_bash("ruff check .") == "lint.run"
    assert classify_bash("mypy --strict .") == "lint.run"


def test_infra():
    assert classify_bash("docker build .") == "infra.docker"
    assert classify_bash("kubectl get pods") == "infra.k8s"
    assert classify_bash("terraform apply") == "infra.iac"


def test_fs_and_net():
    assert classify_bash("rm -rf /tmp/x") == "fs.mutate"
    assert classify_bash("ls -la") == "fs.read"
    assert classify_bash("grep -r foo .") == "fs.search"
    assert classify_bash("rg pattern") == "fs.search"
    assert classify_bash("mkdir new") == "fs.create"
    assert classify_bash("curl https://example.com") == "net.request"
    assert classify_bash("ssh user@host") == "net.transfer"
    assert classify_bash("rsync -av a b") == "net.transfer"


def test_db_and_deploy():
    assert classify_bash("psql -d mydb") == "db.client"
    assert classify_bash("supabase db push") == "db.client"
    assert classify_bash("vercel deploy") == "deploy"
    assert classify_bash("aws s3 sync") == "deploy"


def test_runtimes():
    assert classify_bash("python script.py") == "runtime"
    assert classify_bash("node index.js") == "runtime"
    assert classify_bash("deno run main.ts") == "runtime"


def test_mobile():
    assert classify_bash("expo start") == "mobile.expo"
    assert classify_bash("eas build --platform ios") == "mobile.build"
    assert classify_bash("xcodebuild -workspace x") == "mobile.build"


def test_unknown():
    assert classify_bash("frobnicate --turbo") == "unknown"
    assert classify_bash("./my-custom-script") == "unknown"


def test_never_returns_command_body():
    """Classifier MUST NOT return any portion of the command beyond category."""
    secret = "git commit -m 'CANARY_secret_value_xyz'"
    result = classify_bash(secret)
    assert "CANARY" not in result
    assert "secret" not in result
    assert result == "git.commit"
