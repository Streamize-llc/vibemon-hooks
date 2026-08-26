"""Static checks — bash -n on built install.sh + py_compile on every
embedded Python heredoc (after stripping the surrounding bash).

Catches the most common breakage: someone hand-edits src/install.sh
in a way that produces invalid bash or Python after the build step.
"""

import os
import re
import subprocess
import sys
import tempfile

import pytest


HEREDOCS = [
    ("NOTIFY_SCRIPT",       "shell"),  # bash heredoc body — validate as bash
    ("PYMERGE_CLAUDE",      "python"),
    ("PYMERGE_GEMINI",      "python"),
    ("PYMERGE_CURSOR",      "python"),
    ("PYMERGE_CODEX",       "python"),
    ("PYMERGE_CLAUDE_MCP",  "python"),
    ("PYMERGE_CURSOR_MCP",  "python"),
    ("PYMERGE_GEMINI_MCP",  "python"),
]


def _extract_heredoc(src, marker):
    # trailing shell after the heredoc start (e.g. `|| true`) is legal syntax
    pat = rf"<< '{marker}'[^\n]*\n(.*?)\n{marker}"
    m = re.search(pat, src, re.DOTALL)
    if not m:
        return None
    return m.group(1)


def _bash_check(content):
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as tf:
        tf.write(content.replace("__SUPABASE_URL__", "https://x.supabase.co"))
        path = tf.name
    try:
        r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        return (r.returncode == 0, r.stderr)
    finally:
        os.unlink(path)


def _py_check(content):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(content)
        path = tf.name
    try:
        r = subprocess.run(
            [sys.executable, "-c", f"import py_compile; py_compile.compile({path!r}, doraise=True)"],
            capture_output=True, text=True,
        )
        return (r.returncode == 0, r.stderr)
    finally:
        os.unlink(path)


def test_dist_install_sh_exists(dist_dir):
    p = os.path.join(dist_dir, "install.sh")
    assert os.path.exists(p), (
        "dist/install.sh missing. Run `python3 scripts/build.py` first."
    )


@pytest.mark.skipif(
    os.name == "nt",
    reason="dist/install.sh is a Unix artifact; windows-latest 'bash' resolves to the WSL stub",
)
def test_dist_install_sh_bash_syntax(dist_dir):
    p = os.path.join(dist_dir, "install.sh")
    with open(p, encoding="utf-8") as f:
        src = f.read()
    src = src.replace("__SUPABASE_URL__", "https://x.supabase.co")
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as tf:
        tf.write(src); path = tf.name
    try:
        r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        assert r.returncode == 0, f"dist/install.sh bash -n failed:\n{r.stderr}"
    finally:
        os.unlink(path)


@pytest.mark.parametrize("marker,kind", HEREDOCS)
def test_embedded_heredoc_syntax(marker, kind, dist_dir):
    if kind == "shell" and os.name == "nt":
        pytest.skip("bash heredoc check requires real bash (skipped on Windows)")
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    body = _extract_heredoc(src, marker)
    assert body is not None, f"heredoc {marker} not found in dist/install.sh"

    if kind == "shell":
        ok, err = _bash_check(body)
        assert ok, f"{marker} (bash) syntax error:\n{err}"

        # The shell heredoc itself contains a python heredoc (VIBEMON_PY).
        py_body = _extract_heredoc(body, "VIBEMON_PY")
        assert py_body, "VIBEMON_PY missing inside NOTIFY_SCRIPT"
        ok, err = _py_check(py_body)
        assert ok, f"VIBEMON_PY (python inside notify.sh) syntax error:\n{err}"
    elif kind == "python":
        ok, err = _py_check(body)
        assert ok, f"{marker} (python) syntax error:\n{err}"


# (marker, extra_args) — each PYMERGE_* heredoc is `python3 - <target> [extra…]`,
# mirroring the exact argv install.sh passes (MCP heredocs get the api key, and
# the cursor MCP heredoc additionally gets the "cursor" kind selector).
# Syntax checks (py_compile) above cannot catch a runtime NameError such as a
# missing `# %%EMBED:lock.py%%` (FileLock undefined). This actually EXECUTES
# each heredoc body against a temp config and asserts a clean exit + written file.
EXEC_HEREDOCS = [
    ("PYMERGE_CLAUDE", []),
    ("PYMERGE_GEMINI", []),
    ("PYMERGE_CURSOR", []),
    ("PYMERGE_CODEX", []),
    ("PYMERGE_CLAUDE_MCP", ["vbm_testkey"]),
    ("PYMERGE_CURSOR_MCP", ["vbm_testkey", "cursor"]),
    ("PYMERGE_GEMINI_MCP", ["vbm_testkey", "gemini"]),
]


