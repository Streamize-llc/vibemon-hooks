"""AttemptDB cleanup before the merges (v32).

From 2026-09-03 to 2026-11-08 vibemon.dev's one-liner installed AttemptDB.
Its hooks don't contain "vibemon", so the merges would leave them in place
and every event would be counted twice. Both installers therefore run
`attempt daemon stop` + `attempt uninstall` first, with stdin closed.

Every test here pins PATH to a temporary bin directory: a developer
machine may have the real AttemptDB CLI on PATH, and these tests must
never run it.
"""

import os
import re
import stat
import subprocess

import pytest

import install

FAKE_ATTEMPT = """#!/usr/bin/env bash
# Records each call and whatever arrived on stdin.
printf '%s\\n' "$*" >> "$FAKE_LOG"
cat >> "$FAKE_STDIN" 2>/dev/null || true
case "$1" in
  --version) echo "${FAKE_VERSION:-attempt 0.2.15}" ;;
  uninstall) exit "${FAKE_UNINSTALL_RC:-0}" ;;
esac
exit 0
"""

pytestmark = pytest.mark.skipif(os.name == "nt", reason="fake CLI is a bash script")


@pytest.fixture
def fake(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    stdin = tmp_path / "stdin.txt"
    env = {
        "HOME": str(home),
        "PATH": str(bindir) + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
        "FAKE_LOG": str(log),
        "FAKE_STDIN": str(stdin),
    }

    def install_fake(where=bindir, version=None, uninstall_rc=None):
        where.mkdir(parents=True, exist_ok=True)
        p = where / "attempt"
        p.write_text(FAKE_ATTEMPT, encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        if version is not None:
            env["FAKE_VERSION"] = version
        if uninstall_rc is not None:
            env["FAKE_UNINSTALL_RC"] = str(uninstall_rc)
        return p

    def calls():
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def stdin_seen():
        return stdin.read_text(encoding="utf-8") if stdin.exists() else ""

    return env, home, install_fake, calls, stdin_seen


# ─── install.sh section 4b, extracted from the BUILT installer ───────
def _section_4b(dist_dir):
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"(# ─── 4b\..*?)\n# ─── 5a\.", src, re.DOTALL)
    assert m, "section 4b not found in dist/install.sh"
    return m.group(1)


def _run_4b(dist_dir, env, rest_of_script="echo REST-OF-SCRIPT\n"):
    # Piped like `curl | bash`: the remainder of the script sits on stdin,
    # so a command that reads stdin would swallow it.
    script = "set -euo pipefail\n" + _section_4b(dist_dir) + "\necho AFTER-4B\n" + rest_of_script
    return subprocess.run(["bash"], input=script, capture_output=True, text=True, env=env, timeout=30)


def test_section_4b_runs_before_the_claude_merge(dist_dir):
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    uninstall = src.index('"$ATTEMPT_BIN" uninstall </dev/null')
    assert '"$ATTEMPT_BIN" daemon stop </dev/null' in src
    assert uninstall < src.index("<< 'PYMERGE_CLAUDE'")
    assert uninstall > src.index("<< 'NOTIFY_SCRIPT'")


def test_sh_uninstalls_attemptdb_with_stdin_closed(dist_dir, fake):
    env, home, install_fake, calls, stdin_seen = fake
    install_fake(home / ".local" / "bin")
    r = _run_4b(dist_dir, env)
    assert r.returncode == 0, r.stderr
    assert calls() == ["--version", "daemon stop", "uninstall"]
    assert stdin_seen() == "", "attempt read the piped installer from stdin"
    assert "Previous AttemptDB connector removed" in r.stdout
    assert "AFTER-4B" in r.stdout and "REST-OF-SCRIPT" in r.stdout


def test_sh_finds_attempt_on_path(dist_dir, fake):
    env, _, install_fake, calls, _ = fake
    install_fake()
    r = _run_4b(dist_dir, env)
    assert r.returncode == 0, r.stderr
    assert calls() == ["--version", "daemon stop", "uninstall"]


def test_sh_leaves_an_unrelated_attempt_alone(dist_dir, fake):
    env, _, install_fake, calls, _ = fake
    install_fake(version="attempt-runner 1.0")
    r = _run_4b(dist_dir, env)
    assert r.returncode == 0, r.stderr
    assert calls() == ["--version"]
    assert "AttemptDB" not in r.stdout


def test_sh_without_attemptdb_is_silent(dist_dir, fake):
    env = fake[0]
    r = _run_4b(dist_dir, env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "AFTER-4B\nREST-OF-SCRIPT"


def test_sh_failed_uninstall_warns_and_continues(dist_dir, fake):
    env, home, install_fake, calls, _ = fake
    install_fake(home / ".local" / "bin", uninstall_rc=3)
    r = _run_4b(dist_dir, env)
    assert r.returncode == 0, r.stderr
    assert "Could not fully remove" in r.stdout
    assert "AFTER-4B" in r.stdout


# ─── install.py twin ─────────────────────────────────────────────────
def _py_env(monkeypatch, env):
    for k in ("ATTEMPTDB_BIN_DIR", "LOCALAPPDATA", "FAKE_VERSION", "FAKE_UNINSTALL_RC"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_py_uninstalls_attemptdb(fake, monkeypatch, capsys):
    env, home, install_fake, calls, stdin_seen = fake
    install_fake(home / ".local" / "bin")
    _py_env(monkeypatch, env)
    install._remove_attemptdb()
    assert calls() == ["--version", "daemon stop", "uninstall"]
    assert stdin_seen() == ""
    assert "Previous AttemptDB connector removed" in capsys.readouterr().out


def test_py_honours_attemptdb_bin_dir(fake, tmp_path, monkeypatch):
    env, _, install_fake, calls, _ = fake
    custom = tmp_path / "custom"
    install_fake(custom)
    env["ATTEMPTDB_BIN_DIR"] = str(custom)
    _py_env(monkeypatch, env)
    assert install._find_attempt() == str(custom / "attempt")


def test_py_leaves_an_unrelated_attempt_alone(fake, monkeypatch, capsys):
    env, _, install_fake, calls, _ = fake
    install_fake(version="attempt-runner 1.0")
    _py_env(monkeypatch, env)
    install._remove_attemptdb()
    assert calls() == ["--version"]
    assert capsys.readouterr().out == ""


def test_py_failed_uninstall_warns(fake, monkeypatch, capsys):
    env, home, install_fake, _, _ = fake
    install_fake(home / ".local" / "bin", uninstall_rc=2)
    _py_env(monkeypatch, env)
    install._remove_attemptdb()
    assert "Could not fully remove" in capsys.readouterr().out


def test_py_main_runs_cleanup_before_the_merges():
    src = open(install.__file__, encoding="utf-8").read()
    main = src[src.index("def main("):]
    assert main.index("_remove_attemptdb()") < main.index("merge_claude(")
