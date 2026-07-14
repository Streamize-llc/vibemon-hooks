"""The installer is bash, so it must never be advertised as `| sh`.

`dist/install.sh` uses `set -o pipefail`, `local` and `[[ ]]` — none of which
POSIX sh has. The shebang is inert when the script arrives on stdin via
`curl … | sh`, so on Debian/Ubuntu (where /bin/sh is dash) the advertised
one-liner died at `set -o pipefail` with a cryptic "Illegal option". macOS
hid this for the whole life of the project: its /bin/sh is bash in POSIX
mode, so BASH_VERSION is set and `curl | sh` genuinely works there.

Layer 3 of run.sh only runs `bash -n`, which by construction can never catch
a dash incompatibility — hence these tests.
"""
import os
import shutil
import subprocess

import pytest

DASH = shutil.which("dash") or ("/bin/dash" if os.path.exists("/bin/dash") else None)


@pytest.mark.skipif(
    DASH is None or os.name == "nt",
    reason="needs a real dash — a genuinely non-bash POSIX shell",
)
def test_piped_to_dash_fails_with_an_actionable_message(dist_dir, tmp_path):
    """dash must hit the guard, not the cryptic `set: Illegal option -o pipefail`."""
    script = open(os.path.join(dist_dir, "install.sh"), encoding="utf-8").read()
    env = dict(os.environ, HOME=str(tmp_path))
    r = subprocess.run([DASH], input=script, capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr

    assert "Illegal option" not in out, "guard is missing or sits after the first bash-ism"
    assert r.returncode == 1
    assert "requires bash" in out
    assert "| bash -s --" in out, "the error must name the command that actually works"
    # The guard has to fire before any side effect — a wrong shell must not
    # leave a half-written ~/.vibemon behind.
    assert not os.path.exists(os.path.join(str(tmp_path), ".vibemon"))


def test_installer_never_advertises_sh(dist_dir):
    """Every usage string the installer prints must say bash."""
    script = open(os.path.join(dist_dir, "install.sh"), encoding="utf-8").read()
    offenders = [
        f"{i}: {line.strip()}"
        for i, line in enumerate(script.splitlines(), 1)
        if "| sh -s" in line or "install.sh | sh" in line
    ]
    assert not offenders, "install.sh advertises the broken `| sh` form:\n" + "\n".join(offenders)


@pytest.mark.skipif(
    DASH is None or os.name == "nt",
    reason="needs a real dash — a genuinely non-bash POSIX shell",
)
def test_bash_still_gets_past_the_guard(dist_dir, tmp_path):
    """The guard must not false-positive: bash (and macOS's bash-based /bin/sh) proceeds."""
    script = open(os.path.join(dist_dir, "install.sh"), encoding="utf-8").read()
    env = dict(os.environ, HOME=str(tmp_path))
    r = subprocess.run(["bash"], input=script, capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr

    assert "requires bash" not in out, "guard wrongly fired under bash"
    # No API key passed, so it stops at the next check — proving it got past the guard.
    assert "API key is required" in out