@pytest.mark.parametrize("marker,extra_args", EXEC_HEREDOCS)
def test_embedded_heredoc_executes(marker, extra_args, dist_dir, tmp_path):
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    body = _extract_heredoc(src, marker)
    assert body is not None, f"heredoc {marker} not found in dist/install.sh"

    target = str(tmp_path / "config.json")
    args = [target] + extra_args
    # utf-8 must be pinned at BOTH ends on Windows (same lesson as v17's
    # "encoding on every open()", applied to subprocess):
    #   - encoding=: text=True alone encodes our stdin with the locale codec
    #     (cp1252), so the em dashes in the embedded docstrings become \x97
    #     and Python rejects the stdin script as non-UTF-8 source.
    #   - PYTHONIOENCODING: the child's stdout is a cp1252 PIPE in CI, so
    #     merge_mcp.main()'s "✓" print dies with UnicodeEncodeError. The
    #     real heredocs only ever run under install.sh (Unix, utf-8 or
    #     PEP 538-coerced locales; Windows installs go through install.py,
    #     which never executes these __main__ blocks) — so the harness must
    #     reproduce that utf-8 stdio, not the runner's pipe codec.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, "-", *args],
        input=body, capture_output=True, text=True, encoding="utf-8",
        env=env,
    )
    assert r.returncode == 0, (
        f"{marker} crashed at runtime (e.g. missing lock.py embed → "
        f"NameError: FileLock):\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert os.path.exists(target), f"{marker} ran but wrote no config file"


def test_piped_install_survives_test_probe(dist_dir):
    """`curl | sh` regression (v24): the section-6 notify.sh test probe
    inherits the pipe as stdin; without an explicit </dev/null redirect,
    notify.sh's `cat > "$STDIN_FILE"` slurps the remainder of install.sh
    and the script silently ends mid-run."""
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    probe_lines = [
        l for l in src.splitlines()
        if '"$VIBEMON_DIR/notify.sh" test' in l and not l.lstrip().startswith("#")
    ]
    assert probe_lines, "test-probe invocation not found in dist/install.sh"
    for l in probe_lines:
        assert "</dev/null" in l, f"test probe must pin stdin: {l!r}"


def test_build_is_reproducible(root_dir):
    """Re-running scripts/build.py must produce byte-identical dist/install.sh."""
    r = subprocess.run(
        [sys.executable, os.path.join(root_dir, "scripts", "build.py"), "--check"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        f"dist/install.sh is stale or non-reproducible.\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )
def test_agent_gate_snapshot_precedes_all_mkdirs(dist_dir):
    """v29 gate-order fix: the HAS_* agent-presence snapshot must be taken
    BEFORE any merge section's `mkdir -p` creates the very directories the
    gates test. v28's inline `[ -d "$HOME/.claude" ]` gate ran after 5a's
    mkdir had created ~/.claude, so it was always true and Claude-less
    machines got MCP registrations."""
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    first_mkdir = src.index('mkdir -p "$(dirname ')
    for var in ("HAS_CLAUDE=", "HAS_GEMINI=", "HAS_CURSOR=", "HAS_CODEX="):
        assert var in src, f"{var} snapshot missing from dist/install.sh"
        assert src.index(var) < first_mkdir, (
            f"{var} snapshot must be assigned before the first agent mkdir -p"
        )
    # The MCP gates must consume the snapshot, not re-test the dirs inline.
    assert '[ "$HAS_CLAUDE" = true ]' in src
    assert '[ "$HAS_GEMINI" = true ]' in src
    assert '[ -d "$HOME/.claude" ] || command -v claude' not in src


def test_per_agent_install_probes(dist_dir):
    """v29: every configured agent gets a `notify.sh test <agent>` probe so
    script_install_status learns all four agents (previously the probe ran
    with no agent argument and only claude_code was ever recorded)."""
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    lines = [l for l in src.splitlines() if '"$VIBEMON_DIR/notify.sh" test' in l]
    # Strict probe names its agent explicitly …
    assert any("test claude_code" in l for l in lines), lines
    # … and no probe may fall back to the agent-less form again.
    for l in lines:
        after = l.split('notify.sh" test', 1)[1]
        assert after.strip() and not after.strip().startswith("<"), (
            f"agent-less test probe found: {l!r}"
        )
    # Best-effort per-agent loop covers the other three.
    assert "gemini_cli" in src.split("PROBE_AGENTS=")[1].splitlines()[0]
    assert 'PROBE_AGENTS="$PROBE_AGENTS cursor"' in src
    assert 'PROBE_AGENTS="$PROBE_AGENTS codex_cli"' in src


def test_codex_target_is_hooks_json_in_install_sh(dist_dir):
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    assert 'CODEX_HOOKS="$HOME/.codex/hooks.json"' in src
    assert '$HOME/.codex/settings.json' not in src
    # Honest output — Codex hooks are inert until trusted via /hooks.
    assert "Codex requires approval" in src
