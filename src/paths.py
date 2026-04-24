"""
paths.py — OS-aware filesystem paths and python launcher detection.

Single point of platform branching. All other modules import paths to
avoid sprinkling os.name checks throughout the codebase.

Imported by: install.py, notify.py, merge_*.py
Stdlib only.
"""

import os
import shutil


IS_WINDOWS = os.name == "nt"


def home():
    """User home directory. Windows: %USERPROFILE%, Unix: $HOME."""
    return os.path.expanduser("~")


def vibemon_dir():
    """VibeMon state directory — ~/.vibemon on every platform."""
    return os.path.join(home(), ".vibemon")


def claude_settings():
    return os.path.join(home(), ".claude", "settings.json")


def gemini_settings():
    return os.path.join(home(), ".gemini", "settings.json")


def cursor_hooks():
    return os.path.join(home(), ".cursor", "hooks.json")


def codex_settings():
    return os.path.join(home(), ".codex", "settings.json")


def python_launcher():
    """Absolute path to a Python 3 interpreter usable from a hook command.

    Probed at install time and baked into settings.json so the hook is
    immune to PATH changes after install. On Windows we prefer `py` (the
    standard launcher shipped with python.org installers), then fall back
    to `python3` / `python`.
    """
    candidates = ("py", "python3", "python") if IS_WINDOWS else ("python3", "python")
    for cand in candidates:
        path = shutil.which(cand)
        if path:
            return path
    raise RuntimeError(
        "python3 not found on PATH. Install Python 3.8+ from "
        "https://www.python.org/ and re-run the installer."
    )


def notify_command(launcher=None):
    """Hook command prefix to embed in agent settings.json.

    Format: '"<python>" "<vibemon_dir>/notify.py"'
    Caller appends ' <event> <agent>' suffix.

    Quotes both paths because Windows %USERPROFILE% may contain spaces
    (e.g. 'C:\\Users\\Jane Doe\\.vibemon\\notify.py').
    """
    py = launcher or python_launcher()
    script = os.path.join(vibemon_dir(), "notify.py")
    return '"{}" "{}"'.format(py, script)
