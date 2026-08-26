"""
paths.py — OS-aware filesystem paths and python launcher detection.

Single point of platform branching. All other modules import paths to
avoid sprinkling os.name checks throughout the codebase.

Imported by: install.py, notify.py, merge_*.py
Stdlib only.
"""

import os
import shutil
import sys


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


def codex_hooks():
    """Codex CLI reads hooks from ~/.codex/hooks.json — NOT settings.json
    (v28 wrote there; Codex never read it). merge_codex also scrubs the
    stale sibling settings.json on upgrade."""
    return os.path.join(home(), ".codex", "hooks.json")


def claude_mcp_config():
    """Claude Code's user-scope config file — MCP servers live at its top level."""
    return os.path.join(home(), ".claude.json")


def cursor_mcp_config():
    return os.path.join(home(), ".cursor", "mcp.json")


def bundled_python():
    """The embedded interpreter deployed by the Windows GUI installer
    (VibeMonSetup.exe) at ~/.vibemon/python/. Returns its path or None."""
    exe = os.path.join(vibemon_dir(), "python", "python.exe")
    return exe if os.path.exists(exe) else None


def python_launcher():
    """Absolute path to a Python 3 interpreter usable from a hook command.

    Probed at install time and baked into settings.json so the hook is
    immune to PATH changes after install.

    Probe order (v25):
      1. The GUI installer's bundled interpreter (~/.vibemon/python/) —
         consumer Windows machines often have NO system Python at all,
         and the daily auto-update re-runs the installer there, so the
         bundle must stay authoritative once present.
      2. PATH — `py` (the standard python.org launcher) first on
         Windows, then `python3` / `python`.
      3. sys.executable — whatever is running this code is, by
         definition, a working Python.
    """
    bundled = bundled_python()
    if bundled:
        return bundled
    candidates = ("py", "python3", "python") if IS_WINDOWS else ("python3", "python")
    for cand in candidates:
        path = shutil.which(cand)
        if path:
            return path
    if sys.executable:
        return sys.executable
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
