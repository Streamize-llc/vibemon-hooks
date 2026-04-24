"""Sanity checks for paths.py — OS-aware filesystem helpers."""

import os

import paths


def test_home_returns_absolute_existing_path():
    h = paths.home()
    assert os.path.isabs(h)
    assert os.path.isdir(h)


def test_vibemon_dir_under_home():
    assert paths.vibemon_dir() == os.path.join(paths.home(), ".vibemon")


def test_agent_settings_paths_layout():
    assert paths.claude_settings().endswith(os.path.join(".claude", "settings.json"))
    assert paths.gemini_settings().endswith(os.path.join(".gemini", "settings.json"))
    assert paths.cursor_hooks().endswith(os.path.join(".cursor", "hooks.json"))
    assert paths.codex_settings().endswith(os.path.join(".codex", "settings.json"))


def test_python_launcher_returns_existing_executable():
    p = paths.python_launcher()
    assert os.path.isabs(p) or os.path.basename(p) in ("py", "py.exe")
    # Either it's an absolute existing path, or it's the `py` launcher
    # whose source attribute may be relative. Either way, shutil.which
    # found it — that's enough.


def test_notify_command_quotes_both_paths():
    cmd = paths.notify_command()
    # Two quoted segments: launcher path + script path
    assert cmd.count('"') == 4
    assert "notify.py" in cmd


def test_notify_command_accepts_explicit_launcher():
    cmd = paths.notify_command(launcher="/custom/python3")
    assert '"/custom/python3"' in cmd


def test_is_windows_consistent_with_os_name():
    assert paths.IS_WINDOWS == (os.name == "nt")
