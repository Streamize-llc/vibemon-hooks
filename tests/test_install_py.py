"""install.py argv parsing + launcher pinning (v25).

The Windows GUI installer (VibeMonSetup.exe) passes its bundled
interpreter via --launcher so hook commands never depend on a system
Python existing. paths.python_launcher() gains the same guarantee:
bundled interpreter first, then PATH, then sys.executable.
"""
import os
import sys

import install
import paths


# ─── _parse_argv ─────────────────────────────────────────────────────

def test_parse_positional_key_and_version():
    key, ver, flag, launcher = install._parse_argv(["install.py", "vbm_k", "25"])
    assert (key, ver, flag, launcher) == ("vbm_k", "25", None, None)


def test_parse_launcher_flag():
    key, ver, flag, launcher = install._parse_argv(
        ["install.py", "vbm_k", "25", "--launcher", r"C:\Users\x\.vibemon\python\python.exe"]
    )
    assert key == "vbm_k"
    assert launcher == r"C:\Users\x\.vibemon\python\python.exe"
    assert flag is None


def test_parse_launcher_with_commit_flag():
    key, ver, flag, launcher = install._parse_argv(
        ["install.py", "vbm_k", "25", "--no-commit-msg", "--launcher", "/usr/bin/python3"]
    )
    assert flag == "1"
    assert launcher == "/usr/bin/python3"


def test_parse_launcher_missing_value():
    key, ver, flag, launcher = install._parse_argv(["install.py", "vbm_k", "25", "--launcher"])
    assert launcher is None  # tolerated — falls back to probing


# ─── paths.python_launcher probe order ───────────────────────────────

def test_bundled_python_wins(tmp_path, monkeypatch):
    pydir = tmp_path / "python"
    pydir.mkdir()
    exe = pydir / "python.exe"
    exe.write_text("")  # existence is all bundled_python checks
    monkeypatch.setattr(paths, "vibemon_dir", lambda: str(tmp_path))
    assert paths.python_launcher() == str(exe)


def test_path_probe_when_no_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "vibemon_dir", lambda: str(tmp_path))  # no bundle
    monkeypatch.setattr(paths.shutil, "which", lambda c: "/probed/" + c)
    result = paths.python_launcher()
    assert result.startswith("/probed/")


def test_sys_executable_fallback(tmp_path, monkeypatch):
    """A machine with no bundle and nothing on PATH must still resolve —
    whatever Python is running this code is, by definition, working."""
    monkeypatch.setattr(paths, "vibemon_dir", lambda: str(tmp_path))
    monkeypatch.setattr(paths.shutil, "which", lambda c: None)
    assert paths.python_launcher() == sys.executable


def test_notify_command_uses_launcher_passthrough(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "vibemon_dir", lambda: str(tmp_path))
    cmd = paths.notify_command(r"C:\bundle\python.exe")
    assert cmd.startswith('"C:\\bundle\\python.exe" ')
    assert cmd.endswith(os.path.join("notify.py") + '"')
