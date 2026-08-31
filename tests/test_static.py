"""Static checks — bash -n on built install.sh + py_compile on every
embedded Python heredoc (after stripping the surrounding bash).

Catches the most common breakage: someone hand-edits src/install.sh
in a way that produces invalid bash or Python after the build step.
"""

import json
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


# ─── v30: the env prefix must actually reach python3 ────────────────────
# v28 put an explanatory comment between the backslash-continued VIBEMON_*
# env prefix and the `python3` line that consumes it. That is valid bash —
# `bash -n` accepted it and test_envelope_parity sets VIBEMON_* itself, so
# nothing here noticed — but a comment ENDS the logical line: the
# assignments degraded to plain shell variables, python3 inherited none of
# them, and every envelope fell back to the empty payload. Production
# collection was dead from 2026-08-26 (v28) until v30.

def _continuation_comment_offences(text):
    """Lines ending in `\\` whose successor is a comment, outside heredocs."""
    lines = text.splitlines()
    offences = []
    heredoc = None
    for i, line in enumerate(lines):
        if heredoc is not None:
            if line.strip() == heredoc:
                heredoc = None
            continue
        opener = re.search(r"<<\s*'([A-Za-z_][A-Za-z0-9_]*)'", line)
        if opener:
            heredoc = opener.group(1)
            continue
        if line.rstrip().endswith("\\"):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt.lstrip().startswith("#"):
                offences.append(f"line {i + 1}: {line.strip()!r} -> {nxt.strip()!r}")
    return offences


@pytest.mark.parametrize("name", ["notify.sh", "install.sh"])
def test_no_comment_inside_line_continuation(name, src_dir):
    with open(os.path.join(src_dir, name), encoding="utf-8") as f:
        offences = _continuation_comment_offences(f.read())
    assert not offences, (
        f"src/{name}: a comment after a `\\` continuation silently ends the "
        f"logical line (v28's env-prefix bug). Move the comment above the "
        f"whole command.\n" + "\n".join(offences)
    )


def test_no_comment_inside_line_continuation_in_built_notify(dist_dir):
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        body = _extract_heredoc(f.read(), "NOTIFY_SCRIPT")
    assert body is not None, "NOTIFY_SCRIPT heredoc not found in dist/install.sh"
    offences = _continuation_comment_offences(body)
    assert not offences, (
        "built notify.sh: comment inside a `\\` continuation\n" + "\n".join(offences)
    )


ENVELOPE_ENV_VARS = [
    "VIBEMON_EVT", "VIBEMON_AGENT", "VIBEMON_CWD", "VIBEMON_ROOT",
    "VIBEMON_REPO", "VIBEMON_BRANCH", "VIBEMON_HEAD", "VIBEMON_TS",
    "VIBEMON_FILE", "VIBEMON_NO_COMMIT_MSG",
]


@pytest.mark.skipif(
    os.name == "nt",
    reason="runs the Unix notify.sh envelope block; Windows goes through notify.py",
)
def test_envelope_env_prefix_reaches_python(dist_dir, tmp_path):
    """Execute the real env-prefix block from the BUILT notify.sh and assert
    python3 receives every VIBEMON_* variable.

    Syntax checks cannot catch this class of defect and the parity tests
    supply the environment themselves, so this is the only test that proves
    the shell half of the contract."""
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        notify = _extract_heredoc(f.read(), "NOTIFY_SCRIPT")
    assert notify is not None, "NOTIFY_SCRIPT heredoc not found in dist/install.sh"

    m = re.search(
        r"(VIBEMON_EVT=\"\$EVENT_TYPE\".*?<< 'VIBEMON_PY'[^\n]*\n)"
        r".*?"
        r"(\nVIBEMON_PY\n)",
        notify, re.DOTALL,
    )
    assert m, "envelope env-prefix block not found in built notify.sh"
    probe = (
        'import json, os\n'
        'print(json.dumps({k: v for k, v in os.environ.items() '
        'if k.startswith("VIBEMON_")}))'
    )
    # Drop 2>/dev/null so a broken probe surfaces instead of looking empty.
    block = (m.group(1).replace(" 2>/dev/null", "") + probe + m.group(2))

    out = tmp_path / "envelope.json"
    payload = tmp_path / "payload.json"
    payload.write_text("{}", encoding="utf-8")
    script = tmp_path / "block.sh"
    script.write_text(
        "set -euo pipefail\n"
        'EVENT_TYPE="prompt"\n'
        'AGENT="claude"\n'
        'PROJECT_ROOT="proj"\n'
        'REPO_IDENTIFIER="acme/proj"\n'
        'GIT_BRANCH="main"\n'
        'GIT_HEAD="0123456789abcdef"\n'
        f'STDIN_FILE="{payload}"\n'
        'NO_COMMIT_MSG="0"\n'
        f'ENV_FILE="{out}"\n'
        + block,
        encoding="utf-8",
    )

    r = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, f"block failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
    assert out.exists(), "block produced no envelope file"

    seen = json.loads(out.read_text(encoding="utf-8") or "{}")
    missing = [v for v in ENVELOPE_ENV_VARS if v not in seen]
    assert not missing, (
        "python3 did not inherit the env prefix — the assignments became "
        f"shell variables (v28 bug). Missing: {missing}"
    )
    assert seen["VIBEMON_EVT"] == "prompt"
    assert seen["VIBEMON_AGENT"] == "claude"
    assert seen["VIBEMON_REPO"] == "acme/proj"
