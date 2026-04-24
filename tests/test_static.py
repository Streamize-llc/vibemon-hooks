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
    ("NOTIFY_SCRIPT",   "shell"),  # bash heredoc body — validate as bash
    ("PYMERGE_CLAUDE",  "python"),
    ("PYMERGE_GEMINI",  "python"),
    ("PYMERGE_CURSOR",  "python"),
    ("PYMERGE_CODEX",   "python"),
]


def _extract_heredoc(src, marker):
    pat = rf"<< '{marker}'\n(.*?)\n{marker}"
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
